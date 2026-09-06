"""Client HTTPS minimal utilisant l'identité PinCabOS Link existante."""

from __future__ import annotations

import json
import os
import re
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_API = "https://pincabos.cc"
DEFAULT_DEVICE_STATE = Path("/var/lib/pincabos-link/device.json")
ROOM_CODE_PATTERN = re.compile(r"^[A-Z0-9]{6}$")
MAX_RESPONSE_BYTES = 256 * 1024
CONTROL_STATES = {"released", "armed", "linked", "video", "running", "handoff"}


class MultiplayerClientError(RuntimeError):
    """Erreur sûre pour l'interface; elle ne contient jamais le jeton."""


@dataclass(frozen=True)
class DeviceCredentials:
    token_type: str
    token: str = field(repr=False)
    cabinet_uuid: str


def normalize_room_code(value: object) -> str:
    code = "".join(
        character
        for character in str(value or "").strip().upper()
        if character not in " -\t\r\n"
    )
    if not ROOM_CODE_PATTERN.fullmatch(code):
        raise MultiplayerClientError("room_code_invalid")
    return code


def load_credentials(path: Path = DEFAULT_DEVICE_STATE) -> DeviceCredentials:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MultiplayerClientError("pincabos_link_state_unavailable") from exc

    if not isinstance(payload, dict):
        raise MultiplayerClientError("pincabos_link_state_invalid")

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
        raise MultiplayerClientError("pincabos_link_identity_invalid")

    return DeviceCredentials(token_type, token, cabinet_uuid)


def _disabled_pincabshare(reason: str) -> dict[str, object]:
    return {
        "version": 2,
        "enabled": False,
        "reason": str(reason),
        "session_id": None,
        "room_code": None,
        "local_cabinet_id": None,
        "issued_at": None,
        "expires_at": None,
        "peers": [],
    }


class ServerClient:
    def __init__(
        self,
        credentials: DeviceCredentials,
        *,
        api_root: str | None = None,
        timeout: float = 15.0,
        opener=urlopen,
    ) -> None:
        self.credentials = credentials
        self.api_root = (api_root or os.environ.get("PINCABOS_MULTIPLAYER_API") or DEFAULT_API).rstrip("/")
        if not self.api_root.startswith("https://"):
            raise MultiplayerClientError("https_required")
        self.timeout = timeout
        self._opener = opener

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not path.startswith("/api/device/multiplayer/"):
            raise MultiplayerClientError("endpoint_not_allowed")

        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"{self.credentials.token_type} {self.credentials.token}",
            "User-Agent": "PinCabOS-VPX-MultiPlayers/0.1",
        }
        if method != "GET":
            body = json.dumps(payload or {}, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            self.api_root + path,
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with self._opener(
                request,
                timeout=self.timeout,
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
            raise MultiplayerClientError(str(detail or f"server_http_{exc.code}")) from exc
        except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
            raise MultiplayerClientError("server_unreachable") from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            raise MultiplayerClientError("server_response_too_large")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise MultiplayerClientError("server_response_invalid") from exc
        if status < 200 or status >= 300 or not isinstance(value, dict):
            raise MultiplayerClientError("server_response_invalid")
        if value.get("ok") is False:
            raise MultiplayerClientError(str(value.get("error") or "server_rejected"))
        return value

    def state(self) -> dict:
        # Le contrat historique de contrôle reste l'autorité principale.
        value = self.request("GET", "/api/device/multiplayer/state")

        # PinCabShare V2 est additif. Une version serveur plus ancienne, un
        # endpoint indisponible ou une panne de ce sous-contrat ne doit jamais
        # casser PREPARE/READY/control : le partage reste simplement fermé.
        try:
            share_value = self.request(
                "GET",
                "/api/device/multiplayer/pincabshare",
            )
            policy = share_value.get("pincabshare")
            if not isinstance(policy, dict):
                policy = _disabled_pincabshare("policy-response-invalid")
        except MultiplayerClientError:
            policy = _disabled_pincabshare("policy-endpoint-unavailable")

        value["pincabshare"] = policy
        return value

    def join(self, room_code: str | None = None) -> dict:
        payload = {} if room_code is None else {"room_code": normalize_room_code(room_code)}
        return self.request("POST", "/api/device/multiplayer/join", payload)

    def action(self, action: str, session_id: str, **payload: object) -> dict:
        if action not in {"prepare", "ready", "start", "stop"}:
            raise MultiplayerClientError("action_not_allowed")
        return self.request(
            "POST",
            f"/api/device/multiplayer/{action}",
            {"session_id": session_id, **payload},
        )

    def control_ack(
        self,
        session_id: str,
        generation: object,
        state: str,
        *,
        ok: bool = True,
        detail: str | None = None,
    ) -> dict:
        normalized_state = str(state or "").strip().lower()
        if normalized_state not in CONTROL_STATES:
            raise MultiplayerClientError("control_state_invalid")
        return self.request(
            "POST",
            "/api/device/multiplayer/control-ack",
            {
                "session_id": str(session_id),
                "generation": generation,
                "state": normalized_state,
                "ok": bool(ok),
                "detail": detail,
            },
        )
