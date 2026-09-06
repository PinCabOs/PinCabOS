from __future__ import annotations

import configparser
import ftplib
import hashlib
import html
import json
import mimetypes
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
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


VERSION = "1.2.5"
CONFIG_PATH = Path("/opt/pincabos/config/media-hunter/sources.json")
CREDENTIALS_DIR = CONFIG_PATH.parent / "credentials"
STATE_DIR = Path("/var/lib/pincabos/media-hunter")
STATE_PATH = STATE_DIR / "state.json"
RESULTS_PATH = STATE_DIR / "results.json"
CACHE_DIR = STATE_DIR / "cache"
VPINFE_INI = Path("/home/pinball/.config/vpinfe/vpinfe.ini")
DEFAULT_TABLE_ROOT = Path("/home/pinball/Tables")
VPINMDB_DEFAULT_BASE = "https://github.com/superhac/vpinmediadb/raw/refs/heads/main"
VPINMDB_DEFAULT_INDEX = VPINMDB_DEFAULT_BASE + "/vpinmdb.json"
PINBALLX_FTP_DEFAULT_HOST = "ftp.gameex.com"
PINBALLX_FTP_DEFAULT_PORT = 21
PINBALLX_FTP_DEFAULT_ROOT = "/-PinballX-/Media/Visual Pinball"
PINBALLX_FTP_MEDIA_FOLDERS: dict[str, list[str]] = {
    "bg": ["Backglass Images"],
    "dmd": ["DMD Images"],
    "table": ["Table Images"],
    "wheel": ["Wheel Images"],
    "realdmd": ["Real DMD Images"],
    "realdmd_color": ["Real DMD Color Images"],
    "bg_video": ["Backglass Videos"],
    "dmd_video": ["DMD Videos"],
    "table_video": ["Table Videos", "Table Videos Lite", "Table Videos Desktop"],
    "audio": ["Launch Audio"],
}

MEDIA_SPECS: dict[str, dict[str, Any]] = {
    "bg": {"filename": "bg.png", "kind": "image", "aliases": ["bg", "backglass"]},
    "dmd": {"filename": "dmd.png", "kind": "image", "aliases": ["dmd"]},
    "table": {"filename": "table.png", "kind": "image", "aliases": ["table", "playfield", "pf"]},
    "wheel": {"filename": "wheel.png", "kind": "image", "aliases": ["wheel", "logo"]},
    "cab": {"filename": "cab.png", "kind": "image", "aliases": ["cab", "cabinet"]},
    "realdmd": {"filename": "realdmd.png", "kind": "image", "aliases": ["realdmd", "real dmd"]},
    "realdmd_color": {"filename": "realdmd-color.png", "kind": "image", "aliases": ["realdmd color", "realdmd-color"]},
    "flyer": {"filename": "flyer.png", "kind": "image", "aliases": ["flyer", "gameinfo", "info"]},
    "bg_video": {"filename": "bg.mp4", "kind": "video", "aliases": ["bg video", "backglass video"]},
    "dmd_video": {"filename": "dmd.mp4", "kind": "video", "aliases": ["dmd video"]},
    "table_video": {"filename": "table.mp4", "kind": "video", "aliases": ["table video", "playfield video"]},
    "audio": {"filename": "audio.mp3", "kind": "audio", "aliases": ["audio", "launch audio"]},
}

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "overwrite_existing": False,
    "sources": [
        {
            "id": "vpinmediadb",
            "name": "Superhac VPinMediaDB (source VPin Studio)",
            "type": "vpinmediadb",
            "enabled": True,
            "priority": 10,
            "base_url": VPINMDB_DEFAULT_BASE,
            "media_types": list(MEDIA_SPECS.keys()),
            "read_only": True,
        }
    ],
}

_LOCK = threading.RLock()
_WORKER: threading.Thread | None = None
_STOP = threading.Event()
_MEMORY_STATE: dict[str, Any] = {}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _ensure_layout() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CREDENTIALS_DIR.chmod(0o700)
    except OSError:
        pass
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        _atomic_json_write(CONFIG_PATH, DEFAULT_CONFIG)
    if not STATE_PATH.exists():
        _atomic_json_write(STATE_PATH, _default_state())
    if not RESULTS_PATH.exists():
        _atomic_json_write(RESULTS_PATH, {"tables": [], "summary": {}, "updated_at": ""})


def _default_state() -> dict[str, Any]:
    return {
        "version": VERSION,
        "running": False,
        "mode": "idle",
        "message": "Prêt",
        "started_at": "",
        "updated_at": _now(),
        "finished_at": "",
        "current_table": "",
        "current_media": "",
        "processed": 0,
        "total": 0,
        "downloaded": 0,
        "found": 0,
        "not_found": 0,
        "errors": 0,
        "stop_requested": False,
        "log": [],
    }


def _recover_stale_state() -> None:
    global _MEMORY_STATE
    with _LOCK:
        state = _read_json(STATE_PATH, _default_state())
        if not isinstance(state, dict):
            state = _default_state()

        worker_alive = bool(_WORKER and _WORKER.is_alive())
        if state.get("running") and not worker_alive:
            entries = state.get("log")
            if not isinstance(entries, list):
                entries = []
            entries.append({
                "time": _now(),
                "level": "warning",
                "message": "Opération interrompue automatiquement par un redémarrage de la WebApp.",
            })
            state.update({
                "running": False,
                "mode": "idle",
                "message": "Interrompu par redémarrage — prêt",
                "finished_at": _now(),
                "updated_at": _now(),
                "current_table": "",
                "current_media": "",
                "stop_requested": False,
                "log": entries[-250:],
            })
            _atomic_json_write(STATE_PATH, state)
        _MEMORY_STATE = state


def _atomic_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _load_config() -> dict[str, Any]:
    _ensure_layout()
    config = _read_json(CONFIG_PATH, DEFAULT_CONFIG)
    if not isinstance(config, dict):
        config = json.loads(json.dumps(DEFAULT_CONFIG))
    config.setdefault("version", 1)
    config["overwrite_existing"] = False
    sources = config.get("sources")
    if not isinstance(sources, list):
        sources = []
    config["sources"] = sources
    return config


def _save_config(config: dict[str, Any]) -> None:
    config["overwrite_existing"] = False
    _atomic_json_write(CONFIG_PATH, config)


def _credential_path(source_id: str) -> Path:
    safe_id = _safe_source_id(source_id)
    if not safe_id:
        raise ValueError("Identifiant FTP invalide")
    return CREDENTIALS_DIR / f"{safe_id}.json"


def _load_ftp_credentials(source_id: str) -> dict[str, str]:
    payload = _read_json(_credential_path(source_id), {})
    if not isinstance(payload, dict):
        return {"username": "", "password": ""}
    return {
        "username": str(payload.get("username") or ""),
        "password": str(payload.get("password") or ""),
    }


def _save_ftp_credentials(source_id: str, username: str, password: str) -> None:
    _ensure_layout()
    username = str(username or "").strip()
    password = str(password or "")
    previous = _load_ftp_credentials(source_id)

    if not username:
        username = previous.get("username", "")
    if not password:
        password = previous.get("password", "")

    if not username:
        raise ValueError("Utilisateur FTP requis")
    if not password:
        raise ValueError("Mot de passe FTP requis")

    path = _credential_path(source_id)
    _atomic_json_write(path, {"username": username, "password": password})
    path.chmod(0o600)


def _delete_ftp_credentials(source_id: str) -> None:
    try:
        _credential_path(source_id).unlink()
    except FileNotFoundError:
        pass


def _public_sources() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in _load_config().get("sources", []):
        if not isinstance(source, dict):
            continue
        public = json.loads(json.dumps(source))
        public.pop("password", None)
        public.pop("ftp_password", None)
        if public.get("type") == "ftp":
            credentials = _load_ftp_credentials(str(public.get("id") or ""))
            public["ftp_user"] = credentials.get("username", "")
            public["has_password"] = bool(credentials.get("password"))
        result.append(public)
    return result


def _ftp_clean_path(value: Any) -> str:
    raw = str(value or "/").strip().replace("\\", "/")
    if not raw:
        return "/"
    normalized = posixpath.normpath("/" + raw.lstrip("/"))
    return normalized if normalized.startswith("/") else "/" + normalized


def _ftp_join(base: str, child: str) -> str:
    return _ftp_clean_path(posixpath.join(_ftp_clean_path(base), str(child or "").strip("/")))


def _ftp_connect(source: dict[str, Any]):
    source_id = str(source.get("id") or "")
    credentials = _load_ftp_credentials(source_id)
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    if not username or not password:
        raise RuntimeError("Identifiants FTP absents. Enregistre l'utilisateur et le mot de passe.")

    host = str(source.get("ftp_host") or "").strip()
    if not host:
        raise RuntimeError("Serveur FTP absent")
    port = int(source.get("ftp_port") or 21)
    timeout = max(5, min(120, int(source.get("ftp_timeout") or 30)))
    use_tls = bool(source.get("ftp_tls", False))

    ftp = ftplib.FTP_TLS(timeout=timeout, encoding="utf-8") if use_tls else ftplib.FTP(timeout=timeout, encoding="utf-8")
    ftp.connect(host, port, timeout=timeout)
    ftp.login(username, password)
    if use_tls:
        ftp.prot_p()
    ftp.set_pasv(bool(source.get("ftp_passive", True)))
    return ftp


def _ftp_close(ftp: Any) -> None:
    try:
        ftp.quit()
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass


def _ftp_list_directory(ftp: Any, directory: str) -> list[dict[str, Any]]:
    directory = _ftp_clean_path(directory)
    entries: list[dict[str, Any]] = []

    try:
        for name, facts in ftp.mlsd(directory, facts=["type", "size", "modify"]):
            entry_type = str(facts.get("type") or "").casefold()
            if name in (".", "..") or entry_type in ("cdir", "pdir"):
                continue
            entries.append({
                "name": name,
                "path": _ftp_join(directory, name),
                "type": "dir" if entry_type == "dir" else "file",
                "size": int(facts.get("size") or 0) if str(facts.get("size") or "").isdigit() else 0,
            })
        return entries
    except ftplib.all_errors:
        pass

    original = ftp.pwd()
    try:
        ftp.cwd(directory)
        for name in ftp.nlst():
            base_name = posixpath.basename(str(name).rstrip("/"))
            if base_name in ("", ".", ".."):
                continue
            remote_path = _ftp_join(directory, base_name)
            entry_type = "file"
            size = 0
            try:
                ftp.cwd(remote_path)
                entry_type = "dir"
                ftp.cwd(directory)
            except ftplib.all_errors:
                try:
                    raw_size = ftp.size(remote_path)
                    size = int(raw_size or 0)
                except ftplib.all_errors:
                    size = 0
            entries.append({"name": base_name, "path": remote_path, "type": entry_type, "size": size})
    finally:
        try:
            ftp.cwd(original)
        except ftplib.all_errors:
            pass
    return entries


def _ftp_add_file_to_index(index: dict[str, list[dict[str, Any]]], entry: dict[str, Any]) -> None:
    name = str(entry.get("name") or "")
    if not name:
        return
    key = _normalize(Path(name).stem)
    if not key:
        return
    index.setdefault(key, []).append({
        "path": str(entry.get("path") or ""),
        "name": name,
        "size": int(entry.get("size") or 0),
    })


def _ftp_index_tree(
    ftp: Any,
    root: str,
    recursive: bool,
    max_files: int,
) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    pending = [_ftp_clean_path(root)]
    visited: set[str] = set()
    file_count = 0

    while pending and file_count < max_files:
        if _STOP.is_set():
            break
        current = pending.pop(0)
        if current in visited:
            continue
        visited.add(current)

        for entry in _ftp_list_directory(ftp, current):
            if _STOP.is_set():
                break
            if entry.get("type") == "dir":
                if recursive:
                    pending.append(str(entry.get("path") or ""))
                continue
            _ftp_add_file_to_index(index, entry)
            file_count += 1
            if file_count >= max_files:
                break
    return index


def _ftp_build_index(source: dict[str, Any]) -> dict[str, Any]:
    base_path = _ftp_clean_path(source.get("ftp_path") or "/")
    max_files = max(100, min(500000, int(source.get("max_files") or 100000)))
    pinballx_layout = bool(source.get("ftp_pinballx_layout", False))
    selected = source.get("media_types") or list(MEDIA_SPECS.keys())
    result: dict[str, Any] = {}

    ftp = _ftp_connect(source)
    try:
        if pinballx_layout:
            for media_type in selected:
                folders = PINBALLX_FTP_MEDIA_FOLDERS.get(str(media_type), [])
                if not folders:
                    continue
                media_index: dict[str, list[dict[str, Any]]] = {}
                for folder in folders:
                    remote_dir = _ftp_join(base_path, folder)
                    try:
                        folder_index = _ftp_index_tree(ftp, remote_dir, False, max_files)
                    except ftplib.all_errors as exc:
                        _log(f"FTP {source.get('name')} · {remote_dir}: {exc}", "warning")
                        continue
                    for key, values in folder_index.items():
                        media_index.setdefault(key, []).extend(values)
                result[str(media_type)] = media_index
        else:
            result["__all__"] = _ftp_index_tree(
                ftp,
                base_path,
                bool(source.get("recursive", False)),
                max_files,
            )
    finally:
        _ftp_close(ftp)
    return result



def _source_extensions(
    source: dict[str, Any],
    expected_kind: str,
    defaults: list[str],
) -> list[str]:
    raw = source.get("extensions") or defaults
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    extensions: list[str] = []
    for value in raw:
        suffix = str(value or "").strip().lower()
        if not suffix:
            continue
        if not suffix.startswith("."):
            suffix = "." + suffix
        if suffix not in extensions:
            extensions.append(suffix)
    if expected_kind == "video" and ".f4v" not in extensions:
        extensions.append(".f4v")
    return extensions


def _ftp_find(
    context: dict[str, Any],
    table: dict[str, Any],
    media_type: str,
    specs: dict[str, dict[str, Any]],
    source: dict[str, Any],
) -> str:
    index = context.get(media_type) if bool(source.get("ftp_pinballx_layout", False)) else context.get("__all__")
    if not isinstance(index, dict):
        return ""

    expected_kind = specs[media_type]["kind"]
    extensions = _source_extensions(source, expected_kind, [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4", ".mp3"])
    candidate_keys = [
        _normalize(Path(candidate).stem)
        for candidate in _folder_candidate_names(table, media_type, specs, [str(ext) for ext in extensions])
    ]
    candidate_keys = list(dict.fromkeys(key for key in candidate_keys if key))
    preferred_suffix = Path(specs[media_type]["filename"]).suffix.lower()

    values: list[dict[str, Any]] = []
    for key in candidate_keys:
        exact = index.get(key)
        if isinstance(exact, list):
            values.extend(exact)
    if not values:
        for indexed_key, indexed_values in index.items():
            if not isinstance(indexed_values, list):
                continue
            if any(indexed_key.startswith(key + " ") for key in candidate_keys):
                values.extend(indexed_values)

    def valid(entry: dict[str, Any]) -> bool:
        suffix = Path(str(entry.get("name") or entry.get("path") or "")).suffix.lower()
        if expected_kind == "image":
            return suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp")
        if expected_kind == "video":
            return suffix in (".mp4", ".mkv", ".webm", ".avi", ".f4v")
        if expected_kind == "audio":
            return suffix in (".mp3", ".ogg", ".wav", ".flac", ".m4a")
        return False

    ranked = sorted(
        (entry for entry in values if isinstance(entry, dict) and valid(entry)),
        key=lambda entry: (
            Path(str(entry.get("name") or "")).suffix.lower() != preferred_suffix,
            len(str(entry.get("name") or "")),
            str(entry.get("name") or "").casefold(),
        ),
    )
    return str(ranked[0].get("path") or "") if ranked else ""


def _ftp_download(
    source: dict[str, Any],
    remote_path: str,
    destination: Path,
    expected_kind: str,
) -> tuple[bool, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".part")
    ftp = None
    try:
        temp.unlink(missing_ok=True)
        ftp = _ftp_connect(source)
        with temp.open("wb") as handle:
            def write_chunk(chunk: bytes) -> None:
                if _STOP.is_set():
                    raise InterruptedError("Arrêt demandé")
                handle.write(chunk)
            ftp.retrbinary(f"RETR {remote_path}", write_chunk, blocksize=256 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        return _validate_and_commit(
            temp,
            destination,
            expected_kind,
            source_suffix=Path(remote_path).suffix.lower(),
        )
    except Exception as exc:
        temp.unlink(missing_ok=True)
        return False, str(exc)
    finally:
        if ftp is not None:
            _ftp_close(ftp)


def _load_state() -> dict[str, Any]:
    global _MEMORY_STATE
    _ensure_layout()
    with _LOCK:
        if _MEMORY_STATE:
            return json.loads(json.dumps(_MEMORY_STATE))
        state = _read_json(STATE_PATH, _default_state())
        if not isinstance(state, dict):
            state = _default_state()
        _MEMORY_STATE = state
        return json.loads(json.dumps(state))


def _set_state(**changes: Any) -> dict[str, Any]:
    global _MEMORY_STATE
    with _LOCK:
        state = _load_state()
        state.update(changes)
        state["updated_at"] = _now()
        _MEMORY_STATE = state
        _atomic_json_write(STATE_PATH, state)
        return json.loads(json.dumps(state))


def _log(message: str, level: str = "info") -> None:
    with _LOCK:
        state = _load_state()
        entries = state.setdefault("log", [])
        entries.append({"time": _now(), "level": level, "message": str(message)})
        del entries[:-250]
        state["updated_at"] = _now()
        global _MEMORY_STATE
        _MEMORY_STATE = state
        _atomic_json_write(STATE_PATH, state)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"\bthe\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _slug(value: Any) -> str:
    result = _normalize(value).replace(" ", "-")
    return result[:64] or "source"


def _safe_source_id(value: Any) -> str:
    source_id = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().casefold()).strip("-")
    return source_id[:64]


def _read_vpinfe_settings() -> dict[str, str]:
    settings = {
        "table_root": str(DEFAULT_TABLE_ROOT),
        "table_type": "table",
        "table_resolution": "4k",
        "table_video_resolution": "1k",
    }
    if not VPINFE_INI.exists():
        return settings
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(VPINFE_INI, encoding="utf-8")
        for section in parser.sections():
            for key, target in (
                ("tablerootdir", "table_root"),
                ("tabletype", "table_type"),
                ("tableresolution", "table_resolution"),
                ("tablevideoresolution", "table_video_resolution"),
            ):
                if parser.has_option(section, key):
                    value = parser.get(section, key).strip()
                    if value:
                        settings[target] = os.path.expanduser(value)
    except Exception as exc:
        _log(f"Lecture vpinfe.ini impossible: {exc}", "warning")
    return settings


def _media_specs_for_settings(settings: dict[str, str]) -> dict[str, dict[str, Any]]:
    specs = json.loads(json.dumps(MEDIA_SPECS))
    table_type = settings.get("table_type", "table").strip() or "table"
    specs["table"]["filename"] = f"{table_type}.png"
    specs["table_video"]["filename"] = f"{table_type}.mp4"
    return specs


def _find_vpsdb() -> Path | None:
    candidates = [
        Path("/home/pinball/.config/vpinfe/vpsdb.json"),
        Path(_pco_chemin("vpinfe_dir", "/opt/pinball/vpinfe")) / "resources/vpsdb.json",
        Path("/opt/pincabos/config/vpsdb.json"),
        Path("/opt/pincabos/web/vpsdb.json"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for base in (Path("/home/pinball/.config/vpinfe"), Path(_pco_chemin("vpinfe_dir", "/opt/pinball/vpinfe")), Path("/opt/pincabos")):
        if not base.exists():
            continue
        try:
            found = next(base.rglob("vpsdb.json"), None)
        except OSError:
            found = None
        if found and found.is_file():
            return found
    return None


def _load_vps_tables() -> list[dict[str, Any]]:
    path = _find_vpsdb()
    if not path:
        return []
    data = _read_json(path, [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("tables") or data.get("items") or []
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    return []


def _build_vps_lookup(tables: list[dict[str, Any]]) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str], str], dict[str, dict[str, Any]]]:
    exact: dict[tuple[str, str, str], str] = {}
    name_year: dict[tuple[str, str], str] = {}
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_name_year: set[tuple[str, str]] = set()
    for table in tables:
        table_id = str(table.get("id") or "").strip()
        if not table_id:
            continue
        by_id[table_id] = table
        name = _normalize(table.get("name"))
        manufacturer = _normalize(table.get("manufacturer"))
        year = str(table.get("year") or "").strip()
        if name and manufacturer and year:
            exact.setdefault((name, manufacturer, year), table_id)
        if name and year:
            key = (name, year)
            if key in name_year and name_year[key] != table_id:
                duplicate_name_year.add(key)
            else:
                name_year[key] = table_id
    for key in duplicate_name_year:
        name_year.pop(key, None)
    return exact, name_year, by_id


def _parse_table_folder(name: str) -> tuple[str, str, str]:
    match = re.match(r"^(.+?) \(([^()]+?) (\d{4})\)(?:\s.*)?$", name)
    if match:
        return match.group(1).strip(), match.group(2).strip(), match.group(3)
    return name.strip(), "", ""


def _read_info_metadata(table_dir: Path) -> tuple[str, dict[str, Any]]:
    candidates = sorted(table_dir.glob("*.info"))
    for path in candidates:
        data = _read_json(path, {})
        if not isinstance(data, dict):
            continue
        info = data.get("Info") if isinstance(data.get("Info"), dict) else {}
        vpinfe = data.get("VPinFE") if isinstance(data.get("VPinFE"), dict) else {}
        alt = str(vpinfe.get("altvpsid") or "").strip()
        main = str(info.get("VPSId") or info.get("VPSID") or "").strip()
        return alt or main, data
    return "", {}


def _table_identity(table_dir: Path, exact: dict[tuple[str, str, str], str], name_year: dict[tuple[str, str], str], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    folder_title, folder_manufacturer, folder_year = _parse_table_folder(table_dir.name)
    info_vps_id, info_data = _read_info_metadata(table_dir)
    info = info_data.get("Info") if isinstance(info_data.get("Info"), dict) else {}
    title = str(info.get("Title") or folder_title).strip()
    manufacturer = str(info.get("Manufacturer") or folder_manufacturer).strip()
    year = str(info.get("Year") or folder_year).strip()
    vps_id = info_vps_id
    match = "info" if vps_id else ""
    if vps_id and vps_id not in by_id:
        match = "info-unverified"
    if not vps_id and title and manufacturer and year:
        vps_id = exact.get((_normalize(title), _normalize(manufacturer), year), "")
        if vps_id:
            match = "exact-name-manufacturer-year"
    if not vps_id and title and year:
        vps_id = name_year.get((_normalize(title), year), "")
        if vps_id:
            match = "exact-name-year"
    return {
        "name": table_dir.name,
        "title": title,
        "manufacturer": manufacturer,
        "year": year,
        "vps_id": vps_id,
        "vps_match": match or "none",
        "path": str(table_dir),
    }


def _scan_tables() -> dict[str, Any]:
    settings = _read_vpinfe_settings()
    root = Path(settings["table_root"]).expanduser()
    specs = _media_specs_for_settings(settings)
    if not root.is_dir():
        raise RuntimeError(f"Racine des tables absente: {root}")
    vps_tables = _load_vps_tables()
    exact, name_year, by_id = _build_vps_lookup(vps_tables)
    table_dirs = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name.casefold())
    rows: list[dict[str, Any]] = []
    missing_counts = {key: 0 for key in specs}
    complete = 0
    for index, table_dir in enumerate(table_dirs, start=1):
        if _STOP.is_set():
            break
        identity = _table_identity(table_dir, exact, name_year, by_id)
        media_dir = table_dir / "medias"
        missing: list[str] = []
        present: list[str] = []
        for media_type, spec in specs.items():
            destination = media_dir / spec["filename"]
            if destination.is_file() and destination.stat().st_size > 0:
                present.append(media_type)
            else:
                missing.append(media_type)
                missing_counts[media_type] += 1
        if not missing:
            complete += 1
        identity.update({
            "media_dir": str(media_dir),
            "missing": missing,
            "present": present,
            "status": "complete" if not missing else "missing",
            "last_action": "",
            "found": [],
            "errors": [],
        })
        rows.append(identity)
        _set_state(current_table=table_dir.name, processed=index, total=len(table_dirs), message=f"Analyse {index}/{len(table_dirs)}")
    summary = {
        "table_root": str(root),
        "tables": len(rows),
        "complete": complete,
        "incomplete": len(rows) - complete,
        "missing_total": sum(len(row["missing"]) for row in rows),
        "missing_by_type": missing_counts,
        "vps_matched": sum(1 for row in rows if row.get("vps_id")),
        "vps_unmatched": sum(1 for row in rows if not row.get("vps_id")),
        "vpsdb_path": str(_find_vpsdb() or ""),
    }
    payload = {"tables": rows, "summary": summary, "updated_at": _now(), "settings": settings}
    _atomic_json_write(RESULTS_PATH, payload)
    return payload


def _source_supports(source: dict[str, Any], media_type: str) -> bool:
    media_types = source.get("media_types")
    if not media_types or media_types == ["all"] or media_types == "all":
        return True
    return media_type in media_types


def _http_open(url: str, method: str = "GET", timeout: int = 20):
    request_obj = urllib.request.Request(url, method=method, headers={"User-Agent": f"PinCabOS-Medias-Hunter/{VERSION}"})
    return urllib.request.urlopen(request_obj, timeout=timeout)


def _download_url(url: str, destination: Path, expected_kind: str) -> tuple[bool, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".part")
    try:
        if temp.exists():
            temp.unlink()
        with _http_open(url, "GET", timeout=60) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type or "application/json" in content_type:
                return False, f"Réponse non média ({content_type})"
            with temp.open("wb") as handle:
                while True:
                    if _STOP.is_set():
                        raise InterruptedError("Arrêt demandé")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
        return _validate_and_commit(temp, destination, expected_kind, source_suffix=Path(urllib.parse.urlparse(url).path).suffix.lower())
    except Exception as exc:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        return False, str(exc)


def _copy_local(source_path: Path, destination: Path, expected_kind: str) -> tuple[bool, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".part")
    try:
        if temp.exists():
            temp.unlink()
        shutil.copy2(source_path, temp)
        return _validate_and_commit(temp, destination, expected_kind, source_suffix=source_path.suffix.lower())
    except Exception as exc:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        return False, str(exc)



def _run_media_process(command: list[str], timeout: int = 7200) -> tuple[bool, str]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started = time.monotonic()
    while process.poll() is None:
        if _STOP.is_set():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            return False, "Arrêt demandé"
        if time.monotonic() - started > timeout:
            process.kill()
            process.wait(timeout=5)
            return False, f"Conversion interrompue après {timeout} secondes"
        time.sleep(0.2)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        detail = (stderr or stdout or "Erreur inconnue").strip()
        return False, detail[-1200:]
    return True, (stderr or stdout or "").strip()[-1200:]


def _probe_mp4(path: Path) -> tuple[bool, str]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return False, "ffprobe est absent"
    ok, detail = _run_media_process(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=60,
    )
    if not ok:
        return False, f"Validation ffprobe impossible: {detail}"
    if "video" not in detail.casefold():
        return False, "Aucune piste vidéo détectée dans le MP4"
    return True, "MP4 validé"


def _ffmpeg_encoder_names(ffmpeg: str) -> set[str]:
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return set()

    names: set[str] = set()
    for line in (result.stdout or "").splitlines():
        match = re.match(r"^\s*[VAS\.]{6}\s+([^\s]+)", line)
        if match:
            names.add(match.group(1))
    return names


def _f4v_transcode_attempts(ffmpeg: str, temp: Path, output: Path) -> list[tuple[str, list[str]]]:
    encoders = _ffmpeg_encoder_names(ffmpeg)
    audio_args = ["-c:a", "aac", "-b:a", "192k"] if "aac" in encoders else ["-c:a", "copy"]
    common = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(temp),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]
    ending = [
        *audio_args,
        "-movflags",
        "+faststart",
        str(output),
    ]

    attempts: list[tuple[str, list[str]]] = []
    if "libx264" in encoders:
        attempts.append(
            (
                "transcodage H.264/libx264",
                [
                    *common,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    *ending,
                ],
            )
        )
    if "h264_nvenc" in encoders:
        attempts.append(
            (
                "transcodage H.264/NVIDIA NVENC",
                [
                    *common,
                    "-c:v",
                    "h264_nvenc",
                    "-preset",
                    "p4",
                    "-cq",
                    "20",
                    "-b:v",
                    "0",
                    "-pix_fmt",
                    "yuv420p",
                    *ending,
                ],
            )
        )
    if "libopenh264" in encoders:
        attempts.append(
            (
                "transcodage H.264/OpenH264",
                [
                    *common,
                    "-c:v",
                    "libopenh264",
                    "-b:v",
                    "8M",
                    "-pix_fmt",
                    "yuv420p",
                    *ending,
                ],
            )
        )
    if "mpeg4" in encoders:
        attempts.append(
            (
                "transcodage MPEG-4",
                [
                    *common,
                    "-c:v",
                    "mpeg4",
                    "-q:v",
                    "3",
                    "-pix_fmt",
                    "yuv420p",
                    *ending,
                ],
            )
        )
    return attempts


def _convert_f4v_to_mp4(temp: Path) -> tuple[bool, Path | None, str]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, None, "ffmpeg est absent; impossible de convertir le F4V"

    output = temp.with_name(temp.name + ".converted.mp4")
    output.unlink(missing_ok=True)

    remux_command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(temp),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ]
    ok, detail = _run_media_process(remux_command)
    if ok and output.is_file() and output.stat().st_size >= 64:
        probe_ok, probe_detail = _probe_mp4(output)
        if probe_ok:
            return True, output, "F4V converti en MP4 par remux sans perte"
        detail = probe_detail

    output.unlink(missing_ok=True)
    errors: list[str] = []
    if detail:
        errors.append(f"remux: {detail}")

    attempts = _f4v_transcode_attempts(ffmpeg, temp, output)
    if not attempts:
        return (
            False,
            None,
            "Le remux F4V a échoué et aucun encodeur de secours compatible "
            "(libx264, h264_nvenc, libopenh264 ou mpeg4) n'est disponible",
        )

    for mode, command in attempts:
        output.unlink(missing_ok=True)
        ok, attempt_detail = _run_media_process(command)
        if not ok:
            errors.append(f"{mode}: {attempt_detail}")
            if _STOP.is_set():
                return False, None, "Arrêt demandé"
            continue
        if not output.is_file() or output.stat().st_size < 64:
            errors.append(f"{mode}: aucun MP4 valide produit")
            continue
        probe_ok, probe_detail = _probe_mp4(output)
        if probe_ok:
            return True, output, f"F4V converti en MP4 par {mode}"
        errors.append(f"{mode}: {probe_detail}")

    output.unlink(missing_ok=True)
    detail_text = " | ".join(errors)[-1800:]
    return False, None, f"Conversion F4V vers MP4 impossible: {detail_text}"

def _validate_and_commit(temp: Path, destination: Path, expected_kind: str, source_suffix: str = "") -> tuple[bool, str]:
    if destination.exists():
        temp.unlink(missing_ok=True)
        return False, "Le média existe déjà"
    if not temp.is_file() or temp.stat().st_size < 64:
        temp.unlink(missing_ok=True)
        return False, "Fichier vide ou trop petit"
    head = temp.read_bytes()[:32]
    if head.lstrip().startswith((b"<!DOCTYPE", b"<html", b"{")):
        temp.unlink(missing_ok=True)
        return False, "Le fichier reçu n'est pas un média"
    destination_suffix = destination.suffix.lower()
    actual_source_suffix = (source_suffix or destination_suffix).lower()
    conversion_note = ""
    if expected_kind == "video" and actual_source_suffix == ".f4v":
        converted_ok, converted_path, conversion_note = _convert_f4v_to_mp4(temp)
        if not converted_ok or converted_path is None:
            temp.unlink(missing_ok=True)
            return False, conversion_note
        temp.unlink(missing_ok=True)
        temp = converted_path
    if expected_kind == "image" and actual_source_suffix and actual_source_suffix != destination_suffix:
        if destination_suffix == ".png":
            try:
                from PIL import Image
                converted = temp.with_suffix(".converted.png")
                with Image.open(temp) as image:
                    image.save(converted, format="PNG")
                temp.unlink(missing_ok=True)
                temp = converted
            except Exception as exc:
                temp.unlink(missing_ok=True)
                return False, f"Conversion vers PNG impossible: {exc}"
    os.replace(temp, destination)
    detail = f"Installé ({destination.stat().st_size} octets)"
    if conversion_note:
        detail += f" · {conversion_note}"
    return True, detail


def _vpinmedia_url(index: dict[str, Any], table: dict[str, Any], media_type: str, source: dict[str, Any], settings: dict[str, str]) -> str:
    vps_id = str(table.get("vps_id") or "")
    if not vps_id or vps_id not in index:
        return ""
    entry = index.get(vps_id)
    if not isinstance(entry, dict):
        return ""
    direct_map = {
        "wheel": "wheel",
        "cab": "cab",
        "realdmd": "realdmd",
        "realdmd_color": "realdmd_color",
        "flyer": "flyer",
        "audio": "audio",
    }
    if media_type in direct_map:
        return str(entry.get(direct_map[media_type]) or "")
    if media_type in ("bg", "dmd"):
        group = entry.get("1k")
        return str(group.get(media_type) or "") if isinstance(group, dict) else ""
    if media_type == "table":
        preferred = settings.get("table_resolution", "4k")
        for resolution in (preferred, "4k", "2k", "1k"):
            group = entry.get(resolution)
            if isinstance(group, dict):
                value = group.get(settings.get("table_type", "table")) or group.get("table")
                if value:
                    return str(value)
        return ""
    if media_type in ("bg_video", "dmd_video", "table_video"):
        preferred = settings.get("table_video_resolution", "1k")
        key = media_type
        if media_type == "table_video":
            key = f"{settings.get('table_type', 'table')}_video"
        for resolution in (preferred, "4k", "2k", "1k"):
            group = entry.get(resolution)
            if isinstance(group, dict):
                value = group.get(key) or (group.get("table_video") if media_type == "table_video" else None)
                if value:
                    return str(value)
        return ""
    return ""


def _download_json_cached(url: str, cache_name: str, max_age: int = 3600) -> Any:
    cache_path = CACHE_DIR / cache_name
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < max_age:
        cached = _read_json(cache_path, None)
        if cached is not None:
            return cached
    with _http_open(url, "GET", timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    _atomic_json_write(cache_path, data)
    return data


def _folder_candidate_names(table: dict[str, Any], media_type: str, specs: dict[str, dict[str, Any]], extensions: list[str]) -> list[str]:
    bases: list[str] = []
    for value in (table.get("name"), table.get("title")):
        if value and value not in bases:
            bases.append(str(value))
    title = str(table.get("title") or "")
    manufacturer = str(table.get("manufacturer") or "")
    year = str(table.get("year") or "")
    if title and manufacturer and year:
        bases.append(f"{title} ({manufacturer} {year})")
        bases.append(f"{title} {manufacturer} {year}")
    if table.get("vps_id"):
        bases.append(str(table["vps_id"]))
    aliases = specs[media_type].get("aliases", [])
    names: list[str] = []
    for base in bases:
        for extension in extensions:
            ext = extension if extension.startswith(".") else "." + extension
            names.append(base + ext)
            for alias in aliases:
                names.append(f"{base} {alias}{ext}")
                names.append(f"{base}-{alias}{ext}")
                names.append(f"{base}_{alias}{ext}")
    return list(dict.fromkeys(names))


def _index_folder(source: dict[str, Any]) -> dict[str, list[str]]:
    raw_path = str(source.get("path") or source.get("location") or "").strip()
    if raw_path.startswith("file://"):
        raw_path = urllib.parse.unquote(urllib.parse.urlparse(raw_path).path)
    if raw_path.startswith("\\\\") or raw_path.startswith("smb://"):
        raise RuntimeError("Chemin SMB/UNC non monté. Monte le partage dans Stockage, puis utilise son chemin Linux.")
    root = Path(os.path.expanduser(raw_path))
    if not root.is_dir():
        raise RuntimeError(f"Dossier inaccessible: {root}")
    recursive = bool(source.get("recursive", True))
    iterator = root.rglob("*") if recursive else root.glob("*")
    index: dict[str, list[str]] = {}
    max_files = int(source.get("max_files") or 250000)
    count = 0
    for path in iterator:
        if _STOP.is_set():
            break
        if not path.is_file():
            continue
        count += 1
        if count > max_files:
            break
        key = _normalize(path.stem)
        index.setdefault(key, []).append(str(path))
    return index


def _folder_find(index: dict[str, list[str]], table: dict[str, Any], media_type: str, specs: dict[str, dict[str, Any]], source: dict[str, Any]) -> Path | None:
    expected_kind = specs[media_type]["kind"]
    extensions = _source_extensions(source, expected_kind, [".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mp3"])
    for candidate in _folder_candidate_names(table, media_type, specs, [str(ext) for ext in extensions]):
        values = index.get(_normalize(Path(candidate).stem), [])
        if not values:
            continue
        preferred_suffix = Path(specs[media_type]["filename"]).suffix.lower()
        ranked = sorted(values, key=lambda value: (Path(value).suffix.lower() != preferred_suffix, len(value)))
        for value in ranked:
            path = Path(value)
            suffix = path.suffix.lower()
            if expected_kind == "image" and suffix in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                return path
            if expected_kind == "video" and suffix in (".mp4", ".mkv", ".webm", ".avi", ".f4v"):
                return path
            if expected_kind == "audio" and suffix in (".mp3", ".ogg", ".wav", ".flac"):
                return path
    return None


def _web_candidate_urls(source: dict[str, Any], table: dict[str, Any], media_type: str, specs: dict[str, dict[str, Any]]) -> list[str]:
    base_url = str(source.get("base_url") or source.get("url") or "").strip()
    template = str(source.get("template") or "").strip()
    if not base_url and not template:
        return []
    if base_url and not re.match(r"^https?://", base_url, re.I):
        return []
    filename = specs[media_type]["filename"]
    values = {
        "vps_id": urllib.parse.quote(str(table.get("vps_id") or ""), safe=""),
        "name": urllib.parse.quote(str(table.get("name") or ""), safe=""),
        "title": urllib.parse.quote(str(table.get("title") or ""), safe=""),
        "manufacturer": urllib.parse.quote(str(table.get("manufacturer") or ""), safe=""),
        "year": urllib.parse.quote(str(table.get("year") or ""), safe=""),
        "media": urllib.parse.quote(media_type, safe=""),
        "filename": urllib.parse.quote(filename, safe=""),
    }
    urls: list[str] = []
    if template:
        raw_template = template if re.match(r"^https?://", template, re.I) else base_url.rstrip("/") + "/" + template.lstrip("/")
        try:
            urls.append(raw_template.format(**values))
        except Exception:
            pass
    else:
        extensions = _source_extensions(source, specs[media_type]["kind"], [Path(filename).suffix])
        for candidate in _folder_candidate_names(table, media_type, specs, [str(ext) for ext in extensions]):
            urls.append(base_url.rstrip("/") + "/" + urllib.parse.quote(candidate))
    return list(dict.fromkeys(urls))


def _test_url_exists(url: str) -> bool:
    try:
        with _http_open(url, "HEAD", timeout=10) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            return response.status < 400 and "text/html" not in content_type
    except Exception:
        try:
            request_obj = urllib.request.Request(
                url,
                method="GET",
                headers={
                    "User-Agent": f"PinCabOS-Medias-Hunter/{VERSION}",
                    "Range": "bytes=0-63",
                },
            )
            with urllib.request.urlopen(request_obj, timeout=10) as response:
                content_type = str(response.headers.get("Content-Type") or "").lower()
                return response.status < 400 and "text/html" not in content_type
        except Exception:
            return False


def _hunt_tables(selected_names: list[str] | None = None) -> dict[str, Any]:
    payload = _read_json(RESULTS_PATH, {})
    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), list) or not payload.get("tables"):
        payload = _scan_tables()
    tables = payload.get("tables", [])
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else _read_vpinfe_settings()
    specs = _media_specs_for_settings(settings)
    selected = set(selected_names or [])
    if selected:
        tables_to_process = [table for table in tables if table.get("name") in selected]
    else:
        tables_to_process = [table for table in tables if table.get("missing")]
    config = _load_config()
    sources = sorted(
        (source for source in config.get("sources", []) if isinstance(source, dict) and source.get("enabled", True)),
        key=lambda source: (int(source.get("priority") or 100), str(source.get("name") or "")),
    )
    contexts: dict[str, Any] = {}
    for source in sources:
        source_id = str(source.get("id") or "")
        source_type = str(source.get("type") or "")
        try:
            if source_type == "vpinmediadb":
                base = str(source.get("base_url") or VPINMDB_DEFAULT_BASE).rstrip("/")
                contexts[source_id] = _download_json_cached(base + "/vpinmdb.json", f"{_slug(source_id)}-vpinmdb.json")
            elif source_type == "folder":
                contexts[source_id] = _index_folder(source)
            elif source_type == "ftp":
                contexts[source_id] = _ftp_build_index(source)
        except Exception as exc:
            contexts[source_id] = {"__error__": str(exc)}
            _log(f"Source {source.get('name')}: {exc}", "error")
    downloaded = found = not_found = errors = 0
    total_actions = sum(len(table.get("missing", [])) for table in tables_to_process)
    processed_actions = 0
    _set_state(total=total_actions, processed=0, downloaded=0, found=0, not_found=0, errors=0)
    for table in tables_to_process:
        if _STOP.is_set():
            break
        table["found"] = []
        table["errors"] = []
        media_dir = Path(str(table.get("media_dir") or Path(str(table["path"])) / "medias"))
        remaining: list[str] = []
        for media_type in list(table.get("missing", [])):
            if _STOP.is_set():
                remaining.append(media_type)
                continue
            processed_actions += 1
            _set_state(
                current_table=table.get("name", ""),
                current_media=media_type,
                processed=processed_actions,
                total=total_actions,
                message=f"Recherche {processed_actions}/{total_actions}",
            )
            spec = specs.get(media_type)
            if not spec:
                remaining.append(media_type)
                continue
            destination = media_dir / spec["filename"]
            if destination.exists():
                continue
            installed = False
            source_found = False
            for source in sources:
                if not _source_supports(source, media_type):
                    continue
                source_id = str(source.get("id") or "")
                source_name = str(source.get("name") or source_id)
                source_type = str(source.get("type") or "")
                context = contexts.get(source_id)
                if isinstance(context, dict) and context.get("__error__"):
                    continue
                try:
                    if source_type == "vpinmediadb":
                        url = _vpinmedia_url(context if isinstance(context, dict) else {}, table, media_type, source, settings)
                        if not url:
                            continue
                        source_found = True
                        ok, detail = _download_url(url, destination, spec["kind"])
                        if ok:
                            installed = True
                            downloaded += 1
                            found += 1
                            table["found"].append({"media": media_type, "source": source_name, "value": url, "installed": True})
                            _log(f"{table['name']} · {media_type}: installé depuis {source_name}")
                            break
                        table["errors"].append(f"{source_name}/{media_type}: {detail}")
                    elif source_type == "folder":
                        local_path = _folder_find(context if isinstance(context, dict) else {}, table, media_type, specs, source)
                        if not local_path:
                            continue
                        source_found = True
                        ok, detail = _copy_local(local_path, destination, spec["kind"])
                        if ok:
                            installed = True
                            downloaded += 1
                            found += 1
                            table["found"].append({"media": media_type, "source": source_name, "value": str(local_path), "installed": True})
                            _log(f"{table['name']} · {media_type}: installé depuis {source_name}")
                            break
                        table["errors"].append(f"{source_name}/{media_type}: {detail}")
                    elif source_type == "ftp":
                        remote_path = _ftp_find(context if isinstance(context, dict) else {}, table, media_type, specs, source)
                        if not remote_path:
                            continue
                        source_found = True
                        ok, detail = _ftp_download(source, remote_path, destination, spec["kind"])
                        if ok:
                            installed = True
                            downloaded += 1
                            found += 1
                            table["found"].append({"media": media_type, "source": source_name, "value": remote_path, "installed": True})
                            _log(f"{table['name']} · {media_type}: installé depuis {source_name}")
                            break
                        table["errors"].append(f"{source_name}/{media_type}: {detail}")
                    elif source_type == "web":
                        for url in _web_candidate_urls(source, table, media_type, specs):
                            if _STOP.is_set():
                                break
                            if not _test_url_exists(url):
                                continue
                            source_found = True
                            ok, detail = _download_url(url, destination, spec["kind"])
                            if ok:
                                installed = True
                                downloaded += 1
                                found += 1
                                table["found"].append({"media": media_type, "source": source_name, "value": url, "installed": True})
                                _log(f"{table['name']} · {media_type}: installé depuis {source_name}")
                                break
                            table["errors"].append(f"{source_name}/{media_type}: {detail}")
                        if installed:
                            break
                except Exception as exc:
                    table["errors"].append(f"{source_name}/{media_type}: {exc}")
                    errors += 1
            if not installed:
                remaining.append(media_type)
                not_found += 1
                if source_found:
                    errors += 1
            _set_state(downloaded=downloaded, found=found, not_found=not_found, errors=errors)
        table["missing"] = remaining
        table["status"] = "complete" if not remaining else "missing"
        table["last_action"] = _now()
        _atomic_json_write(RESULTS_PATH, payload)
    payload["updated_at"] = _now()
    summary = payload.setdefault("summary", {})
    summary["complete"] = sum(1 for table in tables if not table.get("missing"))
    summary["incomplete"] = sum(1 for table in tables if table.get("missing"))
    summary["missing_total"] = sum(len(table.get("missing", [])) for table in tables)
    summary["last_hunt"] = {
        "downloaded": downloaded,
        "found": found,
        "not_found": not_found,
        "errors": errors,
        "stopped": _STOP.is_set(),
    }
    _atomic_json_write(RESULTS_PATH, payload)
    return payload


def _run_job(mode: str, selected_names: list[str] | None = None) -> None:
    global _WORKER
    try:
        _STOP.clear()
        state = _default_state()
        state.update({"running": True, "mode": mode, "message": "Démarrage", "started_at": _now()})
        global _MEMORY_STATE
        with _LOCK:
            _MEMORY_STATE = state
            _atomic_json_write(STATE_PATH, state)
        if mode == "scan":
            _log("Analyse des médias manquants démarrée")
            _scan_tables()
        elif mode == "hunt":
            _log("Recherche et installation des médias manquants démarrée")
            _hunt_tables(selected_names)
        final_message = "Arrêté à la demande" if _STOP.is_set() else "Terminé"
        _set_state(running=False, mode="idle", finished_at=_now(), message=final_message, stop_requested=_STOP.is_set(), current_table="", current_media="")
        _log(final_message, "warning" if _STOP.is_set() else "success")
    except Exception as exc:
        _log(f"Erreur fatale: {exc}", "error")
        _set_state(running=False, mode="idle", finished_at=_now(), message=f"Erreur: {exc}", errors=_load_state().get("errors", 0) + 1)
    finally:
        with _LOCK:
            _WORKER = None


def _start_job(mode: str, selected_names: list[str] | None = None) -> tuple[bool, str]:
    global _WORKER
    with _LOCK:
        if _WORKER and _WORKER.is_alive():
            return False, "Une opération Medias Hunter est déjà en cours"
        _WORKER = threading.Thread(target=_run_job, args=(mode, selected_names), daemon=True, name=f"media-hunter-{mode}")
        _WORKER.start()
    return True, "Opération démarrée"


def _source_test(source: dict[str, Any]) -> tuple[bool, str]:
    source_type = str(source.get("type") or "")
    if source_type == "vpinmediadb":
        base = str(source.get("base_url") or VPINMDB_DEFAULT_BASE).rstrip("/")
        data = _download_json_cached(base + "/vpinmdb.json", f"test-{_slug(source.get('id'))}.json", max_age=0)
        count = len(data) if isinstance(data, dict) else 0
        return count > 0, f"Index accessible: {count} entrées"
    if source_type == "folder":
        raw_path = str(source.get("path") or source.get("location") or "").strip()
        if raw_path.startswith("\\\\") or raw_path.startswith("smb://"):
            return False, "Monte d'abord le partage SMB dans Stockage et utilise le chemin Linux monté."
        root = Path(os.path.expanduser(raw_path.replace("file://", "")))
        if not root.is_dir():
            return False, f"Dossier inaccessible: {root}"
        try:
            sample = next((path for path in root.iterdir()), None)
        except Exception as exc:
            return False, f"Lecture impossible: {exc}"
        return True, f"Dossier accessible{': ' + sample.name if sample else ' (vide)'}"
    if source_type == "web":
        url = str(source.get("base_url") or source.get("url") or "").strip()
        if not re.match(r"^https?://", url, re.I):
            return False, "URL HTTP/HTTPS requise"
        try:
            with _http_open(url, "HEAD", timeout=12) as response:
                return response.status < 400, f"HTTP {response.status}"
        except Exception as exc:
            return False, str(exc)
    if source_type == "ftp":
        ftp = None
        try:
            ftp = _ftp_connect(source)
            remote_path = _ftp_clean_path(source.get("ftp_path") or "/")
            entries = _ftp_list_directory(ftp, remote_path)
            sample = next((str(entry.get("name") or "") for entry in entries if entry.get("name")), "")
            mode = "structure PinballX" if source.get("ftp_pinballx_layout") else "dossier FTP"
            return True, f"Connexion FTP réussie · {mode} · {len(entries)} entrées{(' · ' + sample) if sample else ''}"
        except Exception as exc:
            return False, f"Connexion FTP impossible: {exc}"
        finally:
            if ftp is not None:
                _ftp_close(ftp)
    return False, f"Type de source inconnu: {source_type}"



BROWSE_ROOT_CANDIDATES: tuple[tuple[str, Path], ...] = (
    ("Lecteurs réseau PinCabOS", Path("/home/pinball/NetworkDrives")),
    ("Dossier personnel pinball", Path("/home/pinball")),
    ("Montages /mnt", Path("/mnt")),
    ("Montages /media", Path("/media")),
    ("Montages /run/media", Path("/run/media")),
    ("Médias PinCabOS", Path("/opt/pincabos/media")),
)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _available_browse_roots() -> list[dict[str, str]]:
    roots: list[dict[str, str]] = []
    seen: set[str] = set()
    for label, candidate in BROWSE_ROOT_CANDIDATES:
        try:
            resolved = candidate.expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not resolved.is_dir() or not os.access(resolved, os.R_OK | os.X_OK):
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append({"label": label, "path": key})
    return roots


def _resolve_browse_path(raw_path: str) -> tuple[Path, list[Path]]:
    roots_payload = _available_browse_roots()
    roots = [Path(item["path"]) for item in roots_payload]
    if not roots:
        raise RuntimeError("Aucune racine locale accessible")

    value = os.path.expandvars(os.path.expanduser(str(raw_path or "").strip()))
    if not value:
        raise ValueError("Chemin vide")

    candidate = Path(value)
    if not candidate.is_absolute():
        raise ValueError("Un chemin Linux absolu est requis")

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError("Ce dossier n'existe pas") from exc
    except OSError as exc:
        raise OSError(f"Impossible d'ouvrir ce chemin : {exc}") from exc

    if not resolved.is_dir():
        raise NotADirectoryError("Le chemin sélectionné n'est pas un dossier")
    if not any(_path_is_within(resolved, root) for root in roots):
        raise PermissionError("Ce chemin est hors des racines autorisées")
    if not os.access(resolved, os.R_OK | os.X_OK):
        raise PermissionError("Lecture refusée pour ce dossier")
    return resolved, roots


def _browse_directory_payload(current: Path, roots: list[Path]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(current) as iterator:
            for entry in iterator:
                if entry.name.startswith("."):
                    continue
                try:
                    if not entry.is_dir(follow_symlinks=True):
                        continue
                    child = Path(entry.path).resolve(strict=True)
                    if not any(_path_is_within(child, root) for root in roots):
                        continue
                    readable = os.access(child, os.R_OK | os.X_OK)
                    entries.append({
                        "name": entry.name,
                        "path": str(child),
                        "readable": readable,
                    })
                except (OSError, RuntimeError):
                    continue
                if len(entries) >= 1000:
                    truncated = True
                    break
    except PermissionError as exc:
        raise PermissionError("Lecture refusée pour ce dossier") from exc

    entries.sort(key=lambda item: item["name"].casefold())
    root_set = {str(root) for root in roots}
    parent = ""
    if str(current) not in root_set:
        possible_parent = current.parent.resolve()
        if any(_path_is_within(possible_parent, root) for root in roots):
            parent = str(possible_parent)

    return {
        "current": str(current),
        "parent": parent,
        "entries": entries,
        "truncated": truncated,
    }

def _sanitize_source(raw: dict[str, Any], existing_id: str = "") -> dict[str, Any]:
    source_type = str(raw.get("type") or "").strip().casefold()
    if source_type not in {"vpinmediadb", "folder", "web", "ftp"}:
        raise ValueError("Type de source invalide")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("Nom de source requis")
    source_id = _safe_source_id(raw.get("id") or existing_id or _slug(name))
    if not source_id:
        raise ValueError("Identifiant de source invalide")
    media_types = raw.get("media_types") or []
    if isinstance(media_types, str):
        media_types = [item.strip() for item in media_types.split(",") if item.strip()]
    media_types = [item for item in media_types if item in MEDIA_SPECS]
    source: dict[str, Any] = {
        "id": source_id,
        "name": name,
        "type": source_type,
        "enabled": bool(raw.get("enabled", True)),
        "priority": max(1, min(9999, int(raw.get("priority") or 100))),
        "media_types": media_types or list(MEDIA_SPECS.keys()),
        "read_only": True,
    }
    if source_type == "vpinmediadb":
        source["base_url"] = str(raw.get("base_url") or VPINMDB_DEFAULT_BASE).strip().rstrip("/")
    elif source_type == "folder":
        path = str(raw.get("path") or raw.get("location") or "").strip()
        if not path:
            raise ValueError("Chemin requis")
        source["path"] = path
        source["recursive"] = bool(raw.get("recursive", True))
        source["extensions"] = raw.get("extensions") or [".png", ".jpg", ".jpeg", ".webp", ".mp4", ".f4v", ".mp3"]
    elif source_type == "web":
        base_url = str(raw.get("base_url") or raw.get("url") or "").strip()
        if not re.match(r"^https?://", base_url, re.I):
            raise ValueError("URL HTTP/HTTPS requise")
        source["base_url"] = base_url.rstrip("/")
        source["template"] = str(raw.get("template") or "").strip()
        source["extensions"] = raw.get("extensions") or [".png", ".jpg", ".jpeg", ".webp", ".mp4", ".f4v", ".mp3"]
    elif source_type == "ftp":
        host = str(raw.get("ftp_host") or "").strip()
        if not host or "://" in host or "/" in host:
            raise ValueError("Serveur FTP invalide. Utilise seulement un nom comme ftp.gameex.com")
        port = int(raw.get("ftp_port") or 21)
        if not 1 <= port <= 65535:
            raise ValueError("Port FTP invalide")
        source["ftp_host"] = host
        source["ftp_port"] = port
        source["ftp_path"] = _ftp_clean_path(raw.get("ftp_path") or "/")
        source["ftp_passive"] = bool(raw.get("ftp_passive", True))
        source["ftp_tls"] = bool(raw.get("ftp_tls", False))
        source["ftp_pinballx_layout"] = bool(raw.get("ftp_pinballx_layout", False))
        source["recursive"] = bool(raw.get("recursive", False))
        source["ftp_timeout"] = max(5, min(120, int(raw.get("ftp_timeout") or 30)))
        source["max_files"] = max(100, min(500000, int(raw.get("max_files") or 100000)))
        source["extensions"] = raw.get("extensions") or [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4", ".f4v", ".mp3"]
    return source


def _page_html() -> str:
    media_options = "".join(f'<label class="mh-media-item"><input type="checkbox" class="mh-media-cb" value="{html.escape(key)}"><span>{html.escape(key)}</span></label>' for key in MEDIA_SPECS)
    return f"""
<style>
.mh-wrap{{max-width:1800px;margin:0 auto;color:#f6efff}}.mh-wrap *{{box-sizing:border-box}}
.mh-hero,.mh-panel{{border:1px solid rgba(216,158,255,.24);border-radius:18px;background:linear-gradient(180deg,rgba(31,14,55,.91),rgba(11,7,22,.94));box-shadow:0 14px 32px rgba(0,0,0,.25)}}
.mh-hero{{display:flex;gap:20px;align-items:center;padding:18px 22px;margin-bottom:16px}}.mh-hero img{{width:190px;max-height:116px;object-fit:contain}}.mh-hero h1{{margin:0;color:#fff;font-size:34px}}.mh-hero h1 span{{color:#ff9b25}}.mh-hero p{{margin:8px 0 0;color:#d3c6df;line-height:1.5}}
.mh-actions{{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 16px}}.mh-btn{{border:1px solid rgba(255,154,37,.5);border-radius:10px;padding:10px 14px;background:rgba(255,139,20,.12);color:#fff;font-weight:800;cursor:pointer}}.mh-btn.secondary{{border-color:rgba(183,118,255,.45);background:rgba(151,73,232,.12)}}.mh-btn.danger{{border-color:rgba(255,90,90,.48);background:rgba(255,70,70,.1)}}.mh-btn:disabled{{opacity:.45;cursor:not-allowed}}
.mh-stats{{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:10px;margin-bottom:16px}}.mh-stat{{padding:13px;border:1px solid rgba(255,255,255,.12);border-radius:13px;background:rgba(255,255,255,.035)}}.mh-stat b{{display:block;color:#ffad3c;font-size:24px}}.mh-stat span{{color:#cbbbd8;font-size:12px}}
.mh-grid{{display:grid;grid-template-columns:minmax(560px,1.18fr) minmax(600px,1.82fr);gap:16px;align-items:start}}.mh-panel{{padding:18px;min-width:0}}.mh-panel h2{{margin:0 0 12px;color:#fff}}.mh-source{{padding:11px;border:1px solid rgba(255,255,255,.11);border-radius:12px;background:rgba(255,255,255,.03);margin-bottom:9px}}.mh-source-head{{display:flex;justify-content:space-between;gap:10px}}.mh-source small{{display:block;color:#bfaed0;margin-top:5px;word-break:break-all}}.mh-source-actions{{display:flex;gap:6px;margin-top:9px;flex-wrap:wrap}}
.mh-form{{display:grid;gap:9px;margin-top:14px;padding-top:14px;border-top:1px solid rgba(255,255,255,.1)}}.mh-form label{{color:#d5c7e2;font-size:12px;font-weight:800}}.mh-form input,.mh-form select{{width:100%;border:1px solid rgba(255,255,255,.16);border-radius:9px;padding:9px 10px;background:#130b22;color:#fff}}.mh-row2{{display:grid;grid-template-columns:1fr 1fr;gap:9px}}.mh-check{{display:flex;align-items:center;gap:8px}}.mh-check input{{width:auto}}.mh-media-box{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;max-height:none;overflow:visible;padding:12px;border:1px solid rgba(255,255,255,.16);border-radius:12px;background:#130b22}}.mh-media-item{{display:flex;align-items:center;gap:10px;padding:12px 12px;min-height:54px;border:1px solid rgba(255,255,255,.08);border-radius:12px;background:rgba(255,255,255,.03);font-size:13px;color:#fff}}.mh-media-item input{{width:auto;margin:0;flex:0 0 auto}}.mh-media-item span{{line-height:1.2;word-break:break-word}}
.mh-path-row{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center}}.mh-path-row .mh-btn{{height:100%;white-space:nowrap}}
.mh-modal[hidden]{{display:none}}.mh-modal{{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(3,1,8,.82);backdrop-filter:blur(5px)}}.mh-modal-card{{width:min(940px,96vw);max-height:88vh;display:flex;flex-direction:column;border:1px solid rgba(255,159,48,.42);border-radius:17px;background:#10091c;box-shadow:0 24px 80px rgba(0,0,0,.62);overflow:hidden}}.mh-modal-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:15px 17px;border-bottom:1px solid rgba(255,255,255,.1)}}.mh-modal-head h3{{margin:0;color:#fff;font-size:21px}}.mh-modal-body{{padding:14px 17px;min-height:280px;overflow:auto}}.mh-browser-toolbar{{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:8px;margin-bottom:12px}}.mh-browser-toolbar input{{min-width:0;border:1px solid rgba(255,255,255,.16);border-radius:9px;padding:9px 10px;background:#08040e;color:#fff}}.mh-browser-list{{display:grid;gap:7px}}.mh-dir{{width:100%;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 12px;border:1px solid rgba(255,255,255,.11);border-radius:10px;background:rgba(255,255,255,.035);color:#fff;text-align:left;cursor:pointer}}.mh-dir:hover{{border-color:rgba(255,159,48,.55);background:rgba(255,145,30,.09)}}.mh-dir small{{color:#bcaaca;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.mh-modal-foot{{display:flex;justify-content:flex-end;gap:9px;padding:13px 17px;border-top:1px solid rgba(255,255,255,.1)}}

.mh-status{{padding:12px;border:1px solid rgba(255,173,60,.26);border-radius:12px;background:rgba(255,151,32,.06);margin-bottom:12px}}.mh-progress{{height:9px;border-radius:99px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:8px}}.mh-progress i{{display:block;height:100%;width:0;background:linear-gradient(90deg,#8f47e6,#ff8a18)}}
.mh-filter{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}}.mh-filter input,.mh-filter select{{border:1px solid rgba(255,255,255,.15);border-radius:9px;padding:9px;background:#130b22;color:#fff}}.mh-table-wrap{{max-height:690px;overflow:auto;border:1px solid rgba(255,255,255,.09);border-radius:12px}}table.mh-table{{width:100%;border-collapse:collapse;font-size:13px}}.mh-table th{{position:sticky;top:0;background:#180d2a;color:#ffb04c;text-align:left;padding:9px;z-index:1}}.mh-table td{{padding:9px;border-top:1px solid rgba(255,255,255,.07);vertical-align:top}}.mh-badge{{display:inline-block;margin:2px;padding:3px 7px;border-radius:99px;background:rgba(255,145,30,.12);border:1px solid rgba(255,145,30,.24);color:#ffc06c;font-size:11px}}.mh-ok{{color:#72df91}}.mh-warn{{color:#ffc26f}}.mh-error{{color:#ff8585}}.mh-log{{max-height:180px;overflow:auto;margin-top:12px;padding:10px;border-radius:10px;background:#08040e;font-family:monospace;font-size:11px;color:#cfc4da}}
@media(max-width:1400px){{.mh-media-box{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:1200px){{.mh-grid{{grid-template-columns:1fr}}.mh-stats{{grid-template-columns:repeat(3,1fr)}}.mh-media-box{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:700px){{.mh-hero{{align-items:flex-start;flex-direction:column}}.mh-stats{{grid-template-columns:repeat(2,1fr)}}.mh-row2{{grid-template-columns:1fr}}.mh-media-box{{grid-template-columns:1fr}}}}
</style>
<div class="mh-wrap">
  <section class="mh-hero">
    <img src="/static/pincabos-assets/PCOSMediaHunter.png?v=mediahunter12" alt="PinCabOS Medias Hunter">
    <div><h1>PinCabOS <span>Medias Hunter</span></h1><p>Analyse les dossiers <code>medias/</code>, trouve seulement les fichiers manquants et les installe depuis des sources configurables. Aucun média existant, fichier <code>.info</code>, table VPX ou composant VPinFE n'est modifié.</p></div>
  </section>
  <div class="mh-actions"><button class="mh-btn" id="mhScan">Analyser les médias manquants</button><button class="mh-btn secondary" id="mhHuntAll">Chercher tous les manquants</button><button class="mh-btn secondary" id="mhHuntSelected">Chercher la sélection</button><button class="mh-btn danger" id="mhStop">Arrêter</button><a class="mh-btn secondary" href="/tools">Retour aux outils</a></div>
  <section class="mh-stats" id="mhStats"></section>
  <div class="mh-grid">
    <section class="mh-panel"><h2>Sources de médias</h2><div id="mhSources"></div>
      <form id="mhSourceForm" class="mh-form">
        <input type="hidden" id="mhSourceId">
        <div class="mh-row2"><div><label>Nom</label><input id="mhSourceName" required></div><div><label>Type</label><select id="mhSourceType"><option value="folder">Dossier local ou réseau monté</option><option value="web">Lien Web</option><option value="ftp">FTP / PinballX</option><option value="vpinmediadb">VPinMediaDB</option></select></div></div>
        <div id="mhLocationFields"><label>Chemin local ou URL de base</label><div class="mh-path-row"><input id="mhSourceLocation" placeholder="/mnt/medias/wheels ou https://exemple/media"><button class="mh-btn secondary" id="mhBrowseOpen" type="button">📁 Parcourir</button></div></div>
        <div id="mhWebTemplateFields"><label>Modèle Web facultatif</label><input id="mhSourceTemplate" placeholder="{{vps_id}}/1k/{{filename}} ou {{title}}/{{filename}}"></div>
        <div id="mhFtpFields" hidden>
          <div class="mh-row2"><div><label>Serveur FTP</label><input id="mhFtpHost" value="ftp.gameex.com" placeholder="ftp.gameex.com" autocomplete="off"></div><div><label>Port</label><input id="mhFtpPort" type="number" min="1" max="65535" value="21"></div></div>
          <div class="mh-row2"><div><label>Utilisateur FTP</label><input id="mhFtpUser" type="email" placeholder="Adresse courriel du compte GameEx" autocomplete="username"></div><div><label>Mot de passe FTP</label><input id="mhFtpPassword" type="password" placeholder="Laisser vide pour conserver le mot de passe actuel" autocomplete="current-password"></div></div>
          <div><label>Dossier distant de base</label><input id="mhFtpPath" value="/-PinballX-/Media/Visual Pinball" placeholder="/-PinballX-/Media/Visual Pinball"></div>
          <div class="mh-row2"><div><label>Délai réseau, secondes</label><input id="mhFtpTimeout" type="number" min="5" max="120" value="30"></div><div><label>Limite de fichiers indexés</label><input id="mhFtpMaxFiles" type="number" min="100" max="500000" value="100000"></div></div>
          <label class="mh-check"><input id="mhFtpPassive" type="checkbox" checked> Mode passif FTP</label>
          <label class="mh-check"><input id="mhFtpTls" type="checkbox"> FTP explicite avec TLS</label>
          <label class="mh-check"><input id="mhFtpPinballX" type="checkbox" checked> Structure PinballX automatique (Backglass Images, Table Images, Wheel Images, vidéos, etc.)</label>
          <small class="mh-warn">Le mot de passe est enregistré séparément dans un fichier protégé 0600 et n'apparaît jamais dans sources.json. Utilise cette page seulement sur un réseau local de confiance si la WebApp n'est pas en HTTPS.</small>
          <small class="mh-ok">Les vidéos PinballX en .f4v sont automatiquement remuxées ou converties en .mp4 avec FFmpeg avant installation dans VPinFE.</small>
        </div>
        <div><label>Priorité</label><input id="mhSourcePriority" type="number" min="1" max="9999" value="100"></div><div><label>Types de médias</label><div id="mhSourceMedia" class="mh-media-box">{media_options}</div></div>
        <label class="mh-check"><input id="mhSourceEnabled" type="checkbox" checked> Source activée</label><label class="mh-check" id="mhRecursiveWrap"><input id="mhSourceRecursive" type="checkbox" checked> Recherche récursive</label>
        <div class="mh-actions"><button class="mh-btn" type="submit">Enregistrer la source</button><button class="mh-btn secondary" type="button" id="mhSourceReset">Nouvelle source</button></div>
        <small class="mh-warn">Les chemins SMB/UNC doivent être montés depuis Stockage. Pour PinballX, le serveur officiel est ftp.gameex.com sur le port 21; aucune source FTP ni aucun compte n'est créé automatiquement.</small>
      </form>
    </section>
    <section class="mh-panel"><h2>Tables et médias manquants</h2><div class="mh-status" id="mhStatus">Chargement…<div class="mh-progress"><i id="mhProgress"></i></div></div>
      <div class="mh-filter"><input id="mhSearch" placeholder="Filtrer une table"><select id="mhMissingFilter"><option value="">Tous les médias</option>{media_options}</select><button class="mh-btn secondary" id="mhSelectVisible" type="button">Sélectionner visibles</button><button class="mh-btn secondary" id="mhClearSelection" type="button">Vider sélection</button></div>
      <div class="mh-table-wrap"><table class="mh-table"><thead><tr><th></th><th>Table</th><th>VPS</th><th>Manquants</th><th>Dernière action</th></tr></thead><tbody id="mhRows"></tbody></table></div>
      <div class="mh-log" id="mhLog"></div>
    </section>
  </div>

  <div class="mh-modal" id="mhBrowserModal" hidden>
    <div class="mh-modal-card" role="dialog" aria-modal="true" aria-labelledby="mhBrowserTitle">
      <div class="mh-modal-head"><h3 id="mhBrowserTitle">Parcourir les dossiers du PinCab</h3><button class="mh-btn secondary" id="mhBrowserClose" type="button">Fermer</button></div>
      <div class="mh-modal-body">
        <div class="mh-browser-toolbar"><button class="mh-btn secondary" id="mhBrowserRoots" type="button">Racines</button><button class="mh-btn secondary" id="mhBrowserUp" type="button">⬆ Parent</button><input id="mhBrowserCurrent" readonly placeholder="Choisis une racine"></div>
        <div class="mh-browser-list" id="mhBrowserList"><div class="mh-warn">Chargement…</div></div>
      </div>
      <div class="mh-modal-foot"><button class="mh-btn secondary" id="mhBrowserCancel" type="button">Annuler</button><button class="mh-btn" id="mhBrowserChoose" type="button">Utiliser ce dossier</button></div>
    </div>
  </div>
</div>
<script>
(() => {{
  const api = '/api/pincabos/media-hunter';
  let data = {{tables:[],summary:{{}}}}, sources = [], state = {{}}, selected = new Set(), browserState = {{mode:'roots',current:'',parent:'',entries:[],roots:[]}};
  const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
  async function req(path, options={{}}) {{ const r=await fetch(api+path,{{headers:{{'Content-Type':'application/json'}},...options}}); const j=await r.json(); if(!r.ok||j.ok===false) throw new Error(j.error||j.message||'Erreur'); return j; }}
  function mediaCheckboxes() {{ return [...document.querySelectorAll('#mhSourceMedia .mh-media-cb')]; }}
  function getMediaSelection() {{ return mediaCheckboxes().filter(cb=>cb.checked).map(cb=>cb.value); }}
  function setMediaSelection(values) {{ const boxes=mediaCheckboxes(); const picked=new Set((values&&values.length)?values:boxes.map(cb=>cb.value)); boxes.forEach(cb=>cb.checked=picked.has(cb.value)); }}
  function updateSourceTypeUI() {{
    const type=document.querySelector('#mhSourceType').value;
    const folder=type==='folder', web=type==='web', ftp=type==='ftp', vpin=type==='vpinmediadb';
    document.querySelector('#mhLocationFields').hidden=ftp;
    document.querySelector('#mhBrowseOpen').hidden=!folder;
    document.querySelector('#mhWebTemplateFields').hidden=!web;
    document.querySelector('#mhFtpFields').hidden=!ftp;
    document.querySelector('#mhRecursiveWrap').hidden=vpin||ftp&&document.querySelector('#mhFtpPinballX').checked;
    if(ftp) {{
      if(!document.querySelector('#mhFtpHost').value.trim()) document.querySelector('#mhFtpHost').value='ftp.gameex.com';
      if(!document.querySelector('#mhFtpPort').value) document.querySelector('#mhFtpPort').value='21';
      if(!document.querySelector('#mhFtpPath').value.trim()) document.querySelector('#mhFtpPath').value='/-PinballX-/Media/Visual Pinball';
    }}
  }}
  function renderBrowser() {{
    const list=document.querySelector('#mhBrowserList');
    document.querySelector('#mhBrowserCurrent').value=browserState.current||'';
    document.querySelector('#mhBrowserUp').disabled=!browserState.parent;
    document.querySelector('#mhBrowserChoose').disabled=!browserState.current;
    if(browserState.mode==='roots') {{
      const roots=browserState.roots||[];
      list.innerHTML=roots.length?roots.map(r=>`<button class="mh-dir" type="button" data-mh-browse-path="${{esc(r.path)}}"><span>🗂️ ${{esc(r.label)}}</span><small>${{esc(r.path)}}</small></button>`).join(''):'<div class="mh-warn">Aucune racine accessible.</div>';
      return;
    }}
    const entries=browserState.entries||[];
    list.innerHTML=(entries.length?entries.map(d=>`<button class="mh-dir" type="button" data-mh-browse-path="${{esc(d.path)}}" ${{d.readable===false?'disabled':''}}><span>📁 ${{esc(d.name)}}</span><small>${{esc(d.path)}}</small></button>`).join(''):'<div class="mh-warn">Aucun sous-dossier visible.</div>')+(browserState.truncated?'<div class="mh-warn">Liste limitée aux 1000 premiers dossiers.</div>':'');
  }}
  async function loadBrowser(path='') {{
    document.querySelector('#mhBrowserList').innerHTML='<div class="mh-warn">Chargement…</div>';
    const suffix=path?'?path='+encodeURIComponent(path):'';
    browserState=await req('/browse'+suffix);
    renderBrowser();
  }}
  async function openBrowser() {{
    if(document.querySelector('#mhSourceType').value!=='folder') return;
    document.querySelector('#mhBrowserModal').hidden=false;
    const current=document.querySelector('#mhSourceLocation').value.trim();
    try {{ await loadBrowser(current); }} catch(e) {{ try {{ await loadBrowser(''); }} catch(e2) {{ document.querySelector('#mhBrowserList').innerHTML=`<div class="mh-error">${{esc(e2.message)}}</div>`; }} }}
  }}
  function closeBrowser() {{ document.querySelector('#mhBrowserModal').hidden=true; }}
  function stats() {{ const s=data.summary||{{}}; const items=[['Tables',s.tables||0],['Complètes',s.complete||0],['Incomplètes',s.incomplete||0],['Médias manquants',s.missing_total||0],['VPS associés',s.vps_matched||0],['Sans VPS',s.vps_unmatched||0]]; document.querySelector('#mhStats').innerHTML=items.map(([a,b])=>`<div class="mh-stat"><b>${{esc(b)}}</b><span>${{esc(a)}}</span></div>`).join(''); }}
  function renderSources() {{ document.querySelector('#mhSources').innerHTML=sources.length?sources.sort((a,b)=>(a.priority||100)-(b.priority||100)).map(s=>{{const location=s.type==='ftp'?`${{s.ftp_host||''}}:${{s.ftp_port||21}}${{s.ftp_path||'/'}}${{s.has_password?' · 🔐':''}}`:(s.path||s.base_url||'');return `<div class="mh-source"><div class="mh-source-head"><b>${{esc(s.name)}}</b><span class="${{s.enabled?'mh-ok':'mh-warn'}}">${{s.enabled?'Activée':'Désactivée'}}</span></div><small>${{esc(s.type)}} · priorité ${{esc(s.priority)}} · ${{esc(location)}}</small><small>Médias: ${{esc((s.media_types||[]).join(', '))}}</small><div class="mh-source-actions"><button class="mh-btn secondary" data-edit="${{esc(s.id)}}">Modifier</button><button class="mh-btn secondary" data-test="${{esc(s.id)}}">Tester</button><button class="mh-btn danger" data-delete="${{esc(s.id)}}">Supprimer</button></div></div>`;}}).join(''):'<p class="mh-warn">Aucune source configurée.</p>'; }}
  function filtered() {{ const q=document.querySelector('#mhSearch').value.toLowerCase(), m=document.querySelector('#mhMissingFilter').value; return (data.tables||[]).filter(t=>(!q||String(t.name).toLowerCase().includes(q))&&(!m||(t.missing||[]).includes(m))); }}
  function rows() {{ document.querySelector('#mhRows').innerHTML=filtered().map(t=>`<tr><td><input type="checkbox" data-table="${{esc(t.name)}}" ${{selected.has(t.name)?'checked':''}}></td><td><b>${{esc(t.name)}}</b><br><small>${{esc(t.path)}}</small></td><td>${{t.vps_id?`<span class="mh-ok">${{esc(t.vps_id)}}</span><br><small>${{esc(t.vps_match)}}</small>`:'<span class="mh-warn">Non associé</span>'}}</td><td>${{(t.missing||[]).length?(t.missing||[]).map(x=>`<span class="mh-badge">${{esc(x)}}</span>`).join(''):'<span class="mh-ok">Complet</span>'}}${{(t.errors||[]).length?`<br><small class="mh-error">${{esc(t.errors.slice(-2).join(' · '))}}</small>`:''}}</td><td>${{esc(t.last_action||'')}}</td></tr>`).join(''); }}
  function renderState() {{ const total=Number(state.total||0), done=Number(state.processed||0), pct=total?Math.min(100,Math.round(done*100/total)):0; document.querySelector('#mhStatus').firstChild.textContent=`${{state.message||'Prêt'}}${{state.current_table?' · '+state.current_table:''}}${{state.current_media?' · '+state.current_media:''}}`; document.querySelector('#mhProgress').style.width=pct+'%'; document.querySelector('#mhLog').innerHTML=(state.log||[]).slice().reverse().map(x=>`<div class="${{x.level==='error'?'mh-error':x.level==='success'?'mh-ok':''}}">[${{esc(x.time)}}] ${{esc(x.message)}}</div>`).join(''); document.querySelectorAll('#mhScan,#mhHuntAll,#mhHuntSelected').forEach(b=>b.disabled=!!state.running); document.querySelector('#mhStop').disabled=!state.running; }}
  async function refresh() {{ try {{ const j=await req('/state'); state=j.state; data=j.results||data; sources=j.sources||sources; stats(); renderSources(); rows(); renderState(); }} catch(e) {{ document.querySelector('#mhStatus').firstChild.textContent=e.message; }} }}
  function resetForm() {{ document.querySelector('#mhSourceForm').reset(); document.querySelector('#mhSourceId').value=''; document.querySelector('#mhSourcePriority').value='100'; document.querySelector('#mhSourceEnabled').checked=true; document.querySelector('#mhSourceRecursive').checked=true; document.querySelector('#mhFtpHost').value='ftp.gameex.com'; document.querySelector('#mhFtpPort').value='21'; document.querySelector('#mhFtpPath').value='/-PinballX-/Media/Visual Pinball'; document.querySelector('#mhFtpTimeout').value='30'; document.querySelector('#mhFtpMaxFiles').value='100000'; document.querySelector('#mhFtpPassive').checked=true; document.querySelector('#mhFtpTls').checked=false; document.querySelector('#mhFtpPinballX').checked=true; document.querySelector('#mhFtpPassword').value=''; updateSourceTypeUI(); setMediaSelection([]); }}
  document.addEventListener('change',e=>{{ if(e.target.matches('[data-table]')) {{ e.target.checked?selected.add(e.target.dataset.table):selected.delete(e.target.dataset.table); }} }});
  document.addEventListener('click',async e=>{{ const edit=e.target.dataset.edit, test=e.target.dataset.test, del=e.target.dataset.delete; if(edit){{const s=sources.find(x=>x.id===edit); if(!s)return; document.querySelector('#mhSourceId').value=s.id; document.querySelector('#mhSourceName').value=s.name||''; document.querySelector('#mhSourceType').value=s.type||'folder'; document.querySelector('#mhSourceLocation').value=s.path||s.base_url||''; document.querySelector('#mhSourceTemplate').value=s.template||''; document.querySelector('#mhSourcePriority').value=s.priority||100; document.querySelector('#mhSourceEnabled').checked=s.enabled!==false; document.querySelector('#mhSourceRecursive').checked=s.recursive!==false; document.querySelector('#mhFtpHost').value=s.ftp_host||'ftp.gameex.com'; document.querySelector('#mhFtpPort').value=s.ftp_port||21; document.querySelector('#mhFtpUser').value=s.ftp_user||''; document.querySelector('#mhFtpPassword').value=''; document.querySelector('#mhFtpPath').value=s.ftp_path||'/-PinballX-/Media/Visual Pinball'; document.querySelector('#mhFtpTimeout').value=s.ftp_timeout||30; document.querySelector('#mhFtpMaxFiles').value=s.max_files||100000; document.querySelector('#mhFtpPassive').checked=s.ftp_passive!==false; document.querySelector('#mhFtpTls').checked=!!s.ftp_tls; document.querySelector('#mhFtpPinballX').checked=!!s.ftp_pinballx_layout; setMediaSelection(s.media_types||[]); updateSourceTypeUI(); setMediaSelection([]); }} if(test){{try{{const j=await req('/sources/test',{{method:'POST',body:JSON.stringify({{id:test}})}}); alert(j.message);}}catch(err){{alert(err.message);}}}} if(del){{if(!confirm('Supprimer cette source?'))return; try{{await req('/sources/delete',{{method:'POST',body:JSON.stringify({{id:del}})}}); await refresh();}}catch(err){{alert(err.message);}}}} }});
  document.querySelector('#mhSourceForm').addEventListener('submit',async e=>{{e.preventDefault(); const media=getMediaSelection(); const source={{id:document.querySelector('#mhSourceId').value,name:document.querySelector('#mhSourceName').value,type:document.querySelector('#mhSourceType').value,priority:Number(document.querySelector('#mhSourcePriority').value||100),enabled:document.querySelector('#mhSourceEnabled').checked,recursive:document.querySelector('#mhSourceRecursive').checked,media_types:media,path:document.querySelector('#mhSourceLocation').value,base_url:document.querySelector('#mhSourceLocation').value,template:document.querySelector('#mhSourceTemplate').value,ftp_host:document.querySelector('#mhFtpHost').value,ftp_port:Number(document.querySelector('#mhFtpPort').value||21),ftp_user:document.querySelector('#mhFtpUser').value,ftp_password:document.querySelector('#mhFtpPassword').value,ftp_path:document.querySelector('#mhFtpPath').value,ftp_timeout:Number(document.querySelector('#mhFtpTimeout').value||30),max_files:Number(document.querySelector('#mhFtpMaxFiles').value||100000),ftp_passive:document.querySelector('#mhFtpPassive').checked,ftp_tls:document.querySelector('#mhFtpTls').checked,ftp_pinballx_layout:document.querySelector('#mhFtpPinballX').checked}}; try{{await req('/sources/save',{{method:'POST',body:JSON.stringify(source)}}); resetForm(); await refresh();}}catch(err){{alert(err.message);}}}});
  document.querySelector('#mhSourceReset').onclick=resetForm; document.querySelector('#mhSearch').oninput=rows; document.querySelector('#mhMissingFilter').onchange=rows;
  document.querySelector('#mhSourceType').onchange=updateSourceTypeUI;
  document.querySelector('#mhFtpPinballX').onchange=updateSourceTypeUI;
  document.querySelector('#mhBrowseOpen').onclick=openBrowser;
  document.querySelector('#mhBrowserClose').onclick=closeBrowser; document.querySelector('#mhBrowserCancel').onclick=closeBrowser;
  document.querySelector('#mhBrowserRoots').onclick=()=>loadBrowser('').catch(e=>alert(e.message));
  document.querySelector('#mhBrowserUp').onclick=()=>{{if(browserState.parent)loadBrowser(browserState.parent).catch(e=>alert(e.message));}};
  document.querySelector('#mhBrowserChoose').onclick=()=>{{if(!browserState.current)return;document.querySelector('#mhSourceLocation').value=browserState.current;closeBrowser();}};
  document.querySelector('#mhBrowserModal').addEventListener('click',e=>{{if(e.target.id==='mhBrowserModal')closeBrowser();}});
  document.addEventListener('click',e=>{{const button=e.target.closest('[data-mh-browse-path]');if(!button)return;loadBrowser(button.dataset.mhBrowsePath).catch(err=>alert(err.message));}});

  document.querySelector('#mhSelectVisible').onclick=()=>{{filtered().forEach(t=>selected.add(t.name));rows();}}; document.querySelector('#mhClearSelection').onclick=()=>{{selected.clear();rows();}};
  document.querySelector('#mhScan').onclick=async()=>{{try{{await req('/scan',{{method:'POST',body:'{{}}'}});await refresh();}}catch(e){{alert(e.message);}}}};
  document.querySelector('#mhHuntAll').onclick=async()=>{{if(!confirm('Chercher et installer tous les médias manquants trouvés? Les médias existants ne seront jamais écrasés.'))return;try{{await req('/hunt',{{method:'POST',body:JSON.stringify({{tables:[]}})}});await refresh();}}catch(e){{alert(e.message);}}}};
  document.querySelector('#mhHuntSelected').onclick=async()=>{{if(!selected.size){{alert('Sélectionne au moins une table.');return;}}try{{await req('/hunt',{{method:'POST',body:JSON.stringify({{tables:[...selected]}})}});await refresh();}}catch(e){{alert(e.message);}}}};
  document.querySelector('#mhStop').onclick=async()=>{{try{{await req('/stop',{{method:'POST',body:'{{}}'}});await refresh();}}catch(e){{alert(e.message);}}}};
  updateSourceTypeUI(); refresh(); setInterval(refresh,1200);
}})();
</script>
"""


def register(app, page) -> None:
    _ensure_layout()
    _recover_stale_state()
    endpoint = "pincabos_media_hunter_page"
    if endpoint in app.view_functions:
        return

    @app.route("/tools/vpinfe/media-hunter", endpoint=endpoint)
    def media_hunter_page():
        return page("Medias Hunter", _page_html())

    @app.get("/api/pincabos/media-hunter/state")
    def media_hunter_state():
        return jsonify(ok=True, state=_load_state(), results=_read_json(RESULTS_PATH, {"tables": [], "summary": {}}), sources=_public_sources(), version=VERSION)

    @app.post("/api/pincabos/media-hunter/scan")
    def media_hunter_scan():
        ok, message = _start_job("scan")
        return jsonify(ok=ok, message=message), (200 if ok else 409)

    @app.post("/api/pincabos/media-hunter/hunt")
    def media_hunter_hunt():
        payload = request.get_json(silent=True) or {}
        tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
        tables = [str(item) for item in tables if str(item).strip()]
        ok, message = _start_job("hunt", tables or None)
        return jsonify(ok=ok, message=message), (200 if ok else 409)

    @app.post("/api/pincabos/media-hunter/stop")
    def media_hunter_stop():
        _STOP.set()
        _set_state(stop_requested=True, message="Arrêt demandé")
        return jsonify(ok=True, message="Arrêt demandé")

    @app.get("/api/pincabos/media-hunter/browse")
    def media_hunter_browse():
        try:
            raw_path = str(request.args.get("path") or "").strip()
            roots_payload = _available_browse_roots()
            if not raw_path:
                return jsonify(ok=True, mode="roots", roots=roots_payload, current="", parent="", entries=[])
            current, roots = _resolve_browse_path(raw_path)
            payload = _browse_directory_payload(current, roots)
            return jsonify(ok=True, mode="directory", roots=roots_payload, **payload)
        except (ValueError, FileNotFoundError, NotADirectoryError) as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except PermissionError as exc:
            return jsonify(ok=False, error=str(exc)), 403
        except Exception as exc:
            return jsonify(ok=False, error=f"Navigation impossible : {exc}"), 500

    @app.post("/api/pincabos/media-hunter/sources/save")
    def media_hunter_source_save():
        try:
            raw = request.get_json(force=True)
            if not isinstance(raw, dict):
                raise ValueError("Données de source invalides")
            source = _sanitize_source(raw, str(raw.get("id") or ""))
            config = _load_config()
            previous = next(
                (item for item in config["sources"] if isinstance(item, dict) and item.get("id") == source["id"]),
                None,
            )

            if source.get("type") == "ftp":
                _save_ftp_credentials(
                    source["id"],
                    str(raw.get("ftp_user") or ""),
                    str(raw.get("ftp_password") or ""),
                )

            existing = [item for item in config["sources"] if isinstance(item, dict) and item.get("id") != source["id"]]
            existing.append(source)
            config["sources"] = existing
            _save_config(config)

            if isinstance(previous, dict) and previous.get("type") == "ftp" and source.get("type") != "ftp":
                _delete_ftp_credentials(source["id"])

            public = next((item for item in _public_sources() if item.get("id") == source["id"]), source)
            return jsonify(ok=True, source=public)
        except Exception as exc:
            return jsonify(ok=False, error=str(exc)), 400

    @app.post("/api/pincabos/media-hunter/sources/delete")
    def media_hunter_source_delete():
        payload = request.get_json(force=True)
        source_id = _safe_source_id(payload.get("id"))
        config = _load_config()
        before = len(config["sources"])
        config["sources"] = [item for item in config["sources"] if not isinstance(item, dict) or item.get("id") != source_id]
        _save_config(config)
        _delete_ftp_credentials(source_id)
        return jsonify(ok=True, deleted=before - len(config["sources"]))

    @app.post("/api/pincabos/media-hunter/sources/test")
    def media_hunter_source_test():
        payload = request.get_json(force=True)
        source_id = _safe_source_id(payload.get("id"))
        source = next((item for item in _load_config()["sources"] if isinstance(item, dict) and item.get("id") == source_id), None)
        if not source:
            return jsonify(ok=False, error="Source introuvable"), 404
        ok, message = _source_test(source)
        return jsonify(ok=ok, message=message), (200 if ok else 400)
