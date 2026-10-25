from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from starlette.responses import JSONResponse


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    actor_id: str
    scopes: frozenset[str]


current_principal: ContextVar[Principal] = ContextVar("ehr_principal")
DEMO_PRINCIPAL = Principal("demo-clinic", "demo-clinician", frozenset({"ehr:read", "ehr:write", "ehr:audit"}))


def principal_from_token(header: str, principals: dict):
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 4096:
        return None
    data = principals.get(hashlib.sha256(token.encode()).hexdigest())
    if not data:
        return None
    return Principal(data["tenant_id"], data["actor_id"], frozenset(data["scopes"]))


class AuthMiddleware:
    """Pure ASGI middleware preserves identity through MCP request task contexts."""
    def __init__(self, app, settings, credentials):
        self.app, self.settings, self.credentials = app, settings, credentials

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        protected = path.startswith("/api/") or path == "/mcp" or path.startswith("/mcp/")
        if not protected:
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        if origin and origin not in self.settings.allowed_origins:
            return await JSONResponse({"detail": "Origin not allowed"}, status_code=403)(scope, receive, send)
        host = headers.get("host", "").split(":", 1)[0]
        if host not in self.settings.allowed_hosts:
            return await JSONResponse({"detail": "Host not allowed"}, status_code=400)(scope, receive, send)
        credential = headers.get("authorization", "")
        principal = principal_from_token(credential, self.credentials)
        if not principal and not credential and self.settings.demo_mode and path.startswith("/api/"):
            principal = DEMO_PRINCIPAL
        if not principal:
            return await JSONResponse({"detail": "Valid bearer credential required"}, status_code=401,
                                      headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        scope.setdefault("state", {})["principal"] = principal
        token = current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(token)
