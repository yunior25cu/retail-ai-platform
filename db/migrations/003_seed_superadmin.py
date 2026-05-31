"""
003_seed_superadmin.py
Crea el usuario superadmin en auth.users (PostgreSQL).

Lee credenciales de .env (nunca hardcodeadas en codigo).
Si el email ya existe no duplica (idempotente).

Ejecutar: python db/migrations/003_seed_superadmin.py
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

PG_CONN = {
    "host":     os.getenv("PG_HOST",     "localhost"),
    "port":     int(os.getenv("PG_PORT", "5432")),
    "dbname":   os.getenv("PG_DATABASE", "asistente-ia"),
    "user":     os.getenv("PG_USER",     "postgres"),
    "password": os.getenv("PG_PASSWORD", "postgres"),
}

SUPERADMIN_EMAIL    = os.getenv("SUPERADMIN_EMAIL")
SUPERADMIN_PASSWORD = os.getenv("SUPERADMIN_PASSWORD")

if not SUPERADMIN_EMAIL or not SUPERADMIN_PASSWORD:
    print("ERROR: SUPERADMIN_EMAIL y SUPERADMIN_PASSWORD deben estar en .env")
    sys.exit(1)


def run() -> None:
    pw_hash = bcrypt.hashpw(
        SUPERADMIN_PASSWORD.encode(), bcrypt.gensalt(12)
    ).decode()

    conn = psycopg2.connect(**PG_CONN)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO auth.users
            (tenant_id, email, password_hash, role, is_active)
        VALUES
            (NULL, %s, %s, 'superadmin', TRUE)
        ON CONFLICT (email) DO NOTHING
        """,
        (SUPERADMIN_EMAIL, pw_hash),
    )
    affected = cur.rowcount
    conn.commit()

    if affected == 1:
        cur.execute("SELECT id FROM auth.users WHERE email = %s", (SUPERADMIN_EMAIL,))
        uid = cur.fetchone()[0]
        print(f"Superadmin creado: email={SUPERADMIN_EMAIL}, id={uid}, role=superadmin")
    else:
        print(f"Superadmin ya existia: email={SUPERADMIN_EMAIL} (sin cambios)")

    conn.close()


if __name__ == "__main__":
    run()
