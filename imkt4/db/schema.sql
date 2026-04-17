-- imkt4 — schema Postgres mínimo
-- Multi-tenant axiomático: tenant_id em toda tabela de domínio.
--
-- Aplicar via: scripts/db-setup.sh ou
--   docker exec -i imkt4-postgres-1 psql -U imkt4 -d imkt4 < imkt4/db/schema.sql

-- ═════════════════════════════════════════════════════════════════════
-- Tenants e Users
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id     TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    profile_path  TEXT DEFAULT '',
    enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    user_id       TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    display_name  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

-- ═════════════════════════════════════════════════════════════════════
-- Channel Bindings — resolução de identidade por canal
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS channel_bindings (
    binding_id     BIGSERIAL PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    user_id        TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    channel        TEXT NOT NULL,            -- telegram | whatsapp | web
    external_id    TEXT NOT NULL,             -- chat_id do Telegram, phone do WA, user_id da Web
    verified_at    TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel, external_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_bindings_tenant_user ON channel_bindings(tenant_id, user_id);

-- ═════════════════════════════════════════════════════════════════════
-- Source/Publish Bindings — origem e destino configuráveis por tenant
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS source_bindings (
    binding_id       TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    kind             TEXT NOT NULL,           -- youtube | tiktok | webhook | ...
    external_id      TEXT NOT NULL,
    credentials_ref  TEXT NOT NULL,
    label            TEXT DEFAULT '',
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_bindings_tenant ON source_bindings(tenant_id);

CREATE TABLE IF NOT EXISTS publish_bindings (
    binding_id       TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    kind             TEXT NOT NULL,           -- youtube | instagram | ...
    external_id      TEXT NOT NULL,
    credentials_ref  TEXT NOT NULL,
    label            TEXT DEFAULT '',
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_publish_bindings_tenant ON publish_bindings(tenant_id);

-- ═════════════════════════════════════════════════════════════════════
-- Jobs — todo trabalho pesado registrado
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS jobs (
    job_id                       UUID PRIMARY KEY,
    tenant_id                    TEXT NOT NULL,
    user_id                      TEXT NOT NULL,
    worker_type                  TEXT,
    required_capability          TEXT,
    payload                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    priority                     INTEGER NOT NULL DEFAULT 50,
    status                       TEXT NOT NULL DEFAULT 'pending',  -- pending|running|success|failed|cancelled|awaiting_approval
    worker_name                  TEXT,
    output                       JSONB,
    error                        TEXT,
    progress                     REAL DEFAULT 0.0,

    -- Origin tracking
    origin_channel               TEXT DEFAULT '',
    origin_channel_external_id   TEXT DEFAULT '',

    -- Dedupe
    dedupe_key                   TEXT,

    -- Correlação com receita
    parent_job_id                UUID,
    recipe_name                  TEXT,
    recipe_stage                 TEXT,
    fanout_index                 INTEGER,

    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (worker_type IS NOT NULL OR required_capability IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_jobs_tenant_user ON jobs(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_job_id) WHERE parent_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_dedupe ON jobs(tenant_id, user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);

-- ═════════════════════════════════════════════════════════════════════
-- Recipe Runs — execução de receitas
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS recipe_runs (
    run_id                     UUID PRIMARY KEY,
    tenant_id                  TEXT NOT NULL,
    user_id                    TEXT NOT NULL,
    recipe_name                TEXT NOT NULL,
    recipe_version             INTEGER DEFAULT 1,
    input                      JSONB NOT NULL DEFAULT '{}'::jsonb,
    origin_channel             TEXT DEFAULT '',
    origin_channel_external_id TEXT DEFAULT '',
    finished                   BOOLEAN NOT NULL DEFAULT FALSE,
    failed                     BOOLEAN NOT NULL DEFAULT FALSE,
    stages                     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- stage_id -> {status, job_ids, outputs, error}
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runs_tenant_user ON recipe_runs(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_runs_recipe ON recipe_runs(recipe_name);
CREATE INDEX IF NOT EXISTS idx_runs_created ON recipe_runs(created_at DESC);

-- ═════════════════════════════════════════════════════════════════════
-- Approval Log — decisões de aprovação (auditoria unificada)
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS approval_log (
    approval_id     UUID PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    parent_job_id   UUID NOT NULL,           -- aponta para recipe_runs.run_id ou jobs.job_id
    stage_id        TEXT NOT NULL,
    mode            TEXT NOT NULL,            -- user | human_reviewer | auto_reviewer | none
    decision        TEXT NOT NULL,            -- approved | rejected | uncertain | expired
    decider         TEXT NOT NULL,            -- user_id OR "auto-reviewer"
    reason          TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approvals_parent ON approval_log(parent_job_id);
CREATE INDEX IF NOT EXISTS idx_approvals_tenant ON approval_log(tenant_id);

-- ═════════════════════════════════════════════════════════════════════
-- Audit Log — quem fez o quê
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     BIGSERIAL PRIMARY KEY,
    tenant_id    TEXT,
    user_id      TEXT,
    event_type   TEXT NOT NULL,            -- config.updated | worker.registered | recipe.saved | ...
    details      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);

-- ═════════════════════════════════════════════════════════════════════
-- Seed inicial: tenant 'demo' e 'inema'
-- ═════════════════════════════════════════════════════════════════════

INSERT INTO tenants (tenant_id, name, profile_path) VALUES
    ('demo',  'Demo Tenant',  'profiles/demo'),
    ('inema', 'INEMA',        'profiles/inema')
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO users (user_id, tenant_id, display_name) VALUES
    ('web',        'demo',  'Web User'),
    ('inema-admin','inema', 'INEMA Admin')
ON CONFLICT (user_id) DO NOTHING;
