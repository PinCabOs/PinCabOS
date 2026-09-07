#!/usr/bin/env python3
"""PinCabShare V2 — SMB LAN permanent, auto-montages CAB↔CAB liés au Lobby.

SMB local reste disponible en permanence. La couche automatique CAB↔CAB est
fail-closed et n'est ouverte que par un gate frais reçu de PinCabOS.CC via
l'identité PinCabOS Link du cabinet.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import logging
import os
import pwd
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gate_client import GateClientError, fetch_wrapped_gate

DATA_PATH = Path(os.environ.get("PINCABSHARE_DATA") or "/srv/pincabshare/data")
VIEW_PATH = Path(os.environ.get("PINCABSHARE_VIEW") or "/home/pinball/PinCabShare")
RUNTIME_PATH = Path(os.environ.get("PINCABSHARE_RUNTIME") or "/run/pincabshare")
MOUNTS_PATH = RUNTIME_PATH / "mounts"
STATUS_PATH = RUNTIME_PATH / "status.json"
INTERCAB_AVAHI = Path(
    os.environ.get("PINCABSHARE_AVAHI")
    or "/etc/avahi/services/pincabshare-intercab.service"
)
POLL_SECONDS = float(os.environ.get("PINCABSHARE_POLL_SECONDS") or "2")
MAX_GATE_FUTURE_SECONDS = float(
    os.environ.get("PINCABSHARE_MAX_GATE_FUTURE_SECONDS") or "30"
)
SERVICE_TYPE = "_pincabshare._tcp"
SHARE_NAME = "PinCabShare"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s PINCABSHARE %(levelname)s %(message)s",
)


class GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Gate:
    session_id: str
    room_code: str
    nonce: str
    local_cabinet_id: int
    local_label: str
    members: tuple[dict, ...]
    expires_at: float

    @property
    def authorized_ids(self) -> set[int]:
        return {int(item["cabinet_id"]) for item in self.members}


def _parse_time(value: object) -> float:
    text = str(value or "").strip()
    if not text:
        raise GateError("gate_expiry_missing")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GateError("gate_expiry_invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _safe_label(value: object) -> str:
    label = re.sub(r"[\\/\r\n\x00-\x1f]+", "_", str(value or "").strip())
    label = re.sub(r"\s+", " ", label).strip(" .")
    if not label or len(label) > 120:
        raise GateError("cabinet_label_invalid")
    return label


def load_gate(now: float | None = None) -> Gate:
    """Récupère et valide le gate live. Toute erreur ferme l'inter-CAB."""

    now = time.time() if now is None else float(now)
    try:
        state = fetch_wrapped_gate()
    except GateClientError as exc:
        raise GateError(f"gate_server:{exc}") from exc

    if not isinstance(state, dict) or state.get("ok") is not True:
        raise GateError("state_not_ok")

    session = state.get("session")
    gate = state.get("pincabshare")
    if not isinstance(session, dict) or not isinstance(gate, dict):
        raise GateError("gate_missing")

    if gate.get("enabled") is not True:
        raise GateError(str(gate.get("reason") or "gate_disabled"))
    if gate.get("schema") != "pincabshare-gate/v2":
        raise GateError("gate_schema_invalid")

    session_id = str(gate.get("session_id") or "").strip()
    room_code = str(gate.get("room_code") or "").strip().upper()
    nonce = str(gate.get("share_nonce") or "").strip().lower()

    if not session_id or session_id != str(session.get("session_id") or ""):
        raise GateError("session_mismatch")
    if (
        not re.fullmatch(r"[A-Z0-9]{6}", room_code)
        or room_code != str(session.get("room_code") or "").strip().upper()
    ):
        raise GateError("room_mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", nonce):
        raise GateError("nonce_invalid")

    expires_at = _parse_time(gate.get("expires_at"))
    if expires_at <= now:
        raise GateError("gate_expired")
    if expires_at > now + MAX_GATE_FUTURE_SECONDS:
        raise GateError("gate_expiry_too_far")

    raw_members = gate.get("members")
    if not isinstance(raw_members, list) or not 2 <= len(raw_members) <= 4:
        raise GateError("member_count_invalid")

    normalized: list[dict] = []
    seen: set[int] = set()
    for item in raw_members:
        if not isinstance(item, dict):
            raise GateError("member_invalid")
        try:
            cabinet_id = int(item.get("cabinet_id"))
        except (TypeError, ValueError) as exc:
            raise GateError("member_id_invalid") from exc
        if cabinet_id <= 0 or cabinet_id in seen:
            raise GateError("member_id_duplicate")
        seen.add(cabinet_id)
        normalized.append(
            {
                "cabinet_id": cabinet_id,
                "cabinet_name": str(item.get("cabinet_name") or "").strip(),
                "cabinet_label": _safe_label(
                    item.get("cabinet_label") or f"CAB{cabinet_id}"
                ),
            }
        )

    try:
        local_id = int(gate.get("local_cabinet_id"))
    except (TypeError, ValueError) as exc:
        raise GateError("local_cabinet_invalid") from exc

    if local_id not in seen or session.get("is_this_cabinet_member") is not True:
        raise GateError("local_cabinet_not_member")

    local = next(item for item in normalized if item["cabinet_id"] == local_id)
    return Gate(
        session_id,
        room_code,
        nonce,
        local_id,
        local["cabinet_label"],
        tuple(normalized),
        expires_at,
    )


def _run(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.chmod(temp, mode)
    os.replace(temp, path)


def _nonce_tag(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()[:32]


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def ensure_local_storage() -> None:
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    VIEW_PATH.mkdir(parents=True, exist_ok=True)


def _ensure_link(label: str, target: Path) -> bool:
    link = VIEW_PATH / label
    desired = str(target.resolve())

    if link.is_symlink():
        try:
            current = os.path.realpath(link)
        except OSError:
            current = ""
        if current == desired:
            return True
        link.unlink(missing_ok=True)
    elif link.exists():
        logging.error("chemin PinCabShare occupé: %s", link)
        return False

    link.symlink_to(target, target_is_directory=True)
    return True


def ensure_local_view(gate: Gate) -> None:
    """Expose un seul lien local, même après renommage du cabinet."""

    ensure_local_storage()
    wanted = VIEW_PATH / gate.local_label
    local_target = str(DATA_PATH.resolve())

    for item in VIEW_PATH.iterdir():
        if not item.is_symlink() or item == wanted:
            continue
        try:
            target = os.path.realpath(item)
        except OSError:
            continue
        if target == local_target:
            item.unlink(missing_ok=True)

    _ensure_link(gate.local_label, DATA_PATH)


def advertise_intercab(gate: Gate) -> None:
    xml = f'''<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name>PinCabShare-CAB{gate.local_cabinet_id}</name>
  <service>
    <type>{SERVICE_TYPE}</type>
    <port>445</port>
    <txt-record>schema=2</txt-record>
    <txt-record>cab_id={gate.local_cabinet_id}</txt-record>
    <txt-record>gate={_nonce_tag(gate.nonce)}</txt-record>
    <txt-record>label_b64={_b64(gate.local_label)}</txt-record>
  </service>
</service-group>
'''
    current = (
        INTERCAB_AVAHI.read_text(encoding="utf-8")
        if INTERCAB_AVAHI.exists()
        else None
    )
    if current != xml:
        _atomic_write(INTERCAB_AVAHI, xml)
        _run(["systemctl", "reload", "avahi-daemon.service"])


def discover(gate: Gate) -> dict[int, dict]:
    result = _run(
        ["avahi-browse", "-r", "-t", "-p", SERVICE_TYPE],
        timeout=8,
    )
    peers: dict[int, dict] = {}
    tag = _nonce_tag(gate.nonce)

    for line in result.stdout.splitlines():
        if not line.startswith("="):
            continue
        fields = line.split(";")
        if len(fields) < 9 or fields[2] != "IPv4":
            continue
        try:
            ip = ipaddress.ip_address(fields[7])
        except ValueError:
            continue
        if not (ip.is_private or ip.is_link_local):
            continue

        cab = re.search(r"cab_id=(\d+)", line)
        token = re.search(r"gate=([0-9a-f]{32})", line)
        if not cab or not token or token.group(1) != tag:
            continue

        cab_id = int(cab.group(1))
        if cab_id == gate.local_cabinet_id or cab_id not in gate.authorized_ids:
            continue

        member = next(
            item for item in gate.members if int(item["cabinet_id"]) == cab_id
        )
        peers[cab_id] = {
            "cabinet_id": cab_id,
            "address": str(ip),
            "label": member["cabinet_label"],
        }

    return peers


def _is_mount(path: Path) -> bool:
    return _run(["mountpoint", "-q", str(path)]).returncode == 0


def _links_to(target: Path) -> list[Path]:
    if not VIEW_PATH.exists():
        return []
    desired = str(target.resolve())
    result: list[Path] = []
    for item in VIEW_PATH.iterdir():
        if not item.is_symlink():
            continue
        try:
            current = os.path.realpath(item)
        except OSError:
            continue
        if current == desired:
            result.append(item)
    return result


def _remove_links_to(target: Path) -> None:
    for link in _links_to(target):
        link.unlink(missing_ok=True)


def _remove_all_remote_links() -> None:
    if not VIEW_PATH.exists():
        return
    prefix = str(MOUNTS_PATH.resolve()) + os.sep
    for item in VIEW_PATH.iterdir():
        if not item.is_symlink():
            continue
        try:
            target = os.path.realpath(item)
        except OSError:
            continue
        if target.startswith(prefix):
            item.unlink(missing_ok=True)


def _release_mount(path: Path) -> None:
    _remove_links_to(path)
    if _is_mount(path):
        _run(["umount", "-l", str(path)])
    try:
        path.rmdir()
    except OSError:
        pass


def sync_mounts(gate: Gate, peers: dict[int, dict]) -> None:
    account = pwd.getpwnam("pinball")
    MOUNTS_PATH.mkdir(parents=True, exist_ok=True)
    active = set(peers)

    for path in MOUNTS_PATH.glob("CAB*"):
        match = re.fullmatch(r"CAB(\d+)", path.name)
        if match and int(match.group(1)) not in active:
            _release_mount(path)

    for cab_id, peer in peers.items():
        mountpoint = MOUNTS_PATH / f"CAB{cab_id}"
        mountpoint.mkdir(parents=True, exist_ok=True)

        if not _is_mount(mountpoint):
            source = f"//{peer['address']}/{SHARE_NAME}"
            options = (
                "guest,vers=3.0,rw,nosuid,nodev,noexec,iocharset=utf8,"
                f"uid={account.pw_uid},gid={account.pw_gid},"
                "file_mode=0664,dir_mode=0775,actimeo=1"
            )
            result = _run(
                ["mount", "-t", "cifs", "-o", options, source, str(mountpoint)],
                timeout=12,
            )
            if result.returncode != 0:
                logging.warning(
                    "CAB%s SMB non monté: %s",
                    cab_id,
                    result.stderr.strip(),
                )
                continue

        existing = _links_to(mountpoint)
        wanted = VIEW_PATH / peer["label"]
        if len(existing) != 1 or existing[0] != wanted:
            _remove_links_to(mountpoint)
        _ensure_link(peer["label"], mountpoint)


def close_intercab(reason: str) -> None:
    """Ferme seulement les liens automatiques. SMB local reste toujours actif."""

    if INTERCAB_AVAHI.exists():
        INTERCAB_AVAHI.unlink(missing_ok=True)
        _run(["systemctl", "reload", "avahi-daemon.service"])

    _remove_all_remote_links()
    if MOUNTS_PATH.exists():
        for path in MOUNTS_PATH.glob("CAB*"):
            if _is_mount(path):
                _run(["umount", "-l", str(path)])

    write_status(False, reason, None, {})


def write_status(
    intercab_enabled: bool,
    reason: str,
    gate: Gate | None,
    peers: dict[int, dict],
) -> None:
    RUNTIME_PATH.mkdir(parents=True, exist_ok=True)
    value = {
        "schema": "pincabshare-status/v2",
        "smb_lan_enabled": True,
        "smb_share": SHARE_NAME,
        "smb_path": str(DATA_PATH),
        "intercab_enabled": bool(intercab_enabled),
        "reason": reason,
        "session_id": gate.session_id if gate else None,
        "room_code": gate.room_code if gate else None,
        "local_cabinet_id": gate.local_cabinet_id if gate else None,
        "members": [
            {
                "cabinet_id": int(item["cabinet_id"]),
                "cabinet_label": item["cabinet_label"],
            }
            for item in (gate.members if gate else ())
        ],
        "peers": [
            {
                "cabinet_id": int(item["cabinet_id"]),
                "cabinet_label": item["label"],
                "address": item["address"],
            }
            for item in peers.values()
        ],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write(
        STATUS_PATH,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        0o640,
    )


def cycle() -> None:
    ensure_local_storage()
    try:
        gate = load_gate()
    except GateError as exc:
        close_intercab(str(exc))
        return

    ensure_local_view(gate)
    advertise_intercab(gate)
    peers = discover(gate)
    sync_mounts(gate, peers)
    write_status(True, "lobby_gate_valid", gate, peers)


def main() -> int:
    RUNTIME_PATH.mkdir(parents=True, exist_ok=True)
    MOUNTS_PATH.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            cycle()
        except Exception as exc:
            logging.exception("cycle failed")
            close_intercab("runtime_error:" + exc.__class__.__name__)
        time.sleep(max(1.0, min(POLL_SECONDS, 30.0)))


if __name__ == "__main__":
    raise SystemExit(main())
