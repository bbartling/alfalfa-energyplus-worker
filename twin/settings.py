import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    bootstrap_key: str
    dashboard_open: bool
    inline_jobs: bool
    alfalfa_url: str | None
    energyplus_inline: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        alfalfa = os.getenv("ALFALFA_URL", "").strip() or None
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./work/twin.db"),
            bootstrap_key=os.getenv("TWIN_BOOTSTRAP_KEY", "local-demo-key"),
            dashboard_open=os.getenv("TWIN_DASHBOARD_OPEN", "0") == "1",
            inline_jobs=os.getenv("TWIN_INLINE_JOBS", "1") == "1",
            alfalfa_url=alfalfa,
            energyplus_inline=os.getenv("TWIN_ENERGYPLUS_INLINE", "0") == "1",
        )
