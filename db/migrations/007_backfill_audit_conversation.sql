/* ============================================================
 * 007_backfill_audit_conversation.sql
 *
 * Purpose
 *   Completar la migration 006 (que creó audit.conversation y
 *   audit.conversation_message en PostgreSQL pero no migró los
 *   conversation_ids que ya existían en audit.conversation_log).
 *
 * Causa raíz
 *   El commit 662202e introdujo routing PG en load_conversation, que
 *   ahora exige audit.conversation. Las conversaciones anteriores al
 *   commit nunca se persistieron ahí — quedaron únicamente en
 *   conversation_log (escrito por persist_audit_row). El primer chat
 *   follow-up con un conv_id viejo devuelve 404.
 *
 * Qué hace
 *   Inserta en audit.conversation un registro por cada conversation_id
 *   que aparece en conversation_log pero no en audit.conversation.
 *   user_id se recupera del log (puede ser NULL en el log; default 'unknown').
 *   user_role queda en 'produccion' (default seguro para tenant 24);
 *   no podemos derivarlo del log porque no se guarda ahí.
 *   started_at / last_message_at se derivan del MIN/MAX de created_at.
 *
 * Idempotente
 *   ON CONFLICT (conversation_id) DO NOTHING + WHERE NOT EXISTS.
 *   Re-ejecutar no duplica filas.
 *
 * Aplica solo a PostgreSQL (tenants con audit.conversation_log).
 * ============================================================ */

INSERT INTO audit.conversation
    (conversation_id, tenant_id, user_id, user_role,
     title, started_at, last_message_at)
SELECT
    cl.conversation_id,
    cl.tenant_id,
    COALESCE(MAX(cl.user_id::text), 'unknown'),
    'produccion',
    NULL,
    MIN(cl.created_at),
    MAX(cl.created_at)
FROM audit.conversation_log cl
WHERE NOT EXISTS (
    SELECT 1 FROM audit.conversation c
    WHERE c.conversation_id = cl.conversation_id
)
GROUP BY cl.conversation_id, cl.tenant_id
ON CONFLICT (conversation_id) DO NOTHING;

-- Verificación (no falla la migration, solo informa)
DO $$
DECLARE
    v_backfilled INT;
    v_total      INT;
BEGIN
    SELECT COUNT(*) INTO v_total FROM audit.conversation;
    SELECT COUNT(DISTINCT conversation_id) INTO v_backfilled
        FROM audit.conversation_log
        WHERE EXISTS (
            SELECT 1 FROM audit.conversation c
            WHERE c.conversation_id = conversation_log.conversation_id
        );
    RAISE NOTICE 'audit.conversation rows: %  (backfilled from log: %)',
        v_total, v_backfilled;
END $$;
