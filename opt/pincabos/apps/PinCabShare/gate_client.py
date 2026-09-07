#!/usr/bin/env python3
"""Client HTTPS minimal du gate PinCabShare V2.

Réutilise exclusivement l'identité PinCabOS Link déjà provisionnée dans
/var/lib/pincabos-link/device.json. Aucun nouveau secret n'est créé.
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
ENDPOINTS = (
    "/api/device/pincabshare/state",
    "/api/device/multiplayer/share-gate",
)
MAX_RESPONSE_BYTES = 128 * 1024


class GateClientError(RuntimeError):
    """Erreur sûre pour le journal; le token device n'est jamais inclus."""


def load_credentials(path: Path = DEFAULT_DEVICE_STATE) -> tuple[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GateClientError("pincabos_link_state_unavailable") from exc

    if not isinstance(payload, dict):
        raise GateClientError("pincabos_link_state_invalid")

    token = payload.get("device_token")
    token_type = payload.get("token_type") or "PinCabOS-Device"
    cabinet = payload.get("cabinet") or {}
    cabinet_uuid = cabinet.get("cabinet_uuid") if isinstance(cabinet, dict) else None

    if (
        not isinstance(token, str)
        or len(token) < 24
        or token_type != "PinCabOS-Device"
        or not isinstance(cabinet_uuid, str)
        or not cabinet_uuid
    ):
        raise GateClientError("pincabos_link_identity_invalid")

    return token_type, token


def _request_gate(
    root: str,
    endpoint: str,
    token_type: str,
    token: str,
    timeout: float,
    opener,
) -> dict:
    request = Request(
        root + endpoint,
        method="GET",
        headers={
            "Accept": "application/json",
            "Authorization": f"{token_type} {token}",
            "Cache-Control": "no-cache",
            "User-Agent": "PinCabOS-PinCabShare/2",
        },
    )

    try:
        with opener(
            request,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
    except HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES)
        if exc.code == 404:
            raise GateClientError("endpoint_not_found") from exc
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
            timeout if timeout is not None else os.environ.get("PINCABSHARE_HTTP_TIMEOUT", "3")
        )
    except (TypeError, ValueError) as exc:
        raise GateClientError("timeout_invalid") from exc
    request_timeout = max(1.0, min(request_timeout, 10.0))

    token_type, token = load_credentials(credentials_path)
    last_error: GateClientError | None = None

    for endpoint in ENDPOINTS:
        try:
            return _request_gate(
                root,
                endpoint,
                token_type,
                token,
                request_timeout,
                opener,
            )
        except GateClientError as exc:
            last_error = exc
            if str(exc) != "endpoint_not_found":
                raise

    raise last_error or GateClientError("gate_endpoint_unavailable")
