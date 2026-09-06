"""PinCabShare V2: autorisation NFS éphémère pilotée par le Lobby.

Le serveur authentifié fournit une politique courte durée dans
`/api/device/multiplayer/state`. Le cabinet n'autorise que les IPv4 privées
des autres cabinets du même Lobby. Une politique absente, expirée ou invalide
révoque immédiatement l'accès NFS 2049 (fail-closed).

Ce module ne découvre jamais les pairs sur le LAN et ne touche ni VPX privé,
ni BGFX privé, ni VPinFE.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .runtime import RuntimeLayout


NFT_TABLE_FAMILY = "inet"
NFT_TABLE_NAME = "pincabshare_v2"
NFS_PORT = 2049
POLICY_VERSION = 2
MAX_POLICY_LIFETIME_SECONDS = 90.0
CLOCK_SKEW_SECONDS = 10.0


class PinCabShareError(RuntimeError):
    pass


@dataclass(frozen=True)
class PinCabSharePolicy:
    session_id: str
    room_code: str
    local_cabinet_id: int
    peer_cabinet_ids: tuple[int, ...]
    peer_ipv4: tuple[str, ...]
    issued_at: float
    expires_at: float


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _timestamp(value: object) -> float:
    if isinstance(value, bool):
        raise PinCabShareError("timestamp_invalid")
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise PinCabShareError("timestamp_invalid")
        try:
            result = float(raw)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError as exc:
                raise PinCabShareError("timestamp_invalid") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            result = parsed.timestamp()
    else:
        raise PinCabShareError("timestamp_invalid")
    if result <= 0:
        raise PinCabShareError("timestamp_invalid")
    return result


def _positive_int(value: object, error: str) -> int:
    if isinstance(value, bool):
        raise PinCabShareError(error)
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PinCabShareError(error) from exc
    if result <= 0:
        raise PinCabShareError(error)
    return result


def _peer_ipv4(value: object) -> str:
    try:
        address = ipaddress.ip_address(str(value or "").strip())
    except ValueError as exc:
        raise PinCabShareError("peer_ip_invalid") from exc
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise PinCabShareError("peer_ip_not_private_ipv4")
    return str(address)


def validate_policy(state: dict, *, now: float | None = None) -> PinCabSharePolicy:
    current_time = time.time() if now is None else float(now)
    session = state.get("session")
    policy = state.get("pincabshare")

    if not isinstance(policy, dict):
        raise PinCabShareError("policy_missing")
    if policy.get("version") != POLICY_VERSION:
        raise PinCabShareError("policy_version_invalid")
    if policy.get("enabled") is not True:
        raise PinCabShareError("policy_disabled")

    if not isinstance(session, dict):
        raise PinCabShareError("session_missing")
    session_id = str(session.get("session_id") or "").strip()
    if not session_id:
        raise PinCabShareError("session_missing")
    if not bool(session.get("is_this_cabinet_member")):
        raise PinCabShareError("cabinet_not_member")

    policy_session_id = str(policy.get("session_id") or "").strip()
    if policy_session_id != session_id:
        raise PinCabShareError("session_mismatch")

    room_code = str(policy.get("room_code") or "").strip().upper()
    session_room_code = str(session.get("room_code") or "").strip().upper()
    if not room_code or (session_room_code and room_code != session_room_code):
        raise PinCabShareError("room_mismatch")

    local_cabinet_id = _positive_int(
        policy.get("local_cabinet_id"), "local_cabinet_id_invalid"
    )

    issued_at = _timestamp(policy.get("issued_at"))
    expires_at = _timestamp(policy.get("expires_at"))
    if issued_at > current_time + CLOCK_SKEW_SECONDS:
        raise PinCabShareError("policy_from_future")
    if expires_at <= current_time:
        raise PinCabShareError("policy_expired")
    if expires_at <= issued_at:
        raise PinCabShareError("policy_window_invalid")
    if expires_at - issued_at > MAX_POLICY_LIFETIME_SECONDS:
        raise PinCabShareError("policy_lifetime_too_long")

    peers = policy.get("peers")
    if not isinstance(peers, list) or not (1 <= len(peers) <= 3):
        raise PinCabShareError("peers_invalid")

    cabinet_ids: list[int] = []
    addresses: list[str] = []
    seen_ids: set[int] = set()
    seen_addresses: set[str] = set()

    for peer in peers:
        if not isinstance(peer, dict):
            raise PinCabShareError("peer_invalid")
        cabinet_id = _positive_int(peer.get("cabinet_id"), "peer_cabinet_id_invalid")
        if cabinet_id == local_cabinet_id:
            raise PinCabShareError("peer_is_local_cabinet")
        address = _peer_ipv4(peer.get("ip"))

        if cabinet_id in seen_ids or address in seen_addresses:
            raise PinCabShareError("peer_duplicate")
        seen_ids.add(cabinet_id)
        seen_addresses.add(address)
        cabinet_ids.append(cabinet_id)
        addresses.append(address)

    return PinCabSharePolicy(
        session_id=session_id,
        room_code=room_code,
        local_cabinet_id=local_cabinet_id,
        peer_cabinet_ids=tuple(cabinet_ids),
        peer_ipv4=tuple(addresses),
        issued_at=issued_at,
        expires_at=expires_at,
    )


Runner = Callable[[list[str], str | None], subprocess.CompletedProcess[str]]


def _default_runner(
    command: list[str], script: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=script,
        check=False,
        capture_output=True,
        text=True,
    )


class PinCabShareManager:
    """Gère uniquement la barrière réseau NFS de PinCabShare V2."""

    def __init__(
        self,
        layout: RuntimeLayout,
        runner: Runner | None = None,
    ) -> None:
        self.layout = layout
        self.runner = runner or _default_runner
        self.state_path = layout.root / "sessions" / "pincabshare-v2.json"

    def status(self) -> dict:
        return _read_json(self.state_path)

    def _run(
        self, command: list[str], script: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.runner(command, script)

    @staticmethod
    def _base_ruleset() -> str:
        return f"""table {NFT_TABLE_FAMILY} {NFT_TABLE_NAME} {{
    set allowed_peers_v4 {{
        type ipv4_addr
    }}

    chain input_nfs {{
        type filter hook input priority -5; policy accept;
        ip saddr @allowed_peers_v4 tcp dport {NFS_PORT} accept
        ip saddr @allowed_peers_v4 udp dport {NFS_PORT} accept
        tcp dport {NFS_PORT} drop
        udp dport {NFS_PORT} drop
    }}
}}
"""

    @staticmethod
    def _peer_update(addresses: tuple[str, ...]) -> str:
        lines = [
            f"flush set {NFT_TABLE_FAMILY} {NFT_TABLE_NAME} allowed_peers_v4"
        ]
        if addresses:
            elements = ", ".join(addresses)
            lines.append(
                f"add element {NFT_TABLE_FAMILY} {NFT_TABLE_NAME} "
                f"allowed_peers_v4 {{ {elements} }}"
            )
        return "\n".join(lines) + "\n"

    def _apply_script(self, script: str) -> None:
        check = self._run(["nft", "-c", "-f", "-"], script)
        if check.returncode != 0:
            raise PinCabShareError(
                f"nft_check_failed:{(check.stderr or '').strip()[:200]}"
            )
        result = self._run(["nft", "-f", "-"], script)
        if result.returncode != 0:
            raise PinCabShareError(
                f"nft_apply_failed:{(result.stderr or '').strip()[:200]}"
            )

    def _ensure_table(self) -> None:
        result = self._run(
            ["nft", "list", "table", NFT_TABLE_FAMILY, NFT_TABLE_NAME], None
        )
        if result.returncode == 0:
            return
        self._apply_script(self._base_ruleset())

    def _apply_peers(self, addresses: tuple[str, ...]) -> None:
        self._ensure_table()
        self._apply_script(self._peer_update(addresses))

    def _write_status(self, value: dict) -> dict:
        payload = {
            "version": POLICY_VERSION,
            "firewall_family": NFT_TABLE_FAMILY,
            "firewall_table": NFT_TABLE_NAME,
            "nfs_port": NFS_PORT,
            "updated_at": time.time(),
            **value,
        }
        _atomic_json(self.state_path, payload)
        return payload

    def revoke(self, reason: str) -> dict:
        self._apply_peers(())
        return self._write_status(
            {
                "enabled": False,
                "reason": str(reason),
                "session_id": None,
                "room_code": None,
                "local_cabinet_id": None,
                "peer_cabinet_ids": [],
                "peer_ipv4": [],
                "expires_at": None,
            }
        )

    def reconcile(self, state: dict, *, now: float | None = None) -> dict:
        try:
            policy = validate_policy(state, now=now)
        except PinCabShareError as exc:
            return self.revoke(str(exc))

        self._apply_peers(policy.peer_ipv4)
        return self._write_status(
            {
                "enabled": True,
                "reason": "server-policy-active",
                "session_id": policy.session_id,
                "room_code": policy.room_code,
                "local_cabinet_id": policy.local_cabinet_id,
                "peer_cabinet_ids": list(policy.peer_cabinet_ids),
                "peer_ipv4": list(policy.peer_ipv4),
                "issued_at": policy.issued_at,
                "expires_at": policy.expires_at,
            }
        )
