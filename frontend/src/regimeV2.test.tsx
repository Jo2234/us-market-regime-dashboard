import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import recorded from './fixtures/regime-v2.json';
import { applyV2, BottomLine, rawSignalValue } from './regimeV2';
import { demoDashboardData } from './demoData';
import type { RegimeV2 } from './types';
import RegimeHistoryChart from './RegimeHistoryChart';
afterEach(cleanup);
const model=recorded as unknown as RegimeV2;
it('renders the recorded headline, confidence components and arithmetic scenarios',()=>{
 render(<BottomLine model={model}/>);
 expect(screen.getByRole('heading',{level:2})).toHaveTextContent(model.headline);
 expect(screen.getByText('Signal agreement')).toBeInTheDocument();
 expect(screen.getByText('Low confidence')).toBeInTheDocument();
 expect(screen.getAllByRole('listitem')).toHaveLength(3);
 expect(screen.getByText(/not forecasts/)).toBeInTheDocument();
});
it('attributes each signal once and formats claims, breadth and ratios',()=>{
 const data=applyV2(structuredClone(demoDashboardData),model);
 expect(data.signals).toHaveLength(18);
 expect(data.optionalProvidersMissing).toEqual([]);
 expect(data.breadth[0].signal).toContain('of 11');
 expect(rawSignalValue(model.signals.find(s=>s.key==='claims')!)).toContain('claims');
 expect(rawSignalValue(model.signals.find(s=>s.key==='vol_term')!)).toContain('×');
 expect(data.signals.every(s=>s.percentile!==undefined&&s.directionText)).toBe(true);
 expect(data.regime.displayLabel).toBe(model.quadrant);
});
it('uses three synchronized panels and keeps emerging and raw scores while smoothing',()=>{
 const points=[0,1].map(i=>({date:`2026-09-${29+i}`,displayLabel:model.quadrant,growthScore:48.3+i,inflationScore:53.7,stressScore:36.9,riskScore:0,ratesPressureScore:0,emergingLabel:i?'Reflation':null,note:'Recorded model display example'}));
 render(<RegimeHistoryChart data={points} onDateSelect={vi.fn()}/>);
 expect(document.querySelectorAll('.score-panel')).toHaveLength(3);
 expect(document.querySelectorAll('.emerging-marker')).toHaveLength(1);
 const before=document.querySelector('.history-tooltip')!.textContent;
 fireEvent.click(screen.getByRole('checkbox'));
 expect(document.querySelector('.history-tooltip')!.textContent).toBe(before);
});
