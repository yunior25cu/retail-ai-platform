"""
005_audit_cost_columns.py
Agrega tokens_input, tokens_output y cost_usd a audit.conversation_log.

Los datos históricos se backfillean dividiendo tokens_used 50/50 input/output
(estimación neutral).  Las filas futuras serán exactas porque el persister
escribe los tres valores separados.

Ejecutar:
    python db/migrations/005_audit_cost_columns.py
"""

import os
import sys
from pathlib import Path

_env = Path(__file__).parent.parent.parent / "api" / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import psycopg2

PG = {
    "host":     os.getenv("PG_HOST",     "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DATABASE", "asistente-ia"),
    "user":     os.getenv("PG_USER",     "postgres"),
    "password": os.getenv("PG_PASSWORD", "postgres"),
}

MIGRATION = """
-- Step 1: add columns if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'audit'
          AND table_name   = 'conversation_log'
          AND column_name  = 'tokens_input'
    ) THEN
        ALTER TABLE audit.conversation_log
            ADD COLUMN tokens_input  INTEGER     NOT NULL DEFAULT 0,
            ADD COLUMN tokens_output INTEGER     NOT NULL DEFAULT 0,
            ADD COLUMN cost_usd      NUMERIC(10,6) NOT NULL DEFAULT 0.0;
        RAISE NOTICE 'Columns added: tokens_input, tokens_output, cost_usd';
    ELSE
        RAISE NOTICE 'Columns already exist — skipping ADD COLUMN';
    END IF;
END $$;

-- Step 2: backfill historical rows that have tokens_used but no input/output split
-- Split 50/50 (neutral estimate). cost_usd uses Sonnet 4.6 pricing:
--   input  $3.00 / 1M tokens
--   output $15.00 / 1M tokens
UPDATE audit.conversation_log
SET
    tokens_input  = COALESCE(tokens_used, 0) / 2,
    tokens_output = COALESCE(tokens_used, 0) - (COALESCE(tokens_used, 0) / 2),
    cost_usd      = ROUND(
        (COALESCE(tokens_used, 0) / 2        * 3.0  / 1000000.0) +
        ((COALESCE(tokens_used, 0) - (COALESCE(tokens_used, 0) / 2)) * 15.0 / 1000000.0),
        6
    )
WHERE tokens_input = 0
  AND COALESCE(tokens_used, 0) > 0;
"""


def run() -> None:
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute(MIGRATION)
    conn.commit()

    # Report final state
    cur.execute("""
        SELECT COUNT(*) AS total,
               SUM(tokens_used) AS total_tokens,
               SUM(cost_usd)    AS total_cost_usd
        FROM audit.conversation_log
    """)
    row = cur.fetchone()
    print(f"Migration complete.")
    print(f"  Rows in audit.conversation_log : {row[0]}")
    print(f"  Total tokens_used              : {row[1] or 0}")
    print(f"  Total cost_usd (backfilled)    : ${float(row[2] or 0):.6f}")
    conn.close()


if __name__ == "__main__":
    run()
