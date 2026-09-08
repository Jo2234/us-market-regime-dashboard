"""Offline descriptive model. Fixed parameters; latest revised macro vintage."""
from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass, replace
from datetime import date
from statistics import fmean
import math

from app.data.instruments import SECTOR_SYMBOLS
from app.services.analytics import calendar_anchor
from app.services.macro_data import available_on
from app.services.stability import stabilize, changes

VERSION = 1

@dataclass(frozen=True)
class Config:
    baseline: int = 756
    horizons: tuple = (.25, .5, .25)
    breadth_ma: int = 200
    claims_weeks: int = 4
    drawdown_window: int = 252
    persistence: int = 5
    stress_cuts: tuple = (60, 80)
    strong_margin: int = 25
    strong_agreement: float = .75
    confidence_cuts: tuple = (40, 70)

# Every feature has one family. High oriented percentiles increase that family.
SPECS = {
 'equal_weight': ('Growth', 'Equal-weight participation', False, 'ratio_trend'),
 'sector_breadth': ('Growth', 'Sectors above 200-day MA', False, 'breadth'),
 'copper_gold': ('Growth', 'Copper/gold trend', False, 'ratio_trend'),
 'cyclical_defensive': ('Growth', 'Cyclicals versus defensives', False, 'return_difference'),
 'small_large': ('Growth', 'Small versus large companies', False, 'ratio_trend'),
 'claims': ('Growth', 'Initial claims, 4-week average', True, 'claims'),
 'cpi_acceleration': ('Inflation', 'CPI acceleration', False, 'percentage_points'),
 'breakeven': ('Inflation', '10-year breakeven inflation', False, 'percent'),
 'commodities': ('Inflation', 'Oil and broad-commodity trend', False, 'return'),
 'vix': ('Stress', 'VIX level', False, 'index_points'),
 'vol_term': ('Stress', 'VIX / VIX3M', False, 'ratio'),
 'credit': ('Stress', 'High-yield / investment-grade credit trend', True, 'ratio_trend'),
 'financial_conditions': ('Stress', 'Chicago Fed financial conditions', False, 'index_points'),
 'drawdown': ('Stress', 'S&P 500 drawdown magnitude', False, 'return'),
 'real_yield': ('Rates', '10-year real yield', False, 'percent'),
 'nominal_yield': ('Rates', '10-year nominal yield', False, 'percent'),
 'curve': ('Rates', '10Y–2Y Treasury curve', True, 'percentage_points'),
 'dollar': ('Dollar', 'US dollar trend', False, 'return'),
}
FAMILIES = ('Growth', 'Inflation', 'Stress', 'Rates', 'Dollar')
QUADRANTS = {'Goldilocks':(True, False), 'Reflation':(True, True), 'Stagflation':(False, True), 'Slowdown':(False, False)}


def percentile(value, baseline):
    """Empirical midrank, excluding the current observation at the caller."""
    ordered = sorted(baseline)
    return 100 * (bisect_left(ordered, value) + bisect_right(ordered, value)) / (2 * len(ordered)) if ordered else None


def quadrant(growth, inflation):
    return next(label for label, sides in QUADRANTS.items() if sides == (growth >= 50, inflation >= 50))


def stress_label(value, cuts=(60, 80)):
    return 'Calm' if value < cuts[0] else 'Elevated' if value < cuts[1] else 'Stressed'


def confidence(growth, inflation, signals, official, cuts=(40,70)):
    sides = dict(zip(('Growth','Inflation'), QUADRANTS[official]))
    relevant = [s for s in signals if s['axis'] in sides]
    agreement = 100 * sum((s['percentile'] >= 50) == sides[s['axis']] for s in relevant) / len(relevant)
    magnitude = 2 * min(abs(growth-50), abs(inflation-50)) if quadrant(growth,inflation) == official else 0
    score = (agreement + magnitude) / 2
    return {'label':'High' if score >= cuts[1] else 'Medium' if score >= cuts[0] else 'Low',
            'score':round(score,2), 'magnitude':round(magnitude,2), 'agreement':round(agreement,2),
            'interpretation':'Descriptive signal agreement, not a calibrated probability'}


class Inputs:
    def __init__(self, history):
        self.prices = history.price_frames
        self.dates = {s:[r['date'] for r in rows] for s,rows in self.prices.items()}
        self.prefix = {s:[0] for s in self.prices}
        for s,rows in self.prices.items():
            for r in rows:
                self.prefix[s].append(self.prefix[s][-1]+r['value'])
        self.macro = history.macro
        self.publication = {s:[available_on(s,r['date']) for r in rows] for s,rows in self.macro.items()}

    def price(self,s,day):
        rows = self.prices.get(s,[])
        i = bisect_right(self.dates.get(s,[]),day)-1
        return rows[i] if i>=0 else None

    def macro_rows(self,s,day):
        return self.macro.get(s,[])[:bisect_right(self.publication.get(s,[]),day)]

    def trend(self,a,b,day,config):
        now = self.price(a,day)
        other = self.price(b,day) if b else None
        if not now or (b and not other): return None
        endpoint = now['value'] / other['value'] if b else now['value']
        anchors = (calendar_anchor(day,'1m'), calendar_anchor(day,'3m'), calendar_anchor(calendar_anchor(day,'3m'),'3m'))
        # The direct six-month anchor avoids month-end double clipping.
        month_index = day.year*12+day.month-1-6
        import calendar
        year, month = divmod(month_index,12)
        anchors = (*anchors[:2], date(year,month+1,min(day.day,calendar.monthrange(year,month+1)[1])))
        slope = 0
        for weight,anchor in zip(config.horizons,anchors):
            base, denominator = self.price(a,anchor), self.price(b,anchor) if b else None
            if not base or (b and not denominator): return None
            slope += weight / (base['value']/denominator['value'] if b else base['value'])
        return {'value':endpoint*slope-1, 'endpoint':endpoint, 'slope':slope,
                'observations':{a:now['date'].isoformat(), **({b:other['date'].isoformat()} if b else {})}}

    def features(self,day,c):
        result = {}
        def add(key,value,observations,**extra):
            if value is not None and math.isfinite(value):
                result[key] = {'value':value,'observations':observations,**extra}
        for key,a,b in [('equal_weight','RSP','SPY'),('copper_gold','CPER','GLD'),('small_large','IWM','SPY'),('credit','HYG','LQD'),('dollar','DXY',None)]:
            item = self.trend(a,b,day,c)
            if item: result[key] = item
        sector_rows = [(s,self.price(s,day),bisect_right(self.dates.get(s,[]),day)) for s in SECTOR_SYMBOLS]
        if all(row and i>=c.breadth_ma and row['date']==day for s,row,i in sector_rows):
            count = sum(row['value'] > (self.prefix[s][i]-self.prefix[s][i-c.breadth_ma])/c.breadth_ma for s,row,i in sector_rows)
            add('sector_breadth',count/11,{s:day.isoformat() for s in SECTOR_SYMBOLS},count=count)
        basket = {s:self.trend(s,None,day,c) for s in ('XLK','XLY','XLI','XLF','XLU','XLP')}
        if all(basket.values()):
            add('cyclical_defensive',fmean(basket[s]['value'] for s in ('XLK','XLY','XLI','XLF'))-fmean(basket[s]['value'] for s in ('XLU','XLP')),{s:basket[s]['observations'][s] for s in basket})
        claims = self.macro_rows('ICSA',day)[-c.claims_weeks:]
        if len(claims)==c.claims_weeks:
            add('claims',fmean(r['value'] for r in claims),{'ICSA':claims[-1]['date'].isoformat()}, available_on=available_on('ICSA',claims[-1]['date']).isoformat())
        cpi = self.macro_rows('CPI_INDEX',day)
        if cpi:
            by_month = {r['date']:r['value'] for r in cpi}
            # A missing source month prevents a new transformation. Retain the
            # last *computable published* derived observation, never interpolate.
            for current in reversed(cpi):
                previous = by_month.get(calendar_anchor(current['date'],'3m'))
                year_ago = by_month.get(calendar_anchor(current['date'],'1y'))
                if previous and year_ago:
                    add('cpi_acceleration',((current['value']/previous)**4-current['value']/year_ago)*100,{'CPIAUCSL':current['date'].isoformat()},available_on=available_on('CPI_INDEX',current['date']).isoformat(),held_for_missing_month=current['date']!=cpi[-1]['date'])
                    break
        for key,s in [('breakeven','T10YIE'),('financial_conditions','NFCI'),('real_yield','DFII10'),('nominal_yield','DGS10'),('curve','T10Y2Y')]:
            rows = self.macro_rows(s,day)
            if rows: add(key,rows[-1]['value'],{s:rows[-1]['date'].isoformat()},available_on=available_on(s,rows[-1]['date']).isoformat())
        oil, broad = self.trend('USO',None,day,c), self.trend('DBC',None,day,c)
        if oil and broad: add('commodities',(oil['value']+broad['value'])/2,{**oil['observations'],**broad['observations']})
        vix, term = self.price('VIX',day), self.price('VIX3M',day)
        if vix: add('vix',vix['value'],{'VIX':vix['date'].isoformat()})
        if vix and term: add('vol_term',vix['value']/term['value'],{'VIX':vix['date'].isoformat(),'VIX3M':term['date'].isoformat()})
        i = bisect_right(self.dates['SPY'],day)
        if i>=c.drawdown_window:
            rows = self.prices['SPY'][i-c.drawdown_window:i]
            add('drawdown',1-rows[-1]['value']/max(r['value'] for r in rows),{'SPY':rows[-1]['date'].isoformat()})
        return result


def invert_rank(baseline, current, required, inverse=False, increasing=True, discrete=None):
    """Nearest attainable raw value whose empirical rank really crosses the boundary."""
    values = sorted(set(baseline))
    candidates = discrete if discrete is not None else [x for v in values for x in (math.nextafter(v,-math.inf),v,math.nextafter(v,math.inf))]
    ordered = sorted(baseline)
    def oriented(x):
        rank = 100*(bisect_left(ordered,x)+bisect_right(ordered,x))/(2*len(ordered))
        return 100-rank if inverse else rank
    feasible = [v for v in candidates if (oriented(v)>=required if increasing else oriented(v)<=required)]
    if not feasible: return None
    return min(feasible,key=lambda x:abs(x-current))


def nearest_flips(row, baselines, features, cuts=(60,80)):
    signals = row['signals']
    scores = row['axis_scores']
    result=[]
    for signal in signals:
        family=signal['axis']
        if family not in ('Growth','Inflation','Stress'): continue
        score=scores[family]
        boundaries=[(50,score<50)] if family!='Stress' else ([(cuts[0],True)] if score<cuts[0] else [(cuts[0],False),(cuts[1],True)] if score<cuts[1] else [(cuts[1],False)])
        for boundary,increasing in boundaries:
            goal=boundary if increasing else boundary-1e-9
            required=signal['percentile']+(goal-score)/signal['weight']
            if not 0<=required<=100: continue
            key=signal['key']; meta=features[key]; baseline=baselines[key]
            target=invert_rank(baseline,signal['raw_value'],required,signal['inverse'],increasing,[n/11 for n in range(12)] if key=='sector_breadth' else None)
            if target is None: continue
            newp=100-percentile(target,baseline) if signal['inverse'] else percentile(target,baseline)
            achieved=score+signal['weight']*(newp-signal['percentile'])
            if (increasing and achieved<boundary) or (not increasing and achieved>=boundary): continue
            delta=target-signal['raw_value']; verb='rises' if delta>0 else 'falls'
            if signal['unit']=='ratio_trend':
                movement=((1+target)/meta['slope']/meta['endpoint']-1)*100
                change=f"its endpoint {'rises' if movement>0 else 'falls'} about {abs(movement):.1f}%"
            elif key=='sector_breadth': change=f"{round(target*11)} of 11 sectors are above their moving average"
            elif signal['unit']=='claims': change=f"the {4}-week average {verb} about {abs(delta)/1000:.1f}k claims"
            elif signal['unit'] in ('return','return_difference'): change=f"the blended reading {verb} {abs(delta)*100:.2f} percentage points"
            elif signal['unit'] in ('percent','percentage_points'): change=f"the reading {verb} {abs(delta):.2f} percentage points"
            else: change=f"the reading {verb} {abs(delta):.3g} {'ratio units' if signal['unit']=='ratio' else 'points'}"
            condition=f"the {signal['name'].lower()} reading {verb} {abs(delta):.2f} {'percentage points' if signal['unit'] in ('percent','percentage_points') else 'points'}"
            if key=='cyclical_defensive': condition=f"the cyclicals-minus-defensives blended return {verb} {abs(delta)*100:.2f} percentage points"
            elif key=='claims': condition=change
            elif key=='sector_breadth': condition=change
            elif signal['unit']=='return': condition=f"the {signal['name'].lower()} {verb} {abs(delta)*100:.2f} percentage points"
            elif signal['unit']=='ratio': condition=f"the VIX/VIX3M ratio {verb} {abs(delta):.3f}"
            if signal['unit']=='ratio_trend':
                subject={'equal_weight':'the RSP/SPY ratio','copper_gold':'the copper/gold ratio','small_large':'the IWM/SPY ratio','credit':'the HYG/LQD ratio'}[key]
                condition=f"{subject} {change.removeprefix('its endpoint ')}"
            action=f"{family} {'turns up' if increasing else 'turns down'} at {boundary} if {condition}."
            result.append({'key':key,'axis':family,'name':signal['name'],'text':action,'target_raw':target,'current_raw':signal['raw_value'],
                           'target_percentile':newp,'composite_after':achieved,'boundary':boundary,'increasing':increasing,
                           'percentile_distance':abs(newp-signal['percentile'])})
    result.sort(key=lambda item:(round(item['percentile_distance'],10),item['key']))
    chosen=[]
    for item in result:
        if item['key'] not in [x['key'] for x in chosen]: chosen.append(item)
        if len(chosen)==3: break
    return chosen


def build(history, config=Config(), *, details=True):
    inputs=Inputs(history)
    baselines={key:deque(maxlen=config.baseline) for key in SPECS}
    raw=[]
    saved={}
    days=[r['date'] for r in history.price_frames['SPY']]
    for day in days:
        features=inputs.features(day,config)
        signals=[]
        for key,meta in features.items():
            axis,name,inverse,unit=SPECS[key]
            baseline=baselines[key]
            if len(baseline)==config.baseline:
                p=percentile(meta['value'],baseline)
                signals.append({'key':key,'name':name,'axis':axis,'raw_value':meta['value'],'unit':unit,
                    'percentile':100-p if inverse else p,'raw_percentile':p,'inverse':inverse,
                    'direction':'Lower raw values increase this axis' if inverse else 'Higher raw values increase this axis',
                    'weight':1/sum(spec[0]==axis for spec in SPECS.values()),'observations':meta['observations'],
                    'available_on':meta.get('available_on',day.isoformat()),'baseline_count':len(baseline),'held_for_missing_month':meta.get('held_for_missing_month',False)})
        if len(signals)==len(SPECS):
            scores={axis:fmean(s['percentile'] for s in signals if s['axis']==axis) for axis in FAMILIES}
            label=quadrant(scores['Growth'],scores['Inflation'])
            agreement=confidence(scores['Growth'],scores['Inflation'],signals,label)['agreement']/100
            strong=min(abs(scores['Growth']-50),abs(scores['Inflation']-50))>=config.strong_margin and agreement>=config.strong_agreement
            row={'date':day.isoformat(),'regime_label':label,'axis_scores':scores,'signals':signals,'strong_evidence':strong,
                 'stress_label':stress_label(scores['Stress'],config.stress_cuts)}
            if details and day >= days[-252]:
                row['nearest_flips']=nearest_flips(row,baselines,features,config.stress_cuts)
            raw.append(row)
        for key,meta in features.items(): baselines[key].append(meta['value'])
        if day==days[-2]: saved={k:list(v) for k,v in baselines.items()}
    stable=stabilize(raw,persistence=config.persistence,strong=lambda r:r['strong_evidence'])
    for row in stable:
        scores=row['axis_scores']; official=row['official_label']
        row['quadrant']=official
        row['raw_quadrant']=row['raw_label']
        row['confidence']=confidence(scores['Growth'],scores['Inflation'],row['signals'],official,config.confidence_cuts)
        leaders={axis:max((s for s in row['signals'] if s['axis']==axis),key=lambda s:abs(s['percentile']-50)*s['weight']) for axis in ('Growth','Inflation','Stress')}
        row['top_contributors']=[{'key':s['key'],'name':s['name'],'axis':axis,'percentile':round(s['percentile'],1),'contribution':round((s['percentile']-50)*s['weight'],2)} for axis,s in leaders.items()]
        row['driver_sentence']='; '.join(f"{s['name']} {'supports' if s['percentile']>=50 else 'softens'} {axis.lower()} ({s['percentile']:.0f}/100)" for axis,s in leaders.items())+'.'
        row['headline']=f"{official} · {row['stress_label']} · day {row['days_in_regime']}"
        row['version']=VERSION
        row['nearest_flip_note']='One input at a time, holding other inputs and empirical baselines fixed. Raw quadrant flips still require persistence. These are arithmetic scenarios, not forecasts.'
        if details and not row.get('nearest_flips'):
            row['nearest_flip_note']+=' No feasible single-input boundary crossing is available; joint changes would be required.'
    if len(stable)<252:
        raise ValueError(f'Only {len(stable)} fully standardized daily observations; do not shorten the baseline')
    return {'version':VERSION,'snapshots':stable[-252:],'raw_changes':changes(raw[-252:],'regime_label'),
            'official_changes':changes(stable[-252:]),'baselines':saved}


def sensitivity(history):
    cases={'persistence':[(str(n),{'persistence':n}) for n in (3,5,10)],
           'baseline':[(str(n),{'baseline':n}) for n in (504,630,756)],
           'horizon_weights':[('equal',{'horizons':(1/3,1/3,1/3)}),('0.25/0.5/0.25',{})],
           'breadth_ma':[(str(n),{'breadth_ma':n}) for n in (150,200,250)],
           'claims_weeks':[(str(n),{'claims_weeks':n}) for n in (3,4,5)],
           'drawdown':[(str(n),{'drawdown_window':n}) for n in (126,252,378)],
           'stress_cuts':[(str(n),{'stress_cuts':n}) for n in ((55,75),(60,80),(65,85))],
           'strong_evidence':[(f'{m}/{a:.2f}',{'strong_margin':m,'strong_agreement':a}) for m,a in ((20,2/3),(25,.75),(30,.8))],
           'confidence_cuts':[(str(n),{'confidence_cuts':n}) for n in ((30,60),(40,70),(50,80))]}
    result={}
    for group,variants in cases.items():
        result[group]={}
        for label,kwargs in variants:
            b=build(history,replace(Config(),**kwargs),details=False); rows=b['snapshots']
            result[group][label]={'quadrant_changes':b['official_changes'],'raw_changes':b['raw_changes'],
                'stress_changes':changes(rows,'stress_label'),'confidence_counts':{s:sum(r['confidence']['label']==s for r in rows) for s in ('High','Medium','Low')},
                'start':rows[0]['date'],'end':rows[-1]['date'],'points':len(rows)}
    return result
