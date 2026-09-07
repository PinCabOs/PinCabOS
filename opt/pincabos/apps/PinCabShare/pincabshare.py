#!/usr/bin/env python3
"""PinCabShare V2 — partage NFS CAB↔CAB strictement lié au Lobby réel.

Aucun partage permanent n'est ouvert sur le LAN. Le serveur PinCabOS.CC reste
l'autorité de membership. Avahi/mDNS sert uniquement à découvrir l'IPv4 d'un
CAB déjà autorisé par le gate HTTPS.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import pwd
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from gate_client import GateClientError, fetch_gate

DATA_PATH = Path(os.environ.get("PINCABSHARE_DATA") or "/srv/pincabshare/data")
VIEW_PATH = Path(os.environ.get("PINCABSHARE_VIEW") or "/home/pinball/PinCabShare")
RUNTIME_PATH = Path(os.environ.get("PINCABSHARE_RUNTIME") or "/run/pincabshare-v2")
MOUNTS_PATH = RUNTIME_PATH / "mounts"
STATUS_PATH = RUNTIME_PATH / "status.json"
EXPORT_PATH = Path(
    os.environ.get("PINCABSHARE_EXPORT")
    or "/etc/exports.d/pincabshare-v2.exports"
)
AVAHI_PATH = Path(
    os.environ.get("PINCABSHARE_AVAHI")
    or "/etc/avahi/services/pincabshare-v2.service"
)

POLL_SECONDS = float(os.environ.get("PINCABSHARE_POLL_SECONDS") or "2")
HTTP_TIMEOUT = float(os.environ.get("PINCABSHARE_HTTP_TIMEOUT") or "3")
MAX_GATE_FUTURE_SECONDS = 12.0
SERVICE_TYPE = "_pincabshare._tcp"
SCHEMA = "pincabshare-gate/v2"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s PINCABSHARE-V2 %(levelname)s %(message)s",
)


class GateError(RuntimeError):
    pass


class GateClosed(GateError):
    pass


@dataclass(frozen=True)
class Gate:
    session_id: str
    room_code: str
    local_cabinet_id: int
    local_label: str
    members: tuple[dict[str, object], ...]
    expires_at: float
    gate_ttl_seconds: float
    share_nonce: str

    @property
    def authorized_ids(self) -> set[int]:
        return {int(member["cabinet_id"]) for member in self.members}

    @property
    def session_hash(self) -> str:
        return hashlib.sha256(self.session_id.encode("utf-8")).hexdigest()[:16]

    @property
    def gate_tag(self) -> str:
        if not self.share_nonce:
            return ""
        return hashlib.sha256(self.share_nonce.encode("ascii")).hexdigest()[:16]


@dataclass
class LeaseState:
    gate: Gate | None = None
    lease_until: float = 0.0


LEASE = LeaseState()


def _run(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.chmod(temp, mode)
    os.replace(temp, path)


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


def _member_label(item: dict[str, object], cabinet_id: int) -> str:
    label = item.get("cabinet_label")
    if label:
        return _safe_label(label)
    name = str(item.get("cabinet_name") or "").strip()
    return _safe_label(f"{name} — CAB{cabinet_id}" if name else f"CAB{cabinet_id}")


def load_gate(now: float | None = None) -> Gate:
    """Télécharge et valide le gate. Un gate CLOSED ferme immédiatement."""
    now = time.time() if now is None else float(now)
    try:
        value = fetch_gate(timeout=HTTP_TIMEOUT)
    except GateClientError:
        raise

    if not isinstance(value, dict) or value.get("ok") is not True:
        raise GateError("server_response_invalid")

    if value.get("share_allowed") is not True or str(value.get("gate")) != "open":
        raise GateClosed(str(value.get("reason") or "server_gate_closed"))

    schema = str(value.get("schema") or "")
    if schema and schema != SCHEMA:
        raise GateError("gate_schema_invalid")

    session_id = str(value.get("session_id") or "").strip()
    room_code = str(value.get("room_code") or "").strip().upper()
    if not session_id:
        raise GateError("session_missing")
    if not re.fullmatch(r"[A-Z0-9]{6}", room_code):
        raise GateError("room_invalid")

    try:
        local_id = int(value.get("local_cabinet_id"))
    except (TypeError, ValueError) as exc:
        raise GateError("local_cabinet_invalid") from exc
    if local_id <= 0:
        raise GateError("local_cabinet_invalid")

    raw_members = value.get("members")
    if not isinstance(raw_members, list) or not 2 <= len(raw_members) <= 4:
        raise GateError("member_count_invalid")

    members: list[dict[str, object]] = []
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
        members.append(
            {
                "cabinet_id": cabinet_id,
                "cabinet_name": str(item.get("cabinet_name") or "").strip(),
                "cabinet_label": _member_label(item, cabinet_id),
            }
        )

    if local_id not in seen:
        raise GateError("local_cabinet_not_member")

    try:
        ttl = float(value.get("gate_ttl_seconds") or 0)
    except (TypeError, ValueError) as exc:
        raise GateError("gate_ttl_invalid") from exc
    if ttl <= 0 or ttl > 12:
        raise GateError("gate_ttl_invalid")

    expires_at_raw = value.get("expires_at")
    if expires_at_raw:
        expires_at = _parse_time(expires_at_raw)
    else:
        # Alias de compatibilité avec le gate live antérieur: son TTL court
        # reste l'autorité même s'il ne fournit pas encore expires_at.
        expires_at = now + ttl

    if expires_at <= now:
        raise GateError("gate_expired")
    if expires_at > now + MAX_GATE_FUTURE_SECONDS:
        raise GateError("gate_expiry_too_far")

    nonce = str(value.get("share_nonce") or "").strip().lower()
    if nonce and not re.fullmatch(r"[0-9a-f]{64}", nonce):
        raise GateError("share_nonce_invalid")

    local = next(member for member in members if int(member["cabinet_id"]) == local_id)
    return Gate(
        session_id=session_id,
        room_code=room_code,
        local_cabinet_id=local_id,
        local_label=str(local["cabinet_label"]),
        members=tuple(members),
        expires_at=min(expires_at, now + ttl),
        gate_ttl_seconds=ttl,
        share_nonce=nonce,
    )


def ensure_storage() -> None:
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    VIEW_PATH.mkdir(parents=True, exist_ok=True)
    RUNTIME_PATH.mkdir(parents=True, exist_ok=True)
    MOUNTS_PATH.mkdir(parents=True, exist_ok=True)


def _default_network() -> tuple[str, ipaddress.IPv4Network, ipaddress.IPv4Address]:
    route = _run(["ip", "-j", "-4", "route", "show", "default"], timeout=4)
    if route.returncode != 0:
        raise GateError("default_route_unavailable")
    try:
        routes = json.loads(route.stdout)
    except ValueError as exc:
        raise GateError("default_route_invalid") from exc
    if not isinstance(routes, list) or not routes:
        raise GateError("default_route_unavailable")
    interface = str(routes[0].get("dev") or "").strip()
    if not interface:
        raise GateError("default_interface_unavailable")

    addr = _run(["ip", "-j", "-4", "addr", "show", "dev", interface], timeout=4)
    if addr.returncode != 0:
        raise GateError("local_ipv4_unavailable")
    try:
        payload = json.loads(addr.stdout)
    except ValueError as exc:
        raise GateError("local_ipv4_invalid") from exc

    for device in payload if isinstance(payload, list) else []:
        for info in device.get("addr_info", []):
            if info.get("family") != "inet" or info.get("scope") != "global":
                continue
            local = ipaddress.ip_address(str(info.get("local")))
            prefix = int(info.get("prefixlen"))
            if isinstance(local, ipaddress.IPv4Address):
                return interface, ipaddress.ip_network(f"{local}/{prefix}", strict=False), local
    raise GateError("local_ipv4_unavailable")


def _avahi_reload() -> None:
    result = _run(["systemctl", "reload", "avahi-daemon.service"], timeout=5)
    if result.returncode != 0:
        logging.warning("reload Avahi: %s", result.stderr.strip())


def advertise(gate: Gate) -> None:
    txt_gate = (
        f"    <txt-record>gate_tag={gate.gate_tag}</txt-record>\n"
        if gate.gate_tag
        else ""
    )
    xml = (
        '<?xml version="1.0" standalone="no"?>\n'
        '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
        '<service-group>\n'
        f'  <name>PinCabShare-CAB{gate.local_cabinet_id}</name>\n'
        '  <service>\n'
        f'    <type>{SERVICE_TYPE}</type>\n'
        '    <port>2049</port>\n'
        '    <txt-record>schema=2</txt-record>\n'
        f'    <txt-record>cab_id={gate.local_cabinet_id}</txt-record>\n'
        f'    <txt-record>session_hash={gate.session_hash}</txt-record>\n'
        f'{txt_gate}'
        '  </service>\n'
        '</service-group>\n'
    )
    current = AVAHI_PATH.read_text(encoding="utf-8") if AVAHI_PATH.exists() else None
    if current != xml:
        _atomic_write(AVAHI_PATH, xml)
        _avahi_reload()


def withdraw_advertisement() -> None:
    if AVAHI_PATH.exists():
        AVAHI_PATH.unlink(missing_ok=True)
        _avahi_reload()


def discover(gate: Gate) -> dict[int, dict[str, object]]:
    _interface, network, local_ip = _default_network()
    result = _run(["avahi-browse", "-r", "-t", "-p", SERVICE_TYPE], timeout=8)
    peers: dict[int, dict[str, object]] = {}
    if result.returncode != 0:
        return peers

    for line in result.stdout.splitlines():
        if not line.startswith("="):
            continue
        fields = line.split(";")
        if len(fields) < 9 or fields[2] != "IPv4":
            continue

        try:
            address = ipaddress.ip_address(fields[7])
        except ValueError:
            continue
        if not isinstance(address, ipaddress.IPv4Address):
            continue
        if address == local_ip or address not in network:
            continue

        cab_match = re.search(r"cab_id=(\d+)", line)
        session_match = re.search(r"session_hash=([0-9a-f]{16})", line)
        gate_match = re.search(r"gate_tag=([0-9a-f]{16})", line)
        if not cab_match or not session_match:
            continue
        if session_match.group(1) != gate.session_hash:
            continue
        if gate.gate_tag and (not gate_match or gate_match.group(1) != gate.gate_tag):
            continue

        cab_id = int(cab_match.group(1))
        if cab_id == gate.local_cabinet_id or cab_id not in gate.authorized_ids:
            continue
        member = next(member for member in gate.members if int(member["cabinet_id"]) == cab_id)
        peers[cab_id] = {
            "cabinet_id": cab_id,
            "address": str(address),
            "cabinet_label": str(member["cabinet_label"]),
        }
    return peers


def _export_content(peers: dict[int, dict[str, object]]) -> str:
    if not peers:
        return ""
    account = pwd.getpwnam("pinball")
    options = (
        "rw,sync,no_subtree_check,all_squash,"
        f"anonuid={account.pw_uid},anongid={account.pw_gid}"
    )
    clients = " ".join(
        f"{peer['address']}({options})"
        for _cab_id, peer in sorted(peers.items())
    )
    return f"{DATA_PATH} {clients}\n"


def sync_export(peers: dict[int, dict[str, object]]) -> None:
    desired = _export_content(peers)
    current = EXPORT_PATH.read_text(encoding="utf-8") if EXPORT_PATH.exists() else ""
    if desired == current:
        return

    if desired:
        _atomic_write(EXPORT_PATH, desired)
    else:
        EXPORT_PATH.unlink(missing_ok=True)

    result = _run(["exportfs", "-ra"], timeout=8)
    if result.returncode != 0:
        EXPORT_PATH.unlink(missing_ok=True)
        _run(["exportfs", "-ra"], timeout=8)
        raise GateError("nfs_export_reload_failed")


def remove_export() -> None:
    if EXPORT_PATH.exists():
        EXPORT_PATH.unlink(missing_ok=True)
        _run(["exportfs", "-ra"], timeout=8)


def _is_mount(path: Path) -> bool:
    return _run(["mountpoint", "-q", str(path)], timeout=3).returncode == 0


def _ensure_link(label: str, target: Path) -> bool:
    link = VIEW_PATH / _safe_label(label)
    desired = os.path.realpath(target)
    if link.is_symlink():
        if os.path.realpath(link) == desired:
            return True
        link.unlink(missing_ok=True)
    elif link.exists():
        logging.error("chemin utilisateur occupé, non modifié: %s", link)
        return False
    link.symlink_to(target, target_is_directory=True)
    return True


def _remove_managed_links() -> None:
    if not VIEW_PATH.exists():
        return
    local_target = os.path.realpath(DATA_PATH)
    remote_prefix = os.path.realpath(MOUNTS_PATH) + os.sep
    for item in VIEW_PATH.iterdir():
        if not item.is_symlink():
            continue
        target = os.path.realpath(item)
        if target == local_target or target.startswith(remote_prefix):
            item.unlink(missing_ok=True)


def sync_links_and_mounts(gate: Gate, peers: dict[int, dict[str, object]]) -> None:
    MOUNTS_PATH.mkdir(parents=True, exist_ok=True)
    VIEW_PATH.mkdir(parents=True, exist_ok=True)

    wanted_ids = set(peers)
    for path in MOUNTS_PATH.glob("CAB*"):
        match = re.fullmatch(r"CAB(\d+)", path.name)
        if not match:
            continue
        if int(match.group(1)) in wanted_ids:
            continue
        _remove_links_for_target(path)
        if _is_mount(path):
            _run(["umount", "-l", str(path)], timeout=5)
        try:
            path.rmdir()
        except OSError:
            pass

    # Retire un ancien label local après renommage, puis expose le label autoritaire.
    local_target = os.path.realpath(DATA_PATH)
    for item in VIEW_PATH.iterdir():
        if item.is_symlink() and os.path.realpath(item) == local_target:
            if item.name != gate.local_label:
                item.unlink(missing_ok=True)
    _ensure_link(gate.local_label, DATA_PATH)

    for cab_id, peer in sorted(peers.items()):
        mountpoint = MOUNTS_PATH / f"CAB{cab_id}"
        mountpoint.mkdir(parents=True, exist_ok=True)
        if not _is_mount(mountpoint):
            source = f"{peer['address']}:{DATA_PATH}"
            options = "vers=4,rw,soft,timeo=10,retrans=1,nosuid,nodev,noexec"
            result = _run(
                ["mount", "-t", "nfs", "-o", options, source, str(mountpoint)],
                timeout=12,
            )
            if result.returncode != 0:
                logging.warning("CAB%s NFS non monté: %s", cab_id, result.stderr.strip())
                continue

        _remove_links_for_target(mountpoint, except_name=str(peer["cabinet_label"]))
        _ensure_link(str(peer["cabinet_label"]), mountpoint)


def _remove_links_for_target(target: Path, except_name: str | None = None) -> None:
    if not VIEW_PATH.exists():
        return
    desired = os.path.realpath(target)
    for item in VIEW_PATH.iterdir():
        if not item.is_symlink():
            continue
        if os.path.realpath(item) != desired:
            continue
        if except_name is not None and item.name == except_name:
            continue
        item.unlink(missing_ok=True)


def unmount_all() -> None:
    _remove_managed_links()
    if not MOUNTS_PATH.exists():
        return
    for path in MOUNTS_PATH.glob("CAB*"):
        if _is_mount(path):
            _run(["umount", "-l", str(path)], timeout=5)
        try:
            path.rmdir()
        except OSError:
            pass


def write_status(
    gate_state: str,
    reason: str,
    gate: Gate | None = None,
    peers: dict[int, dict[str, object]] | None = None,
) -> None:
    RUNTIME_PATH.mkdir(parents=True, exist_ok=True)
    peer_values = peers or {}
    value = {
        "schema": "pincabshare-v2/status",
        "gate": gate_state,
        "reason": reason,
        "session_id": gate.session_id if gate else None,
        "room_code": gate.room_code if gate else None,
        "local_cabinet_id": gate.local_cabinet_id if gate else None,
        "present_count": len(gate.members) if gate else 0,
        "members": [
            {
                "cabinet_id": int(member["cabinet_id"]),
                "cabinet_label": str(member["cabinet_label"]),
            }
            for member in (gate.members if gate else ())
        ],
        "peers": [
            {
                "cabinet_id": int(peer["cabinet_id"]),
                "cabinet_label": str(peer["cabinet_label"]),
                "address": str(peer["address"]),
            }
            for _cab_id, peer in sorted(peer_values.items())
        ],
        "updated_at": time.time(),
    }
    _atomic_write(
        STATUS_PATH,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        0o640,
    )


def close_all(reason: str) -> None:
    LEASE.gate = None
    LEASE.lease_until = 0.0
    withdraw_advertisement()
    remove_export()
    unmount_all()
    write_status("closed", reason)


def open_cycle(gate: Gate) -> None:
    ensure_storage()
    advertise(gate)
    peers = discover(gate)
    sync_export(peers)
    sync_links_and_mounts(gate, peers)
    LEASE.gate = gate
    LEASE.lease_until = gate.expires_at
    write_status("open", "authorized", gate, peers)


def cycle() -> None:
    now = time.time()
    try:
        gate = load_gate(now)
    except GateClosed as exc:
        close_all(str(exc))
        return
    except GateClientError as exc:
        if LEASE.gate is not None and now < LEASE.lease_until:
            write_status("open", f"lease_hold:{exc}", LEASE.gate)
            return
        close_all(str(exc))
        return
    except GateError as exc:
        close_all(str(exc))
        return

    open_cycle(gate)


def main() -> int:
    ensure_storage()
    while True:
        try:
            cycle()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logging.exception("cycle failed")
            close_all("runtime_error:" + exc.__class__.__name__)
        time.sleep(max(1.0, min(POLL_SECONDS, 10.0)))
    close_all("service_stopped")
    return 0


if __name__ == "__main__":
    if "--close" in sys.argv[1:]:
        ensure_storage()
        close_all("manual_close")
        raise SystemExit(0)
    raise SystemExit(main())
