"""
013_conversation_message_cards.py
Agrega cards_json y request_id a conversation_message (PostgreSQL y SQL Server).

Para que el historial de una conversacion muestre las tarjetas (tablas, KPIs,
acciones preparadas) y permita calificar las respuestas, el orquestador guarda
con cada respuesta del asistente sus tarjetas y el request_id. No van dentro de
content_json porque ese campo se le reenvia a Claude como historia.

Idempotente: solo agrega las columnas que faltan. La API funciona antes y
despues de correrla (sin las columnas guarda y lee solo el texto), y no hace
falta reiniciarla despues: vuelve a intentar las columnas cada 10 minutos.

Ejecutar:
    python db/migrations/013_conversation_message_cards.py            # ambos
    python db/migrations/013_conversation_message_cards.py --pg       # solo PostgreSQL
    python db/migrations/013_conversation_message_cards.py --ss       # solo SQL Server

SQL Server usa la misma conexion que la API (SQL_SERVER, SQL_DATABASE, etc. en api/.env).
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

PG_DDL = """
ALTER TABLE audit.conversation_message ADD COLUMN IF NOT EXISTS cards_json TEXT NULL;
ALTER TABLE audit.conversation_message ADD COLUMN IF NOT EXISTS request_id VARCHAR(64) NULL;
"""

SS_DDL = [
    """IF COL_LENGTH('api_audit.conversation_message', 'cards_json') IS NULL
           ALTER TABLE api_audit.conversation_message ADD cards_json NVARCHAR(MAX) NULL;""",
    """IF COL_LENGTH('api_audit.conversation_message', 'request_id') IS NULL
           ALTER TABLE api_audit.conversation_message ADD request_id NVARCHAR(64) NULL;""",
]


def run_pg() -> None:
    import psycopg2

    conn = psycopg2.connect(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        dbname=os.getenv("PG_DATABASE", "asistente-ia"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", "postgres"),
    )
    try:
        cur = conn.cursor()
        cur.execute(PG_DDL)
        conn.commit()
        cur.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'audit' AND table_name = 'conversation_message'
                 AND column_name IN ('cards_json', 'request_id')"""
        )
        print("PostgreSQL audit.conversation_message:", sorted(r[0] for r in cur.fetchall()))
    finally:
        conn.close()


def run_ss() -> None:
    import pyodbc

    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))
    from app.config.settings import settings

    if not settings.sql_server:
        print("SQL Server: SQL_SERVER no definido, se omite.")
        return
    conn = pyodbc.connect(settings.odbc_connection_string, autocommit=True)
    try:
        cur = conn.cursor()
        for ddl in SS_DDL:
            cur.execute(ddl)
        cur.execute(
            """SELECT name FROM sys.columns
               WHERE object_id = OBJECT_ID('api_audit.conversation_message')
                 AND name IN ('cards_json', 'request_id')"""
        )
        print("SQL Server api_audit.conversation_message:", sorted(r[0] for r in cur.fetchall()))
    finally:
        conn.close()


if __name__ == "__main__":
    args = set(sys.argv[1:])
    if not args or "--pg" in args:
        run_pg()
    if not args or "--ss" in args:
        run_ss()
