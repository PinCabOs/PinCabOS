# PINCABOS_EXPLORER_NATIVE_TABLES_V1
# PINCABOS_EXPLORER_DIRECT_FIRST_LOAD_V3
# PINCABOS_EXPLORER_CONTROLS_DOM_READY_V2
# PINCABOS_EXPLORER_TABLE_TEST_CENTER_V1
# PINCABOS_EXPLORER_CONTROLS_INSTANT_V1
# PINCABOS_EXPLORER_TABLE_CONTROLS_STABLE_V1
from __future__ import annotations

import functools
import html
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from flask import jsonify, request

TABLES_ROOT = Path("/home/pinball/Tables").resolve()
STATE_DIR = Path("/var/lib/pincabos/table-test")
STATE_FILE = STATE_DIR / "state.json"
CONTROL = Path("/usr/local/sbin/pincabos-table-test-control")
SERVICE = "pincabos-table-test.service"
VPINFE_SERVICE = "pincabos-vpinfe.service"
VPS_HOME = "https://virtualpinballspreadsheet.github.io/"
VPS_ID_URL = VPS_HOME + "?game={}"

ROM_ROOTS = (
    Path("/opt/pincabos/apps/vpinball/PinMAME/roms"),
    Path("/home/pinball/.vpinball/pinmame/roms"),
    Path("/home/pinball/.local/share/VPinballX/PinMAME/roms"),
    Path("/opt/pinball/vpx/PinMAME/roms"),
)

_LOCK = threading.RLock()
_DETECT_BATCH = None
_HEALTH_CACHE: dict[tuple[str, bool], tuple[float, float, dict[str, Any]]] = {}

CATALOG_INDEX_FILE = STATE_DIR / "catalog-index.json"
CATALOG_REFRESH_SECONDS = 300
_CATALOG_LOCK = threading.RLock()
_CATALOG_WAKE = threading.Event()
_CATALOG_THREAD_STARTED = False


def _json_read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _state() -> dict[str, Any]:
    with _LOCK:
        data = _json_read(STATE_FILE, {})
        return data if isinstance(data, dict) else {}


def _write_state(data: dict[str, Any]) -> None:
    with _LOCK:
        _json_write(STATE_FILE, data)


def _update_state(**updates: Any) -> dict[str, Any]:
    with _LOCK:
        data = _state()
        data.update(updates)
        data["updated_at"] = int(time.time())
        _write_state(data)
        return data


def _resolve_rel(rel: str, must_exist: bool = True) -> Path:
    clean = str(rel or "").replace("\\", "/").lstrip("/")
    candidate = (TABLES_ROOT / clean).resolve(strict=False)
    try:
        candidate.relative_to(TABLES_ROOT)
    except ValueError as exc:
        raise PermissionError("Chemin hors du dossier Tables.") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError("Dossier de table introuvable.")
    return candidate


def _relative(path: Path) -> str:
    return path.resolve().relative_to(TABLES_ROOT).as_posix()


def _is_backup_name(path: Path) -> bool:
    lower = path.name.casefold()
    return any(token in lower for token in (
        ".bak",
        ".backup",
        ".before-",
        "~",
    ))


# PINCABOS_EXPLORER_TABLE_BUTTONS_ROOT_ONLY_V1
def _files(
    folder: Path,
    suffix: str,
    recursive: bool = True,
) -> list[Path]:
    # Le catalogue principal inspecte seulement le niveau direct.
    # Play et les détails utilisent encore l’analyse récursive complète.
    entries = folder.rglob("*") if recursive else folder.iterdir()

    return sorted(
        (
            item
            for item in entries
            if item.is_file()
            and not _is_backup_name(item)
            and item.name.casefold().endswith(suffix.casefold())
        ),
        key=lambda item: item.name.casefold(),
    )


def _normal(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _choose_main_vpx(folder: Path, vpx_files: list[Path]) -> Path | None:
    if not vpx_files:
        return None
    if len(vpx_files) == 1:
        return vpx_files[0]

    folder_key = _normal(folder.name)
    exact = [
        item for item in vpx_files
        if _normal(item.stem) in {folder_key, folder_key.replace("table", "")}
    ]
    if exact:
        return exact[0]

    return max(vpx_files, key=lambda item: item.stat().st_size)


def _walk_metadata(value: Any, result: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lower = str(key).casefold().replace("-", "_")
            if isinstance(item, (str, int, float)):
                text = str(item).strip()
                if lower in {"vpsid", "vps_id", "vpsdb_id", "vps_database_id"} and text:
                    result.setdefault("vps_id", text)
                elif lower in {"vpsurl", "vps_url", "vpsdb_url", "table_url"} and text:
                    result.setdefault("vps_url", text)
                elif lower in {"rom", "rom_name", "romname", "cgamename"} and text:
                    result.setdefault("rom", text.removesuffix(".zip"))
            _walk_metadata(item, result)
    elif isinstance(value, list):
        for item in value:
            _walk_metadata(item, result)


def _metadata(
    folder: Path,
    recursive: bool = True,
) -> dict[str, Any]:
    result: dict[str, str] = {}
    info_files = _files(
        folder,
        ".info",
        recursive=recursive,
    )

    url_re = re.compile(
        r"https?://[^\s\"'<>]*(?:virtualpinballspreadsheet|vps)[^\s\"'<>]*",
        re.IGNORECASE,
    )
    vps_id_re = re.compile(
        r"(?im)^\s*(?:vpsid|vps_id|vpsdb_id)\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)"
    )
    rom_re = re.compile(
        r"(?im)^\s*(?:rom|rom_name|romname|cgamename)\s*[:=]\s*[\"']?([A-Za-z0-9_.-]+)"
    )

    for path in info_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if parsed is not None:
            _walk_metadata(parsed, result)

        url_match = url_re.search(text)
        if url_match:
            result.setdefault("vps_url", url_match.group(0).rstrip(".,;)"))

        id_match = vps_id_re.search(text)
        if id_match:
            result.setdefault("vps_id", id_match.group(1))

        rom_match = rom_re.search(text)
        if rom_match:
            result.setdefault("rom", rom_match.group(1).removesuffix(".zip"))

    if "rom" not in result:
        script_re = re.compile(
            r"""(?ix)
            (?:cGameName|GameName|\.GameName)\s*=\s*
            ["']([A-Za-z0-9_.-]+)["']
            """
        )
        for path in _files(
            folder,
            ".vbs",
            recursive=recursive,
        ):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            match = script_re.search(text)
            if match:
                result["rom"] = match.group(1).removesuffix(".zip")
                break

    return {
        "info_files": [item.name for item in info_files],
        **result,
    }


# PINCABOS_EXPLORER_ROM_LOCAL_PINMAME_FIX_V1
# PINCABOS_EXPLORER_ROM_REQUIREMENT_VBS_TRUTH_V2
def _strip_vbs_comments(text: str) -> str:
    cleaned_lines: list[str] = []

    for raw_line in text.splitlines():
        output: list[str] = []
        in_string = False
        index = 0

        while index < len(raw_line):
            char = raw_line[index]

            if char == '"':
                output.append(char)

                if in_string:
                    if (
                        index + 1 < len(raw_line)
                        and raw_line[index + 1] == '"'
                    ):
                        output.append('"')
                        index += 2
                        continue

                    in_string = False
                else:
                    in_string = True

                index += 1
                continue

            if char == "'" and not in_string:
                break

            output.append(char)
            index += 1

        cleaned_lines.append("".join(output))

    return "\n".join(cleaned_lines)


def _root_vbs_runtime_profile(folder: Path) -> dict[str, Any]:
    root_scripts = sorted(
        (
            item
            for item in folder.iterdir()
            if item.is_file()
            and item.suffix.casefold() == ".vbs"
            and not _is_backup_name(item)
        ),
        key=lambda item: item.name.casefold(),
    )

    chunks: list[str] = []

    for script in root_scripts:
        try:
            chunks.append(
                _strip_vbs_comments(
                    script.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )
            )
        except OSError:
            continue

    source = "\n".join(chunks)

    signals = {
        "vpinmame_controller": bool(
            re.search(
                r'(?i)createobject\s*\(\s*["\']vpinmame\.controller["\']\s*\)',
                source,
            )
        ),
        "loadvpm": bool(
            re.search(r"(?i)\bloadvpm\b", source)
        ),
        "vpminit": bool(
            re.search(r"(?i)\bvpminit\b", source)
        ),
        "controller_run": bool(
            re.search(
                r"(?im)(?:\bcontroller\s*\.\s*run\b|^\s*\.run\s+)",
                source,
            )
        ),
        "controller_gamename": bool(
            re.search(
                r"(?im)(?:\bcontroller\s*\.\s*gamename\s*=|^\s*\.gamename\s*=)",
                source,
            )
        ),
        "controller_games": bool(
            re.search(
                r"(?i)\bcontroller\s*\.\s*games\s*\(",
                source,
            )
        ),
    }

    score = sum(
        1
        for key in (
            "loadvpm",
            "vpminit",
            "controller_run",
            "controller_gamename",
            "controller_games",
        )
        if signals[key]
    )

    uses_pinmame = bool(
        signals["vpinmame_controller"]
        or score >= 3
    )

    rom_candidates: list[str] = []

    if uses_pinmame:
        rom_patterns = (
            re.compile(
                r'(?im)^\s*(?:const\s+)?cgamename\s*=\s*["\']([^"\']+)["\']'
            ),
            re.compile(
                r'(?im)^\s*romname\s*=\s*["\']([^"\']+)["\']'
            ),
            re.compile(
                r'(?im)^\s*(?:controller\s*\.\s*)?gamename\s*=\s*["\']([^"\']+)["\']'
            ),
        )

        known: set[str] = set()

        for pattern in rom_patterns:
            for match in pattern.findall(source):
                candidate = str(match).strip()

                if not candidate:
                    continue

                key = candidate.casefold()

                if key in known:
                    continue

                known.add(key)
                rom_candidates.append(candidate)

    uses_pup = bool(
        re.search(
            r"(?i)\bpuplayer\b|\bpinupplayer\b|\bpup(?:pack|event|capture|init|videos?)\b|\bpupvideos\b",
            source,
        )
    )

    uses_flexdmd = bool(
        re.search(
            r"(?i)\bflexdmd\b|\bultradmd\b",
            source,
        )
    )

    uses_b2s_controller = bool(
        re.search(
            r'(?i)createobject\s*\(\s*["\']b2s\.(?:server|controller)["\']\s*\)',
            source,
        )
    )

    technologies: list[str] = []

    if uses_pinmame:
        technologies.append("PinMAME")

    if uses_pup:
        technologies.append("PuP")

    if uses_flexdmd:
        technologies.append("FlexDMD/UltraDMD")

    if uses_b2s_controller:
        technologies.append("B2S")

    if not technologies:
        technologies.append("VPX natif")

    return {
        "root_vbs": [item.name for item in root_scripts],
        "uses_pinmame": uses_pinmame,
        "uses_pup": uses_pup,
        "uses_flexdmd": uses_flexdmd,
        "uses_b2s_controller": uses_b2s_controller,
        "rom_required": uses_pinmame,
        "rom": rom_candidates[0] if rom_candidates else "",
        "rom_candidates": rom_candidates,
        "pinmame_signals": signals,
        "pinmame_score": score,
        "runtime": " + ".join(technologies),
    }


def _rom_exists(
    rom_name: str,
    folder: Path,
    recursive: bool = True,
) -> bool:
    if not rom_name:
        return False

    expected = (
        rom_name.casefold().removesuffix(".zip")
        + ".zip"
    )

    def matches_in(directory: Path) -> bool:
        if not directory.is_dir():
            return False

        try:
            for item in directory.iterdir():
                if (
                    item.is_file()
                    and item.name.casefold() == expected
                ):
                    return True
        except OSError:
            return False

        return False

    if recursive:
        try:
            for local in folder.rglob("*.zip"):
                if local.name.casefold() == expected:
                    return True
        except OSError:
            pass
    else:
        # Scan rapide ciblé utilisé par le catalogue Explorer.
        # Les packages portables PinCabOS rangent habituellement la ROM ici:
        #   Table/pinmame/roms/rom_name.zip
        local_roots = [folder]

        try:
            for child in folder.iterdir():
                if (
                    child.is_dir()
                    and child.name.casefold() == "pinmame"
                ):
                    local_roots.append(child)

                    try:
                        for subdirectory in child.iterdir():
                            if (
                                subdirectory.is_dir()
                                and subdirectory.name.casefold() == "roms"
                            ):
                                local_roots.append(subdirectory)
                    except OSError:
                        pass
        except OSError:
            pass

        for local_root in local_roots:
            if matches_in(local_root):
                return True

    for root in ROM_ROOTS:
        if matches_in(root):
            return True

    return False



def _deep_detect(folder: Path) -> dict[str, Any]:
    if not callable(_DETECT_BATCH):
        return {}
    try:
        detected = _DETECT_BATCH(folder)
        return detected if isinstance(detected, dict) else {}
    except Exception:
        return {}


def _folder_stamp(folder: Path) -> float:
    newest = folder.stat().st_mtime
    try:
        for item in folder.iterdir():
            newest = max(newest, item.stat().st_mtime)
    except OSError:
        pass
    return newest


# PINCABOS_EXPLORER_PUP_B2S_RUNTIME_DMD_JOURNAL_V2
def _runtime_dmd_diagnostics(
    folder: Path,
    runtime_profile: dict[str, Any],
) -> dict[str, list[str]]:
    state = _state()

    if str(state.get("rel") or "") != _relative(folder):
        return {
            "problems": [],
            "warnings": [],
        }

    raw_log_file = str(
        state.get("log_file") or ""
    ).strip()

    if not raw_log_file:
        return {
            "problems": [],
            "warnings": [],
        }

    log_file = Path(raw_log_file)
    expected_root = (STATE_DIR / "runs").resolve()

    try:
        resolved_log = log_file.resolve()
        resolved_log.relative_to(expected_root)
    except (OSError, ValueError):
        return {
            "problems": [],
            "warnings": [
                "Journal runtime rejeté : chemin non sécurisé"
            ],
        }

    if not resolved_log.is_file():
        return {
            "problems": [],
            "warnings": [],
        }

    try:
        log = resolved_log.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return {
            "problems": [],
            "warnings": [
                "Journal runtime illisible"
            ],
        }

    problems: list[str] = []
    warnings: list[str] = []

    uses_flexdmd = bool(
        runtime_profile.get("uses_flexdmd")
    )
    uses_pup = bool(
        runtime_profile.get("uses_pup")
    )

    lowered = log.casefold()

    error_lines = [
        line.strip()
        for line in log.splitlines()
        if " error " in f" {line.casefold()} "
        or "script error" in line.casefold()
        or "exception" in line.casefold()
    ]

    duplicate_full_dmd = [
        line
        for line in error_lines
        if "duplicate label" in line.casefold()
        and any(
            token in line.casefold()
            for token in (
                "fulldmd",
                "screennum=5",
                "screen 5",
                "screen=5",
            )
        )
    ]

    explicit_dmd_errors = [
        line
        for line in error_lines
        if any(
            token in line.casefold()
            for token in (
                "flexdmd",
                "ultradmd",
                "dmdobject",
                "full dmd",
                "fulldmd",
            )
        )
    ]

    hard_failure_patterns = (
        "failed to load flexdmd",
        "failed to load ultradmd",
        "flexdmd not found",
        "ultradmd not found",
        "cannot create flexdmd",
        "cannot create ultradmd",
        "unable to create flexdmd",
        "unable to create ultradmd",
        "unknown com object flexdmd",
        "unknown com object ultradmd",
    )

    hard_dmd_failure = any(
        token in lowered
        for token in hard_failure_patterns
    )

    plugin_loaded = (
        "plugin flexdmd loaded" in lowered
    )

    if duplicate_full_dmd and (uses_pup or uses_flexdmd):
        problems.append(
            "FlexDMD/FullDMD : labels PuP dupliqués "
            f"({len(duplicate_full_dmd)} erreur(s))"
        )

    if uses_flexdmd and hard_dmd_failure:
        problems.append(
            "FlexDMD/UltraDMD : chargement ou création impossible"
        )
    elif uses_flexdmd and explicit_dmd_errors:
        problems.append(
            "FlexDMD/UltraDMD : erreur d’exécution détectée"
        )

    finished = str(
        state.get("phase") or ""
    ) in {
        "finished",
        "stopped",
        "error",
    }

    if (
        uses_flexdmd
        and finished
        and not plugin_loaded
        and not problems
    ):
        warnings.append(
            "FlexDMD requis par le VBS, mais le plugin "
            "n’a pas été confirmé dans le journal"
        )

    return {
        "problems": problems,
        "warnings": warnings,
    }


# PINCABOS_EXPLORER_FIXED_TABLE_LOG_GO_NOGO_V1
TABLE_TEST_LOG_NAME = "PinCabOS-Test.log"


def _fixed_log_truth(folder: Path) -> dict[str, Any]:
    log_file = folder / TABLE_TEST_LOG_NAME

    if not log_file.is_file():
        return {
            "exists": False,
            "status": "VERIFY",
            "reasons": [
                "Aucun journal de test — table à vérifier"
            ],
            "path": str(log_file),
        }

    try:
        text = log_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return {
            "exists": True,
            "status": "VERIFY",
            "reasons": [
                "Journal de test illisible — relancer la table"
            ],
            "path": str(log_file),
        }

    statuses = re.findall(
        r"(?m)^PINCABOS_STATUS=(RUNNING|GO|NOGO)\s*$",
        text,
    )

    status = statuses[-1] if statuses else "VERIFY"
    final = bool(
        re.findall(r"(?m)^PINCABOS_FINAL=1\s*$", text)
    )

    if "===== PINCABOS RESULT =====" in text:
        result_text = text.rsplit(
            "===== PINCABOS RESULT =====",
            1,
        )[-1]
    else:
        result_text = ""

    reasons = [
        item.strip()
        for item in re.findall(
            r"(?m)^PINCABOS_REASON=(.+)$",
            result_text,
        )
        if item.strip()
    ]

    if status == "RUNNING":
        state = _state()
        same_table = (
            str(state.get("rel") or "")
            == _relative(folder)
        )
        live_phase = str(
            state.get("phase") or ""
        ) in {"launching", "running"}

        if not same_table or not live_phase:
            status = "VERIFY"
            reasons = ["Journal incomplet — relancer la table"]

    elif status in {"GO", "NOGO"} and not final:
        status = "VERIFY"
        reasons = ["Journal non finalisé — relancer la table"]

    elif status == "NOGO" and not reasons:
        reasons = [
            "Le dernier lancement contient une erreur bloquante"
        ]

    elif status == "GO":
        reasons = []

    elif status not in {"RUNNING", "GO", "NOGO"}:
        status = "VERIFY"
        reasons = ["Format du journal inconnu — relancer la table"]

    return {
        "exists": True,
        "status": status,
        "reasons": reasons,
        "path": str(log_file),
    }


def _fast_vps_metadata(info_files: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}

    url_re = re.compile(
        r"https?://[^\s\"'<>]*"
        r"(?:virtualpinballspreadsheet|vps)"
        r"[^\s\"'<>]*",
        re.IGNORECASE,
    )

    id_re = re.compile(
        r"(?im)^\s*(?:vpsid|vps_id|vpsdb_id)"
        r"\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)"
    )

    for info_file in info_files:
        try:
            content = info_file.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        try:
            parsed = json.loads(content)
        except Exception:
            parsed = None

        if parsed is not None:
            walked: dict[str, str] = {}
            _walk_metadata(parsed, walked)

            for key in ("vps_id", "vps_url"):
                value = str(walked.get(key) or "").strip()

                if value:
                    result.setdefault(key, value)

        url_match = url_re.search(content)

        if url_match:
            result.setdefault(
                "vps_url",
                url_match.group(0).rstrip(".,;)"),
            )

        id_match = id_re.search(content)

        if id_match:
            result.setdefault("vps_id", id_match.group(1))

    return result


# PINCABOS_EXPLORER_GO_CONTENT_SUMMARY_V1
def _named_child(
    parent: Path,
    names: set[str],
) -> Path | None:
    if not parent.is_dir():
        return None

    wanted = {
        name.casefold()
        for name in names
    }

    try:
        children = parent.iterdir()
    except OSError:
        return None

    for child in children:
        try:
            is_directory = child.is_dir()
        except OSError:
            continue

        if (
            is_directory
            and child.name.casefold() in wanted
        ):
            return child

    return None


def _count_zip_files(
    directories: list[Path],
) -> int:
    found: set[str] = set()

    for directory in directories:
        if not directory.is_dir():
            continue

        try:
            children = directory.iterdir()
        except OSError:
            continue

        for child in children:
            try:
                is_file = child.is_file()
            except OSError:
                continue

            if (
                is_file
                and child.suffix.casefold() == ".zip"
            ):
                found.add(
                    str(child.resolve())
                )

    return len(found)


def _has_extension(
    roots: list[Path],
    extensions: set[str],
) -> bool:
    wanted = {
        extension.casefold()
        for extension in extensions
    }

    for root in roots:
        if not root.is_dir():
            continue

        try:
            candidates = root.rglob("*")
        except OSError:
            continue

        try:
            for candidate in candidates:
                try:
                    is_file = candidate.is_file()
                except OSError:
                    continue

                if (
                    is_file
                    and candidate.suffix.casefold() in wanted
                ):
                    return True
        except OSError:
            continue

    return False


def _inventory_token(
    label: str,
    value: bool | int,
) -> str:
    if isinstance(value, bool):
        return (
            f"{label} ✓"
            if value
            else f"{label} —"
        )

    if value <= 0:
        return f"{label} —"

    if value == 1:
        return f"{label} ✓"

    return f"{label} {value}"


# PINCABOS_EXPLORER_GO_CONTENT_RUNTIME_TRUTH_V2
def _content_inventory(
    folder: Path,
    vpx_files: list[Path],
    b2s_files: list[Path],
    vps_exact: bool,
) -> dict[str, Any]:
    log_file = folder / TABLE_TEST_LOG_NAME

    try:
        log = log_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        log = ""

    lines = log.splitlines()

    def child_dir(
        parent: Path | None,
        wanted_name: str,
    ) -> Path | None:
        if parent is None or not parent.is_dir():
            return None

        wanted = wanted_name.casefold()

        try:
            children = parent.iterdir()
        except OSError:
            return None

        for child in children:
            try:
                is_directory = child.is_dir()
            except OSError:
                continue

            if (
                is_directory
                and child.name.casefold() == wanted
            ):
                return child

        return None

    def has_files(
        directory: Path | None,
        suffixes: set[str] | None = None,
    ) -> bool:
        if directory is None or not directory.is_dir():
            return False

        wanted = (
            {
                suffix.casefold()
                for suffix in suffixes
            }
            if suffixes
            else None
        )

        try:
            candidates = directory.rglob("*")
        except OSError:
            return False

        try:
            for candidate in candidates:
                try:
                    is_file = candidate.is_file()
                except OSError:
                    continue

                if not is_file:
                    continue

                if (
                    wanted is None
                    or candidate.suffix.casefold() in wanted
                ):
                    return True
        except OSError:
            return False

        return False

    def root_vbs_text() -> str:
        chunks: list[str] = []

        try:
            children = folder.iterdir()
        except OSError:
            return ""

        for child in children:
            try:
                is_file = child.is_file()
            except OSError:
                continue

            if (
                not is_file
                or child.suffix.casefold() != ".vbs"
                or _is_backup_name(child)
            ):
                continue

            try:
                chunks.append(
                    child.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )
            except OSError:
                continue

        return "\n".join(chunks)

    def useful_lines(
        required_tokens: tuple[str, ...],
        rejected_tokens: tuple[str, ...],
    ) -> list[str]:
        result: list[str] = []

        for line in lines:
            folded = line.casefold()

            if not any(
                token in folded
                for token in required_tokens
            ):
                continue

            if any(
                token in folded
                for token in rejected_tokens
            ):
                continue

            result.append(line)

        return result

    game_ids: list[str] = []

    for match in re.finditer(
        r"OnControllerGameStart.*?gameId="
        r"([A-Za-z0-9_.-]+)",
        log,
        re.IGNORECASE,
    ):
        value = match.group(1).strip()

        if value.casefold() not in {
            item.casefold()
            for item in game_ids
        }:
            game_ids.append(value)

    game_id = (
        game_ids[0]
        if game_ids
        else ""
    )

    pinmame = child_dir(
        folder,
        "pinmame",
    )

    pupvideos = child_dir(
        folder,
        "pupvideos",
    )

    altsound_root = (
        child_dir(pinmame, "altsound")
        or child_dir(folder, "altsound")
    )

    altcolor_root = (
        child_dir(pinmame, "altcolor")
        or child_dir(folder, "altcolor")
    )

    serum_root = (
        child_dir(pinmame, "serum")
        or child_dir(folder, "serum")
    )

    def game_directory(
        parent: Path | None,
    ) -> Path | None:
        if parent is None or not game_id:
            return None

        return child_dir(
            parent,
            game_id,
        )

    vbs = root_vbs_text()

    vpx_used = bool(
        re.search(
            r"(?i)(?:Starting VPX -|LoadGameFromFilename\s+.+\.vpx)",
            log,
        )
    )

    b2s_used = bool(
        re.search(
            r"(?i)directb2s file found at:",
            log,
        )
    )

    rom_used = bool(
        game_id
        or re.search(
            r"(?i)PinmameSetConfig\(\)",
            log,
        )
    )

    pup_runtime_lines = useful_lines(
        (
            "[pup:",
            "puplayer",
            "pinupplayer",
            "pupscreen",
            "puppack",
            "pupevent",
        ),
        (
            "plugin pup loaded",
            "plugin pup unloaded",
            "puppluginload",
            "no global pup folder configured",
            "pup manager stop",
            "pupmanager::stop",
            "plugin was found but is disabled",
        ),
    )

    pup_vbs = bool(
        re.search(
            r"(?i)\b(?:PuPlayer|PinUpPlayer|"
            r"PUPPack|PUPEvent|PUPCapture)\b",
            vbs,
        )
    )

    pup_used = bool(
        pup_runtime_lines
        or (
            pup_vbs
            and has_files(pupvideos)
        )
    )

    serum_runtime_lines = useful_lines(
        (
            "[serum:",
            ".crz",
            ".serum",
        ),
        (
            "plugin serum loaded",
            "plugin serum unloaded",
            "no colorization file found",
            "not found",
            "missing",
            "failed",
            "error",
        ),
    )

    serum_used = bool(
        serum_runtime_lines
        or has_files(
            game_directory(serum_root),
            {
                ".crz",
                ".serum",
            },
        )
        or has_files(
            game_directory(altcolor_root),
            {
                ".crz",
                ".serum",
            },
        )
    )

    altsound_runtime_lines = useful_lines(
        (
            "[altsound:",
            "altsound::",
        ),
        (
            "plugin altsound loaded",
            "plugin altsound unloaded",
            "not found",
            "missing",
            "failed",
            "error",
            "no altsound",
        ),
    )

    altsound_used = bool(
        altsound_runtime_lines
        or has_files(
            game_directory(altsound_root)
        )
    )

    altcolor_runtime_lines = useful_lines(
        (
            "[vni:",
            ".pal",
            ".vni",
            ".pac",
            "altcolor",
        ),
        (
            "plugin vni loaded",
            "plugin vni unloaded",
            "no pal file found",
            "no vni file found",
            "no colorization file found",
            "not found",
            "missing",
            "failed",
            "error",
        ),
    )

    altcolor_used = bool(
        altcolor_runtime_lines
        or has_files(
            game_directory(altcolor_root),
            {
                ".pal",
                ".vni",
                ".pac",
            },
        )
    )

    inventory = {
        "vpx": vpx_used,
        "b2s": b2s_used,
        "rom": rom_used,
        "pup": pup_used,
        "serum": serum_used,
        "altsound": altsound_used,
        "altcolor": altcolor_used,
        "vps": bool(vps_exact),
        "game_id": game_id,
        "source": "PinCabOS-Test.log",
    }

    inventory["summary"] = " · ".join(
        [
            _inventory_token(
                "VPX",
                inventory["vpx"],
            ),
            _inventory_token(
                "B2S",
                inventory["b2s"],
            ),
            _inventory_token(
                "ROM",
                inventory["rom"],
            ),
            _inventory_token(
                "PuP",
                inventory["pup"],
            ),
            _inventory_token(
                "Serum",
                inventory["serum"],
            ),
            _inventory_token(
                "AltSound",
                inventory["altsound"],
            ),
            _inventory_token(
                "AltColor",
                inventory["altcolor"],
            ),
            _inventory_token(
                "VPS",
                inventory["vps"],
            ),
        ]
    )

    return inventory




def scan_table(folder: Path, deep: bool = False) -> dict[str, Any]:
    folder = folder.resolve()

    if deep:
        vpx_files = _files(folder, ".vpx", recursive=True)
        b2s_files = _files(folder, ".directb2s", recursive=True)
        pov_files = _files(folder, ".pov", recursive=True)
        ini_files = _files(folder, ".ini", recursive=True)
        vbs_files = _files(folder, ".vbs", recursive=True)
        info_files = _files(folder, ".info", recursive=True)
    else:
        try:
            entries = [
                item
                for item in folder.iterdir()
                if item.is_file()
                and not _is_backup_name(item)
            ]
        except OSError:
            entries = []

        def direct_files(suffix: str) -> list[Path]:
            wanted = suffix.casefold()
            return sorted(
                (
                    item
                    for item in entries
                    if item.suffix.casefold() == wanted
                ),
                key=lambda item: item.name.casefold(),
            )

        vpx_files = direct_files(".vpx")
        b2s_files = direct_files(".directb2s")
        pov_files = direct_files(".pov")
        ini_files = direct_files(".ini")
        vbs_files = direct_files(".vbs")
        info_files = direct_files(".info")

    main_vpx = _choose_main_vpx(folder, vpx_files)
    vps_metadata = _fast_vps_metadata(info_files)

    vps_id = str(vps_metadata.get("vps_id") or "").strip()
    vps_url = str(vps_metadata.get("vps_url") or "").strip()

    if not vps_url and vps_id:
        vps_url = VPS_ID_URL.format(
            urllib.parse.quote(vps_id, safe="")
        )

    if not vps_url:
        vps_url = VPS_HOME

    vps_exact = bool(
        vps_id
        or vps_metadata.get("vps_url")
    )

    content_inventory = _content_inventory(
        folder,
        vpx_files,
        b2s_files,
        vps_exact,
    )

    truth = _fixed_log_truth(folder)
    log_status = str(truth.get("status") or "VERIFY")

    problems: list[str] = []
    warnings: list[str] = []

    if log_status == "NOGO":
        problems.extend(list(truth.get("reasons") or []))
        status = "problem"
    elif log_status == "GO":
        status = "go"
    elif log_status == "RUNNING":
        warnings.append("Test en cours — journal en écriture")
        status = "running"
    else:
        warnings.extend(list(truth.get("reasons") or []))
        status = "warning"

    return {
        "rel": _relative(folder),
        "name": folder.name,
        "main_vpx": _relative(main_vpx) if main_vpx else "",
        "main_vpx_name": main_vpx.name if main_vpx else "",
        "vpx_count": len(vpx_files),
        "b2s_count": len(b2s_files),
        "has_b2s": bool(b2s_files),
        "has_info": bool(info_files),
        "has_pov": bool(pov_files),
        "has_ini": bool(ini_files),
        "has_vbs": bool(vbs_files),
        "rom": "",
        "rom_required": False,
        "rom_ok": True,
        "uses_pinmame": False,
        "uses_pup": False,
        "uses_flexdmd": False,
        "uses_b2s_controller": False,
        "runtime": "",
        "vps_id": vps_id,
        "vps_url": vps_url,
        "vps_exact": vps_exact,
        "content_inventory": content_inventory,
        "content_summary": str(
            content_inventory.get("summary") or ""
        ),
        "test_log_name": TABLE_TEST_LOG_NAME,
        "test_log_path": str(truth.get("path") or ""),
        "test_log_exists": bool(truth.get("exists")),
        "test_log_status": log_status,
        "test_log_reasons": list(truth.get("reasons") or []),
        "problems": problems,
        "warnings": warnings,
        "status": status,
        "go": log_status == "GO",
    }





# PINCABOS_EXPLORER_DUAL_LAUNCH_V1
_PCO_PUP_ROOT_NAMES = {
    "pupvideos",
    "pupvideo",
    "pinupvideo",
    "pinupvideos",
}

_PCO_PUP_MEDIA_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".m4v",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp3",
    ".ogg",
    ".wav",
    ".flac",
}


def _pco_pup_node_has_content(root: Path) -> bool:
    try:
        if not root.is_dir():
            return False

        if (root / "screens.pup").is_file():
            return True

        if (root / "triggers.pup").is_file():
            return True

        children = list(root.iterdir())

        if any(
            child.is_file()
            and child.suffix.casefold() in _PCO_PUP_MEDIA_EXTENSIONS
            for child in children
        ):
            return True

        for child in children:
            if not child.is_dir():
                continue

            if (child / "screens.pup").is_file():
                return True

            if (child / "triggers.pup").is_file():
                return True

            try:
                if any(
                    item.is_file()
                    and item.suffix.casefold()
                    in _PCO_PUP_MEDIA_EXTENSIONS
                    for item in child.iterdir()
                ):
                    return True
            except OSError:
                continue

    except OSError:
        return False

    return False


def _pco_local_pup_available(folder: Path) -> bool:
    try:
        for child in folder.iterdir():
            if (
                child.is_dir()
                and child.name.casefold() in _PCO_PUP_ROOT_NAMES
                and _pco_pup_node_has_content(child)
            ):
                return True
    except OSError:
        return False

    return False


def _service_active() -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE],
        check=False,
    )
    return result.returncode == 0


def _control(action: str) -> subprocess.CompletedProcess[str]:
    command = [str(CONTROL), action]
    if os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def status_payload() -> dict[str, Any]:
    state = _state()
    active = _service_active()

    rel = str(state.get("rel") or "")
    health: dict[str, Any] = {}
    if rel:
        try:
            health = scan_table(_resolve_rel(rel), deep=not active)
        except Exception:
            health = {}

    phase = str(state.get("phase") or "idle")
    if active and phase in {"starting", "launching", "running"}:
        phase = "running"

    return {
        "ok": True,
        "active": active,
        "phase": phase,
        "state": state,
        "health": health,
    }



# PINCABOS_EXPLORER_NATIVE_TABLES_V1_INDEX
def _catalog_read() -> dict[str, Any]:
    with _CATALOG_LOCK:
        payload = _json_read(
            CATALOG_INDEX_FILE,
            {
                "version": 1,
                "generated_at": 0,
                "tables": {},
            },
        )

    if not isinstance(payload, dict):
        payload = {}

    tables = payload.get("tables")
    if not isinstance(tables, dict):
        tables = {}

    clean_tables = {
        str(rel): value
        for rel, value in tables.items()
        if isinstance(value, dict)
    }

    return {
        "version": 1,
        "generated_at": int(payload.get("generated_at") or 0),
        "scan_seconds": float(payload.get("scan_seconds") or 0.0),
        "changed": int(payload.get("changed") or 0),
        "count": len(clean_tables),
        "tables": clean_tables,
    }


def _catalog_write(payload: dict[str, Any]) -> None:
    with _CATALOG_LOCK:
        _json_write(CATALOG_INDEX_FILE, payload)


def _catalog_fingerprint(folder: Path) -> str:
    rows: list[tuple[str, int, int, int]] = []

    try:
        stat = folder.stat()
        rows.append((
            ".",
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(stat.st_ino),
        ))
    except OSError:
        return "missing"

    interesting_directories = {
        "pinmame",
        "pupvideos",
        "altsound",
        "altcolor",
        "serum",
        "dmd",
        "medias",
        "media",
        "music",
    }

    try:
        children = list(folder.iterdir())
    except OSError:
        children = []

    for child in children:
        try:
            is_file = child.is_file()
            is_dir = child.is_dir()
        except OSError:
            continue

        lower = child.name.casefold()
        relevant_file = (
            lower == TABLE_TEST_LOG_NAME.casefold()
            or child.suffix.casefold() in {
                ".vpx",
                ".directb2s",
                ".info",
                ".vbs",
            }
        )
        relevant_directory = (
            is_dir
            and lower in interesting_directories
        )

        if not (
            (is_file and relevant_file)
            or relevant_directory
        ):
            continue

        try:
            stat = child.stat()
        except OSError:
            continue

        rows.append((
            child.name,
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(stat.st_ino),
        ))

    rows.sort(key=lambda item: item[0].casefold())
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def _catalog_placeholder(folder: Path) -> dict[str, Any]:
    return {
        "rel": _relative(folder),
        "name": folder.name,
        "main_vpx": "",
        "main_vpx_name": "",
        "vps_id": "",
        "vps_url": VPS_HOME,
        "vps_exact": False,
        "content_inventory": {},
        "content_summary": "Analyse en arrière-plan",
        "test_log_name": TABLE_TEST_LOG_NAME,
        "test_log_path": str(folder / TABLE_TEST_LOG_NAME),
        "test_log_exists": False,
        "test_log_status": "VERIFY",
        "test_log_reasons": [
            "Index en préparation — table à vérifier"
        ],
        "problems": [],
        "warnings": [
            "Index en préparation — table à vérifier"
        ],
        "status": "indexing",
        "go": False,
        "_placeholder": True,
    }


def refresh_catalog_now() -> dict[str, Any]:
    started = time.monotonic()
    previous = _catalog_read()
    previous_tables = previous.get("tables") or {}

    try:
        folders = sorted(
            (
                entry
                for entry in TABLES_ROOT.iterdir()
                if entry.is_dir()
            ),
            key=lambda entry: entry.name.casefold(),
        )
    except OSError:
        folders = []

    tables: dict[str, dict[str, Any]] = {}
    changed = 0
    errors = 0

    for folder in folders:
        rel = _relative(folder)
        fingerprint = _catalog_fingerprint(folder)
        old = previous_tables.get(rel)

        if (
            isinstance(old, dict)
            and old.get("_fingerprint") == fingerprint
        ):
            tables[rel] = old
            continue

        changed += 1

        try:
            entry = scan_table(folder, deep=False)
        except Exception as exc:
            errors += 1
            entry = _catalog_placeholder(folder)
            entry["warnings"] = [
                f"Analyse impossible : {exc}"
            ]
            entry["status"] = "warning"

        entry["_fingerprint"] = fingerprint
        entry["_indexed_at"] = int(time.time())
        tables[rel] = entry

    payload = {
        "version": 1,
        "generated_at": int(time.time()),
        "scan_seconds": round(
            time.monotonic() - started,
            4,
        ),
        "changed": changed,
        "errors": errors,
        "count": len(tables),
        "tables": tables,
    }

    _catalog_write(payload)
    return payload


def _catalog_worker() -> None:
    while True:
        try:
            refresh_catalog_now()
        except Exception:
            pass

        _CATALOG_WAKE.wait(CATALOG_REFRESH_SECONDS)
        _CATALOG_WAKE.clear()


def _start_catalog_worker() -> None:
    global _CATALOG_THREAD_STARTED

    with _CATALOG_LOCK:
        if _CATALOG_THREAD_STARTED:
            return
        _CATALOG_THREAD_STARTED = True

    thread = threading.Thread(
        target=_catalog_worker,
        name="pincabos-explorer-catalog",
        daemon=True,
    )
    thread.start()


def native_catalog_context() -> dict[str, Any]:
    catalog = _catalog_read()
    state = _state()
    active = _service_active()

    return {
        "catalog": catalog,
        "tables": catalog.get("tables") or {},
        "active": active,
        "active_rel": (
            str(state.get("rel") or "")
            if active
            else ""
        ),
        "state": state,
    }


def _native_status_label(entry: dict[str, Any]) -> tuple[str, str]:
    status = str(entry.get("status") or "indexing")

    if status == "go":
        return "go", "✓ GO"
    if status == "problem":
        return "problem", "✗ PROBLÈME"
    if status == "running":
        return "running", "● EN TEST"
    if status == "warning":
        return "warning", "! À VÉRIFIER"

    return "indexing", "··· ANALYSE"


def _native_inventory_html(entry: dict[str, Any]) -> str:
    # PINCABOS_EXPLORER_NATIVE_FAST_V2_COMPACT_SUMMARY
    summary = str(entry.get("content_summary") or "").strip()

    if not summary:
        inventory = entry.get("content_inventory")

        if isinstance(inventory, dict) and inventory:
            tokens = (
                ("VPX", "vpx"),
                ("B2S", "b2s"),
                ("ROM", "rom"),
                ("PuP", "pup"),
                ("Serum", "serum"),
                ("AltSound", "altsound"),
                ("AltColor", "altcolor"),
                ("VPS", "vps"),
            )

            summary = " · ".join(
                label + " " + ("✓" if inventory.get(key) else "—")
                for label, key in tokens
            )

    if not summary:
        summary = "Analyse en arrière-plan"

    return (
        '<span class="pco-native-inventory-text">'
        + html.escape(summary)
        + "</span>"
    )


def native_controls_html(
    rel: str,
    context: dict[str, Any] | None = None,
) -> str:
    clean_rel = str(rel or "").replace("\\", "/").strip("/")

    if not clean_rel:
        return ""

    if context is None:
        context = native_catalog_context()

    tables = context.get("tables")
    if not isinstance(tables, dict):
        tables = {}

    entry = tables.get(clean_rel)

    if not isinstance(entry, dict):
        try:
            entry = _catalog_placeholder(_resolve_rel(clean_rel))
        except Exception:
            return ""

    status_class, status_label = _native_status_label(entry)

    active = bool(context.get("active"))
    active_rel = str(context.get("active_rel") or "")
    is_active = active and active_rel == clean_rel

    problems = list(entry.get("problems") or [])
    warnings = list(entry.get("warnings") or [])
    title = "\n".join(str(item) for item in problems + warnings)

    vps_url = str(entry.get("vps_url") or VPS_HOME).strip()
    if not re.match(r"^https?://", vps_url, re.IGNORECASE):
        vps_url = VPS_HOME

    vps_exact = bool(entry.get("vps_exact"))
    vps_label = "🔗 VPS" if vps_exact else "🔗 Associer VPS"

    cached = not bool(entry.get("_placeholder"))
    play_disabled = (
        cached
        and not str(entry.get("main_vpx") or "")
    )

    escaped_rel = html.escape(clean_rel, quote=True)
    escaped_title = html.escape(title, quote=True)
    escaped_url = html.escape(vps_url, quote=True)

    pup_available = False
    try:
        pup_available = _pco_local_pup_available(
            _resolve_rel(clean_rel)
        )
    except Exception:
        pup_available = False

    play_disabled_attr = " disabled" if play_disabled else ""
    stop_disabled_attr = "" if is_active else " disabled"

    return (
        '<div class="pco-native-table-tools is-'
        + status_class
        + (' is-active' if is_active else '')
        + '" data-pco-base-status="'
        + status_class
        + '" data-pco-rel="'
        + escaped_rel
        + '">'
        + '<div class="pco-native-controls-line">'
        + '<span class="pco-native-status is-'
        + status_class
        + '" data-pco-base-label="'
        + html.escape(status_label, quote=True)
        + '" title="'
        + escaped_title
        + '">'
        + html.escape(status_label)
        + "</span>"
        + '<button type="button" class="pco-native-button pco-native-play pco-native-play-legacy" '
        + 'data-pco-action="play-legacy" data-pco-rel="'
        + escaped_rel
        + '" data-pco-base-disabled="'
        + ("1" if play_disabled else "0")
        + '"'
        + play_disabled_attr
        + ">▶ Play Legacy</button>"
        + (
            '<button type="button" class="pco-native-button pco-native-play pco-native-play-pup" '
            + 'data-pco-action="play-pup" data-pco-rel="'
            + escaped_rel
            + '" data-pco-base-disabled="'
            + ("1" if play_disabled else "0")
            + '"'
            + play_disabled_attr
            + ">▶ Play PUPPack</button>"
        )
        + '<button type="button" class="pco-native-button pco-native-stop" '
        + 'data-pco-action="stop" data-pco-rel="'
        + escaped_rel
        + '"'
        + stop_disabled_attr
        + ">■ Stop</button>"
        + '<a class="pco-native-button pco-native-vps" href="'
        + escaped_url
        + '" target="_blank" rel="noopener noreferrer">'
        + html.escape(vps_label)
        + "</a>"
        + "</div>"
        + '<div class="pco-native-summary" title="'
        + escaped_title
        + '">'
        + _native_inventory_html(entry)
        + "</div>"
        + "</div>"
    )


def _inject_assets(body: str, css: str = "", js: str = "") -> str:
    if css and css not in body:
        tag = f'<link rel="stylesheet" href="{html.escape(css)}">'
        if "</head>" in body:
            body = body.replace("</head>", tag + "</head>", 1)
        else:
            body = tag + body
    if js and js not in body:
        tag = f'<script src="{html.escape(js)}"></script>'
        if "</body>" in body:
            body = body.replace("</body>", tag + "</body>", 1)
        else:
            body += tag
    return body


def _wrap_commander(app: Any) -> str:
    target_endpoint = None
    for rule in app.url_map.iter_rules():
        if rule.rule == "/tools/commander" and "GET" in rule.methods:
            target_endpoint = rule.endpoint
            break
    if not target_endpoint:
        return "route-absente"

    original = app.view_functions[target_endpoint]
    if getattr(original, "_pco_table_test_wrapped", False):
        return "déjà-wrapped"

    @functools.wraps(original)
    def wrapped(*args: Any, **kwargs: Any):
        response = app.make_response(original(*args, **kwargs))
        if (
            request.method == "GET"
            and request.args.get("root", "") in ("", "Tables")
            and response.mimetype == "text/html"
            and not response.direct_passthrough
        ):
            body = response.get_data(as_text=True)
            body = _inject_assets(
                body,
                "/static/pincabos-explorer-table-test-v1.css?v=39",
                "/static/pincabos-explorer-table-test-v1.js?v=41",
            )
            response.set_data(body)
        return response

    wrapped._pco_table_test_wrapped = True
    app.view_functions[target_endpoint] = wrapped
    return "wrapped"


def register(app: Any, detect_batch: Any = None) -> None:
    global _DETECT_BATCH
    _DETECT_BATCH = detect_batch
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # PINCABOS_COMMANDER_ZERO_BACKGROUND_V1_NO_CATALOG_WORKER
    # Catalogue lu depuis le cache; aucun scan périodique.

    # PINCABOS_EXPLORER_INSTALLED_TABLE_COUNT_V1
    @app.get("/api/explorer/table-count")
    def pco_explorer_installed_table_count():
        # Compte uniquement les dossiers directement installés dans
        # /home/pinball/Tables. Aucun scan VPX, VBS, ROM ou média.
        try:
            if not TABLES_ROOT.is_dir():
                raise NotADirectoryError(
                    "Le dossier Tables est introuvable."
                )

            count = sum(
                1
                for entry in TABLES_ROOT.iterdir()
                if entry.is_dir()
            )

            response = jsonify({
                "ok": True,
                "count": count,
                "root": str(TABLES_ROOT),
                "method": "direct-folders",
            })
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            return response
        except Exception as exc:
            return jsonify({
                "ok": False,
                "count": 0,
                "error": str(exc),
            }), 500

    @app.get("/api/explorer/table-test/list")
    def pco_explorer_table_test_list():
        try:
            requested = str(
                request.args.get("path", "") or ""
            ).replace("\\", "/").strip("/")

            if requested:
                return jsonify({
                    "ok": True,
                    "path": requested,
                    "tables": [],
                    "test": status_payload(),
                    "root_only": True,
                    "source": "native-cache",
                })

            context = native_catalog_context()
            indexed = context.get("tables") or {}
            tables = []

            for item in sorted(
                (
                    entry
                    for entry in TABLES_ROOT.iterdir()
                    if entry.is_dir()
                ),
                key=lambda entry: entry.name.casefold(),
            ):
                rel = _relative(item)
                entry = indexed.get(rel)

                if not isinstance(entry, dict):
                    entry = _catalog_placeholder(item)

                tables.append(entry)

            catalog = context.get("catalog") or {}

            return jsonify({
                "ok": True,
                "path": "",
                "tables": tables,
                "test": status_payload(),
                "root_only": True,
                "source": "native-cache",
                "generated_at": int(
                    catalog.get("generated_at") or 0
                ),
                "scan_seconds": float(
                    catalog.get("scan_seconds") or 0.0
                ),
            })
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": str(exc),
            }), 400

    @app.get("/api/explorer/table-test/health")
    def pco_explorer_table_test_health():
        try:
            folder = _resolve_rel(request.args.get("path", ""))
            if not folder.is_dir():
                raise NotADirectoryError("Dossier de table invalide.")
            return jsonify({"ok": True, "health": scan_table(folder, deep=True)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.get("/api/explorer/table-test/status")
    def pco_explorer_table_test_status():
        return jsonify(status_payload())

    @app.post("/api/explorer/table-test/play")
    def pco_explorer_table_test_play():
        try:
            payload = request.get_json(silent=True) or {}

            launch_mode = str(
                payload.get("mode") or "original"
            ).strip().casefold()

            if launch_mode == "legacy":
                launch_mode = "original"

            if launch_mode not in {"original", "pup"}:
                return jsonify({
                    "ok": False,
                    "error": "Mode de lancement invalide.",
                }), 400

            folder = _resolve_rel(str(payload.get("path") or ""))
            if not folder.is_dir():
                raise NotADirectoryError("Dossier de table invalide.")

            health = scan_table(folder, deep=True)
            if not health.get("main_vpx"):
                return jsonify({
                    "ok": False,
                    "error": "Aucun fichier VPX principal ne peut être lancé.",
                    "health": health,
                }), 400

            if _service_active():
                current = status_payload()
                return jsonify({
                    "ok": False,
                    "error": "Une table est déjà en test.",
                    "test": current,
                }), 409

            vpx = _resolve_rel(str(health["main_vpx"]))

            # PINCABOS_EXPLORER_PUPPACK_MANUAL_OVERRIDE_V1
            # Le bouton Play PUPPack est une commande manuelle.
            # La detection PuP reste informative dans l'inventaire
            # mais ne bloque pas un lancement demande explicitement.

            state = {
                "phase": "starting",
                "rel": _relative(folder),
                "table_name": folder.name,
                "vpx": str(vpx),
                "vpx_name": vpx.name,
                "launch_mode": launch_mode,
                "started_at": int(time.time()),
                "stop_requested": False,
                "exit_code": None,
            }
            _write_state(state)

            result = _control("play")
            if result.returncode != 0:
                _update_state(
                    phase="error",
                    error=(result.stderr or result.stdout or "Démarrage impossible").strip(),
                )
                return jsonify({
                    "ok": False,
                    "error": (result.stderr or result.stdout or "Démarrage impossible").strip(),
                }), 500

            return jsonify(status_payload())
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/explorer/table-test/stop")
    def pco_explorer_table_test_stop():
        state = _state()
        if state:
            state["stop_requested"] = True
            state["phase"] = "stopping"
            _write_state(state)

        result = _control("stop")
        if result.returncode != 0:
            return jsonify({
                "ok": False,
                "error": (result.stderr or result.stdout or "Arrêt impossible").strip(),
            }), 500
        return jsonify(status_payload())

    commander_mode = _wrap_commander(app)

    @app.after_request
    def pco_table_test_dashboard_asset(response):
        if (
            request.method == "GET"
            and response.mimetype == "text/html"
            and not response.direct_passthrough
        ):
            body = response.get_data(as_text=True)
            if (
                'id="pco-dashboard-batch-controls"' in body
                and "pincabos-dashboard-table-test-v1.js" not in body
            ):
                body = _inject_assets(
                    body,
                    js="/static/pincabos-dashboard-table-test-v1.js?v=1",
                )
                response.set_data(body)
        return response

    print(
        "GO: Explorer Table Test Center loaded "
        f"commander={commander_mode}"
    )
