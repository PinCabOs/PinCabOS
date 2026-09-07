import importlib.util
import json
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "gate_client.py"
spec = importlib.util.spec_from_file_location("pincabshare_gate_client_test", MODULE)
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self._raw


class GateClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.device = Path(self.tmp.name) / "device.json"
        self.device.write_text(
            json.dumps(
                {
                    "token_type": "PinCabOS-Device",
                    "device_token": "x" * 40,
                    "cabinet": {"cabinet_uuid": "cab-test"},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_https_gate_request_uses_device_authorization(self):
        seen = {}

        def opener(request, **kwargs):
            seen["url"] = request.full_url
            seen["authorization"] = request.headers.get("Authorization")
            seen["timeout"] = kwargs.get("timeout")
            seen["context"] = kwargs.get("context")
            return FakeResponse(
                {
                    "ok": True,
                    "schema": "pincabshare-gate/v2",
                    "enabled": False,
                    "reason": "not_enough_fresh_lobby_members",
                }
            )

        value = g.fetch_gate(
            api_root="https://pincabos.cc",
            timeout=2,
            credentials_path=self.device,
            opener=opener,
        )

        self.assertTrue(value["ok"])
        self.assertEqual(
            seen["url"],
            "https://pincabos.cc/api/device/pincabshare/state",
        )
        self.assertEqual(
            seen["authorization"],
            "PinCabOS-Device " + "x" * 40,
        )
        self.assertEqual(seen["timeout"], 2.0)
        self.assertIsInstance(seen["context"], ssl.SSLContext)

    def test_plain_http_is_rejected(self):
        with self.assertRaisesRegex(g.GateClientError, "https_required"):
            g.fetch_gate(
                api_root="http://pincabos.cc",
                credentials_path=self.device,
                opener=lambda *_args, **_kwargs: None,
            )

    def test_server_unreachable_is_safe_error(self):
        def opener(*_args, **_kwargs):
            raise URLError("offline")

        with self.assertRaisesRegex(g.GateClientError, "server_unreachable"):
            g.fetch_gate(
                credentials_path=self.device,
                opener=opener,
            )

    def test_wrapped_gate_marks_membership_only_when_enabled(self):
        original = g.fetch_gate
        try:
            g.fetch_gate = lambda **_kwargs: {
                "ok": True,
                "schema": "pincabshare-gate/v2",
                "enabled": True,
                "session_id": "mp-1",
                "room_code": "ABC123",
            }
            wrapped = g.fetch_wrapped_gate()
        finally:
            g.fetch_gate = original

        self.assertEqual(wrapped["session"]["session_id"], "mp-1")
        self.assertEqual(wrapped["session"]["room_code"], "ABC123")
        self.assertTrue(wrapped["session"]["is_this_cabinet_member"])


if __name__ == "__main__":
    unittest.main()
