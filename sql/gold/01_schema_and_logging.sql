/* ============================================================
 * 01_schema_and_logging.sql  (originally: block_1)
 * Purpose : create [gold] schema + ETL batch log + DQ metrics tables.
 * Depends : SQL Server 2019+. Run against the target Gold database.
 * Frequency: ONCE on initial deploy. Re-running DROPs and recreates the
 *            log/DQ tables and LOSES history. In production, comment out
 *            the DROP statements to preserve audit trail.
 * ============================================================ */

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'gold')
    EXEC('CREATE SCHEMA gold AUTHORIZATION dbo');
GO

-- etl_batch_log: one row per (batch, step). Correlates all sub-steps of a refresh.
IF OBJECT_ID('gold.etl_batch_log','U') IS NOT NULL DROP TABLE gold.etl_batch_log;
GO
CREATE TABLE gold.etl_batch_log (
    id              BIGINT IDENTITY(1,1) NOT NULL,
    batch_id        UNIQUEIDENTIFIER     NOT NULL,
    tenant_id       BIGINT               NOT NULL,
    step_name       NVARCHAR(120)        NOT NULL,
    started_at      DATETIME2(3)         NOT NULL CONSTRAINT df_etl_batch_log_started DEFAULT SYSUTCDATETIME(),
    finished_at     DATETIME2(3)         NULL,
    status          NVARCHAR(20)         NOT NULL CONSTRAINT df_etl_batch_log_status  DEFAULT N'RUNNING',
    rows_processed  BIGINT               NULL,
    error_msg       NVARCHAR(MAX)        NULL,
    CONSTRAINT pk_etl_batch_log PRIMARY KEY CLUSTERED (id)
);
CREATE INDEX ix_etl_batch_log_batch          ON gold.etl_batch_log (batch_id);
CREATE INDEX ix_etl_batch_log_tenant_started ON gold.etl_batch_log (tenant_id, started_at DESC);
GO

-- etl_data_quality_metrics: persisted DQ indicators (1 row per metric per batch).
IF OBJECT_ID('gold.etl_data_quality_metrics','U') IS NOT NULL DROP TABLE gold.etl_data_quality_metrics;
GO
CREATE TABLE gold.etl_data_quality_metrics (
    id              BIGINT IDENTITY(1,1) NOT NULL,
    batch_id        UNIQUEIDENTIFIER     NOT NULL,
    tenant_id       BIGINT               NOT NULL,
    table_name      NVARCHAR(120)        NOT NULL,
    metric_name     NVARCHAR(120)        NOT NULL,
    metric_value    DECIMAL(18,4)        NULL,
    severity        NVARCHAR(20)         NOT NULL CONSTRAINT df_dq_severity DEFAULT N'INFO',
    recorded_at     DATETIME2(3)         NOT NULL CONSTRAINT df_dq_recorded DEFAULT SYSUTCDATETIME(),
    notes           NVARCHAR(500)        NULL,
    CONSTRAINT pk_dq PRIMARY KEY CLUSTERED (id)
);
CREATE INDEX ix_dq_batch    ON gold.etl_data_quality_metrics (batch_id);
CREATE INDEX ix_dq_severity ON gold.etl_data_quality_metrics (severity, recorded_at DESC);
GO
