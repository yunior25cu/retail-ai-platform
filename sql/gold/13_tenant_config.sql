/* ============================================================
 * 13_tenant_config.sql
 * Purpose : add api_audit.ai_tenant_config — key/value settings
 *           per tenant for the AI Assistant module (memory turns,
 *           monthly budget, per-role rate limits, suggestions
 *           toggle, budget alert threshold).
 * Depends : setup_audit_schema.sql (api_audit must exist).
 * Idempotent: IF NOT EXISTS for the table; per-row guard for seeds.
 * ============================================================ */

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = 'api_audit'
      AND TABLE_NAME   = 'ai_tenant_config'
)
BEGIN
    CREATE TABLE api_audit.ai_tenant_config (
        id            BIGINT IDENTITY(1,1) NOT NULL
                          CONSTRAINT pk_ai_tenant_config PRIMARY KEY,
        tenant_id     INT            NOT NULL,
        config_key    NVARCHAR(100)  NOT NULL,
        config_value  NVARCHAR(500)  NOT NULL,
        updated_at    DATETIME2(3)   NOT NULL
                          CONSTRAINT df_ai_tenant_config_updated DEFAULT SYSUTCDATETIME(),
        updated_by    BIGINT         NULL,
        CONSTRAINT uq_ai_tenant_config UNIQUE (tenant_id, config_key)
    );

    CREATE INDEX ix_ai_tenant_config_tenant
        ON api_audit.ai_tenant_config (tenant_id);
END;
GO

/* ------------------------------------------------------------
 * Seed defaults for any tenant that has ever logged a chat.
 * Per-row guard so re-running never overwrites a tenant's
 * already-customised value.
 * ------------------------------------------------------------ */
WITH defaults(key_name, default_value) AS (
    SELECT 'memory_turns',         '3'    UNION ALL
    SELECT 'monthly_budget_usd',   '0'    UNION ALL  -- 0 = unlimited
    SELECT 'budget_alert_pct',     '80'   UNION ALL
    SELECT 'rate_limit_director',  '50'   UNION ALL
    SELECT 'rate_limit_marca',     '30'   UNION ALL
    SELECT 'rate_limit_tienda',    '15'   UNION ALL
    SELECT 'rate_limit_producto',  '15'   UNION ALL
    SELECT 'suggestions_enabled',  'true'
),
tenants AS (
    SELECT DISTINCT tenant_id FROM api_audit.ai_audit_log
)
INSERT INTO api_audit.ai_tenant_config (tenant_id, config_key, config_value)
SELECT t.tenant_id, d.key_name, d.default_value
FROM tenants t
CROSS JOIN defaults d
WHERE NOT EXISTS (
    SELECT 1 FROM api_audit.ai_tenant_config c
    WHERE c.tenant_id  = t.tenant_id
      AND c.config_key = d.key_name
);
GO
