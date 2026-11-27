import os
from dataclasses import dataclass

DEMO_KEY = "local-demo-key"


@dataclass(frozen=True)
class Settings:
    database_url: str
    bootstrap_key: str
    dashboard_open: bool
    inline_jobs: bool
    alfalfa_url: str | None
    energyplus_inline: bool = False
    env: str = "prod"
    tenant: str = "local"

    @classmethod
    def from_env(cls) -> "Settings":
        alfalfa = os.getenv("ALFALFA_URL", "").strip() or None
        env = os.getenv("TWIN_ENV", "prod").strip().lower() or "prod"
        key = os.getenv("TWIN_BOOTSTRAP_KEY", "")
        if env == "demo" and not key:
            key = DEMO_KEY
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./work/twin.db"),
            bootstrap_key=key,
            dashboard_open=os.getenv("TWIN_DASHBOARD_OPEN", "0") == "1",
            inline_jobs=os.getenv("TWIN_INLINE_JOBS", "1") == "1",
            alfalfa_url=alfalfa,
            energyplus_inline=os.getenv("TWIN_ENERGYPLUS_INLINE", "0") == "1",
            env=env,
            tenant=os.getenv("TWIN_TENANT", "local"),
        )

    def validate(self) -> None:
        if self.env not in {"demo", "prod"}:
            raise RuntimeError("TWIN_ENV must be demo or prod")
        if self.env != "prod":
            return
        if not self.bootstrap_key or self.bootstrap_key == DEMO_KEY or len(self.bootstrap_key) < 32:
            raise RuntimeError("prod requires a bootstrap key of at least 32 characters, not the demo key")
        if self.dashboard_open:
            raise RuntimeError("prod refuses TWIN_DASHBOARD_OPEN=1")
