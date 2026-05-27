/* ============================================================
 * 12_feedback.sql
 * Purpose : add api_audit.ai_response_feedback table.
 *           Stores per-response user ratings (thumbs up/down)
 *           and optional free-text comments from the frontend.
 * Depends : setup_audit_schema.sql must have run first
 *           (api_audit schema must already exist).
 * Idempotent: IF NOT EXISTS pattern.
 * ============================================================ */

IF OBJECT_ID('api_audit.ai_response_feedback', 'U') IS NULL
BEGIN
    CREATE TABLE api_audit.ai_response_feedback (
        id          BIGINT IDENTITY(1,1) NOT NULL
                        CONSTRAINT pk_ai_feedback PRIMARY KEY,
        request_id  NVARCHAR(36)  NOT NULL,   -- UUID from ai_audit_log.request_id
        tenant_id   INT           NOT NULL,
        user_id     BIGINT        NOT NULL,
        rating      NVARCHAR(10)  NOT NULL,   -- 'positive' | 'negative'
        comment     NVARCHAR(500) NULL,
        created_at  DATETIME2(3)  NOT NULL
                        CONSTRAINT df_feedback_created DEFAULT SYSUTCDATETIME()
    );

    -- Lookup by request_id (most common read pattern from audit dashboards)
    CREATE INDEX ix_feedback_request
        ON api_audit.ai_response_feedback (request_id);

    -- Tenant-scoped time-ordered reads for analytics
    CREATE INDEX ix_feedback_tenant
        ON api_audit.ai_response_feedback (tenant_id, created_at DESC);
END;
GO
