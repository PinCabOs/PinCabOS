#!/usr/bin/env python3
"""Client HTTPS minimal pour le gate PinCabShare V2.

Ce module utilise uniquement l'identité PinCabOS Link déjà provisionnée sur le
cabinet. Il ne dépend pas du runtime VPX et ne modifie aucun état Multiplayer.
"""
from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API = "https://pincabos.cc"
DEFAULT_DEVICE_STATE = Path("/var/lib/pincabos-link/device.json")
ENDPOINT = "/api/device/pincabshare/state"
MAX_RESPONSE_BYTES = 128 * 1024


class GateClientError(RuntimeError):
    """Erreur réseau/auth sûre; ne contient jamais le jeton device."""


def load_credentials(path: Path = DEFAULT_DEVICE_STATE) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateClientError("pincabos_link_state_unavailable") from exc

    if not isinstance(payload, dict):
        raise GateClientError("pincabos_link_state_invalid")

    token = payload.get("device_token")
    token_type = payload.get("token_type") or "PinCabOS-Device"

    if (
        not isinstance(token, str)
        or len(token) < 24
        or token_type != "PinCabOS-Device"
    ):
        raise GateClientError("pincabos_link_identity_invalid")

    return token_type, token


def fetch_gate(
    *,
    api_root: str | None = None,
    timeout: float | None = None,
    credentials_path: Path = DEFAULT_DEVICE_STATE,
    opener=urlopen,
) -> dict:
    root = (api_root or os.environ.get("PINCABSHARE_API") or DEFAULT_API).rstrip("/")
    if not root.startswith("https://"):
        raise GateClientError("https_required")

    try:
        request_timeout = float(
            timeout
            if timeout is not None
            else os.environ.get("PINCABSHARE_HTTP_TIMEOUT", "4")
        )
    except (TypeError, ValueError) as exc:
        raise GateClientError("timeout_invalid") from exc

    request_timeout = max(1.0, min(request_timeout, 15.0))
    token_type, token = load_credentials(credentials_path)

    request = Request(
        root + ENDPOINT,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"{token_type} {token}",
            "User-Agent": "PinCabOS-PinCabShare/2",
        },
    )

    try:
        with opener(
            request,
            timeout=request_timeout,
            context=ssl.create_default_context(),
        ) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
    except HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES)
        try:
            detail = json.loads(raw.decode("utf-8")).get("error")
        except Exception:
            detail = None
        raise GateClientError(str(detail or f"server_http_{exc.code}")) from exc
    except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        raise GateClientError("server_unreachable") from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise GateClientError("server_response_too_large")

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GateClientError("server_response_invalid") from exc

    if status < 200 or status >= 300 or not isinstance(value, dict):
        raise GateClientError("server_response_invalid")
    if value.get("ok") is not True:
        raise GateClientError(str(value.get("error") or "server_rejected"))

    return value


def fetch_wrapped_gate(**kwargs) -> dict:
    """Adapte la réponse serveur au contrat interne du daemon PinCabShare.

    Le serveur est l'autorité de membership. Quand ``enabled`` est vrai, le
    serveur a déjà vérifié que le CAB authentifié appartient bien à la session,
    que sa présence Lobby est fraîche et que 2 à 4 CAB sont présents.
    """

    gate = fetch_gate(**kwargs)
    session_id = str(gate.get("session_id") or "")
    room_code = str(gate.get("room_code") or "")

    return {
        "ok": True,
        "session": {
            "session_id": session_id,
            "room_code": room_code,
            "is_this_cabinet_member": bool(gate.get("enabled")),
        },
        "pincabshare": gate,
    }
