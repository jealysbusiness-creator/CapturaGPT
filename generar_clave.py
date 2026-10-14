"""Genera una licencia de prueba de 50 créditos con la clave privada del servidor."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).with_name(".env"))


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Configura {name} en backend_servidor/.env.")
    return value


def generate_license() -> str:
    url = required_env("SUPABASE_URL")
    key = required_env("SUPABASE_SERVICE_ROLE_KEY")
    license_key = str(uuid.uuid4())
    client = create_client(url, key)
    result = client.table("licenses").insert({
        "license_key": license_key,
        "credits_remaining": 50,
    }).execute()
    if not result.data or result.data[0].get("license_key") != license_key:
        raise RuntimeError("Supabase no confirmó la creación de la licencia.")
    return license_key


def main() -> int:
    try:
        license_key = generate_license()
    except Exception as exc:
        print(f"No se pudo crear la licencia ({type(exc).__name__}). Revisa .env, permisos y esquema SQL.", file=sys.stderr)
        return 1
    print(f"Licencia: {license_key}")
    print("Créditos iniciales: 50")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
