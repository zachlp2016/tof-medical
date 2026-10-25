"""Explicit local demo mode; deployment credentials are server-provisioned."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:////tmp/tof-ehr.db"
    demo_mode: bool = False
    principal_file: str = ""
    principals: dict = field(default_factory=dict)
    frontend_dir: str = "/app/frontend/dist"
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver", "tof-ehr", "ehr")
    allowed_origins: tuple[str, ...] = ("http://localhost:8080", "http://127.0.0.1:8080")
    ai_service_url: str = ""
    ai_service_token_file: str = ""
    ai_timeout_seconds: float = 120.0
    clinical_entities_provider: str = "openmed"
    utility_inference_token_file: str = ""
    utility_compute_token_file: str = ""
    utility_state_dir: str = "/var/lib/tof-clinical/utility"

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:////tmp/tof-ehr.db"),
            demo_mode=os.getenv("DEMO_MODE", "false").lower() == "true",
            principal_file=os.getenv("TOKEN_PRINCIPALS_FILE", os.getenv("EHR_PRINCIPALS_FILE", "")),
            frontend_dir=os.getenv("FRONTEND_DIR", "/app/frontend/dist"),
            allowed_hosts=tuple(x.strip() for x in os.getenv("EHR_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,tof-ehr,ehr").split(",")),
            allowed_origins=tuple(x.strip() for x in os.getenv("EHR_ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",")),
            ai_service_url=os.getenv("AI_SERVICE_URL", "").rstrip("/"),
            ai_service_token_file=os.getenv("AI_SERVICE_TOKEN_FILE", ""),
            ai_timeout_seconds=float(os.getenv("AI_SERVICE_TIMEOUT_SECONDS", "120")),
            clinical_entities_provider=os.getenv("CLINICAL_ENTITIES_PROVIDER", "openmed"),
            utility_inference_token_file=os.getenv("UTILITY_INFERENCE_TOKEN_FILE", ""),
            utility_compute_token_file=os.getenv("UTILITY_COMPUTE_TOKEN_FILE", ""),
            utility_state_dir=os.getenv("UTILITY_STATE_DIR", "/var/lib/tof-clinical/utility"),
        )

    def load_principals(self):
        values = self.principals
        if self.principal_file:
            values = json.loads(Path(self.principal_file).read_text(encoding="utf-8-sig"))
        if not isinstance(values, dict):
            raise ValueError("EHR_PRINCIPALS_FILE must contain an object keyed by SHA-256 token digest")
        for digest, principal in values.items():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Credential keys must be lowercase SHA-256 digests")
            if not isinstance(principal, dict) or not all(principal.get(k) for k in ("tenant_id", "actor_id", "scopes")):
                raise ValueError("Every credential requires tenant_id, actor_id, and scopes")
            if any(not isinstance(principal[k], str) or len(principal[k]) > 100 or not principal[k].strip() for k in ("tenant_id", "actor_id")):
                raise ValueError("Tenant and actor identifiers must be nonempty strings of at most 100 characters")
            if not isinstance(principal["scopes"], list) or not set(principal["scopes"]) <= {"ehr:read", "ehr:write", "ehr:audit"}:
                raise ValueError("Invalid credential scopes")
            if self.demo_mode and principal["tenant_id"] != "demo-clinic":
                raise ValueError("Demo credentials must bind to the synthetic demo-clinic tenant")
        if not self.demo_mode and not values:
            raise ValueError("Production requires provisioned credentials in EHR_PRINCIPALS_FILE")
        if not self.demo_mode and not self.database_url.startswith("postgresql"):
            raise ValueError("Production requires a PostgreSQL DATABASE_URL")
        return values
