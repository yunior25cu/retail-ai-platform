/* ============================================================
 * setup_audit_schema.sql
 * Purpose : create [api_audit] schema with conversation + token map +
 *           AI request audit log. These tables are operational metadata
 *           for the API layer, kept SEPARATE from the analytical [gold]
 *           schema by design.
 * Depends : nothing. Idempotent (IF NOT EXISTS).
 * Target  : same database as [gold] (e.g. pymeconta_local).
 * ============================================================ */

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'api_audit')
    EXEC('CREATE SCHEMA api_audit AUTHORIZATION dbo');
GO

------------------------------------------------------------------
-- conversation: top-level multi-turn conversation
------------------------------------------------------------------
IF OBJECT_ID('api_audit.conversation','U') IS NULL
BEGIN
    CREATE TABLE api_audit.conversation (
        conversation_id  UNIQUEIDENTIFIER NOT NULL CONSTRAINT pk_conversation PRIMARY KEY,
        tenant_id        BIGINT           NOT NULL,
        user_id          NVARCHAR(120)    NOT NULL,
        user_role        NVARCHAR(40)     NOT NULL,            -- direccion / marca / tienda / sku
        started_at       DATETIME2(3)     NOT NULL CONSTRAINT df_conv_started DEFAULT SYSUTCDATETIME(),
        last_message_at  DATETIME2(3)     NULL,
        title            NVARCHAR(200)    NULL
    );
    CREATE INDEX ix_conversation_tenant_started
        ON api_audit.conversation (tenant_id, started_at DESC);
END;
GO

------------------------------------------------------------------
-- conversation_token_map: sanitiser mapping (token <-> internal id)
-- Used by the sanitiser layer to obfuscate internal IDs in the LLM
-- prompt/response and re-hydrate before showing to the user.
------------------------------------------------------------------
IF OBJECT_ID('api_audit.conversation_token_map','U') IS NULL
BEGIN
    CREATE TABLE api_audit.conversation_token_map (
        id               BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_token_map PRIMARY KEY,
        conversation_id  UNIQUEIDENTIFIER NOT NULL,
        token            NVARCHAR(60)     NOT NULL,
        entity_type      NVARCHAR(30)     NOT NULL,            -- sku / store / brand / etc.
        entity_id        BIGINT           NOT NULL,
        display_name     NVARCHAR(200)    NULL,
        created_at       DATETIME2(3)     NOT NULL CONSTRAINT df_token_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT fk_token_conv FOREIGN KEY (conversation_id)
            REFERENCES api_audit.conversation(conversation_id)
    );
    CREATE UNIQUE INDEX ux_token_conv_token
        ON api_audit.conversation_token_map (conversation_id, token);
    CREATE UNIQUE INDEX ux_token_conv_entity
        ON api_audit.conversation_token_map (conversation_id, entity_type, entity_id);
END;
GO

------------------------------------------------------------------
-- conversation_message: persisted multi-turn history
-- One row per Anthropic message (user / assistant). Content_json holds the
-- raw content blocks as serialised by orchestrator so tool_use/tool_result
-- cycles survive across turns.
------------------------------------------------------------------
IF OBJECT_ID('api_audit.conversation_message','U') IS NULL
BEGIN
    CREATE TABLE api_audit.conversation_message (
        id               BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_conv_msg PRIMARY KEY,
        conversation_id  UNIQUEIDENTIFIER NOT NULL,
        sequence         INT              NOT NULL,
        role             NVARCHAR(20)     NOT NULL,            -- 'user' / 'assistant'
        content_json     NVARCHAR(MAX)    NOT NULL,            -- anthropic content blocks
        created_at       DATETIME2(3)     NOT NULL CONSTRAINT df_conv_msg_created DEFAULT SYSUTCDATETIME(),
        CONSTRAINT fk_conv_msg_conversation FOREIGN KEY (conversation_id)
            REFERENCES api_audit.conversation(conversation_id)
    );
    CREATE INDEX ix_conv_msg_seq ON api_audit.conversation_message (conversation_id, sequence);
END;
GO

------------------------------------------------------------------
-- ai_audit_log: one row per /chat request
-- Captures user question, tools invoked, final response, tokens, cost,
-- duration. Hashes for large payloads (system prompt, tool responses)
-- so we can correlate later without storing every variant.
------------------------------------------------------------------
IF OBJECT_ID('api_audit.ai_audit_log','U') IS NULL
BEGIN
    CREATE TABLE api_audit.ai_audit_log (
        audit_id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_ai_audit PRIMARY KEY,
        request_id            UNIQUEIDENTIFIER NOT NULL,
        conversation_id       UNIQUEIDENTIFIER NULL,
        tenant_id             BIGINT           NOT NULL,
        user_id               NVARCHAR(120)    NOT NULL,
        user_role             NVARCHAR(40)     NOT NULL,
        timestamp_utc         DATETIME2(3)     NOT NULL CONSTRAINT df_audit_ts DEFAULT SYSUTCDATETIME(),
        user_question         NVARCHAR(MAX)    NULL,
        system_prompt_hash    VARCHAR(64)      NULL,
        tools_invoked         NVARCHAR(MAX)    NULL,           -- JSON array of {name, args, duration_ms}
        tool_responses_hash   VARCHAR(64)      NULL,
        final_response        NVARCHAR(MAX)    NULL,
        tokens_input          INT              NULL,
        tokens_output         INT              NULL,
        cost_usd              DECIMAL(10,6)    NULL,
        duration_ms           INT              NULL,
        status                NVARCHAR(20)     NOT NULL CONSTRAINT df_audit_status DEFAULT N'SUCCESS', -- SUCCESS/ERROR/TIMEOUT
        error_msg             NVARCHAR(MAX)    NULL
    );
    CREATE INDEX ix_audit_tenant_ts     ON api_audit.ai_audit_log (tenant_id, timestamp_utc DESC);
    CREATE INDEX ix_audit_conversation  ON api_audit.ai_audit_log (conversation_id);
    CREATE UNIQUE INDEX ux_audit_request ON api_audit.ai_audit_log (request_id);
END;
GO
