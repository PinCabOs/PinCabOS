import importlib.util
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODULE = ROOT / "pincabshare.py"
spec = importlib.util.spec_from_file_location("pincabshare_test_module", MODULE)
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.original_fetch = p.fetch_wrapped_gate
        self.original_future = p.MAX_GATE_FUTURE_SECONDS
        p.MAX_GATE_FUTURE_SECONDS = 30
        self.now = time.time()

    def tearDown(self):
        p.fetch_wrapped_gate = self.original_fetch
        p.MAX_GATE_FUTURE_SECONDS = self.original_future

    def payload(self, *, expires_delta=10):
        expiry = datetime.fromtimestamp(
            self.now + expires_delta,
            timezone.utc,
        ).isoformat()
        gate = {
            "schema": "pincabshare-gate/v2",
            "enabled": True,
            "reason": "same_lobby_presence_fresh",
            "session_id": "mp-1",
            "room_code": "ABC123",
            "share_nonce": "a" * 64,
            "local_cabinet_id": 1,
            "expires_at": expiry,
            "members": [
                {
                    "cabinet_id": 1,
                    "cabinet_name": "Alpha",
                    "cabinet_label": "Alpha — CAB1",
                },
                {
                    "cabinet_id": 10,
                    "cabinet_name": "Beta",
                    "cabinet_label": "Beta — CAB10",
                },
            ],
        }
        return {
            "ok": True,
            "session": {
                "session_id": "mp-1",
                "room_code": "ABC123",
                "is_this_cabinet_member": True,
            },
            "pincabshare": gate,
        }

    def use(self, value):
        p.fetch_wrapped_gate = lambda: value

    def test_valid_gate(self):
        self.use(self.payload())
        gate = p.load_gate(now=self.now)
        self.assertEqual(gate.authorized_ids, {1, 10})
        self.assertEqual(gate.local_label, "Alpha — CAB1")

    def test_disabled_gate_is_closed(self):
        value = self.payload()
        value["pincabshare"]["enabled"] = False
        value["pincabshare"]["reason"] = "local_lobby_presence_stale"
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "local_lobby_presence_stale"):
            p.load_gate(now=self.now)

    def test_wrong_session_is_closed(self):
        value = self.payload()
        value["pincabshare"]["session_id"] = "mp-2"
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "session_mismatch"):
            p.load_gate(now=self.now)

    def test_wrong_room_is_closed(self):
        value = self.payload()
        value["pincabshare"]["room_code"] = "ZZZZ99"
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "room_mismatch"):
            p.load_gate(now=self.now)

    def test_invalid_nonce_is_closed(self):
        value = self.payload()
        value["pincabshare"]["share_nonce"] = "not-a-server-nonce"
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "nonce_invalid"):
            p.load_gate(now=self.now)

    def test_local_cabinet_must_be_member(self):
        value = self.payload()
        value["pincabshare"]["local_cabinet_id"] = 77
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "local_cabinet_not_member"):
            p.load_gate(now=self.now)

    def test_duplicate_member_is_closed(self):
        value = self.payload()
        value["pincabshare"]["members"][1]["cabinet_id"] = 1
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "member_id_duplicate"):
            p.load_gate(now=self.now)

    def test_expired_gate_is_closed(self):
        self.use(self.payload(expires_delta=-1))
        with self.assertRaisesRegex(p.GateError, "gate_expired"):
            p.load_gate(now=self.now)

    def test_gate_too_far_in_future_is_closed(self):
        self.use(self.payload(expires_delta=120))
        with self.assertRaisesRegex(p.GateError, "gate_expiry_too_far"):
            p.load_gate(now=self.now)

    def test_server_failure_is_closed(self):
        def fail():
            raise p.GateClientError("server_unreachable")

        p.fetch_wrapped_gate = fail
        with self.assertRaisesRegex(p.GateError, "gate_server:server_unreachable"):
            p.load_gate(now=self.now)


if __name__ == "__main__":
    unittest.main()
