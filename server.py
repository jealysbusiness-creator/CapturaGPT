"""Proxy privado: consume un crédito antes de llamar a OpenAI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import re
import time
from pathlib import Path

import jwt
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from openai import OpenAI
from PIL import Image, UnidentifiedImageError

load_dotenv(Path(__file__).with_name(".env"))

app = FastAPI(title="Servidor proxy de análisis", docs_url=None, redoc_url=None)
logger = logging.getLogger("capturagpt")
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000

PROMPT = """
Analiza la captura completa de una pregunta de opción múltiple. Lee el enunciado,
las instrucciones, todas las alternativas y cualquier diagrama, tabla, cifra o
ilustración relevante.

Determina todas y solamente las alternativas correctas. No supongas que hay una
sola: el número correcto puede ser una, dos o más. Antes de responder, revisa de
forma independiente cada alternativa y confirma que la lista final incluye cada
alternativa correcta y ninguna incorrecta.

Usa las letras visibles de las alternativas. Si las alternativas no tienen letra,
asigna letras por posición visual: A para la primera, B para la segunda, y así
sucesivamente. Conserva el orden en que aparecen en la captura.

Si falta una parte esencial o la imagen es ilegible, indica que no es posible
resolverla. No inventes opciones ni selecciones una respuesta por defecto.
""".strip()

ANSWER_SCHEMA = {
    "type": "json_schema",
    "name": "multiple_choice_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "correct_count": {"type": "integer", "minimum": 0, "maximum": 26},
            "answer_ids": {
                "type": "array",
                "items": {"type": "string", "pattern": "^[A-Z]$"},
                "maxItems": 26,
            },
        },
        "required": ["answerable", "correct_count", "answer_ids"],
        "additionalProperties": False,
    },
}


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("PEGA_AQUI") or "TU-PROYECTO" in value:
        raise RuntimeError(f"Falta configurar {name} en el entorno privado del servidor.")
    return value


def prepare_image(upload: UploadFile) -> str:
    if upload.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(415, "Solo se aceptan imágenes JPEG o PNG.")
    raw = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "La imagen supera 8 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in ("JPEG", "PNG"):
                raise HTTPException(415, "El archivo no es JPEG o PNG.")
            if probe.width * probe.height > Image.MAX_IMAGE_PIXELS:
                raise HTTPException(413, "La imagen tiene demasiados píxeles.")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as source:
            image = source.convert("RGB")
            image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(415, "La imagen no es válida.") from None
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if (algorithm, n, r, p) != ("scrypt", "16384", "8", "1"):
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def supabase_headers() -> dict[str, str]:
    key = required_env("SUPABASE_SERVICE_ROLE_KEY")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def bind_account_device(username: str, hardware_id: str) -> int:
    url = required_env("SUPABASE_URL").rstrip("/")
    try:
        response = requests.post(
            f"{url}/rest/v1/rpc/bind_account_device",
            headers=supabase_headers(),
            json={"p_username": username, "p_hardware_id": hardware_id},
            timeout=(5, 15),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Account hardware binding failed: %s", type(exc).__name__)
        raise HTTPException(503, "No se pudo validar el equipo.") from exc
    if not isinstance(data, dict):
        raise HTTPException(503, "Respuesta inválida de cuentas.")
    if data.get("ok") is not True:
        raise HTTPException(403, data.get("error", "INVALID_CREDENTIALS"))
    credits = data.get("credits_left")
    if type(credits) is not int or credits < 0:
        raise HTTPException(503, "Respuesta inválida de cuentas.")
    return credits

def consume_account_credit(username: str, hardware: str) -> int:
    url = required_env("SUPABASE_URL").rstrip("/")
    try:
        r = requests.post(
            f"{url}/rest/v1/rpc/consume_account_credit",
            headers=supabase_headers(),
            json={"p_username": username, "p_hardware_id": hardware},
            timeout=(5, 15),
        )
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(503, "No se pudo validar la cuenta.") from exc
    if not isinstance(data, dict):
        raise HTTPException(503, "Respuesta inválida de cuentas.")
    if data.get("ok") is not True:
        code = data.get("error", "INVALID_CREDENTIALS")
        raise HTTPException(402 if code == "INSUFFICIENT_CREDITS" else 403, code)
    credits = data.get("credits_left")
    if type(credits) is not int or credits < 0:
        raise HTTPException(503, "Respuesta inválida de cuentas.")
    return credits

def consume_credit(license_key: str, hardware_id: str) -> int:
    url = required_env("SUPABASE_URL").rstrip("/")
    key = required_env("SUPABASE_SERVICE_ROLE_KEY")
    try:
        response = requests.post(
            f"{url}/rest/v1/rpc/consume_credit",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            json={"p_license_key": license_key, "p_hardware_id": hardware_id},
            timeout=(5, 15),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(503, "No se pudo validar la licencia.") from exc
    if not isinstance(data, dict):
        raise HTTPException(503, "Respuesta inválida del servicio de licencias.")
    if data.get("ok") is False:
        error = data.get("error", "INVALID_LICENSE")
        if error == "INSUFFICIENT_CREDITS":
            raise HTTPException(402, error)
        raise HTTPException(403, error)
    remaining = data.get("credits_left")
    if data.get("ok") is not True or type(remaining) is not int or remaining < 0:
        raise HTTPException(503, "Respuesta inválida del servicio de licencias.")
    return remaining


def parse_structured_answer(output_text: str) -> str:
    try:
        data = json.loads(output_text)
    except (TypeError, json.JSONDecodeError):
        raise ValueError("OpenAI respondió con un formato inesperado.") from None
    if not isinstance(data, dict) or type(data.get("answerable")) is not bool:
        raise ValueError("Respuesta estructurada inválida.")
    if data["answerable"] is False:
        return "No se puede verificar: la captura no muestra una pregunta completa y legible."
    ids = data.get("answer_ids")
    count = data.get("correct_count")
    if type(count) is not int or not isinstance(ids, list) or not ids or count != len(ids):
        raise ValueError("Respuesta estructurada inválida.")
    if len(ids) > 26 or len(set(ids)) != len(ids) or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Z]", item) for item in ids
    ):
        raise ValueError("Respuesta estructurada inválida.")
    if len(ids) == 1:
        return ids[0]
    if len(ids) == 2:
        return f"{ids[0]} y {ids[1]}"
    return ", ".join(ids[:-1]) + f" y {ids[-1]}"


@app.post("/api/v1/auth/login")
def login(username: str = Form(...), password: str = Form(...), hardware_id: str = Form(...)):
    username = username.strip()
    hardware_id = hardware_id.strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username)
        or not 8 <= len(password) <= 256
        or not re.fullmatch(r"[0-9a-f]{64}", hardware_id)
    ):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    try:
        signing_key = required_env("AUTH_TOKEN_SECRET")
    except RuntimeError:
        logger.error("AUTH_TOKEN_SECRET is missing")
        raise HTTPException(503, "Servidor de autenticación sin configurar.") from None
    try:
        r = requests.get(
            f"{required_env('SUPABASE_URL').rstrip('/')}/rest/v1/accounts",
            headers=supabase_headers(),
            params={"username": f"eq.{username}", "select": "password_hash,is_active"},
            timeout=(5, 15),
        )
        r.raise_for_status()
        rows = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(503, "No se pudo conectar con cuentas.") from exc
    if not isinstance(rows, list) or not rows or not rows[0].get("is_active"):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    if not verify_password(password, rows[0].get("password_hash", "")):
        raise HTTPException(401, "INVALID_CREDENTIALS")
    credits_left = bind_account_device(username, hardware_id)
    token = jwt.encode(
        {"sub": username, "hardware_id": hardware_id, "exp": int(time.time()) + 43200},
        signing_key,
        algorithm="HS256",
    )
    return {"access_token": token, "token_type": "bearer", "credits_left": credits_left}

def authenticated_user(authorization: str):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "AUTH_REQUIRED")
    try:
        data = jwt.decode(
            authorization[7:].strip(), required_env("AUTH_TOKEN_SECRET"), algorithms=["HS256"]
        )
        username = str(data["sub"])
        hardware_id = str(data["hardware_id"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username) or not re.fullmatch(r"[0-9a-f]{64}", hardware_id):
            raise ValueError("Invalid token claims")
        return username, hardware_id
    except Exception as exc:
        raise HTTPException(401, "INVALID_SESSION") from exc

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/analyze")
def analyze(
    image: UploadFile = File(...),
    authorization: str = Header(default=""),
) -> dict[str, str | int]:
    username, hardware_id = authenticated_user(authorization)
    try:
        openai_key = required_env("OPENAI_API_KEY")
    except RuntimeError:
        raise HTTPException(503, "Servidor sin configurar.") from None
    image_url = prepare_image(image)
    # El débito es atómico en PostgreSQL. Una petición rechazada nunca llega a OpenAI.
    credits_left = consume_account_credit(username, hardware_id)
    model = os.getenv("OPENAI_MODEL", "gpt-5.6").strip() or "gpt-5.6"
    kwargs = {"reasoning": {"effort": "high"}} if model.startswith("gpt-5") else {}
    try:
        response = OpenAI(api_key=openai_key, timeout=90, max_retries=0).responses.create(
            model=model,
            text={"format": ANSWER_SCHEMA},
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": PROMPT},
                {"type": "input_image", "image_url": image_url, "detail": "high"},
            ]}],
            **kwargs,
        )
        if not response.output_text:
            raise ValueError("OpenAI no devolvió texto analizable.")
        result = parse_structured_answer(response.output_text)
    except Exception as exc:
        # No se devuelve el detalle del proveedor ni secretos al cliente.
        logger.error(
            "Analysis failed after debit: type=%s status=%s code=%s detail=%s",
            type(exc).__name__,
            getattr(exc, "status_code", None),
            getattr(exc, "code", None),
            str(exc) if isinstance(exc, ValueError) else "hidden",
        )
        raise HTTPException(502, {"error": "ANALYSIS_FAILED", "credits_left": credits_left}) from exc
    return {"result": result, "credits_left": credits_left}





