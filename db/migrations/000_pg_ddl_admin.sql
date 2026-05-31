-- Paso a: SQL previo para admin infrastructure
-- Ejecutar en: asistente-ia (PostgreSQL)

-- 1. Permitir superadmin sin tenant
ALTER TABLE auth.users ALTER COLUMN tenant_id DROP NOT NULL;

-- 2. Tabla de auditoria admin
CREATE TABLE IF NOT EXISTS auth.admin_audit_log (
    id          BIGSERIAL PRIMARY KEY,
    admin_id    BIGINT       NOT NULL,
    action      VARCHAR(100) NOT NULL,
    target_type VARCHAR(50)  NOT NULL,
    target_id   VARCHAR(50)  NULL,
    detail      TEXT         NULL,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_admin_audit_admin
    ON auth.admin_audit_log(admin_id, created_at DESC);

-- Verificacion
SELECT column_name, is_nullable
FROM information_schema.columns
WHERE table_schema='auth' AND table_name='users'
  AND column_name='tenant_id';

SELECT tablename FROM pg_tables
WHERE schemaname='auth' AND tablename='admin_audit_log';
