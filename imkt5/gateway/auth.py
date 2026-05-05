"""Auth bearer-token simples com RBAC baseado em papéis.

Tokens e seus papéis vêm de env `IMKT5_AUTH_TOKENS` (JSON) ou
`config/auth.yaml`. Em dev, se não há nada configurado, roda em modo
aberto (audit-only). Em prod, setar `IMKT5_AUTH_REQUIRED=1`.

Papéis suportados:
- `admin-global`: pode tudo em qualquer tenant.
- `admin-tenant:<tid>`: pode tudo no tenant <tid>.
- `user:<tid>`: pode disparar jobs/recipes no tenant <tid>; não pode
  mexer em config nem aprovar pra outros.
- `reviewer:<tid>`: pode aprovar stages; não pode mexer em config.

Uso (FastAPI):
    from imkt5.gateway.auth import Principal, require

    @app.post("/jobs", dependencies=[Depends(require(scope="job.create"))])
    async def create_job(req, principal: Principal = Depends(current_principal)):
        # principal.tenant_id / principal.user_id disponíveis
        ...
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Header, HTTPException, Request

log = logging.getLogger("imkt5.auth")


@dataclass(frozen=True)
class Principal:
    token: str
    user_id: str
    tenant_id: str | None           # None = admin global
    roles: tuple[str, ...]

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def is_admin_global(self) -> bool:
        return "admin-global" in self.roles

    def is_admin_of(self, tenant_id: str) -> bool:
        return self.is_admin_global() or f"admin-tenant:{tenant_id}" in self.roles

    def can_act_in_tenant(self, tenant_id: str) -> bool:
        if self.is_admin_global():
            return True
        if self.tenant_id is None:
            return False
        return self.tenant_id == tenant_id


# ── token registry ───────────────────────────────────────────────────
def _load_tokens() -> dict[str, dict[str, Any]]:
    """Carrega tokens de env IMKT5_AUTH_TOKENS (JSON) ou arquivo.

    Formato:
    {
      "<token>": {
        "user_id": "nei",
        "tenant_id": "inema" | null,
        "roles": ["admin-global" | "admin-tenant:inema" | "user:inema"]
      }
    }
    """
    raw = os.environ.get("IMKT5_AUTH_TOKENS")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            log.warning("IMKT5_AUTH_TOKENS inválido — ignorando")

    path = os.environ.get("IMKT5_AUTH_TOKENS_FILE", "config/auth.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as exc:  # noqa: BLE001
            log.warning("auth tokens file %s: %s", path, exc)
    return {}


_TOKENS = _load_tokens()


def reload_tokens() -> None:
    global _TOKENS
    _TOKENS = _load_tokens()


def _required() -> bool:
    return os.environ.get("IMKT5_AUTH_REQUIRED", "0") == "1"


# ── principal resolution ─────────────────────────────────────────────
async def current_principal(
    request: Request,
    authorization: str | None = Header(None),
) -> Principal:
    token = ""
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]

    if not token:
        if _required():
            raise HTTPException(401, "Bearer token obrigatório")
        # modo aberto: anônimo
        return Principal(
            token="",
            user_id=request.headers.get("X-User-Id", "anon"),
            tenant_id=request.headers.get("X-Tenant-Id"),
            roles=("anon",),
        )

    rec = _TOKENS.get(token)
    if rec is None:
        raise HTTPException(401, "token inválido")

    return Principal(
        token=token,
        user_id=rec.get("user_id", "unknown"),
        tenant_id=rec.get("tenant_id"),
        roles=tuple(rec.get("roles", ())),
    )


# ── scope enforcement ────────────────────────────────────────────────
SCOPES: dict[str, tuple[str, ...]] = {
    # scope → papéis que o concedem (qualquer papel desta lista basta)
    "job.create":       ("admin-global", "admin-tenant", "user"),
    "job.read":         ("admin-global", "admin-tenant", "user", "reviewer"),
    "recipe.run":       ("admin-global", "admin-tenant", "user"),
    "recipe.read":      ("admin-global", "admin-tenant", "user", "reviewer"),
    "run.read":         ("admin-global", "admin-tenant", "user", "reviewer"),
    "approval.decide":  ("admin-global", "admin-tenant", "reviewer"),
    "workers.read":     ("admin-global", "admin-tenant", "user", "reviewer"),
    "config.write":     ("admin-global", "admin-tenant"),
    "audit.read":       ("admin-global", "admin-tenant"),
}


def _role_family(role: str) -> str:
    """admin-tenant:x → admin-tenant; user:x → user."""
    return role.split(":", 1)[0]


def require(*, scope: str) -> Callable:
    """Dependency factory: exige scope + enforce tenant boundary."""
    async def _dep(
        request: Request,
        principal: Principal = None,  # type: ignore
    ) -> None:
        # evita re-resolver se chamado manualmente
        if principal is None:
            principal = await current_principal(request)  # type: ignore[arg-type]

        # modo aberto (auth_required=False, anon) só permite scopes de leitura
        if principal.roles == ("anon",):
            if _required() or scope in ("config.write",):
                raise HTTPException(403, f"scope '{scope}' exige autenticação")
            return

        allowed = SCOPES.get(scope, ())
        if not any(_role_family(r) in allowed for r in principal.roles):
            raise HTTPException(403, f"scope '{scope}' negado pros papéis {principal.roles}")

        # enforce tenant boundary pra body com tenant_id
        body_tenant = _extract_tenant(request)
        if body_tenant and not principal.can_act_in_tenant(body_tenant):
            raise HTTPException(403, f"sem permissão no tenant {body_tenant}")

    return _dep


def _extract_tenant(request: Request) -> str | None:
    # tenta path param primeiro, depois query/header
    pp = request.path_params or {}
    return pp.get("tenant_id") or request.query_params.get("tenant_id")
