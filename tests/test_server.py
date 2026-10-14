"""Pruebas sin secretos ni consumo real de créditos."""

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generar_clave  # noqa: E402
import server  # noqa: E402


def jpeg() -> bytes:
    image = Image.new("RGB", (20, 20), "white")
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.fields = {"license_key": "test-license", "hardware_id": "a" * 64}

    def test_rejected_credit_never_calls_openai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
             patch.object(server, "consume_credit", side_effect=HTTPException(402, "INSUFFICIENT_CREDITS")), \
             patch.object(server, "OpenAI") as openai:
            response = self.client.post("/api/v1/analyze", data=self.fields,
                                        files={"image": ("test.jpg", jpeg(), "image/jpeg")})
        self.assertEqual(response.status_code, 402)
        openai.assert_not_called()

    def test_invalid_image_never_debits(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
             patch.object(server, "consume_credit") as debit:
            response = self.client.post("/api/v1/analyze", data=self.fields,
                                        files={"image": ("bad.jpg", b"invalid", "image/jpeg")})
        self.assertEqual(response.status_code, 415)
        debit.assert_not_called()

    def test_success_returns_result_and_balance(self):
        fake = Mock()
        fake.responses.create.return_value.output_text = json.dumps({
            "answerable": True, "correct_count": 1, "answer_ids": ["C"]
        })
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
             patch.object(server, "consume_credit", return_value=49), \
             patch.object(server, "OpenAI", return_value=fake):
            response = self.client.post("/api/v1/analyze", data=self.fields,
                                        files={"image": ("test.jpg", jpeg(), "image/jpeg")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"result": "C", "credits_left": 49})

    def test_generator_inserts_50_credits(self):
        fake = Mock()
        result = Mock(data=[{"license_key": "fixed-key"}])
        fake.table.return_value.insert.return_value.execute.return_value = result
        with patch.dict(os.environ, {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "test-only",
        }), patch.object(generar_clave.uuid, "uuid4", return_value="fixed-key"), \
             patch.object(generar_clave, "create_client", return_value=fake):
            key = generar_clave.generate_license()
        self.assertEqual(key, "fixed-key")
        fake.table.assert_called_once_with("licenses")
        fake.table.return_value.insert.assert_called_once_with({
            "license_key": "fixed-key", "credits_remaining": 50,
        })


if __name__ == "__main__":
    unittest.main()
