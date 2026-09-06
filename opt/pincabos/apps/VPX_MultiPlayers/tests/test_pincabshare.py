from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from pincabos_multiplayer.pincabshare import (
    NFT_TABLE_NAME,
    PinCabShareError,
    PinCabShareManager,
    validate_policy,
)
from pincabos_multiplayer.runtime import RuntimeLayout


NOW = 1_800_000_000.0


def state(
    *,
    peer_ip: str = "192.168.254.142",
    issued_at: float = NOW - 5,
    expires_at: float = NOW + 30,
    session_id: str = "mp-test",
    policy_session_id: str | None = None,
    enabled: bool = True,
) -> dict:
    return {
        "session": {
            "session_id": session_id,
            "room_code": "ABC123",
            "is_this_cabinet_member": True,
        },
        "pincabshare": {
            "version": 2,
            "enabled": enabled,
            "session_id": policy_session_id or session_id,
            "room_code": "ABC123",
            "local_cabinet_id": 1,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "peers": [
                {
                    "cabinet_id": 10,
                    "ip": peer_ip,
                }
            ],
        },
    }


class FakeNft:
    def __init__(self) -> None:
        self.table_exists = False
        self.commands: list[tuple[list[str], str | None]] = []
        self.applied_scripts: list[str] = []

    def __call__(
        self, command: list[str], script: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append((list(command), script))
        if command == ["nft", "list", "table", "inet", NFT_TABLE_NAME]:
            return subprocess.CompletedProcess(
                command, 0 if self.table_exists else 1, "", ""
            )
        if command == ["nft", "-c", "-f", "-"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["nft", "-f", "-"]:
            if script and f"table inet {NFT_TABLE_NAME}" in script:
                self.table_exists = True
            self.applied_scripts.append(script or "")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "unexpected")


class PinCabSharePolicyTests(unittest.TestCase):
    def test_valid_policy_accepts_only_exact_private_peer(self):
        policy = validate_policy(state(), now=NOW)

        self.assertEqual(policy.session_id, "mp-test")
        self.assertEqual(policy.local_cabinet_id, 1)
        self.assertEqual(policy.peer_cabinet_ids, (10,))
        self.assertEqual(policy.peer_ipv4, ("192.168.254.142",))

    def test_expired_policy_is_rejected(self):
        with self.assertRaisesRegex(PinCabShareError, "policy_expired"):
            validate_policy(
                state(issued_at=NOW - 60, expires_at=NOW - 1),
                now=NOW,
            )

    def test_policy_cannot_live_longer_than_90_seconds(self):
        with self.assertRaisesRegex(PinCabShareError, "policy_lifetime_too_long"):
            validate_policy(
                state(issued_at=NOW - 1, expires_at=NOW + 100),
                now=NOW,
            )

    def test_public_peer_ip_is_rejected(self):
        with self.assertRaisesRegex(PinCabShareError, "peer_ip_not_private_ipv4"):
            validate_policy(state(peer_ip="8.8.8.8"), now=NOW)

    def test_session_mismatch_is_rejected(self):
        with self.assertRaisesRegex(PinCabShareError, "session_mismatch"):
            validate_policy(
                state(policy_session_id="mp-other"),
                now=NOW,
            )


class PinCabShareManagerTests(unittest.TestCase):
    def test_valid_policy_installs_only_peer_ip_on_nfs_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = RuntimeLayout(Path(directory) / "VPX_MultiPlayers")
            layout.prepare_writable_directories()
            nft = FakeNft()
            manager = PinCabShareManager(layout, runner=nft)

            status = manager.reconcile(state(), now=NOW)

            self.assertTrue(status["enabled"])
            self.assertEqual(status["peer_ipv4"], ["192.168.254.142"])
            update = nft.applied_scripts[-1]
            self.assertIn("flush set inet pincabshare_v2 allowed_peers_v4", update)
            self.assertIn("192.168.254.142", update)
            self.assertNotIn("192.168.254.0/24", update)

    def test_missing_policy_revokes_all_peers(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = RuntimeLayout(Path(directory) / "VPX_MultiPlayers")
            layout.prepare_writable_directories()
            nft = FakeNft()
            manager = PinCabShareManager(layout, runner=nft)

            status = manager.reconcile(
                {
                    "session": {
                        "session_id": "mp-test",
                        "room_code": "ABC123",
                        "is_this_cabinet_member": True,
                    }
                },
                now=NOW,
            )

            self.assertFalse(status["enabled"])
            self.assertEqual(status["reason"], "policy_missing")
            self.assertEqual(status["peer_ipv4"], [])
            update = nft.applied_scripts[-1]
            self.assertIn("flush set inet pincabshare_v2 allowed_peers_v4", update)
            self.assertNotIn("add element", update)

    def test_expiry_removes_previously_authorized_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = RuntimeLayout(Path(directory) / "VPX_MultiPlayers")
            layout.prepare_writable_directories()
            nft = FakeNft()
            manager = PinCabShareManager(layout, runner=nft)

            active = manager.reconcile(state(), now=NOW)
            self.assertTrue(active["enabled"])

            expired = manager.reconcile(
                state(issued_at=NOW - 60, expires_at=NOW - 1),
                now=NOW,
            )

            self.assertFalse(expired["enabled"])
            self.assertEqual(expired["reason"], "policy_expired")
            update = nft.applied_scripts[-1]
            self.assertIn("flush set inet pincabshare_v2 allowed_peers_v4", update)
            self.assertNotIn("add element", update)

    def test_base_rules_drop_nfs_for_every_non_authorized_source(self):
        rules = PinCabShareManager._base_ruleset()

        self.assertIn("tcp dport 2049 drop", rules)
        self.assertIn("udp dport 2049 drop", rules)
        self.assertIn("ip saddr @allowed_peers_v4 tcp dport 2049 accept", rules)
        self.assertIn("ip saddr @allowed_peers_v4 udp dport 2049 accept", rules)


if __name__ == "__main__":
    unittest.main()
