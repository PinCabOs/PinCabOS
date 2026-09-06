# PINCABOS_PINBALL_ENGINE_VPX_VERSION_V1
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from flask import jsonify, request


def _pco_chemin(cle, defaut):
    """PINCABOS_RUNTIMES_OPT_V1 : chemin de pincabos_paths (source de verite), sinon la valeur livree."""
    try:
        import sys as _sys
        if "/opt/pincabos/tools" not in _sys.path:
            _sys.path.insert(0, "/opt/pincabos/tools")
        from pincabos_paths import PATHS as _pco
        return getattr(_pco, cle)
    except Exception:  # hors cab (tests, banc)
        return defaut


MARKER = "PINCABOS_PINBALL_ENGINE_VPX_VERSION_V1"
GITHUB_RELEASE_URL = "https://api.github.com/repos/vpinball/vpinball/releases?per_page=20"
CACHE_TTL_SECONDS = 300

_cache_lock = threading.RLock()
_remote_cache: dict[str, Any] = {
    "expires": 0.0,
    "value": None,
}

VERSION_RE = re.compile(
    r"(?:VPinballX(?:_BGFX)?[-_])?v?(\d+\.\d+\.\d+)"
    r"(?:[-_](\d+))?"
    r"(?:[-_]([0-9a-f]{7,40}))?",
    re.IGNORECASE,
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _version_parts(text: str) -> tuple[str, str, str]:
    match = VERSION_RE.search(text or "")
    if not match:
        return "", "", ""
    return (
        str(match.group(1) or ""),
        str(match.group(2) or ""),
        str(match.group(3) or ""),
    )


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    try:
        parts = [int(item) for item in str(value).split(".")]
        if len(parts) != 3:
            return None
        return tuple(parts)  # type: ignore[return-value]
    except Exception:
        return None


def _extract_candidate_paths(text: str) -> list[Path]:
    results: list[Path] = []

    for raw in re.findall(
        r"(/[^\s'\"`]+/VPinballX(?:_BGFX)?(?:[^\s'\"`]*)?)",
        text,
        re.IGNORECASE,
    ):
        candidate = Path(raw.rstrip(";,)}]"))
        if candidate.name.startswith("VPinballX"):
            results.append(candidate)

    for raw in re.findall(
        r"(?im)^\s*(?:export\s+)?(?:VPX_MAIN|VPX_BIN|VPX_BINARY)\s*=\s*[\"']?([^\"'\n]+)",
        text,
    ):
        candidate = Path(raw.strip().rstrip(";,)}]"))
        if candidate.name.startswith("VPinballX"):
            results.append(candidate)

    return results


def _configured_candidates() -> list[Path]:
    candidates: list[Path] = []

    files = [
        Path("/opt/pincabos/scripts/VPXlauncher.sh"),
        Path("/opt/pincabos/bin/vpx-vpinfe-default.sh"),
        Path("/home/pinball/.config/vpinfe/vpinfe.ini"),
        Path("/home/pinball/.vpinball/VPinballX.ini"),
        Path("/home/pinball/.local/share/VPinballX/10.8/VPinballX.ini"),
    ]

    for path in files:
        text = _read_text(path)
        candidates.extend(_extract_candidate_paths(text))

        for value in re.findall(
            r"(?im)^\s*vpxbinpath\s*=\s*(.+?)\s*$",
            text,
        ):
            wrapper = Path(value.strip().strip("\"'"))
            if wrapper.is_file():
                candidates.extend(_extract_candidate_paths(_read_text(wrapper)))

    runtimes = _pco_chemin("runtimes", "/opt/pinball")
    fallback_patterns = [
        f"{runtimes}/VPinballX*/VPinballX_BGFX",
        f"{runtimes}/VPinballX*/VPinballX*",
        "/opt/pincabos/apps/vpinball*/**/VPinballX_BGFX",
        "/opt/pincabos/apps/vpinball*/**/VPinballX*",
    ]

    for pattern in fallback_patterns:
        candidates.extend(Path("/").glob(pattern.lstrip("/")))

    unique: list[Path] = []
    seen: set[str] = set()

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate

        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)

        if (
            resolved.is_file()
            and os.access(resolved, os.X_OK)
            and resolved.name.startswith("VPinballX")
        ):
            unique.append(resolved)

    return unique


def _local_vpx() -> dict[str, Any]:
    # PINCABOS_VPX_CANONICAL_LINK_V2
    #
    # La source de vérité locale est le symlink officiel /opt/pinball/vpx
    # (PINCABOS_RUNTIMES_OPT_V1). Plusieurs versions VPX sont volontairement
    # conservées pour rollback : il ne faut donc jamais choisir arbitrairement
    # le premier répertoire VPinballX_BGFX-* trouvé sur disque.
    canonical = Path(_pco_chemin("vpx_bin", "/opt/pinball/vpx/VPinballX_BGFX"))

    preferred = None

    try:
        resolved = canonical.resolve()
        if (
            resolved.is_file()
            and os.access(resolved, os.X_OK)
            and resolved.name.startswith("VPinballX")
        ):
            preferred = resolved
    except OSError:
        preferred = None

    if preferred is None:
        candidates = _configured_candidates()

        if not candidates:
            return {
                "available": False,
                "display": "VPX local introuvable",
                "path": "",
                "version": "",
                "revision": "",
                "commit": "",
                "engine": "",
            }

        preferred = sorted(
            candidates,
            key=lambda item: (
                "VPinballX_BGFX" not in item.name,
                str(item),
            ),
        )[-1]

    version, revision, commit = _version_parts(str(preferred))

    if not version:
        try:
            probe = subprocess.run(
                [str(preferred), "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=3,
                check=False,
                env={"LANG": "C", "LC_ALL": "C"},
            )
            version, revision, commit = _version_parts(probe.stdout or "")
        except Exception:
            pass

    engine = "BGFX" if "BGFX" in preferred.name.upper() else "Standard"
    display_bits = ["VPX"]

    if version:
        display_bits.append(version)
    if revision:
        display_bits.append(f"Rev {revision}")
    if commit:
        display_bits.append(commit)
    display_bits.append(engine)
    display_bits.append("Linux x64")

    return {
        "available": bool(version),
        "display": " · ".join(display_bits),
        "path": str(preferred),
        "version": version,
        "revision": revision,
        "commit": commit,
        "engine": engine,
    }


def _remote_vpx() -> dict[str, Any]:
    now = time.monotonic()

    with _cache_lock:
        if _remote_cache.get("value") and float(_remote_cache.get("expires") or 0) > now:
            return dict(_remote_cache["value"])

    try:
        request_obj = urllib.request.Request(
            GITHUB_RELEASE_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "PinCabOS-VPX-Version-Check",
            },
        )

        with urllib.request.urlopen(request_obj, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        if isinstance(payload, list):
            payload = next(
                (rel for rel in payload if isinstance(rel, dict)
                 and "DO NOT USE" not in
                 ((rel.get("name") or "") + " "
                  + (rel.get("tag_name") or "")).upper()),
                {})

        tag = str(payload.get("tag_name") or "").strip()
        assets = payload.get("assets") if isinstance(payload.get("assets"), list) else []

        ranked_assets: list[tuple[int, str]] = []
        for asset in assets:
            name = str(asset.get("name") or "").strip()
            lowered = name.lower()
            score = 0

            if "linux" in lowered:
                score += 10
            if "x64" in lowered or "x86_64" in lowered:
                score += 8
            if "bgfx" in lowered:
                score += 4

            if score:
                ranked_assets.append((score, name))

        ranked_assets.sort(reverse=True)
        asset_name = ranked_assets[0][1] if ranked_assets else ""

        source_text = asset_name or tag
        version, revision, commit = _version_parts(source_text or tag)

        display_bits = ["GitHub"]
        if version:
            display_bits.append(version)
        if revision:
            display_bits.append(f"Rev {revision}")
        if commit:
            display_bits.append(commit)
        if asset_name:
            display_bits.append("Linux x64")

        result = {
            "available": bool(version or tag),
            "display": " · ".join(display_bits) if len(display_bits) > 1 else "GitHub indisponible",
            "tag": tag,
            "asset": asset_name,
            "version": version,
            "revision": revision,
            "commit": commit,
            "published_at": str(payload.get("published_at") or ""),
            "error": "",
        }

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as error:
        result = {
            "available": False,
            "display": "GitHub indisponible",
            "tag": "",
            "asset": "",
            "version": "",
            "revision": "",
            "commit": "",
            "published_at": "",
            "error": str(error),
        }

    with _cache_lock:
        _remote_cache["value"] = dict(result)
        _remote_cache["expires"] = time.monotonic() + CACHE_TTL_SECONDS

    return result


def _comparison(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, str]:
    local_version = _version_tuple(str(local.get("version") or ""))
    remote_version = _version_tuple(str(remote.get("version") or ""))

    if not local.get("available"):
        return {
            "state": "unknown",
            "label": "Version locale non détectée",
        }

    if not remote.get("available"):
        return {
            "state": "unknown",
            "label": "GitHub non disponible — version locale détectée",
        }

    if local_version and remote_version:
        if local_version > remote_version:
            return {
                "state": "ok",
                "label": "Build local plus récent que la dernière build GitHub",
            }

        if local_version < remote_version:
            return {
                "state": "update",
                "label": "Mise à jour VPX disponible sur GitHub",
            }

    local_rev = str(local.get("revision") or "")
    remote_rev = str(remote.get("revision") or "")

    if local_rev.isdigit() and remote_rev.isdigit():
        lr, rr = int(local_rev), int(remote_rev)
        if lr < rr:
            return {"state": "update", "label": "Mise à jour VPX-BGFX disponible"}
        if lr > rr:
            return {"state": "ok",
                    "label": "Build local plus récent que la dernière build GitHub"}
        return {"state": "ok", "label": f"À jour (build {local_rev})"}

    if local_rev and remote_rev and local_rev == remote_rev:
        return {
            "state": "ok",
            "label": "Même version et même révision",
        }

    return {
        "state": "ok",
        "label": "Même version principale — révision à vérifier",
    }


def register_pincabos_pinball_engine_vpx_version(app: Any) -> None:
    if app.extensions.get("pincabos_pinball_engine_vpx_version_v1"):
        return

    app.extensions["pincabos_pinball_engine_vpx_version_v1"] = True

    @app.route("/api/pinball-engine/vpx-version", methods=["GET"])
    def pincabos_pinball_engine_vpx_version() -> Any:
        local = _local_vpx()
        remote = _remote_vpx()
        return jsonify(
            {
                "ok": True,
                "local": local,
                "github": remote,
                "comparison": _comparison(local, remote),
            }
        )

    @app.after_request
    def pincabos_pinball_engine_vpx_version_inject(response: Any) -> Any:
        if request.method != "GET":
            return response

        if "text/html" not in (response.headers.get("Content-Type") or "").lower():
            return response

        try:
            body = response.get_data(as_text=True)
        except Exception:
            return response

        if MARKER in body or "</body" not in body.lower():
            return response

        injection = (
            f'<!-- {MARKER} -->'
            '<script src="/static/pincabos-pinball-engine-vpx-version.js?v=4"></script>'
        )

        index = body.lower().rfind("</body")
        if index < 0:
            return response

        response.set_data(body[:index] + injection + body[index:])
        response.headers.pop("Content-Length", None)
        return response
