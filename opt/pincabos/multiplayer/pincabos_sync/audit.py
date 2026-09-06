"""Audit strictement en lecture seule des composants protégés."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from . import AGENT_VERSION, PROTOCOL_VERSION

DEFAULT_PROTECTED_PATHS = (
    Path("/opt/pincabos/apps/vpinball/current/VPinballX-BGFX"),
    Path("/opt/pincabos/bin/vpx.sh"),
    Path("/opt/pinball/vpinfe/vpinfe"),
    Path("/home/pinball/.vpinball/VPinballX.ini"),
    Path("/home/pinball/.local/share/VPinballX/10.8/VPinballX.ini"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_only_audit(paths: Iterable[Path] = DEFAULT_PROTECTED_PATHS) -> dict[str, object]:
    files = []
    for path in paths:
        item: dict[str, object] = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            item["sha256"] = sha256_file(path)
            item["size"] = path.stat().st_size
        files.append(item)
    return {
        "agent_version": AGENT_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "transport_active": False,
        "launcher_active": False,
        "vpinfe_in_multiplayer_path": False,
        "protected_files": files,
    }
