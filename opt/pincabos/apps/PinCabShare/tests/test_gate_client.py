import importlib.util
import json
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

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
            return FakeResponse({"ok": True, "gate": "closed", "share_allowed": False})

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

    def test_404_on_canonical_falls_back_to_live_alias(self):
        seen = []

        def opener(request, **_kwargs):
            seen.append(request.full_url)
            if request.full_url.endswith("/api/device/pincabshare/state"):
                raise HTTPError(request.full_url, 404, "not found", {}, None)
            return FakeResponse({"ok": True, "gate": "closed", "share_allowed": False})

        value = g.fetch_gate(
            api_root="https://pincabos.cc",
            credentials_path=self.device,
            opener=opener,
        )

        self.assertTrue(value["ok"])
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[1].endswith("/api/device/multiplayer/share-gate"))

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

    def test_invalid_device_identity_is_rejected(self):
        self.device.write_text(
            json.dumps({"token_type": "PinCabOS-Device", "device_token": "short"}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(g.GateClientError, "pincabos_link_identity_invalid"):
            g.fetch_gate(
                credentials_path=self.device,
                opener=lambda *_args, **_kwargs: None,
            )


if __name__ == "__main__":
    unittest.main()
