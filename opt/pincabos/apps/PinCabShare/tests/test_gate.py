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
        self.original_fetch = p.fetch_gate
        self.now = time.time()

    def tearDown(self):
        p.fetch_gate = self.original_fetch

    def payload(self, *, expires_delta=7):
        return {
            "ok": True,
            "schema": "pincabshare-gate/v2",
            "enabled": True,
            "share_allowed": True,
            "gate": "open",
            "reason": "authorized",
            "session_id": "mp-1",
            "room_code": "ABC123",
            "share_nonce": "a" * 64,
            "local_cabinet_id": 1,
            "gate_ttl_seconds": 8,
            "expires_at": datetime.fromtimestamp(
                self.now + expires_delta,
                timezone.utc,
            ).isoformat(),
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

    def use(self, value):
        p.fetch_gate = lambda **_kwargs: value

    def test_valid_gate(self):
        self.use(self.payload())
        gate = p.load_gate(now=self.now)
        self.assertEqual(gate.authorized_ids, {1, 10})
        self.assertEqual(gate.local_label, "Alpha — CAB1")
        self.assertEqual(gate.gate_ttl_seconds, 8)
        self.assertEqual(len(gate.session_hash), 16)
        self.assertEqual(len(gate.gate_tag), 16)

    def test_server_closed_gate_is_immediate_close(self):
        value = self.payload()
        value["enabled"] = False
        value["share_allowed"] = False
        value["gate"] = "closed"
        value["reason"] = "not_enough_present_cabinets"
        self.use(value)
        with self.assertRaisesRegex(p.GateClosed, "not_enough_present_cabinets"):
            p.load_gate(now=self.now)

    def test_local_cabinet_must_be_member(self):
        value = self.payload()
        value["local_cabinet_id"] = 77
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "local_cabinet_not_member"):
            p.load_gate(now=self.now)

    def test_duplicate_member_is_closed(self):
        value = self.payload()
        value["members"][1]["cabinet_id"] = 1
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "member_id_duplicate"):
            p.load_gate(now=self.now)

    def test_invalid_nonce_is_closed(self):
        value = self.payload()
        value["share_nonce"] = "not-a-nonce"
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "share_nonce_invalid"):
            p.load_gate(now=self.now)

    def test_expired_gate_is_closed(self):
        self.use(self.payload(expires_delta=-1))
        with self.assertRaisesRegex(p.GateError, "gate_expired"):
            p.load_gate(now=self.now)

    def test_gate_ttl_above_fail_closed_limit_is_rejected(self):
        value = self.payload()
        value["gate_ttl_seconds"] = 30
        self.use(value)
        with self.assertRaisesRegex(p.GateError, "gate_ttl_invalid"):
            p.load_gate(now=self.now)

    def test_gate_too_far_in_future_is_closed(self):
        self.use(self.payload(expires_delta=30))
        with self.assertRaisesRegex(p.GateError, "gate_expiry_too_far"):
            p.load_gate(now=self.now)

    def test_live_compatibility_alias_without_expires_at_uses_short_ttl(self):
        value = self.payload()
        value.pop("expires_at")
        value.pop("schema")
        value.pop("share_nonce")
        self.use(value)
        gate = p.load_gate(now=self.now)
        self.assertGreater(gate.expires_at, self.now)
        self.assertLessEqual(gate.expires_at, self.now + 8)
        self.assertEqual(gate.gate_tag, "")

    def test_server_failure_is_propagated_for_lease_logic(self):
        def fail(**_kwargs):
            raise p.GateClientError("server_unreachable")

        p.fetch_gate = fail
        with self.assertRaisesRegex(p.GateClientError, "server_unreachable"):
            p.load_gate(now=self.now)


if __name__ == "__main__":
    unittest.main()
