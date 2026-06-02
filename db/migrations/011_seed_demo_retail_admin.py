"""
011_seed_demo_retail_admin.py

FASE 5+6 — Setup del tenant 23 (Demo Retail Co) en PostgreSQL:
  1. Inserta auth.tenants (slug='demo-retail', vertical='retail',
     platform_tenant_id=23). FK que usa auth.users.
  2. Inserta config.tenant_config (8 settings: vertical, budget,
     memory, suggestions, rate-limits por rol).
  3. Crea 5 usuarios en auth.users:
        - admin@demo-retail.com         admin_tenant
        - director@demo-retail.com      direccion
        - marca@demo-retail.com         marca
        - tienda@demo-retail.com        tienda
        - producto@demo-retail.com      sku
     Passwords: patron legible DemoRetail2026!@<role>, hash bcrypt
     cost 12. Reporta credenciales al final del log.

Idempotente: ON CONFLICT DO NOTHING en todas las sentencias. Re-ejecutar
no crea duplicados. Si el usuario ya existe el password NO se cambia.

Ejecutar:
    python db/migrations/011_seed_demo_retail_admin.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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

PLATFORM_TENANT_ID = 23
TENANT_SLUG    = "demo-retail"
TENANT_NAME    = "Demo Retail Co"
TENANT_VERTICAL = "retail"

# Config per Demo Retail Co: vertical retail con 4 roles (director,
# marca, tienda, sku). Mismos defaults que Prolimpio pero con los
# rate-limit keys del retail (no _produccion / _compras).
_CONFIG_ROWS = [
    ("vertical",            "retail"),
    ("monthly_budget_usd",  "5.00"),
    ("budget_alert_pct",    "80"),
    ("memory_turns",        "3"),
    ("suggestions_enabled", "true"),
    ("rate_limit_director", "50"),
    ("rate_limit_marca",    "30"),
    ("rate_limit_tienda",   "15"),
    ("rate_limit_producto", "15"),
]

# (email_local, role, plain_password). Patron legible para testing
# inicial — rotar via UI/admin antes de produccion real.
_USERS = [
    ("admin",     "admin_tenant", "DemoRetail2026!@admin"),
    ("director",  "direccion",    "DemoRetail2026!@director"),
    ("marca",     "marca",        "DemoRetail2026!@marca"),
    ("tienda",    "tienda",       "DemoRetail2026!@tienda"),
    ("producto",  "sku",          "DemoRetail2026!@producto"),
]

EMAIL_DOMAIN = "demo-retail.com"


def run() -> None:
    conn = psycopg2.connect(**PG_CONN)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ── 1. Tenant en auth.tenants ──────────────────────────────────────
    print(f"\n=== Tenant {PLATFORM_TENANT_ID} ({TENANT_NAME}) ===")
    cur.execute(
        """
        INSERT INTO auth.tenants
            (slug, name, vertical, platform_tenant_id, is_active)
        VALUES (%s, %s, %s, %s, TRUE)
        ON CONFLICT (slug) DO NOTHING
        """,
        (TENANT_SLUG, TENANT_NAME, TENANT_VERTICAL, PLATFORM_TENANT_ID),
    )
    conn.commit()

    cur.execute("SELECT id FROM auth.tenants WHERE slug = %s", (TENANT_SLUG,))
    auth_tenant_id = cur.fetchone()["id"]
    print(f"  auth.tenants.id = {auth_tenant_id}  (platform_tenant_id={PLATFORM_TENANT_ID})")

    # ── 2. Config rows (platform_tenant_id) ────────────────────────────
    print(f"\nConfig (platform_tenant_id={PLATFORM_TENANT_ID}):")
    for k, v in _CONFIG_ROWS:
        cur.execute(
            """
            INSERT INTO config.tenant_config (tenant_id, config_key, config_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, config_key) DO NOTHING
            """,
            (PLATFORM_TENANT_ID, k, v),
        )
        mark = "+" if cur.rowcount == 1 else "~"
        print(f"  {mark} {k:<22} = {v!r}")
    conn.commit()

    # ── 3. Usuarios ────────────────────────────────────────────────────
    print("\nUsuarios:")
    created = []
    skipped = []
    for local, role, plain_pw in _USERS:
        email = f"{local}@{EMAIL_DOMAIN}"
        pw_hash = bcrypt.hashpw(plain_pw.encode(), bcrypt.gensalt(12)).decode()
        cur.execute(
            """
            INSERT INTO auth.users
                (tenant_id, email, password_hash, role, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            ON CONFLICT (email) DO NOTHING
            """,
            (auth_tenant_id, email.lower().strip(), pw_hash, role),
        )
        if cur.rowcount == 1:
            cur.execute("SELECT id FROM auth.users WHERE email = %s", (email,))
            uid = cur.fetchone()["id"]
            created.append((email, role, plain_pw, uid))
            print(f"  + {email:<30} role={role:<14} id={uid}")
        else:
            skipped.append(email)
            print(f"  ~ {email:<30} role={role:<14} ya existia")
        conn.commit()

    conn.close()

    # ── 4. Resumen credenciales ────────────────────────────────────────
    if created:
        print("\n=== CREDENCIALES (guardar en gestor seguro) ===")
        print(f"  slug:  {TENANT_SLUG}")
        print(f"  domain: {EMAIL_DOMAIN}")
        print()
        print(f"  {'email':<32} {'role':<14} password")
        print(f"  {'-'*32} {'-'*14} {'-'*30}")
        for email, role, pw, _ in created:
            print(f"  {email:<32} {role:<14} {pw}")
        print()
        print("  Login: POST /api/v1/auth/login")
        print("         {'tenant_slug':'demo-retail', 'email':'...', 'password':'...'}")
    if skipped:
        print(f"\n  {len(skipped)} usuarios ya existian (password no modificado).")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
