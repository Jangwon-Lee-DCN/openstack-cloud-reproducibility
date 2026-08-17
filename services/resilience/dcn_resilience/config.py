from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    mode: str
    database: str
    integration: dict[str, str]

    @classmethod
    def from_env(cls) -> "Config":
        mode = os.environ.get("RESILIENCE_MODE", "development")
        if mode not in {"development", "integration", "production"}:
            raise RuntimeError("RESILIENCE_MODE must be development, integration or production")
        integration = {}
        if mode in {"integration", "production"}:
            required = ("KEYSTONE_AUTH_URL", "KEYSTONE_APPLICATION_CREDENTIAL_ID",
                        "KEYSTONE_APPLICATION_CREDENTIAL_SECRET", "OPA_URL", "TRACK_A_URL", "TRACK_B_URL")
            missing = [name for name in required if not os.environ.get(name)]
            if missing:
                raise RuntimeError(f"real integration is fail-closed; missing {missing}")
            if os.environ.get("RESILIENCE_ALLOW_DESTRUCTIVE", "false").lower() != "false":
                raise RuntimeError("destructive integration is fenced in this release")
            integration = {name: os.environ[name] for name in required}
        return cls(mode=mode, database=os.environ.get("RESILIENCE_DB", "/data/resilience.db"), integration=integration)
