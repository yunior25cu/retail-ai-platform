"""
004_seed_prolimpio_admin.py
Seed para tenant 24 (Prolimpio / vertical=produccion):

  1. Inserta config de presupuesto y rate limits en config.tenant_config
  2. Crea usuario admin_tenant (admin@prolimpio.com) en auth.users

Idempotente: ON CONFLICT DO NOTHING en todas las sentencias.
Lee credenciales de .env si existen; si no usa defaults.

Ejecutar:
    python db/migrations/004_seed_prolimpio_admin.py

Variables de entorno opcionales:
    PROLIMPIO_ADMIN_EMAIL     (default: admin@prolimpio.com)
    PROLIMPIO_ADMIN_PASSWORD  (default: Prolimpio2026!)
"""

import os
import sys
from pathlib import Path

# Cargar .env desde api/.env si las vars no estan en el entorno
_env_file = Path(__file__).parent.parent.parent / "api" / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            if key.strip() not in os.environ:
                os.environ[key.strip()] = val.strip()

import bcrypt
import psycopg2
import psycopg2.extras

PG_CONN = {
    "host":     os.getenv("PG_HOST",     "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DATABASE", "asistente-ia"),
    "user":     os.getenv("PG_USER",     "postgres"),
    "password": os.getenv("PG_PASSWORD", "postgres"),
}

# platform_tenant_id: used in JWT claims and config.tenant_config
PLATFORM_TENANT_ID = 24
TENANT_SLUG    = "prolimpio"
ADMIN_EMAIL    = os.getenv("PROLIMPIO_ADMIN_EMAIL",    "admin@prolimpio.com")
ADMIN_PASSWORD = os.getenv("PROLIMPIO_ADMIN_PASSWORD", "Prolimpio2026!")

# Config rows use platform_tenant_id (24) — this is what the API/JWT uses
_CONFIG_ROWS = [
    ("vertical",            "produccion"),
    ("monthly_budget_usd",  "5.00"),
    ("budget_alert_pct",    "80"),
    ("memory_turns",        "3"),
    ("suggestions_enabled", "true"),
    # Rate limits por rol (produccion vertical)
    ("rate_limit_director",   "50"),
    ("rate_limit_produccion", "30"),
    ("rate_limit_compras",    "30"),
]


def run() -> None:
    conn = psycopg2.connect(**PG_CONN)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Resolve internal auth tenant_id (FK in auth.users) from slug
    cur.execute(
        "SELECT id FROM auth.tenants WHERE slug = %s",
        (TENANT_SLUG,),
    )
    row = cur.fetchone()
    if not row:
        print(f"ERROR: No se encontró tenant con slug='{TENANT_SLUG}' en auth.tenants")
        conn.close()
        return
    auth_tenant_id = row["id"]
    print(f"Tenant '{TENANT_SLUG}': auth_tenant_id={auth_tenant_id}, platform_tenant_id={PLATFORM_TENANT_ID}")

    # ── 1. Config rows (usan platform_tenant_id) ───────────────────────────────
    print(f"\nInsertando config para platform_tenant_id={PLATFORM_TENANT_ID}...")
    for config_key, config_value in _CONFIG_ROWS:
        cur.execute(
            """
            INSERT INTO config.tenant_config (tenant_id, config_key, config_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, config_key) DO NOTHING
            """,
            (PLATFORM_TENANT_ID, config_key, config_value),
        )
        if cur.rowcount == 1:
            print(f"  + {config_key} = {config_value!r}")
        else:
            print(f"  ~ {config_key} ya existe (sin cambios)")
    conn.commit()

    # ── 2. Usuario admin_tenant (usa auth_tenant_id como FK) ──────────────────
    print(f"\nCreando usuario admin_tenant: {ADMIN_EMAIL}...")
    pw_hash = bcrypt.hashpw(ADMIN_PASSWORD.encode(), bcrypt.gensalt(12)).decode()

    cur.execute(
        """
        INSERT INTO auth.users
            (tenant_id, email, password_hash, role, is_active)
        VALUES
            (%s, %s, %s, 'admin_tenant', TRUE)
        ON CONFLICT (email) DO NOTHING
        """,
        (auth_tenant_id, ADMIN_EMAIL.lower().strip(), pw_hash),
    )
    if cur.rowcount == 1:
        conn.commit()
        cur.execute("SELECT id FROM auth.users WHERE email = %s", (ADMIN_EMAIL,))
        uid = cur.fetchone()["id"]
        print(f"  + Usuario creado: email={ADMIN_EMAIL}, id={uid}, role=admin_tenant")
    else:
        conn.commit()
        print(f"  ~ Usuario ya existia: email={ADMIN_EMAIL} (sin cambios)")

    conn.close()
    print("\nListo.")


if __name__ == "__main__":
    run()
