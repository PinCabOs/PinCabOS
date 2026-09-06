from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pincabos_multiplayer.client import (
    DeviceCredentials,
    MultiplayerClientError,
    ServerClient,
    load_credentials,
    normalize_room_code,
)


class FakeResponse:
    status = 200

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return json.dumps(self.value).encode("utf-8")


class ClientTests(unittest.TestCase):
    def test_room_code_is_normalized_and_strict(self):
        self.assertEqual(normalize_room_code(" ab-cd 23 "), "ABCD23")
        with self.assertRaises(MultiplayerClientError):
            normalize_room_code("ABC")

    def test_credentials_are_loaded_without_exposing_the_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "device.json"
            path.write_text(
                json.dumps(
                    {
                        "token_type": "PinCabOS-Device",
                        "device_token": "s" * 48,
                        "cabinet": {"cabinet_uuid": "cab-uuid"},
                    }
                ),
                encoding="utf-8",
            )
            value = load_credentials(path)
        self.assertEqual(value.cabinet_uuid, "cab-uuid")
        self.assertNotIn(value.token, repr(value))

    def test_only_multiplayer_device_endpoints_are_allowed(self):
        client = ServerClient(
            DeviceCredentials("PinCabOS-Device", "s" * 48, "cab-1"),
            opener=lambda *_args, **_kwargs: FakeResponse({"ok": True}),
        )
        with self.assertRaises(MultiplayerClientError):
            client.request("GET", "/api/me")

    def test_state_keeps_control_contract_when_pincabshare_route_is_missing(self):
        client = ServerClient(
            DeviceCredentials("PinCabOS-Device", "s" * 48, "cab-1"),
            opener=lambda *_args, **_kwargs: FakeResponse({"ok": True}),
        )
        calls = []

        def request(method, path, payload=None):
            calls.append((method, path, payload))
            if path == "/api/device/multiplayer/state":
                return {
                    "ok": True,
                    "session": {"session_id": "mp-test"},
                    "control": {"desired": "released", "generation": 1},
                }
            raise MultiplayerClientError("server_http_404")

        client.request = request
        value = client.state()

        self.assertEqual(value["control"]["desired"], "released")
        self.assertFalse(value["pincabshare"]["enabled"])
        self.assertEqual(
            value["pincabshare"]["reason"],
            "policy-endpoint-unavailable",
        )
        self.assertEqual(
            [path for _method, path, _payload in calls],
            [
                "/api/device/multiplayer/state",
                "/api/device/multiplayer/pincabshare",
            ],
        )

    def test_state_merges_valid_pincabshare_policy(self):
        client = ServerClient(
            DeviceCredentials("PinCabOS-Device", "s" * 48, "cab-1"),
            opener=lambda *_args, **_kwargs: FakeResponse({"ok": True}),
        )

        def request(_method, path, _payload=None):
            if path == "/api/device/multiplayer/state":
                return {"ok": True, "control": {"desired": "released"}}
            return {
                "ok": True,
                "pincabshare": {
                    "version": 2,
                    "enabled": True,
                    "session_id": "mp-test",
                    "room_code": "ABC123",
                    "local_cabinet_id": 1,
                    "issued_at": "2026-09-06T22:00:00Z",
                    "expires_at": "2026-09-06T22:00:12Z",
                    "peers": [
                        {"cabinet_id": 10, "ip": "192.168.254.142"}
                    ],
                },
            }

        client.request = request
        value = client.state()

        self.assertTrue(value["pincabshare"]["enabled"])
        self.assertEqual(value["pincabshare"]["peers"][0]["cabinet_id"], 10)

    def test_join_sends_normalized_room_code(self):
        captured = {}

        def opener(request, **_kwargs):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["authorization"] = request.headers["Authorization"]
            return FakeResponse({"ok": True, "room_code": "ABC123"})

        client = ServerClient(
            DeviceCredentials("PinCabOS-Device", "s" * 48, "cab-1"),
            opener=opener,
        )
        result = client.join("abc-123")
        self.assertEqual(result["room_code"], "ABC123")
        self.assertEqual(captured["body"], {"room_code": "ABC123"})
        self.assertTrue(captured["authorization"].startswith("PinCabOS-Device "))

    def test_control_ack_uses_device_endpoint_and_strict_state(self):
        captured = {}

        def opener(request, **_kwargs):
            captured["path"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"ok": True})

        client = ServerClient(
            DeviceCredentials("PinCabOS-Device", "s" * 48, "cab-1"),
            opener=opener,
        )
        client.control_ack(
            "mp-test",
            12,
            "armed",
            ok=True,
            detail=None,
        )

        self.assertTrue(captured["path"].endswith("/api/device/multiplayer/control-ack"))
        self.assertEqual(
            captured["body"],
            {
                "session_id": "mp-test",
                "generation": 12,
                "state": "armed",
                "ok": True,
                "detail": None,
            },
        )

        with self.assertRaises(MultiplayerClientError):
            client.control_ack("mp-test", 12, "shell", ok=True)


if __name__ == "__main__":
    unittest.main()
