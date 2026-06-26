from functools import lru_cache
import os
from pathlib import Path
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseModel):
    project_root: Path = PROJECT_ROOT
    database_path: Path = Path(os.getenv("MARKET_REGIME_DATABASE_PATH", PROJECT_ROOT / "data" / "market_regime.sqlite3"))
    demo_source: str = "demo_seed"
    stale_after_days: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
