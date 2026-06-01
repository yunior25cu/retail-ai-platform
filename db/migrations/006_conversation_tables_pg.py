"""
006_conversation_tables_pg.py
Crea las tablas de conversación en PostgreSQL (schema audit).

Antes las conversaciones solo se guardaban en SQL Server (api_audit.conversation).
En modo standalone (sin SQL Server), las escrituras fallaban silenciosamente.

Ejecutar:
    python db/migrations/006_conversation_tables_pg.py
"""

import os
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

DDL = """
CREATE TABLE IF NOT EXISTS audit.conversation (
    conversation_id VARCHAR(36)  PRIMARY KEY,
    tenant_id       INTEGER      NOT NULL,
    user_id         VARCHAR(100),
    user_role       VARCHAR(50),
    title           VARCHAR(200),
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_conv_tenant_user
    ON audit.conversation (tenant_id, user_id, last_message_at DESC);

CREATE TABLE IF NOT EXISTS audit.conversation_message (
    id              BIGSERIAL    PRIMARY KEY,
    conversation_id VARCHAR(36)  NOT NULL REFERENCES audit.conversation(conversation_id) ON DELETE CASCADE,
    sequence        INTEGER      NOT NULL,
    role            VARCHAR(20)  NOT NULL,
    content_json    TEXT         NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (conversation_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_conv_msg_conv_id
    ON audit.conversation_message (conversation_id, sequence ASC);
"""


def run() -> None:
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM audit.conversation")
    n_conv = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM audit.conversation_message")
    n_msg = cur.fetchone()[0]
    print("Tablas creadas (o ya existian):")
    print(f"  audit.conversation        : {n_conv} filas")
    print(f"  audit.conversation_message: {n_msg} filas")
    conn.close()


if __name__ == "__main__":
    run()
