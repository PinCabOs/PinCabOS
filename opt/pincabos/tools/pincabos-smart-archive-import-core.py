#!/usr/bin/env python3
# PinCabOS-File created by Karots Sugarpie
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

try:
    import olefile
except Exception:
    olefile = None

def pincabos_force_standard_table_name(name):
    """
    Force le format:
    Table Name (Manufacturer Year)

    Exemples:
    The Leprechaun King_Original_2019_ -> The Leprechaun King (Original 2019)
    Ramones _Original 2021_           -> Ramones (Original 2021)
    Ramones_Original_2021_            -> Ramones (Original 2021)
    """
    name = str(name or "").strip()

    name = name.replace("\\", " ").replace("/", " ")
    name = re.sub(r'[:"*?<>|]+', " ", name)
    name = re.sub(r"\s+", " ", name).strip()

    # Cas: Table_Manufacturer_Year_
    m = re.match(r"^(?P<table>.+?)_(?P<mfg>[^_()]+)_(?P<year>\d{4})_$", name)
    if m:
        table = re.sub(r"[_\s]+", " ", m.group("table")).strip()
        mfg = re.sub(r"[_\s]+", " ", m.group("mfg")).strip()
        year = m.group("year").strip()
        return f"{table} ({mfg} {year})"

    # Cas: Table _Manufacturer Year_
    m = re.match(r"^(?P<table>.+?)\s+_(?P<mfg>[^_()]+?)\s+(?P<year>\d{4})_$", name)
    if m:
        table = re.sub(r"[_\s]+", " ", m.group("table")).strip()
        mfg = re.sub(r"[_\s]+", " ", m.group("mfg")).strip()
        year = m.group("year").strip()
        return f"{table} ({mfg} {year})"

    # Cas: Table Manufacturer 2021, seulement si pas déjà avec parenthèses
    if "(" not in name and ")" not in name:
        m = re.match(r"^(?P<table>.+?)\s+(?P<mfg>Original|Williams|Stern|Bally|Gottlieb|Data East|Sega|HauntFreaks|MOD)\s+(?P<year>\d{4})$", name, re.I)
        if m:
            table = re.sub(r"[_\s]+", " ", m.group("table")).strip()
            mfg = re.sub(r"[_\s]+", " ", m.group("mfg")).strip()
            year = m.group("year").strip()
            return f"{table} ({mfg} {year})"

    return name or "Imported Table"


BASE = Path("/opt/pincabos")
TABLES_ROOT = Path("/home/pinball/Tables")
IMPORT_LOGS_ROOT = BASE / "imports" / "logs"

ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".pincabos"}

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".apng"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac"}
FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}
DOC_EXTS = {".txt", ".pdf", ".doc", ".docx", ".rtf", ".nfo", ".md"}

MEDIA_EXTS = VIDEO_EXTS | IMAGE_EXTS | AUDIO_EXTS

ROOT_EXTS = {
    ".vpx",
    ".directb2s",
    ".vbs",
    ".scv",
    ".pov",
    ".res",
}

PINCABOS_VPXTOOL_RELEASE_MANIFEST = (
    BASE / "update" / "vpxtool-release.json"
)
PINCABOS_VPXTOOL_CANDIDATES = (
    Path("/opt/pincabos/bin/vpxtool"),
    Path("/usr/local/bin/vpxtool"),
)
PINCABOS_VPX_OLE_MAGIC = bytes.fromhex(
    "d0cf11e0a1b11ae1"
)
PINCABOS_SMART_IMPORT_RESOURCE_MANIFEST = (
    ".pincabos-smart-import-resources.json"
)
PINCABOS_VPSDB_PATH = Path(
    "/home/pinball/.config/vpinfe/vpsdb.json"
)
PINCABOS_VPSDB_RESOURCE_KEYS = (
    "tableFiles",
    "b2sFiles",
    "romFiles",
    "pupPackFiles",
    "altSoundFiles",
    "altColorFiles",
    "soundFiles",
    "povFiles",
    "mediaPackFiles",
    "wheelArtFiles",
    "topperFiles",
    "ruleFiles",
    "tutorialFiles",
)
PINCABOS_VPSDB_RESOURCE_TYPES = {
    "tableFiles": "tableFile",
    "b2sFiles": "b2sFile",
    "romFiles": "romFile",
    "pupPackFiles": "pupPackFile",
    "altSoundFiles": "altSoundFile",
    "altColorFiles": "altColorFile",
    "soundFiles": "soundFile",
    "povFiles": "povFile",
    "mediaPackFiles": "mediaPackFile",
    "wheelArtFiles": "wheelArtFile",
    "topperFiles": "topperFile",
    "ruleFiles": "ruleFile",
    "tutorialFiles": "tutorialFile",
}

VNI_EXTS = {".pal", ".vni"}
SERUM_EXTS = {".crz", ".serum"}
ALTCOLOR_MISC_EXTS = {".pac"}

PINMAME_CFG_EXTS = {".cfg"}
PINMAME_NVRAM_EXTS = {".nv", ".nvram"}

TEMP_NAMES = {
    "extract",
    "tmp",
    "temp",
    "_raw_files",
    "raw_files",
    "upload",
    "uploads",
    "archive",
    "nested",
}

def log(msg):
    print(msg, flush=True)


def standard_table_folder_name(name):
    return pincabos_force_standard_table_name(name)



def safe_name(value):
    value = str(value or "").strip()
    value = value.replace("\\", " ").replace("/", " ")
    value = re.sub(r'[:"*?<>|]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "Imported Table"

def is_temp_name(name):
    n = str(name or "").strip().lower()
    return (
        n in TEMP_NAMES
        or n.startswith("_archive_")
        or n.startswith("archive_")
        or n.startswith("_nested_")
        or n.startswith("nested_")
        or n.startswith("_forced_")
        or n.startswith("forced_")
        or n.startswith("_already_extracted_")
        or n.startswith("already_extracted_")
        or n.startswith("pincabos-")
    )

def run(cmd, timeout=1800):
    log("$ " + " ".join(str(x) for x in cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)

def list_files(root):
    return [p for p in Path(root).rglob("*") if p.is_file()]

def list_dirs(root):
    return [p for p in Path(root).rglob("*") if p.is_dir()]

def archive_probe(src):
    try:
        r = run(["7z", "l", "-slt", str(src)], timeout=180)
        return (r.stdout or "") + "\n" + (r.stderr or "")
    except Exception as e:
        return str(e)

def archive_is_passworded(src):
    """
    Détection informative seulement.

    Une mention générale de chiffrement dans le catalogue
    ne permet pas de conclure qu'un mot de passe est requis.
    L'extraction réelle demeure la source de vérité.
    """
    data = archive_probe(src).lower()

    return any(marker in data for marker in (
        "wrong password",
        "password is incorrect",
        "can not open encrypted archive",
    ))

def archive_file_list(src):
    data = archive_probe(src)
    out = []
    for line in data.splitlines():
        line = line.strip()
        if line.startswith("Path = "):
            val = line.split("=", 1)[1].strip()
            if val and val != str(src):
                out.append(val)
    return out

def archive_kind(src):
    src = Path(src)
    if src.suffix.lower() not in ARCHIVE_EXTS:
        return ""

    files = [x.lower().replace("\\", "/") for x in archive_file_list(src)]
    names = [Path(x).name.lower() for x in files]

    if any(x.endswith(".dif") for x in files):
        return "vpu_patch_archive"

    if any(x.endswith(".vpx") for x in files):
        return "table_archive"

    if "pinupplayer.ini" in names or any(x.endswith(".pup") for x in files):
        return "pup_archive"

    if "altsound.ini" in names or "altsound.csv" in names or any("/altsound/" in x or x.startswith("altsound/") for x in files):
        return "altsound_archive"

    audio_files = [x for x in files if x.endswith((".mp3", ".wav", ".ogg", ".flac"))]
    if audio_files:
        if any("/music/" in x or x.startswith("music/") for x in files):
            return "music_archive"
        if len(audio_files) >= 1:
            return "music_archive"

    if any(x.endswith(".crz") for x in files):
        return "serum_archive"

    if any(x.endswith(".pal") or x.endswith(".vni") for x in files):
        return "vni_archive"

    if src.suffix.lower() == ".zip":
        # Une ROM PinMAME est souvent un ZIP avec des fichiers binaires sans VPX/media/config.
        if not any(x.endswith((
            ".vpx", ".directb2s", ".vbs", ".scv", ".pov", ".res",
            ".pup", ".mp4", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".apng",
            ".ini", ".cfg", ".nv", ".nvram", ".pal", ".vni", ".crz"
        )) for x in files):
            return "rom_zip"

    return "support_archive"

def extract_archive(src, dest):
    """
    Extrait une archive portable PinCabOS.

    Les archives RAR utilisent UnRAR officiel afin de prendre
    en charge les méthodes RAR 7 que 7-Zip peut cataloguer sans
    être capable de les décompresser.

    Les autres formats continuent d'utiliser 7-Zip.
    """
    src = Path(src)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() == ".rar":
        unrar = Path("/usr/local/bin/pincabos-unrar")

        if not unrar.is_file():
            raise RuntimeError(
                "SUPPORT RAR 7 ABSENT: "
                "/usr/local/bin/pincabos-unrar"
            )

        command = [
            str(unrar),
            "x",
            "-o+",
            "-p-",
            str(src),
            str(dest) + "/",
        ]

        extractor_name = "UnRAR"

    else:
        command = [
            "7z",
            "x",
            "-y",
            f"-o{dest}",
            str(src),
        ]

        extractor_name = "7-Zip"

    r = run(command)

    stdout = r.stdout or ""
    stderr = r.stderr or ""
    data = (stdout + "\n" + stderr).lower()

    password_errors = (
        "wrong password",
        "password is incorrect",
        "incorrect password",
        "missing password",
        "password required",
        "can not open encrypted archive",
        "cannot open encrypted archive",
    )

    if (
        r.returncode != 0
        and any(marker in data for marker in password_errors)
    ):
        raise RuntimeError(
            f"ARCHIVE PASSWORD REFUSÉE: {src}\n"
            f"Extracteur: {extractor_name}\n"
            f"{stdout}\n{stderr}"
        )

    if r.returncode != 0:
        raise RuntimeError(
            "ÉCHEC EXTRACTION ARCHIVE "
            f"(extracteur={extractor_name}, "
            f"code={r.returncode}): {src}\n"
            f"{stdout}\n{stderr}"
        )

    extracted_files = [
        item
        for item in dest.rglob("*")
        if item.is_file()
    ]

    if not extracted_files:
        raise RuntimeError(
            f"Extraction vide: {src}"
        )

    log(
        f"Extraction réussie avec {extractor_name}: "
        f"{src.name} -> {len(extracted_files)} fichier(s)"
    )

def is_password_protected_error(exc):
    return "ARCHIVE PASSWORD REFUSÉE:" in str(exc)

def copy_file(src, dest_dir, new_name=None):
    # PINCABOS_COPY_FILE_ATOMIC_V2
    #
    # Ne jamais faire copy2() directement sur un fichier existant
    # potentiellement possédé par root.
    #
    # copy2() copie d'abord vers un inode temporaire appartenant
    # à l'utilisateur courant, puis Path.replace() remplace
    # atomiquement la destination.
    #
    # Cela conserve les métadonnées copy2() sans appeler utime()
    # sur l'ancien inode root-owned.

    src = Path(src)
    dest_dir = Path(dest_dir)

    dest_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    dest = (
        dest_dir
        / safe_name(
            new_name or src.name
        )
    )

    with tempfile.NamedTemporaryFile(
        prefix=f".{dest.name}.pincabos-copy-",
        suffix=".tmp",
        dir=str(dest_dir),
        delete=False,
    ) as handle:
        temporary = Path(handle.name)

    try:

        shutil.copy2(
            src,
            temporary,
        )

        temporary.replace(
            dest
        )

    finally:

        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

    log(
        f"INSTALLÉ: {src} -> {dest}"
    )

    return dest

# === PINCABOS_SMART_IMPORT_UPDATE_V1 START ===

PINCABOS_SMART_IMPORT_MTIME_TOLERANCE = 2.0

PINCABOS_SMART_IMPORT_BACKUP_ROOT = (
    Path(
        "/home/pinball/.local/share/"
        "pincabos/backups/smart-import"
    )
)

PINCABOS_SMART_IMPORT_LOCK = Path(
    "/tmp/pincabos-smart-import.lock"
)


def pincabos_file_sha256(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as handle:
        for chunk in iter(
            lambda: handle.read(8 * 1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def pincabos_table_identity_key(name):
    return standard_table_folder_name(
        safe_name(name)
    ).casefold()


def pincabos_find_existing_table_dir(title):
    wanted = pincabos_table_identity_key(title)

    exact = (
        TABLES_ROOT
        / standard_table_folder_name(
            safe_name(title)
        )
    )

    if exact.exists():
        if exact.is_symlink():
            raise RuntimeError(
                "NOGO: dossier de table symlink "
                f"refusé: {exact}"
            )

        if not exact.is_dir():
            raise RuntimeError(
                "NOGO: destination de table "
                f"non-dossier: {exact}"
            )

        return exact

    matches = []

    try:
        for candidate in TABLES_ROOT.iterdir():
            if (
                not candidate.is_dir()
                or candidate.is_symlink()
            ):
                continue

            if (
                pincabos_table_identity_key(
                    candidate.name
                )
                == wanted
            ):
                matches.append(candidate)

    except FileNotFoundError:
        return exact

    if len(matches) > 1:
        raise RuntimeError(
            "NOGO: plusieurs dossiers "
            "correspondent au même nom normalisé: "
            + " | ".join(
                str(item)
                for item in matches
            )
        )

    return matches[0] if matches else exact


def pincabos_load_resource_manifest(path, batch_dir):
    path = Path(path)
    batch_dir = Path(batch_dir).resolve()

    if (
        path.name != PINCABOS_SMART_IMPORT_RESOURCE_MANIFEST
        or path.resolve().parent != batch_dir
        or not path.is_file()
    ):
        raise RuntimeError(
            "NOGO: inventaire VPS-ID absent ou hors du batch."
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"NOGO: inventaire VPS-ID illisible: {exc}"
        ) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("format")
        != "PinCabOS Smart Import resources"
        or not isinstance(payload.get("resources"), list)
        or not str(payload.get("game_vpsid", "") or "").strip()
    ):
        raise RuntimeError("NOGO: inventaire VPS-ID invalide.")

    manifest_game_vpsid = str(
        payload.get("game_vpsid", "") or ""
    ).strip()
    association_mode = str(
        payload.get("association_mode", "complete_vpsid")
        or "complete_vpsid"
    ).strip()

    if association_mode not in {"complete_vpsid", "partial_vpsid"}:
        raise RuntimeError("NOGO: mode d'association VPS-ID invalide.")

    seen_names = set()
    has_resolved_vpsid = False

    for resource in payload["resources"]:
        if not isinstance(resource, dict):
            raise RuntimeError("NOGO: ressource VPS-ID invalide.")

        stored_name = str(resource.get("stored_name", "") or "").strip()
        vpsid = str(resource.get("vpsid", "") or "").strip()
        game_vpsid = str(resource.get("game_vpsid", "") or "").strip()
        resource_type = str(resource.get("resource_type", "") or "").strip()
        association = str(resource.get("association", "") or "").strip()
        expected_sha256 = str(resource.get("sha256", "") or "").strip().lower()
        candidate = batch_dir / stored_name

        if (
            not stored_name
            or Path(stored_name).name != stored_name
            or stored_name.casefold() in seen_names
        ):
            raise RuntimeError(
                f"NOGO: nom de ressource invalide: {stored_name!r}"
            )

        seen_names.add(stored_name.casefold())

        if game_vpsid.casefold() != manifest_game_vpsid.casefold():
            raise RuntimeError(
                f"NOGO: jeu VPSDB incohérent pour {stored_name}."
            )

        if vpsid:
            has_resolved_vpsid = True
            if resource_type == "unresolved":
                raise RuntimeError(
                    f"NOGO: type unresolved interdit avec VPS-ID pour {stored_name}."
                )
        else:
            if association_mode != "partial_vpsid":
                raise RuntimeError(
                    f"NOGO: VPS-ID manquant dans un inventaire complet: {stored_name}."
                )
            if resource_type != "unresolved" or association != "inferred_game":
                raise RuntimeError(
                    f"NOGO: ressource sans VPS-ID non marquée comme inférée: {stored_name}."
                )
            if bool(resource.get("contains_vpu_patch")):
                raise RuntimeError(
                    "NOGO: un patch VPU Remix .dif exige son VPS-ID exact: "
                    f"{stored_name}."
                )

        if not candidate.is_file() or candidate.is_symlink():
            raise RuntimeError(
                f"NOGO: fichier inventorié absent ou non régulier: {candidate}"
            )

        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or pincabos_file_sha256(candidate) != expected_sha256
        ):
            raise RuntimeError(
                f"NOGO: SHA-256 du fichier modifié depuis l'analyse: {stored_name}"
            )

    if association_mode == "partial_vpsid" and not has_resolved_vpsid:
        raise RuntimeError(
            "NOGO: inventaire partiel sans aucun VPS-ID d'ancrage validé."
        )

    actual_names = {
        item.name.casefold()
        for item in batch_dir.iterdir()
        if item.is_file()
        and item.name != PINCABOS_SMART_IMPORT_RESOURCE_MANIFEST
    }

    if actual_names != seen_names:
        raise RuntimeError(
            "NOGO: le contenu du batch ne correspond plus exactement "
            "à l'inventaire VPS-ID analysé."
        )

    if any(
        item.is_symlink() or item.is_dir()
        for item in batch_dir.iterdir()
    ):
        raise RuntimeError(
            "NOGO: sous-dossier ou lien inattendu dans le batch analysé."
        )

    resource_index = pincabos_vpsdb_resource_index()

    if not resource_index:
        raise RuntimeError(
            "NOGO: VPSDB locale absente ou vide; les VPS-ID du batch "
            "ne peuvent pas être revérifiés."
        )

    for resource in payload["resources"]:
        vpsid = str(resource.get("vpsid", "") or "").strip()
        if not vpsid:
            continue

        expected = resource_index.get(vpsid.casefold(), [])

        if len(expected) != 1:
            raise RuntimeError(
                "NOGO: VPS-ID absent ou ambigu dans la VPSDB locale: "
                f"{vpsid}"
            )

        canonical = expected[0]

        if (
            str(resource.get("game_vpsid", "") or "").strip().casefold()
            != canonical["game_vpsid"].casefold()
            or str(resource.get("resource_type", "") or "").strip()
            != canonical["resource_type"]
        ):
            raise RuntimeError(
                "NOGO: type ou jeu VPSDB modifié depuis l'analyse pour "
                f"{vpsid}."
            )

    primary_table_vpsid = str(
        payload.get("primary_table_vpsid", "") or ""
    ).strip().casefold()

    if primary_table_vpsid and not any(
        str(resource.get("vpsid", "") or "").strip().casefold()
        == primary_table_vpsid
        and resource.get("resource_type") == "tableFile"
        for resource in payload["resources"]
    ):
        raise RuntimeError(
            "NOGO: tableFile principale absente de l'inventaire VPS-ID."
        )

    return payload


def pincabos_vpsdb_resource_index():
    cached = getattr(
        pincabos_vpsdb_resource_index,
        "_cache",
        None,
    )

    if cached is not None:
        return cached

    index = {}

    try:
        entries = json.loads(
            PINCABOS_VPSDB_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        entries = []

    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            game_vpsid = str(entry.get("id", "") or "").strip()
            if not game_vpsid:
                continue

            for resource_key, resource_type in (
                PINCABOS_VPSDB_RESOURCE_TYPES.items()
            ):
                for resource in entry.get(resource_key, []):
                    if not isinstance(resource, dict):
                        continue

                    vpsid = str(resource.get("id", "") or "").strip()
                    if not vpsid:
                        continue

                    index.setdefault(vpsid.casefold(), []).append({
                        "vpsid": vpsid,
                        "game_vpsid": game_vpsid,
                        "resource_type": resource_type,
                        "resource_key": resource_key,
                    })

    pincabos_vpsdb_resource_index._cache = index
    return index


def pincabos_vpsdb_id_to_game_map():
    cached = getattr(
        pincabos_vpsdb_id_to_game_map,
        "_cache",
        None,
    )

    if cached is not None:
        return cached

    mapping = {}

    try:
        entries = json.loads(
            PINCABOS_VPSDB_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        entries = []

    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            game_vpsid = str(entry.get("id", "") or "").strip()
            if not game_vpsid:
                continue

            mapping[game_vpsid.casefold()] = game_vpsid

            for key in PINCABOS_VPSDB_RESOURCE_KEYS:
                for resource in entry.get(key, []):
                    if not isinstance(resource, dict):
                        continue

                    resource_vpsid = str(resource.get("id", "") or "").strip()
                    if resource_vpsid:
                        mapping[resource_vpsid.casefold()] = game_vpsid

    pincabos_vpsdb_id_to_game_map._cache = mapping
    return mapping


def pincabos_manifest_game_vpsids(manifest):
    if not isinstance(manifest, dict):
        return set()

    values = set()
    direct = str(manifest.get("game_vpsid", "") or "").strip()

    if direct:
        values.add(direct.casefold())

    for resource in manifest.get("resources", []):
        if not isinstance(resource, dict):
            continue
        candidate = str(resource.get("game_vpsid", "") or "").strip()
        if candidate:
            values.add(candidate.casefold())

    legacy_vpsid = str(manifest.get("vpsid", "") or "").strip()
    if legacy_vpsid:
        mapped = pincabos_vpsdb_id_to_game_map().get(
            legacy_vpsid.casefold(),
            "",
        )
        if mapped:
            values.add(mapped.casefold())

    return values


def pincabos_find_existing_table_dir_by_game(game_vpsid, title):
    wanted = str(game_vpsid or "").strip().casefold()

    if not wanted:
        return pincabos_find_existing_table_dir(title)

    matches = []

    try:
        candidates = sorted(TABLES_ROOT.iterdir())
    except FileNotFoundError:
        candidates = []

    for candidate in candidates:
        if not candidate.is_dir() or candidate.is_symlink():
            continue

        manifest_path = candidate / "pincabos-table-manifest.json"
        manifest = {}

        if manifest_path.is_file():
            try:
                manifest = json.loads(
                    manifest_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )
                )
            except Exception:
                continue

        if wanted in pincabos_manifest_game_vpsids(manifest):
            matches.append(candidate)

    if len(matches) > 1:
        raise RuntimeError(
            "NOGO: plusieurs tables installées portent le même jeu VPSDB: "
            + " | ".join(str(item) for item in matches)
        )

    if matches:
        return matches[0]

    return pincabos_find_existing_table_dir(title)


def pincabos_read_existing_table_identity(
    table_dir,
):
    table_dir = Path(table_dir)

    result = {
        "vpsid": "",
        "title": table_dir.name,
        "manifest": {},
        "manifest_path": (
            table_dir
            / "pincabos-table-manifest.json"
        ),
        "info_path": None,
    }

    manifest_path = result["manifest_path"]
    manifest_vpsid = ""

    if manifest_path.is_file():
        try:
            manifest = json.loads(
                manifest_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

            if isinstance(manifest, dict):
                result["manifest"] = manifest

                manifest_vpsid = str(
                    manifest.get(
                        "vpsid",
                        "",
                    )
                    or ""
                ).strip()

                manifest_title = str(
                    manifest.get(
                        "title",
                        "",
                    )
                    or ""
                ).strip()

                if manifest_title:
                    result["title"] = (
                        manifest_title
                    )

        except Exception as exc:
            raise RuntimeError(
                "NOGO: manifest existant "
                f"illisible: {manifest_path}: "
                f"{exc}"
            )

    info_vpsid = ""

    for info_path in sorted(
        table_dir.glob("*.info")
    ):
        try:
            payload = json.loads(
                info_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

            info = (
                payload.get("Info", {})
                if isinstance(payload, dict)
                else {}
            )

            if not isinstance(info, dict):
                continue

            candidate_vpsid = str(
                info.get("VPSId", "")
                or ""
            ).strip()

            candidate_title = str(
                info.get("Title", "")
                or ""
            ).strip()

            if result["info_path"] is None:
                result["info_path"] = info_path

            if candidate_vpsid:
                info_vpsid = candidate_vpsid
                result["info_path"] = info_path

                if candidate_title:
                    result["title"] = (
                        candidate_title
                    )

                break

        except Exception:
            continue

    if (
        manifest_vpsid
        and info_vpsid
        and manifest_vpsid != info_vpsid
    ):
        raise RuntimeError(
            "NOGO: identité VPSId incohérente "
            "entre manifest et .info: "
            f"manifest={manifest_vpsid} "
            f"info={info_vpsid}"
        )

    result["vpsid"] = (
        manifest_vpsid
        or info_vpsid
    )

    return result


def pincabos_validate_existing_identity(
    table_dir,
    incoming_title,
    incoming_vpsid,
    parent_vpsid="",
    game_vpsid="",
    allow_missing_vpsid=False,
):
    identity = (
        pincabos_read_existing_table_identity(
            table_dir
        )
    )

    if (
        pincabos_table_identity_key(
            table_dir.name
        )
        != pincabos_table_identity_key(
            incoming_title
        )
    ):
        raise RuntimeError(
            "NOGO: le nom normalisé de la "
            "table existante ne correspond pas "
            "à l'import: "
            f"existant={table_dir.name!r} "
            f"entrant={incoming_title!r}"
        )

    existing_vpsid = str(
        identity.get("vpsid", "")
        or ""
    ).strip()

    incoming_vpsid = str(
        incoming_vpsid
        or ""
    ).strip()

    parent_vpsid = str(
        parent_vpsid
        or ""
    ).strip()

    game_vpsid = str(
        game_vpsid
        or ""
    ).strip()

    if allow_missing_vpsid and (
        not existing_vpsid or not incoming_vpsid
    ):
        identity["relation"] = "selected_target"
        return identity

    if not existing_vpsid:
        raise RuntimeError(
            "NOGO: table existante sans "
            "VPSId fiable. Mise à jour "
            "automatique refusée."
        )

    if not incoming_vpsid:
        raise RuntimeError(
            "NOGO: import entrant sans VPSId. "
            "Mise à jour automatique d'une "
            "table existante refusée."
        )

    if (
        existing_vpsid != incoming_vpsid
        and existing_vpsid != parent_vpsid
        and not (
            parent_vpsid
            and game_vpsid
            and existing_vpsid == game_vpsid
        )
    ):
        raise RuntimeError(
            "NOGO: même nom normalisé mais "
            "VPSId différent et aucune relation "
            "parent VPU Remix valide. "
            f"existant={existing_vpsid} "
            f"entrant={incoming_vpsid} "
            f"parent={parent_vpsid or '(aucun)'} "
            f"jeu={game_vpsid or '(aucun)'}"
        )

    if existing_vpsid == incoming_vpsid:
        identity["relation"] = "same"
    elif existing_vpsid == parent_vpsid:
        identity["relation"] = "vpu_parent"
    else:
        identity["relation"] = "vpu_game"

    return identity


def pincabos_safe_table_target(
    table_dir,
    relative,
):
    table_dir = Path(table_dir)
    relative = Path(relative)

    if (
        relative.is_absolute()
        or ".." in relative.parts
    ):
        raise RuntimeError(
            "NOGO: chemin relatif invalide: "
            f"{relative}"
        )

    root_real = table_dir.resolve()

    destination = (
        table_dir
        / relative
    )

    parent_real = (
        destination.parent.resolve()
    )

    if (
        parent_real != root_real
        and root_real
        not in parent_real.parents
    ):
        raise RuntimeError(
            "NOGO: destination hors table "
            f"détectée: {destination}"
        )

    if destination.is_symlink():
        raise RuntimeError(
            "NOGO: destination symlink "
            f"refusée: {destination}"
        )

    return destination


def pincabos_compare_staged_file(
    source,
    destination,
):
    source = Path(source)
    destination = Path(destination)

    if not destination.exists():
        return (
            "new",
            "destination absente",
        )

    if (
        not destination.is_file()
        or destination.is_symlink()
    ):
        raise RuntimeError(
            "NOGO: destination existante "
            f"non régulière: {destination}"
        )

    src_stat = source.stat()
    dst_stat = destination.stat()

    src_mtime = float(
        src_stat.st_mtime
    )

    dst_mtime = float(
        dst_stat.st_mtime
    )

    tolerance = (
        PINCABOS_SMART_IMPORT_MTIME_TOLERANCE
    )

    # 0/1 = date volontairement inconnue.
    if (
        src_mtime <= 1
        or dst_mtime <= 1
    ):
        same = (
            pincabos_file_sha256(source)
            == pincabos_file_sha256(
                destination
            )
        )

        if same:
            return (
                "identical",
                "date inconnue + "
                "SHA-256 identique",
            )

        return (
            "update",
            "date inconnue + "
            "SHA-256 différent",
        )

    if (
        src_mtime
        > dst_mtime + tolerance
    ):
        return (
            "update",
            "entrant plus récent",
        )

    if (
        src_mtime
        < dst_mtime - tolerance
    ):
        return (
            "older",
            "entrant plus vieux",
        )

    same = (
        pincabos_file_sha256(source)
        == pincabos_file_sha256(
            destination
        )
    )

    if same:
        return (
            "identical",
            "date équivalente + "
            "SHA-256 identique",
        )

    return (
        "update",
        "date équivalente + "
        "SHA-256 différent",
    )


def pincabos_build_staged_plan(
    staged_table,
    table_dir,
):
    staged_table = Path(staged_table)
    table_dir = Path(table_dir)

    staged_real = (
        staged_table.resolve()
    )

    plan = []

    for source in sorted(
        staged_table.rglob("*")
    ):
        if source.is_symlink():
            raise RuntimeError(
                "NOGO: symlink entrant "
                f"refusé: {source}"
            )

        if not source.is_file():
            continue

        relative = (
            source.resolve()
            .relative_to(staged_real)
        )

        destination = (
            pincabos_safe_table_target(
                table_dir,
                relative,
            )
        )

        action, reason = (
            pincabos_compare_staged_file(
                source,
                destination,
            )
        )

        plan.append({
            "action": action,
            "reason": reason,
            "source": source,
            "destination": destination,
            "relative": relative,
        })

    return plan


def pincabos_new_transaction(
    table_dir,
    existed_before,
):
    table_dir = Path(table_dir)

    backup_root = None

    if existed_before:
        stamp = time.strftime(
            "%Y%m%d-%H%M%S"
        )

        token = (
            f"{time.time_ns() % 1000000000:09d}"
        )

        backup_root = (
            PINCABOS_SMART_IMPORT_BACKUP_ROOT
            / (
                f"{stamp}-{token}-"
                f"{safe_name(table_dir.name)}"
            )
        )

        backup_root.mkdir(
            parents=True,
            exist_ok=False,
        )

    return {
        "table_dir": table_dir,
        "existed_before": bool(
            existed_before
        ),
        "backup_root": backup_root,
        "backed": {},
        "created_files": [],
        "created_dirs": [],
    }


def pincabos_tx_record_parent_dirs(
    transaction,
    destination,
):
    table_dir = Path(
        transaction["table_dir"]
    )

    root_real = (
        table_dir.resolve()
    )

    destination = Path(destination)
    current = destination.parent

    pending = []

    while True:
        current_real = (
            current.resolve()
        )

        if current_real == root_real:
            break

        if (
            root_real
            not in current_real.parents
        ):
            raise RuntimeError(
                "NOGO: parent hors table "
                "pendant transaction: "
                f"{current}"
            )

        if current.exists():
            break

        pending.append(current)
        current = current.parent

    for directory in reversed(
        pending
    ):
        if (
            directory
            not in transaction[
                "created_dirs"
            ]
        ):
            transaction[
                "created_dirs"
            ].append(directory)


def pincabos_tx_backup_existing(
    transaction,
    path,
):
    path = Path(path)

    if not path.exists():
        return

    if (
        path.is_symlink()
        or not path.is_file()
    ):
        raise RuntimeError(
            "NOGO: fichier de destination "
            f"non régulier: {path}"
        )

    table_dir = Path(
        transaction["table_dir"]
    ).resolve()

    relative = (
        path.resolve()
        .relative_to(table_dir)
    )

    key = relative.as_posix()

    if key in transaction["backed"]:
        return

    backup_root = transaction.get(
        "backup_root"
    )

    if backup_root is None:
        return

    backup_path = (
        backup_root
        / relative
    )

    backup_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        path,
        backup_path,
    )

    transaction["backed"][key] = (
        str(backup_path)
    )


def pincabos_tx_prepare_write(
    transaction,
    destination,
):
    destination = Path(destination)

    if destination.exists():
        pincabos_tx_backup_existing(
            transaction,
            destination,
        )
    else:
        pincabos_tx_record_parent_dirs(
            transaction,
            destination,
        )

        if (
            destination
            not in transaction[
                "created_files"
            ]
        ):
            transaction[
                "created_files"
            ].append(destination)


def pincabos_rollback_transaction(
    transaction,
):
    table_dir = Path(
        transaction["table_dir"]
    )

    if not transaction[
        "existed_before"
    ]:
        if table_dir.exists():
            shutil.rmtree(table_dir)

        return

    for created in reversed(
        transaction["created_files"]
    ):
        try:
            Path(created).unlink()
        except FileNotFoundError:
            pass
        except IsADirectoryError:
            pass

    for key, backup_name in (
        transaction["backed"].items()
    ):
        relative = Path(key)

        destination = (
            pincabos_safe_table_target(
                table_dir,
                relative,
            )
        )

        backup_path = Path(
            backup_name
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        copy_file(
            backup_path,
            destination.parent,
            destination.name,
        )

    for directory in sorted(
        transaction["created_dirs"],
        key=lambda item: len(
            Path(item).parts
        ),
        reverse=True,
    ):
        try:
            Path(directory).rmdir()
        except OSError:
            pass


def pincabos_apply_staged_plan(
    plan,
    transaction,
):
    stats = {
        "new": 0,
        "update": 0,
        "identical": 0,
        "older": 0,
    }

    for item in plan:
        action = item["action"]

        stats[action] += 1

        if action in {
            "identical",
            "older",
        }:
            log(
                f"{action.upper()}: "
                f"{item['relative']} "
                f"({item['reason']})"
            )
            continue

        destination = Path(
            item["destination"]
        )

        pincabos_tx_prepare_write(
            transaction,
            destination,
        )

        copy_file(
            item["source"],
            destination.parent,
            destination.name,
        )

        log(
            f"{action.upper()}: "
            f"{item['relative']} "
            f"({item['reason']})"
        )

    return stats


def pincabos_remap_installed_to_relative(
    installed,
    staged_table,
):
    staged_real = Path(
        staged_table
    ).resolve()

    out = {}

    for category, values in (
        installed or {}
    ).items():
        clean = []
        seen = set()

        for value in values:
            candidate = Path(
                str(value)
            )

            try:
                relative = (
                    candidate.resolve()
                    .relative_to(
                        staged_real
                    )
                )
            except Exception:
                continue

            portable = (
                relative.as_posix()
            )

            if (
                portable
                and portable not in seen
            ):
                seen.add(portable)
                clean.append(portable)

        out[category] = clean

    return out


def pincabos_merge_installed(
    existing_manifest,
    incoming_installed,
):
    merged = {}

    old_installed = {}

    if isinstance(
        existing_manifest,
        dict,
    ):
        candidate = (
            existing_manifest.get(
                "installed",
                {},
            )
        )

        if isinstance(
            candidate,
            dict,
        ):
            old_installed = candidate

    categories = (
        set(old_installed)
        | set(
            incoming_installed
            or {}
        )
    )

    for category in sorted(
        categories
    ):
        values = []
        seen = set()

        for source_values in (
            old_installed.get(
                category,
                [],
            ),
            (
                incoming_installed
                or {}
            ).get(
                category,
                [],
            ),
        ):
            if not isinstance(
                source_values,
                list,
            ):
                continue

            for value in source_values:
                portable = str(
                    value or ""
                ).strip().lstrip("/")

                if (
                    portable
                    and portable
                    not in seen
                ):
                    seen.add(portable)
                    values.append(
                        portable
                    )

        merged[category] = values

    return merged


PINCABOS_RESOURCE_INSTALLED_CATEGORIES = {
    "tableFile": ("root",),
    "b2sFile": ("root",),
    "romFile": ("pinmame_roms",),
    "pupPackFile": ("pupvideos", "fonts"),
    "altSoundFile": ("altsound",),
    "altColorFile": ("pinmame_altcolor",),
    "soundFile": ("music",),
    "povFile": ("root",),
    "mediaPackFile": ("medias",),
    "wheelArtFile": ("medias",),
    "topperFile": ("medias",),
    "ruleFile": ("extras",),
    "tutorialFile": ("extras",),
}


def pincabos_annotate_resource_inventory(
    resource_manifest,
    incoming_installed,
    plan,
):
    if not isinstance(resource_manifest, dict):
        return {}

    payload = json.loads(json.dumps(resource_manifest))
    accepted_paths = {
        Path(item["relative"]).as_posix()
        for item in plan
        if item.get("action") != "older"
    }
    older_paths = {
        Path(item["relative"]).as_posix()
        for item in plan
        if item.get("action") == "older"
    }

    for resource in payload.get("resources", []):
        if not isinstance(resource, dict):
            continue

        resource_installed = resource.get("_incoming_installed", {})
        categories = tuple(resource_installed) or (
            PINCABOS_RESOURCE_INSTALLED_CATEGORIES.get(
                str(resource.get("resource_type", "") or ""),
                ("extras",),
            )
        )
        candidates = []
        seen = set()

        for category in categories:
            for value in (resource_installed or {}).get(category, []):
                portable = str(value or "").strip().lstrip("/")
                if portable and portable not in seen:
                    seen.add(portable)
                    candidates.append(portable)

        installed_paths = [
            value
            for value in candidates
            if value in accepted_paths
        ]
        skipped_older_paths = [
            value
            for value in candidates
            if value in older_paths
        ]

        resource["installed_paths"] = installed_paths
        resource["installed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        if installed_paths:
            resource["install_status"] = "installed-or-identical"
        elif skipped_older_paths:
            resource["install_status"] = "older-input-kept-existing"
            resource["skipped_older_paths"] = skipped_older_paths
        else:
            raise RuntimeError(
                "NOGO: aucune destination installable n'a été produite "
                "pour la ressource VPSDB "
                f"{resource.get('vpsid', '(vide)')} "
                f"({resource.get('stored_name', 'fichier inconnu')})."
            )

        resource.pop("_extract_root", None)
        resource.pop("_staged_installed", None)
        resource.pop("_incoming_installed", None)

    return payload


def pincabos_merge_resource_inventory(
    previous_manifest,
    resource_manifest,
):
    merged = []
    positions = {}

    def append_or_replace(resource, incoming=False):
        if not isinstance(resource, dict):
            return

        if (
            incoming
            and resource.get("install_status")
            == "older-input-kept-existing"
        ):
            return

        resource_type = str(resource.get("resource_type", "") or "").strip()
        vpsid = str(resource.get("vpsid", "") or "").strip()

        if not resource_type or not vpsid:
            return

        key = (resource_type.casefold(), vpsid.casefold())
        clean = {
            field: resource[field]
            for field in (
                "vpsid",
                "game_vpsid",
                "resource_type",
                "resource_key",
                "version",
                "parent_vpsid",
                "parent_version",
                "features",
                "comment",
                "folder",
                "file_name",
                "table_format",
                "original_name",
                "stored_name",
                "sha256",
                "size",
                "client_mtime_ms",
                "contains_vpu_patch",
                "installed_paths",
                "installed_at",
                "install_status",
            )
            if resource.get(field) not in (None, "", [], {})
        }

        if key in positions:
            merged[positions[key]] = clean
        else:
            positions[key] = len(merged)
            merged.append(clean)

    if isinstance(previous_manifest, dict):
        for resource in previous_manifest.get("resources", []):
            append_or_replace(resource)

    if isinstance(resource_manifest, dict):
        for resource in resource_manifest.get("resources", []):
            append_or_replace(resource, incoming=True)

    return merged


def pincabos_atomic_write_json(
    path,
    payload,
):
    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tempfile.NamedTemporaryFile(
        prefix=(
            f".{path.name}."
            "pincabos-meta-"
        ),
        suffix=".tmp",
        dir=str(path.parent),
        delete=False,
        mode="w",
        encoding="utf-8",
    ) as handle:
        temporary = Path(
            handle.name
        )

        json.dump(
            payload,
            handle,
            indent=2,
            ensure_ascii=False,
        )

        handle.write("\n")
        handle.flush()

    try:
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def pincabos_write_transaction_record(
    transaction,
    stats,
    incoming_vpsid,
):
    backup_root = (
        transaction.get(
            "backup_root"
        )
    )

    if backup_root is None:
        return

    payload = {
        "table": str(
            transaction["table_dir"]
        ),
        "vpsid": str(
            incoming_vpsid or ""
        ),
        "created_at": (
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        ),
        "stats": stats,
        "backed_files": sorted(
            transaction["backed"]
        ),
        "created_files": [],
    }

    table_dir = Path(
        transaction["table_dir"]
    )

    for item in transaction[
        "created_files"
    ]:
        item = Path(item)

        try:
            payload[
                "created_files"
            ].append(
                str(
                    item.relative_to(
                        table_dir
                    )
                )
            )
        except Exception:
            pass

    pincabos_atomic_write_json(
        backup_root
        / "transaction.json",
        payload,
    )


def pincabos_log_update_summary(
    stats,
):
    log("")
    log(
        "================================"
        "=================="
    )
    log(
        " Résumé mise à jour "
        "Smart Import"
    )
    log(
        "================================"
        "=================="
    )

    log(
        f"{stats.get('new', 0)} nouveaux · "
        f"{stats.get('update', 0)} mis à jour · "
        f"{stats.get('identical', 0)} déjà à jour · "
        f"{stats.get('older', 0)} fichiers "
        "entrants plus vieux ignorés"
    )

# === PINCABOS_SMART_IMPORT_UPDATE_V1 END ===



def copy_dir_contents(src_dir, dest_dir):
    src_dir = Path(src_dir)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for f in sorted(src_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(src_dir)
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        copied.append(str(target))
        log(f"INSTALLÉ: {f} -> {target}")

    return copied

def extract_all_inputs(batch_dir, extract_root, resource_manifest=None):
    batch_dir = Path(batch_dir)
    extract_root = Path(extract_root)
    extract_root.mkdir(parents=True, exist_ok=True)

    resources_by_name = {}

    if isinstance(resource_manifest, dict):
        for index, resource in enumerate(resource_manifest.get("resources", [])):
            if not isinstance(resource, dict):
                continue

            stored_name = str(resource.get("stored_name", "") or "").strip()
            resource_root = (
                extract_root
                / (
                    f"resource_{index:03d}_"
                    f"{safe_name(resource.get('resource_type', 'file'))}_"
                    f"{safe_name(resource.get('vpsid', 'unknown'))}"
                )
            )
            resource_root.mkdir(parents=True, exist_ok=True)
            resource["_extract_root"] = str(resource_root)
            resource["_staged_installed"] = {}
            resources_by_name[stored_name.casefold()] = (resource, resource_root)

    raw_dir = extract_root / "_raw_files"

    if not resource_manifest:
        raw_dir.mkdir(parents=True, exist_ok=True)

    for item in sorted(batch_dir.rglob("*")):
        if not item.is_file():
            continue

        if item.name == PINCABOS_SMART_IMPORT_RESOURCE_MANIFEST:
            continue

        resource = None
        item_extract_root = extract_root
        item_raw_dir = raw_dir

        if resource_manifest:
            resolved = resources_by_name.get(item.name.casefold())

            if resolved is None:
                raise RuntimeError(
                    "NOGO: fichier absent de l’inventaire Smart Import analysé: "
                    f"{item.name}"
                )

            resource, item_extract_root = resolved
            item_raw_dir = item_extract_root / "_raw_files"
            item_raw_dir.mkdir(parents=True, exist_ok=True)

        suffix = item.suffix.lower()

        if suffix in ARCHIVE_EXTS:
            kind = archive_kind(item)

            if kind == "rom_zip":
                copy_file(item, item_raw_dir)
                continue

            dest = item_extract_root / ("archive_" + safe_name(item.stem))
            log("")
            log("==================================================")
            log(f"ARCHIVE: {item}")
            log(f"TYPE: {kind}")
            log("==================================================")
            try:
                extract_archive(item, dest)
            except RuntimeError as exc:
                # Une table chiffrée est bloquante. Les composants annexes
                # (AltSound, PuP, médias, VNI, etc.) sont ignorés proprement.
                if is_password_protected_error(exc) and kind not in {
                    "table_archive",
                    "vpu_patch_archive",
                }:
                    log(f"WARNING: ARCHIVE OPTIONNEL IGNORÉ — protégé par mot de passe: {item} | type={kind}")
                    continue
                raise
        else:
            copy_file(item, item_raw_dir)

    changed = True
    loop = 0

    while changed and loop < 6:
        changed = False
        loop += 1

        for item in sorted(extract_root.rglob("*")):
            if not item.is_file():
                continue

            if item.suffix.lower() not in ARCHIVE_EXTS:
                continue

            if item.name.startswith("already_extracted_"):
                continue

            kind = archive_kind(item)

            if kind == "rom_zip":
                continue

            dest = item.parent / ("nested_" + safe_name(item.stem))
            if dest.exists():
                continue

            log("")
            log(f"ARCHIVE INTERNE: {item}")
            log(f"TYPE INTERNE: {kind}")
            try:
                extract_archive(item, dest)
            except RuntimeError as exc:
                if is_password_protected_error(exc) and kind not in {
                    "table_archive",
                    "vpu_patch_archive",
                }:
                    log(f"WARNING: ARCHIVE INTERNE OPTIONNEL IGNORÉ — protégé par mot de passe: {item} | type={kind}")
                    item.rename(item.with_name("already_extracted_" + item.name))
                    changed = True
                    continue
                raise

            item.rename(item.with_name("already_extracted_" + item.name))
            changed = True

def choose_main_vpx(root):
    vpxs = [p for p in list_files(root) if p.suffix.lower() == ".vpx"]
    if not vpxs:
        return None
    vpxs.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
    return vpxs[0]


def pincabos_vpxtool_required_version():
    try:
        data = json.loads(
            PINCABOS_VPXTOOL_RELEASE_MANIFEST.read_text(
                encoding="utf-8"
            )
        )
        version = str(data.get("version") or "").strip().lstrip("v")
    except Exception as exc:
        raise RuntimeError(
            "NOGO: manifeste vpxtool absent ou illisible: "
            f"{PINCABOS_VPXTOOL_RELEASE_MANIFEST}"
        ) from exc

    if not re.fullmatch(r"\d+(?:\.\d+){2,3}", version):
        raise RuntimeError(
            "NOGO: version vpxtool invalide dans le manifeste: "
            f"{version!r}"
        )

    return version


def pincabos_find_vpxtool():
    required_version = pincabos_vpxtool_required_version()
    candidates = list(PINCABOS_VPXTOOL_CANDIDATES)
    discovered = shutil.which("vpxtool")

    if discovered:
        candidates.append(Path(discovered))

    seen = set()

    for candidate in candidates:
        candidate = Path(candidate)

        try:
            resolved = candidate.resolve(strict=True)
        except Exception:
            continue

        if resolved in seen:
            continue

        seen.add(resolved)

        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            continue

        version_result = run(
            [str(resolved), "--version"],
            timeout=30,
        )
        version_text = (
            (version_result.stdout or "")
            + "\n"
            + (version_result.stderr or "")
        ).strip()

        if (
            version_result.returncode == 0
            and f"v{required_version}" in version_text
        ):
            return resolved, version_text

    raise RuntimeError(
        "NOGO: moteur VPU Remix absent ou version invalide. "
        "PinCabOS requiert /opt/pincabos/bin/vpxtool "
        f"v{required_version}. "
        "Relancer : sudo -n /opt/pincabos/tools/pincabos-vpxtool-update "
        "--install"
    )


def pincabos_vpu_patch_files(root):
    return sorted(
        item
        for item in list_files(root)
        if (
            item.suffix.lower() == ".dif"
            and not should_skip_file(item)
        )
    )


def pincabos_vpu_select_base_vpx(
    extract_root,
    patch_path,
    existing_table_dir=None,
):
    extract_root = Path(extract_root)
    patch_path = Path(patch_path)

    bundled = sorted(
        item
        for item in list_files(extract_root)
        if (
            item.suffix.lower() == ".vpx"
            and not should_skip_file(item)
        )
    )

    if len(bundled) == 1:
        return bundled[0], "batch"

    if len(bundled) > 1:
        exact = [
            item
            for item in bundled
            if item.stem.casefold() == patch_path.stem.casefold()
        ]

        if len(exact) == 1:
            return exact[0], "batch"

        raise RuntimeError(
            "NOGO: plusieurs tables VPX sources dans le batch; "
            "la source du patch .dif est ambiguë: "
            + " | ".join(str(item) for item in bundled)
        )

    if existing_table_dir:
        existing_table_dir = Path(existing_table_dir)
        installed = sorted(
            item
            for item in existing_table_dir.glob("*.vpx")
            if item.is_file() and not item.is_symlink()
        )

        if len(installed) == 1:
            return installed[0], "installed_table"

        if len(installed) > 1:
            exact = [
                item
                for item in installed
                if item.stem.casefold() == patch_path.stem.casefold()
            ]

            if len(exact) == 1:
                return exact[0], "installed_table"

            raise RuntimeError(
                "NOGO: plusieurs VPX sont installés dans la table; "
                "la source du patch .dif est ambiguë: "
                + " | ".join(str(item) for item in installed)
            )

    raise RuntimeError(
        "NOGO: patch VPU Remix détecté, mais aucune table VPX "
        "source fiable n'est disponible. Importer la version parent "
        "exacte indiquée par VPSDB avant le patch, ou joindre cette "
        "table VPX au même batch."
    )


def pincabos_apply_vpu_patch(
    extract_root,
    existing_table_dir=None,
    existing_vpsid="",
    incoming_vpsid="",
    expected_parent_version="",
):
    patches = pincabos_vpu_patch_files(extract_root)

    if not patches:
        return None

    if len(patches) != 1:
        raise RuntimeError(
            "NOGO: PinCabOS accepte exactement un patch VPU Remix "
            "par import; patches détectés: "
            + " | ".join(str(item) for item in patches)
        )

    patch_path = patches[0]
    source_vpx, source_kind = pincabos_vpu_select_base_vpx(
        extract_root,
        patch_path,
        existing_table_dir=existing_table_dir,
    )

    if (
        source_kind == "installed_table"
        and existing_vpsid
        and incoming_vpsid
        and existing_vpsid == incoming_vpsid
    ):
        raise RuntimeError(
            "NOGO: ce VPSId de patch est déjà installé. "
            "PinCabOS refuse d'appliquer deux fois le même .dif."
        )

    vpxtool, engine_version = pincabos_find_vpxtool()
    output_dir = Path(extract_root) / "_pincabos_vpu_patch_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_vpx = output_dir / f"{safe_name(patch_path.stem)}.vpx"

    if output_vpx.exists():
        raise RuntimeError(
            f"NOGO: sortie VPU Remix déjà présente: {output_vpx}"
        )

    source_sha256 = pincabos_file_sha256(source_vpx)
    patch_sha256 = pincabos_file_sha256(patch_path)
    source_table_version = ""

    if source_kind == "installed_table" or expected_parent_version:
        source_info_result = run(
            [str(vpxtool), "info", "show", str(source_vpx)],
            timeout=180,
        )
        source_info_text = (
            (source_info_result.stdout or "")
            + "\n"
            + (source_info_result.stderr or "")
        ).strip()

        if (
            source_info_result.returncode != 0
            or "VPX Version:" not in source_info_text
        ):
            raise RuntimeError(
                "NOGO: la table source du patch n'est pas un VPX "
                "lisible par vpxtool"
                + (
                    f": {source_info_text[-3000:]}"
                    if source_info_text
                    else "."
                )
            )

        version_match = re.search(
            r"^\s*Version:\s*(.*?)\s*$",
            source_info_text,
            flags=re.MULTILINE,
        )

        if version_match:
            source_table_version = version_match.group(1).strip()

        if expected_parent_version:
            expected_key = re.sub(
                r"^v",
                "",
                str(expected_parent_version).strip().casefold(),
            )
            detected_key = re.sub(
                r"^v",
                "",
                source_table_version.casefold(),
            )

            if not detected_key or detected_key != expected_key:
                raise RuntimeError(
                    "NOGO: version VPX source incompatible avec le "
                    "parent VPSDB du patch. "
                    f"attendue={expected_parent_version} "
                    f"détectée={source_table_version or '(vide)'}"
                )

    log("")
    log("==================================================")
    log(" VPU Remix - reconstruction isolée")
    log("==================================================")
    log(f"SOURCE VPX             : {source_vpx}")
    log(f"SOURCE TYPE            : {source_kind}")
    log(f"SOURCE SHA256          : {source_sha256}")
    if source_table_version:
        log(f"SOURCE VERSION         : {source_table_version}")
    log(f"PATCH DIF              : {patch_path}")
    log(f"PATCH SHA256           : {patch_sha256}")

    patch_result = run(
        [
            str(vpxtool),
            "patch",
            str(source_vpx),
            str(patch_path),
            str(output_vpx),
        ],
        timeout=1800,
    )

    if patch_result.returncode != 0:
        detail = (
            (patch_result.stdout or "")
            + "\n"
            + (patch_result.stderr or "")
        ).strip()
        raise RuntimeError(
            "NOGO: vpxtool n'a pas pu appliquer le patch VPU Remix"
            + (f": {detail[-3000:]}" if detail else ".")
        )

    if not output_vpx.is_file() or output_vpx.stat().st_size < 4096:
        raise RuntimeError(
            "NOGO: la reconstruction VPU Remix est absente ou trop petite."
        )

    with output_vpx.open("rb") as handle:
        magic = handle.read(len(PINCABOS_VPX_OLE_MAGIC))

    if magic != PINCABOS_VPX_OLE_MAGIC:
        raise RuntimeError(
            "NOGO: la reconstruction n'est pas un conteneur VPX/OLE valide."
        )

    info_result = run(
        [str(vpxtool), "info", "show", str(output_vpx)],
        timeout=180,
    )
    info_text = (
        (info_result.stdout or "")
        + "\n"
        + (info_result.stderr or "")
    ).strip()

    if (
        info_result.returncode != 0
        or "VPX Version:" not in info_text
    ):
        raise RuntimeError(
            "NOGO: vpxtool ne peut pas relire la table reconstruite"
            + (f": {info_text[-3000:]}" if info_text else ".")
        )

    output_sha256 = pincabos_file_sha256(output_vpx)
    log(f"SORTIE VPX             : {output_vpx}")
    log(f"SORTIE SHA256          : {output_sha256}")
    log("VALIDATION VPX         : GO")

    return {
        "output_path": str(output_vpx),
        "engine": "vpxtool",
        "engine_version": engine_version,
        "source_kind": source_kind,
        "source_file": source_vpx.name,
        "source_sha256": source_sha256,
        "source_table_version": source_table_version,
        "patch_file": patch_path.name,
        "patch_sha256": patch_sha256,
        "output_file": output_vpx.name,
        "output_sha256": output_sha256,
    }

def read_text_script(path):
    path = Path(path)
    for enc in ("utf-8-sig", "utf-16", "utf-16-le", "latin-1"):
        try:
            data = path.read_text(encoding=enc, errors="ignore")
            if data.strip():
                return data
        except Exception:
            pass
    return ""


def extract_vbs_from_vpx(vpx_path, dest_dir=None):
    # PINCABOS_VBS_VPINFE_SOURCE_V1
    # VPinFE est la première vérité pour le chemin VPX.
    import os
    import re
    import shlex
    import shutil
    import subprocess

    vpx_path = Path(vpx_path)
    if not vpx_path.is_file() or vpx_path.suffix.lower() != ".vpx":
        return None

    dest_dir = Path(dest_dir) if dest_dir else vpx_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    expected_src_vbs = vpx_path.with_suffix(".vbs")
    final_vbs = dest_dir / (vpx_path.stem + ".vbs")

    if final_vbs.exists() and final_vbs.stat().st_size >= 1000:
        log(f"INFO: VBS déjà présent, extraction sautée: {final_vbs}")
        return final_vbs

    candidates = []

    def add_candidate(raw):
        value = str(raw or "").strip().strip("\"'")
        if not value:
            return

        try:
            parts = shlex.split(value)
        except Exception:
            parts = [value]

        if not parts:
            return

        candidate = Path(parts[0]).expanduser()

        if candidate not in candidates:
            candidates.append(candidate)

    # PINCABOS_VPX_BINARY_DISCOVERY_V2
    # VPinFE lance un wrapper; -ExtractVBS doit utiliser le vrai ELF.
    direct_candidates = []
    home = Path("/home/pinball")

    for pattern in (
        "VPinballX_BGFX-*/VPinballX_BGFX",
        "VPinballX-*/VPinballX",
        "VPinballX*/VPinballX_BGFX",
        "VPinballX*/VPinballX",
    ):
        for candidate in home.glob(pattern):
            try:
                if (
                    candidate.is_file()
                    and candidate not in direct_candidates
                ):
                    direct_candidates.append(candidate)
            except OSError:
                pass

    try:
        direct_candidates.sort(
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        pass

    for candidate in direct_candidates:
        add_candidate(candidate)

    for discovered_ini in (
        Path("/home/pinball/.config/vpinfe/vpinfe.ini"),
        Path("/opt/pincabos/config/vpinfe/vpinfe.ini"),
        Path("/opt/pinball/vpinfe/vpinfe.ini"),
    ):
        if not discovered_ini.is_file():
            continue

        ini_text = discovered_ini.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for line in ini_text.splitlines():
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            normalized = re.sub(
                r"[^a-z0-9]",
                "",
                key.lower(),
            )

            if normalized in {
                "vpxbinpath",
                "vpxbinarypath",
                "vpxexecutablepath",
            }:
                add_candidate(value)

    vpinfe_ini = Path("/opt/pincabos/config/vpinfe/vpinfe.ini")
    if vpinfe_ini.is_file():
        ini_text = vpinfe_ini.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for line in ini_text.splitlines():
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())

            if (
                "vpx" in normalized
                and "executable" in normalized
                and "path" in normalized
            ):
                add_candidate(value)

    launcher = Path("/opt/pincabos/scripts/VPXlauncher.sh")
    if launcher.is_file():
        launcher_text = launcher.read_text(
            encoding="utf-8",
            errors="replace",
        )

        for variable in ("VPX_MAIN", "VPX_EXECUTABLE", "VPX_BIN"):
            match = re.search(
                rf'^\s*{variable}=["\']([^"\']+)["\']',
                launcher_text,
                re.MULTILINE,
            )
            if match:
                add_candidate(match.group(1))

    for command in ("VPinballX_BGFX", "VPinballX-BGFX", "VPinballX"):
        found = shutil.which(command)
        if found:
            add_candidate(found)

    for root in (
        Path("/opt/pincabos/apps/vpinball"),
        Path("/opt/pincabos/vpinball"),
        Path("/home/pinball/vpinball"),
    ):
        if not root.is_dir():
            continue

        for pattern in ("VPinballX_BGFX", "VPinballX-BGFX", "VPinballX"):
            for candidate in root.rglob(pattern):
                add_candidate(candidate)

    valid = []
    for candidate in candidates:
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                valid.append(candidate)
        except OSError:
            pass

    if not valid:
        log("WARNING: aucun exécutable VPX valide trouvé.")
        return None

    for candidate in {expected_src_vbs, final_vbs}:
        try:
            if candidate.exists() and candidate.stat().st_size == 0:
                candidate.unlink()
        except OSError:
            pass

    runuser = shutil.which("runuser")
    attempts = []

    for vpxbin in valid:
        for switch in ("-ExtractVBS", "-extractvbs"):
            direct = [str(vpxbin), switch, str(vpx_path)]

            if os.geteuid() == 0:
                if not runuser:
                    continue

                cmd = [
                    runuser,
                    "-u",
                    "pinball",
                    "--",
                    "/usr/bin/env",
                    "HOME=/home/pinball",
                    "USER=pinball",
                    "LOGNAME=pinball",
                    "DISPLAY=:0",
                    "XAUTHORITY=/home/pinball/.Xauthority",
                    "XDG_RUNTIME_DIR=/run/user/1000",
                    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
                ] + direct
                env = None
            else:
                cmd = direct
                env = os.environ.copy()
                env.update(
                    {
                        "HOME": "/home/pinball",
                        "USER": "pinball",
                        "LOGNAME": "pinball",
                        "DISPLAY": ":0",
                        "XAUTHORITY": "/home/pinball/.Xauthority",
                        "XDG_RUNTIME_DIR": "/run/user/1000",
                        "DBUS_SESSION_BUS_ADDRESS": (
                            "unix:path=/run/user/1000/bus"
                        ),
                    }
                )

            log("$ " + " ".join(cmd))

            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(vpxbin.parent),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=180,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                attempts.append(f"{vpxbin.name} {switch}: timeout")
                continue
            except Exception as exc:
                attempts.append(f"{vpxbin.name} {switch}: {exc}")
                continue

            output = proc.stdout or ""
            for line in output.splitlines()[-80:]:
                log("extractvbs: " + line)

            attempts.append(
                f"{vpxbin.name} {switch}: rc={proc.returncode}"
            )

            extracted = None
            for candidate_vbs in (
                expected_src_vbs,
                vpx_path.parent / (vpx_path.stem + ".vbs"),
                Path.cwd() / (vpx_path.stem + ".vbs"),
            ):
                try:
                    if (
                        candidate_vbs.is_file()
                        and candidate_vbs.stat().st_size >= 1000
                    ):
                        extracted = candidate_vbs
                        break
                except OSError:
                    pass

            if extracted is None:
                continue

            if extracted.resolve() != final_vbs.resolve():
                shutil.copy2(extracted, final_vbs)

            if final_vbs.is_file() and final_vbs.stat().st_size >= 1000:
                log(
                    "VBS EXTRAIT OFFICIEL: "
                    f"{vpx_path} -> {final_vbs} "
                    f"({final_vbs.stat().st_size} bytes)"
                )
                return final_vbs

    log(
        "WARNING: extraction VBS impossible après essais: "
        + " | ".join(attempts[-20:])
    )
    return None



def detect_rom_from_script_text(script):
    script = str(script or "")

    # Détection robuste sans regex complexe:
    # cherche GameName, RomName, cGameName ou OptRom puis extrait la valeur entre quotes.
    keys = ("cGameName", "GameName", "RomName", "OptRom")

    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("'"):
            continue

        low = line.lower()

        for key in keys:
            k = key.lower()
            if k not in low:
                continue
            if "=" not in line:
                continue

            right = line.split("=", 1)[1].strip()

            # Enlever commentaires VBScript après la valeur si possible.
            if "'" in right:
                right = right.split("'", 1)[0].strip()

            if len(right) >= 2 and right[0] in ("'", '"'):
                quote = right[0]
                rest = right[1:]
                if quote in rest:
                    rom = rest.split(quote, 1)[0].strip()
                else:
                    rom = rest.strip()
            else:
                rom = right.split()[0].strip() if right.split() else ""

            rom = rom.strip().strip('"').strip("'").strip()

            if rom:
                return rom[:-4] if rom.lower().endswith(".zip") else rom

    return ""

def detect_rom_name(root, provided_rom="", main_vpx=None):
    provided_rom = str(provided_rom or "").strip()
    if provided_rom:
        return provided_rom[:-4] if provided_rom.lower().endswith(".zip") else provided_rom

    for vbs in sorted([p for p in list_files(root) if p.suffix.lower() == ".vbs"], key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True):
        rom = detect_rom_from_script_text(read_text_script(vbs))
        if rom:
            log(f"ROM détectée depuis VBS: {rom} ({vbs})")
            return rom

    if main_vpx:
        tmp_vbs = extract_vbs_from_vpx(main_vpx, Path(root) / "_raw_files")
        if tmp_vbs:
            rom = detect_rom_from_script_text(read_text_script(tmp_vbs))
            if rom:
                log(f"ROM détectée depuis VPX/VBS extrait: {rom}")
                return rom

    roms = []
    for p in list_files(root):
        if p.suffix.lower() == ".zip" and archive_kind(p) == "rom_zip":
            roms.append(p)
    if roms:
        roms.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)
        return roms[0].stem
    return ""



# PINCABOS_PUP_ROM_FIRST_V1
def safe_pup_pack_folder_name(value):
    """
    Conserve le nom exact demandé par le script PuP, mais refuse
    tout élément qui pourrait sortir de pupvideos/.
    """
    name = str(value or "").strip()

    if not name:
        return ""

    if name in {".", ".."} or "\x00" in name:
        log(f"WARNING: nom PuP invalide refusé: {name!r}")
        return ""

    if "/" in name or "\\" in name:
        log(f"WARNING: nom PuP avec séparateur refusé: {name!r}")
        return ""

    return name


def detect_pup_name_from_script_text(script):
    """
    Détecte le nom du dossier PuP demandé par le script VPX.

    Priorité :
      1. Nom littéral dans PuPlayer.B2SInit.
      2. pGameName / PuPGameName / PUPPackName.
      3. pGameName = cGameName / GameName / RomName.

    Un nom n'est accepté que si le script utilise réellement PuP.
    """
    import re

    script = str(script or "")
    low_script = script.lower()

    has_pup = (
        "pinupplayer.pindisplay" in low_script
        or "puplayer.b2sinit" in low_script
        or "puplayer.b2sdata" in low_script
        or "pupinit" in low_script
    )

    if not has_pup:
        return ""

    direct = re.search(
        r'(?im)\bPuPlayer\.B2SInit\s+""\s*,\s*"([^"]+)"',
        script,
    )

    if direct:
        return safe_pup_pack_folder_name(direct.group(1))

    keys = ("pGameName", "PuPGameName", "PUPPackName")

    for raw_line in script.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("'"):
            continue

        code = line.split("'", 1)[0].strip()

        for key in keys:
            pattern = (
                r'(?i)\b'
                + re.escape(key)
                + r'\b\s*=\s*"([^"]+)"'
            )

            match = re.search(pattern, code)

            if match:
                name = safe_pup_pack_folder_name(match.group(1))
                if name:
                    return name

    # Cas fréquent : pGameName = cGameName.
    for raw_line in script.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("'"):
            continue

        code = line.split("'", 1)[0].strip()

        match = re.search(
            r'(?i)\bpGameName\b\s*=\s*'
            r'(cGameName|GameName|RomName|OptRom)\b',
            code,
        )

        if match:
            return safe_pup_pack_folder_name(
                detect_rom_from_script_text(script)
            )

    return ""


def read_table_script_for_identity(root, main_vpx=None):
    """
    Lit d'abord un VBS fourni. À défaut, extrait temporairement le script
    de la table principale sans contaminer l'arbre d'import.
    """
    import tempfile

    root = Path(root)
    candidates = []
    seen = set()

    def add_candidate(path):
        path = Path(path)

        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)

        if key in seen or not path.is_file():
            return

        seen.add(key)
        candidates.append(path)

    if main_vpx:
        main_vpx = Path(main_vpx)
        add_candidate(main_vpx.with_suffix(".vbs"))

        for candidate in sorted(
            root.rglob(main_vpx.stem + ".vbs"),
            key=lambda item: item.stat().st_size if item.exists() else 0,
            reverse=True,
        ):
            add_candidate(candidate)

    for candidate in sorted(
        [p for p in root.rglob("*.vbs") if p.is_file()],
        key=lambda item: item.stat().st_size if item.exists() else 0,
        reverse=True,
    ):
        add_candidate(candidate)

    for candidate in candidates:
        script = read_text_script(candidate)

        if script:
            return script, candidate

    if main_vpx:
        with tempfile.TemporaryDirectory(
            prefix="pincabos-identity-vbs-"
        ) as temp_dir:
            extracted = extract_vbs_from_vpx(
                main_vpx,
                Path(temp_dir),
            )

            if extracted:
                script = read_text_script(extracted)

                if script:
                    return script, Path(extracted)

    return "", None


def detect_import_identity(root, provided_rom="", main_vpx=None):
    """
    Première analyse Smart Import :
    ROM et PuP sont déterminés avant toute installation/copie.
    """
    provided_rom = str(provided_rom or "").strip()
    script, script_path = read_table_script_for_identity(root, main_vpx)

    script_rom = detect_rom_from_script_text(script) if script else ""
    pup_pack = detect_pup_name_from_script_text(script) if script else ""

    if provided_rom:
        rom = (
            provided_rom[:-4]
            if provided_rom.lower().endswith(".zip")
            else provided_rom
        )

        if script_rom and script_rom.lower() != rom.lower():
            log(
                "WARNING: ROM fournie manuellement différente du script: "
                f"manuel={rom} script={script_rom}"
            )
    else:
        rom = script_rom or detect_rom_name(
            root,
            "",
            main_vpx=main_vpx,
        )

    if script_path:
        log(f"Analyse script         : {script_path}")
    else:
        log("WARNING: aucun script lisible pour analyse ROM/PuP.")

    log(f"ROM pré-analysée        : {rom or '(aucune)'}")

    if pup_pack:
        log(
            "PuP-Pack pré-analysé   : "
            f"{pup_pack} -> pupvideos/{pup_pack}/"
        )
    elif script:
        log(
            "WARNING: script sans nom PuP explicite; "
            "aucun dossier PuP ne sera inventé."
        )

    return {
        "rom": rom,
        "pup_pack": pup_pack,
        "script_path": str(script_path) if script_path else "",
    }


def ensure_table_tree(table_dir):
    """
    Structure portable officielle PinCabOS, autonome par table.

    Aucun contenu PinMAME/AltSound/AltColor n'est installé globalement.
    """
    table_dir = Path(table_dir)

    for rel in (
        "pinmame/roms",
        "pinmame/altcolor",
        "pinmame/altsound",
        "pinmame/ini",
        "pinmame/cfg",
        "pinmame/nvram",
        "pupvideos",
        "music",
        "ultradmd",
        "fonts",
        "medias",
        "extras",
    ):
        (table_dir / rel).mkdir(parents=True, exist_ok=True)

    return table_dir

def normalize_media_name(src):
    p = Path(src)
    name = p.name.lower()
    suffix = p.suffix.lower()

    if "wheel" in name:
        return "wheel" + suffix

    if "backglass" in name or "background" in name or name.startswith("bg") or "(backglass)" in name:
        return "bg" + suffix

    if "realdmd" in name or "real-dmd" in name or "(realdmd)" in name:
        return "realdmd" + suffix

    if "fulldmd" in name or "dmd" in name or "(dmd)" in name:
        return "dmd" + suffix

    if "flyer" in name:
        return "flyer" + suffix

    if "cab" in name or "cabinet" in name:
        return "cab" + suffix

    if "playfield" in name or "(playfield)" in name:
        if suffix in VIDEO_EXTS:
            return "table" + suffix
        if suffix in IMAGE_EXTS:
            return "table" + suffix

    if suffix in AUDIO_EXTS and ("audio" in name or "music" in name or "theme" in name):
        return "audio" + suffix

    return p.name


def find_literal_pupvideos_dirs(root):
    """
    Règle PinCabOS:
    Si l'archive contient un dossier nommé pupvideos / PupVideos,
    on copie son contenu tel quel dans <table>/pupvideos/.
    On ne renomme pas, on ne classe pas, on ne touche pas à ce qu'il y a dedans.
    """
    root = Path(root)
    found = []

    for d in sorted(root.rglob("*")):
        if not d.is_dir():
            continue

        if d.name.lower() != "pupvideos":
            continue

        # Ne jamais prendre un dossier temporaire créé par l'importeur comme racine logique.
        if any(is_temp_name(part) for part in d.parts):
            # On permet quand même archive_xxx/.../pupvideos, car archive_xxx est notre extract container.
            # Le dossier important est le dossier pupvideos lui-même.
            pass

        found.append(d)

    # Garder seulement les pupvideos les plus hauts.
    final = []
    for d in found:
        if any(parent in found for parent in d.parents):
            continue
        final.append(d)

    return final


def looks_like_pup_dir(d):
    """
    Reconnaît uniquement la vraie racine d'un PupPack.

    Important : ne pas utiliser une recherche récursive ici, sinon le
    dossier parent d'une archive peut être pris pour le PupPack et toute
    la table risque d'être copiée dans pupvideos/.
    """
    d = Path(d)

    if is_temp_name(d.name) or not d.is_dir():
        return False

    direct_files = [p for p in d.iterdir() if p.is_file()]
    direct_dirs = {p.name.lower() for p in d.iterdir() if p.is_dir()}
    names = {p.name.lower() for p in direct_files}
    lname = d.name.lower()

    if "pinupplayer.ini" in names or "screens.pup" in names:
        return True

    if any(p.suffix.lower() == ".pup" for p in direct_files):
        return True

    pup_asset_dirs = {"fonts", "pupalphas", "pupoverlays"}
    if "pup" in lname and direct_dirs.intersection(pup_asset_dirs):
        return True

    return False


def looks_like_music_dir(d):
    d = Path(d)
    if is_temp_name(d.name):
        return False

    lname = d.name.lower()
    files = list_files(d)
    audio_count = sum(1 for x in files if x.suffix.lower() in AUDIO_EXTS)

    if lname == "music":
        return audio_count >= 1

    return False


def looks_like_altsound_dir(d):
    d = Path(d)
    if is_temp_name(d.name):
        return False

    files = list_files(d)
    names = {x.name.lower() for x in files}

    if "altsound.ini" in names or "altsound.csv" in names:
        return True

    audio_count = sum(1 for x in files if x.suffix.lower() in AUDIO_EXTS)
    return audio_count >= 10 and "alt" in d.name.lower()

def looks_like_ultradmd_dir(d):
    d = Path(d)
    if is_temp_name(d.name):
        return False

    lname = d.name.lower()
    files = list_files(d)
    names = {x.name.lower() for x in files}

    if lname.endswith(".ultradmd"):
        return True

    if "ultradmd" in lname or "flexdmd" in lname:
        return True

    if any("ultradmd" in n or "flexdmd" in n for n in names):
        return True

    return False

def find_roots(root, predicate):
    candidates = []

    for d in sorted(list_dirs(root)):
        if predicate(d):
            candidates.append(d)

    final = []
    for d in candidates:
        if any(parent in candidates for parent in d.parents):
            continue
        final.append(d)

    return final

def best_plugin_folder_name(d, fallback):
    d = Path(d)
    n = safe_name(d.name)
    if n and not is_temp_name(n) and n.lower() not in {"pupvideos", "pupvideo", "puppack", "pup-pack", "altsound"}:
        return n
    return safe_name(fallback)

def detect_ultradmd_folder_name(ultra_roots, table_title):
    for d in ultra_roots:
        n = safe_name(d.name)
        if is_temp_name(n):
            continue
        if n.lower().endswith(".ultradmd"):
            return n
        if "ultradmd" in n.lower() or "flexdmd" in n.lower():
            return n
    return safe_name(table_title) + ".UltraDMD"

def should_skip_file(f):
    text = str(f).lower()
    return "/already_extracted_" in text


def classify_and_install(
    extract_root,
    table_dir,
    rom,
    pup_pack="",
    main_vpx=None,
    resource_manifest=None,
):
    # PINCABOS_PORTABLE_LAYOUT_V2
    #
    # Une table est entièrement autonome :
    #
    #   <Table>/
    #     <Table>.vpx
    #     <Table>.directb2s
    #     fonts/
    #     pinmame/
    #       roms/
    #       altcolor/<ROM>/
    #       altsound/<ROM>/
    #
    # Aucun dossier racine altsound/, serum/, vni/ ou altcolor/ n'est utilisé.

    extract_root = Path(extract_root)
    table_dir = Path(table_dir)
    ensure_table_tree(table_dir)

    table_title = safe_name(table_dir.name)
    rom_name = safe_name(rom or table_title)

    pup_pack_name = safe_pup_pack_folder_name(pup_pack)
    pup_target = table_dir / "pupvideos"

    if pup_pack_name:
        pup_target = pup_target / pup_pack_name
        log(
            "PuP destination script  : "
            f"{pup_target}"
        )
    else:
        log(
            "WARNING: PuP sans nom détecté; "
            "conservation dans pupvideos/ sans sous-dossier inventé."
        )

    installed = {
        "root": [],
        "fonts": [],
        "pupvideos": [],
        "music": [],
        "altsound": [],
        "ultradmd": [],
        "pinmame_roms": [],
        "pinmame_altcolor": [],
        "pinmame_ini": [],
        "pinmame_cfg": [],
        "pinmame_nvram": [],
        "pinmame_alias": [],
        "medias": [],
        "extras": [],
    }

    resource_rows = (
        resource_manifest.get("resources", [])
        if isinstance(resource_manifest, dict)
        else []
    )
    preferred_vpx = Path(main_vpx).resolve() if main_vpx else None
    primary_table_vpsid = str(
        (
            resource_manifest.get("primary_table_vpsid", "")
            if isinstance(resource_manifest, dict)
            else ""
        )
        or ""
    ).strip().casefold()

    def resource_for_source(source):
        try:
            source_resolved = Path(source).resolve()
        except Exception:
            return None

        for resource in resource_rows:
            if not isinstance(resource, dict):
                continue

            root_value = str(resource.get("_extract_root", "") or "").strip()
            if not root_value:
                continue

            try:
                source_resolved.relative_to(Path(root_value).resolve())
                return resource
            except Exception:
                continue

        if preferred_vpx and source_resolved == preferred_vpx:
            for resource in resource_rows:
                if (
                    isinstance(resource, dict)
                    and str(resource.get("resource_type", "") or "")
                    == "tableFile"
                    and str(resource.get("vpsid", "") or "").strip().casefold()
                    == primary_table_vpsid
                ):
                    return resource

        return None

    copied = set()

    def put(category, source, destination, new_name=None, owner_resource=None):
        source = Path(source)
        destination = Path(destination)

        try:
            source_key = str(source.resolve())
        except Exception:
            source_key = str(source)

        final_name = str(new_name or source.name)
        key = (source_key, str(destination), final_name)

        if key in copied:
            return None

        copied.add(key)
        result = copy_file(source, destination, final_name)
        installed[category].append(str(result))

        owner = owner_resource or resource_for_source(source)
        if isinstance(owner, dict):
            staged = owner.setdefault("_staged_installed", {})
            staged.setdefault(category, []).append(str(result))

        return result

    def copy_tree(
        category,
        source_dir,
        destination_dir,
        fonts_to_table=True,
        owner_resource=None,
    ):
        source_dir = Path(source_dir)
        destination_dir = Path(destination_dir)

        for item in sorted(source_dir.rglob("*")):
            if not item.is_file():
                continue

            if should_skip_file(item):
                continue

            suffix = item.suffix.lower()

            # Les fonts doivent toujours rester directement dans <table>/fonts/.
            if fonts_to_table and suffix in FONT_EXTS:
                put(
                    "fonts",
                    item,
                    table_dir / "fonts",
                    item.name,
                    owner_resource=owner_resource,
                )
                continue

            relative = item.relative_to(source_dir)
            put(
                category,
                item,
                destination_dir / relative.parent,
                relative.name,
                owner_resource=owner_resource,
            )

    excluded_dirs = set()

    def resource_content_root(resource_root, folder=""):
        current = Path(resource_root)
        wanted_folder = str(folder or "").strip().casefold()

        for _unused in range(5):
            if looks_like_pup_dir(current):
                break

            if wanted_folder and current.name.casefold() == wanted_folder:
                break

            children = [
                item
                for item in current.iterdir()
                if (
                    item.is_dir()
                    and not item.is_symlink()
                    and any(
                        candidate.is_file()
                        and not should_skip_file(candidate)
                        for candidate in item.rglob("*")
                    )
                )
            ]
            direct_files = [
                item
                for item in current.iterdir()
                if item.is_file() and not should_skip_file(item)
            ]

            if direct_files or len(children) != 1:
                break

            current = children[0]

        return current

    # Les types VPSDB auxiliaires pilotent directement leur destination.
    # Le classificateur historique reste ensuite actif pour tableFile, B2S,
    # ROM, POV et les fichiers non couverts.
    for resource in resource_rows:
        if not isinstance(resource, dict):
            continue

        resource_type = str(resource.get("resource_type", "") or "").strip()
        resource_root_value = str(resource.get("_extract_root", "") or "").strip()

        if not resource_root_value:
            continue

        resource_root = Path(resource_root_value)
        if not resource_root.is_dir():
            continue

        db_folder = safe_name(resource.get("folder", ""))
        content_root = resource_content_root(resource_root, db_folder)

        if resource_type == "pupPackFile":
            destination_name = (
                db_folder
                or pup_pack_name
                or safe_pup_pack_folder_name(content_root.name)
                or table_title
            )
            destination = (
                table_dir
                / "pupvideos"
                / safe_pup_pack_folder_name(destination_name)
            )
            log(
                "PuP destination VPSDB   : "
                f"{content_root} -> {destination}"
            )
            copy_tree(
                "pupvideos",
                content_root,
                destination,
                fonts_to_table=False,
                owner_resource=resource,
            )

            for font in sorted(content_root.rglob("*")):
                if font.is_file() and font.suffix.lower() in FONT_EXTS:
                    put(
                        "fonts",
                        font,
                        table_dir / "fonts",
                        font.name,
                        owner_resource=resource,
                    )

            excluded_dirs.add(resource_root.resolve())

        elif resource_type == "altSoundFile":
            destination = (
                table_dir
                / "pinmame"
                / "altsound"
                / safe_name(db_folder or rom_name)
            )
            copy_tree(
                "altsound",
                content_root,
                destination,
                owner_resource=resource,
            )
            excluded_dirs.add(resource_root.resolve())

        elif resource_type == "altColorFile":
            destination = (
                table_dir
                / "pinmame"
                / "altcolor"
                / safe_name(db_folder or rom_name)
            )
            copy_tree(
                "pinmame_altcolor",
                content_root,
                destination,
                owner_resource=resource,
            )
            excluded_dirs.add(resource_root.resolve())

    # 1) PuP : vraie racine avant un sous-dossier PupVideos.
    # PINCABOS_PUP_ROOT_FIRST_V1
    true_pup_roots = []

    for candidate in find_roots(extract_root, looks_like_pup_dir):
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate

        if any(
            root == resolved or root in resolved.parents
            for root in excluded_dirs
        ):
            continue

        if resolved not in true_pup_roots:
            true_pup_roots.append(resolved)

    highest_pup_roots = []
    for candidate in true_pup_roots:
        if any(
            other != candidate and other in candidate.parents
            for other in true_pup_roots
        ):
            continue
        highest_pup_roots.append(candidate)

    def pup_root_score(candidate):
        score = 0
        name = candidate.name.casefold()

        if pup_pack_name and name == pup_pack_name.casefold():
            score += 1000000

        direct_names = {
            item.name.casefold()
            for item in candidate.iterdir()
            if item.is_file()
        }

        if "screens.pup" in direct_names:
            score += 500000
        if "playlists.pup" in direct_names:
            score += 100000
        if "triggers.pup" in direct_names:
            score += 50000

        try:
            score += min(
                sum(
                    1
                    for item in candidate.rglob("*")
                    if item.is_file()
                ),
                40000,
            )
        except Exception:
            pass

        return score

    if highest_pup_roots:
        highest_pup_roots.sort(
            key=pup_root_score,
            reverse=True,
        )
        pup_source = highest_pup_roots[0]
        destination_name = (
            pup_pack_name
            or best_plugin_folder_name(pup_source, table_title)
        )
        destination = (
            table_dir
            / "pupvideos"
            / safe_pup_pack_folder_name(destination_name)
        )

        log(
            "PuP vraie racine       : "
            f"{pup_source} -> {destination}"
        )

        copy_tree(
            "pupvideos",
            pup_source,
            destination,
            fonts_to_table=False,
        )

        for font in sorted(pup_source.rglob("*")):
            if font.is_file() and font.suffix.lower() in FONT_EXTS:
                put("fonts", font, table_dir / "fonts", font.name)

        excluded_dirs.add(pup_source.resolve())

        for ignored in highest_pup_roots[1:]:
            log(
                "WARNING: autre racine PuP ignorée pour éviter "
                f"un mélange de packs: {ignored}"
            )
            excluded_dirs.add(ignored.resolve())
    else:
        literal_pupvideos_dirs = find_literal_pupvideos_dirs(
            extract_root
        )

        for wrapper in literal_pupvideos_dirs:
            source = wrapper
            destination = table_dir / "pupvideos"

            if pup_pack_name:
                matches = [
                    child
                    for child in wrapper.iterdir()
                    if (
                        child.is_dir()
                        and child.name.casefold()
                        == pup_pack_name.casefold()
                    )
                ]

                if len(matches) == 1:
                    source = matches[0]

                destination = (
                    table_dir
                    / "pupvideos"
                    / pup_pack_name
                )

            copy_tree(
                "pupvideos",
                source,
                destination,
                fonts_to_table=False,
            )
            excluded_dirs.add(wrapper.resolve())

    # 3) Musique par table.
    for music_dir in find_roots(extract_root, looks_like_music_dir):
        resolved = music_dir.resolve()
        if any(root == resolved or root in resolved.parents for root in excluded_dirs):
            continue
        copy_tree("music", music_dir, table_dir / "music")
        excluded_dirs.add(resolved)

    # 4) AltSound exclusivement dans pinmame/altsound/<ROM>/.
    altsound_target = table_dir / "pinmame" / "altsound" / rom_name
    for altsound_dir in find_roots(extract_root, looks_like_altsound_dir):
        resolved = altsound_dir.resolve()
        if any(root == resolved or root in resolved.parents for root in excluded_dirs):
            continue
        copy_tree("altsound", altsound_dir, altsound_target)
        excluded_dirs.add(resolved)

    # 5) UltraDMD par table.
    ultra_roots = find_roots(extract_root, looks_like_ultradmd_dir)
    ultra_name = detect_ultradmd_folder_name(ultra_roots, table_title)
    for ultra in ultra_roots:
        resolved = ultra.resolve()
        if any(root == resolved or root in resolved.parents for root in excluded_dirs):
            continue
        copy_tree("ultradmd", ultra, table_dir / "ultradmd" / ultra_name)
        excluded_dirs.add(resolved)

    all_files = sorted(list_files(extract_root))

    # Le VPX et le B2S principal sont toujours renommés selon le titre final.
    vpx_files = [f for f in all_files if f.suffix.lower() == ".vpx"]
    vpx_files.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)

    if preferred_vpx:
        preferred_matches = [
            item
            for item in vpx_files
            if item.resolve() == preferred_vpx
        ]

        if len(preferred_matches) != 1:
            raise RuntimeError(
                "NOGO: le VPX principal validé n'est plus présent "
                f"dans le staging: {preferred_vpx}"
            )

        vpx_files.remove(preferred_matches[0])
        vpx_files.insert(0, preferred_matches[0])

    if vpx_files:
        put("root", vpx_files[0], table_dir, f"{table_title}.vpx")

    b2s_files = [f for f in all_files if f.suffix.lower() == ".directb2s"]
    b2s_files.sort(key=lambda p: p.stat().st_size if p.exists() else 0, reverse=True)

    if b2s_files:
        put("root", b2s_files[0], table_dir, f"{table_title}.directb2s")

    vpx_stems = {f.stem.lower() for f in vpx_files}
    if vpx_files:
        vpx_stems.add(table_title.lower())

    for f in all_files:
        if not f.is_file() or should_skip_file(f):
            continue

        suffix = f.suffix.lower()

        # Font = toujours <table>/fonts/, même si elle provient d'un dossier PUP.
        if suffix in FONT_EXTS:
            put("fonts", f, table_dir / "fonts", f.name)
            continue

        try:
            parent_resolved = f.parent.resolve()
        except Exception:
            parent_resolved = f.parent

        if any(root == parent_resolved or root in parent_resolved.parents for root in excluded_dirs):
            continue

        # Déjà traité comme table/B2S principal.
        if suffix == ".vpx" or suffix == ".directb2s":
            continue

        path_parts = {part.lower() for part in f.parts}
        filename_lower = f.name.lower()

        # AltSound identifié même lorsqu'il est livré sans archive dédiée.
        if (
            "altsound" in path_parts
            or filename_lower in {"altsound.ini", "altsound.csv"}
        ):
            put("altsound", f, altsound_target, f.name)
            continue

        # Toutes les variantes AltColor/Serum vont au même endroit autonome.
        if suffix in (VNI_EXTS | SERUM_EXTS | ALTCOLOR_MISC_EXTS):
            put(
                "pinmame_altcolor",
                f,
                table_dir / "pinmame" / "altcolor" / rom_name,
                f.name,
            )
            continue

        # ROM PinMAME.
        if suffix == ".zip" and archive_kind(f) == "rom_zip":
            put("pinmame_roms", f, table_dir / "pinmame" / "roms", f.name)
            continue

        # VBS associé à la table.
        if suffix == ".vbs":
            put("root", f, table_dir, f"{table_title}.vbs")
            continue

        # Fichiers VPX associés.
        if suffix in {".scv", ".pov", ".res"}:
            put("root", f, table_dir, f.name)
            continue

        # Configurations PinMAME.
        if suffix == ".ini":
            if (
                vpx_files
                and f.stem.casefold()
                == vpx_files[0].stem.casefold()
            ):
                put("root", f, table_dir, f"{table_title}.ini")
            elif f.stem.lower() in vpx_stems:
                put("root", f, table_dir, f.name)
            elif rom and f.stem.lower().startswith(str(rom).lower()):
                put("pinmame_ini", f, table_dir / "pinmame" / "ini", f.name)
            else:
                put("extras", f, table_dir / "extras", f.name)
            continue

        if suffix in PINMAME_CFG_EXTS:
            put("pinmame_cfg", f, table_dir / "pinmame" / "cfg", f.name)
            continue

        if suffix in PINMAME_NVRAM_EXTS:
            put("pinmame_nvram", f, table_dir / "pinmame" / "nvram", f.name)
            continue

        if suffix in {".dat", ".txt"} and rom and f.stem.lower().startswith(str(rom).lower()):
            put("pinmame_alias", f, table_dir / "pinmame", f.name)
            continue

        # Médias restant : PUP, UltraDMD, musique ou médias généraux.
        if suffix in AUDIO_EXTS:
            put("music", f, table_dir / "music", f.name)
            continue

        if suffix in VIDEO_EXTS or suffix in IMAGE_EXTS:
            if "pup" in path_parts or "pinup" in path_parts:
                put("pupvideos", f, pup_target, f.name)
            elif "ultradmd" in path_parts:
                put("ultradmd", f, table_dir / "ultradmd" / ultra_name, f.name)
            else:
                put("medias", f, table_dir / "medias", normalize_media_name(f))
            continue

        # Archives non reconnues et documents : extras par table.
        put("extras", f, table_dir / "extras", f.name)

    return installed

def write_info_and_manifest(
    table_dir,
    title,
    manufacturer,
    year,
    rom,
    vpsid,
    ipdbid,
    installed,
    info_path_override=None,
    existing_manifest=None,
    patch_info=None,
    resource_manifest=None,
):
    # PINCABOS_MANIFEST_RELATIVE_PATHS_V1
    # PINCABOS_SMART_IMPORT_UPDATE_V1

    table_dir = Path(table_dir)
    table_resolved = table_dir.resolve()

    normalized_installed = {}

    for category, values in (
        installed or {}
    ).items():
        clean_values = []
        seen_values = set()

        for value in values:
            candidate = Path(
                str(value)
            )

            try:
                if candidate.is_absolute():
                    relative = (
                        candidate.resolve()
                        .relative_to(
                            table_resolved
                        )
                    )
                else:
                    relative = candidate

            except Exception:
                continue

            portable = (
                relative
                .as_posix()
                .lstrip("/")
            )

            if (
                portable
                and portable
                not in seen_values
            ):
                seen_values.add(
                    portable
                )
                clean_values.append(
                    portable
                )

        normalized_installed[
            category
        ] = clean_values

    installed = (
        normalized_installed
    )

    info = {
        "Info": {
            "Title": title,
            "Manufacturer": manufacturer,
            "Year": str(
                year or ""
            ),
            "Rom": rom,
            "VPSId": vpsid,
            "IPDBId": ipdbid,
        }
    }

    if info_path_override:
        info_path = Path(
            info_path_override
        )

        if (
            info_path.parent.resolve()
            != table_resolved
            or info_path.suffix.lower()
            != ".info"
        ):
            raise RuntimeError(
                "NOGO: chemin .info "
                f"invalide: {info_path}"
            )
    else:
        info_path = (
            table_dir
            / (
                f"{safe_name(title)}"
                ".info"
            )
        )

    now = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    previous = (
        existing_manifest
        if isinstance(
            existing_manifest,
            dict,
        )
        else {}
    )

    manifest = {
        "format": (
            "PinCabOS portable "
            "VPX table"
        ),
        "format_version": 6,
        "model": (
            "single-folder-"
            "portable-table"
        ),
        "title": title,
        "manufacturer": manufacturer,
        "year": str(
            year or ""
        ),
        "rom": rom,
        "vpsid": vpsid,
        "ipdbid": ipdbid,
        "table_dir": str(
            table_dir
        ),
        "layout": {
            "root": [
                "*.vpx",
                "*.directb2s",
                "*.info",
                "*.ini",
                "*.vbs",
                "*.scv",
                "*.pov",
                "*.res",
            ],
            "altsound": (
                "pinmame/altsound/"
                "<name>/"
            ),
            "cache": "cache/",
            "medias": "medias/",
            "music": "music/",
            "pinmame": {
                "roms": (
                    "pinmame/roms/"
                ),
                "nvram": (
                    "pinmame/nvram/"
                ),
                "cfg": (
                    "pinmame/cfg/"
                ),
                "ini": (
                    "pinmame/ini/"
                ),
                "alias": (
                    "pinmame/"
                    "alias.txt"
                ),
            },
            "pupvideos": (
                "pupvideos/"
            ),
            "scripts": "scripts/",
            "serum": (
                "pinmame/altcolor/"
                "<name>/"
            ),
            "ultradmd": (
                "<Table Name>."
                "UltraDMD/"
            ),
            "user": "user/",
            "vni": (
                "pinmame/altcolor/"
                "<name>/"
            ),
            "extras": "extras/",
        },
        "legacy_global_paths_used": (
            False
        ),
        "installed": installed,
        "created_at": str(
            previous.get(
                "created_at"
            )
            or now
        ),
    }

    game_vpsid = str(
        (
            resource_manifest.get("game_vpsid", "")
            if isinstance(resource_manifest, dict)
            else ""
        )
        or previous.get("game_vpsid", "")
        or ""
    ).strip()

    if game_vpsid:
        manifest["game_vpsid"] = game_vpsid

    resources = pincabos_merge_resource_inventory(
        previous,
        resource_manifest,
    )

    if resources:
        manifest["resource_inventory_version"] = 1
        manifest["resources"] = resources

    patch_manifest = {}

    if isinstance(patch_info, dict):
        for key in (
            "engine",
            "engine_version",
            "source_kind",
            "source_file",
            "source_sha256",
            "source_table_version",
            "patch_file",
            "patch_sha256",
            "output_file",
            "output_sha256",
            "parent_vpsid",
            "parent_version",
            "target_vpsid",
            "target_version",
        ):
            value = patch_info.get(key)

            if value not in (None, ""):
                patch_manifest[key] = value

    elif isinstance(previous.get("vpu_patch"), dict):
        patch_manifest = dict(previous["vpu_patch"])

    if patch_manifest:
        manifest["vpu_patch"] = patch_manifest

    if previous:
        manifest[
            "updated_at"
        ] = now

    pincabos_atomic_write_json(
        info_path,
        info,
    )

    manifest_path = (
        table_dir
        / "pincabos-table-manifest.json"
    )

    pincabos_atomic_write_json(
        manifest_path,
        manifest,
    )

    log(f"META: {info_path}")
    log(f"META: {manifest_path}")



def write_import_tree_log(table_dir, title, rom, installed):
    IMPORT_LOGS_ROOT.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_name = safe_name(title).replace(" ", "_")
    log_path = IMPORT_LOGS_ROOT / f"import-{stamp}-{log_name}.txt"

    try:
        tree = subprocess.run(
            ["find", str(table_dir), "-maxdepth", "8", "-print"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        tree_output = tree.stdout.strip()
        tree_error = tree.stderr.strip()
    except Exception as e:
        tree_output = ""
        tree_error = str(e)

    lines = []
    lines.append("======================================================================")
    lines.append(" PinCabOS - Import table log")
    lines.append("======================================================================")
    lines.append(f"Date       : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Title      : {title}")
    lines.append(f"ROM        : {rom or '(aucune)'}")
    lines.append(f"Table dir  : {table_dir}")
    lines.append("")
    lines.append("======================================================================")
    lines.append(" Résumé install")
    lines.append("======================================================================")
    for k, v in installed.items():
        lines.append(f"{k}: {len(v)}")
    lines.append("")
    lines.append("======================================================================")
    lines.append(" Fichiers installés par catégorie")
    lines.append("======================================================================")
    for k, v in installed.items():
        lines.append("")
        lines.append(f"--- {k} ({len(v)}) ---")
        for item in v:
            lines.append(str(item))
    lines.append("")
    lines.append("======================================================================")
    lines.append(" Résultat find")
    lines.append("======================================================================")
    lines.append(tree_output)
    if tree_error:
        lines.append("")
        lines.append("======================================================================")
        lines.append(" Erreurs find")
        lines.append("======================================================================")
        lines.append(tree_error)
    lines.append("")
    lines.append("======================================================================")
    lines.append(" FIN")
    lines.append("======================================================================")

    log_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")

    try:
        subprocess.run(["chown", "pinball:pinball", str(log_path)], timeout=10, check=False)
        subprocess.run(["chmod", "664", str(log_path)], timeout=10, check=False)
    except Exception:
        pass

    log(f"IMPORT LOG: {log_path}")
    return log_path



def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("batch_dir")
    ap.add_argument(
        "--title",
        default="",
    )
    ap.add_argument(
        "--manufacturer",
        default="",
    )
    ap.add_argument(
        "--year",
        default="",
    )
    ap.add_argument(
        "--vpsid",
        default="",
    )
    ap.add_argument(
        "--parent-vpsid",
        default="",
    )
    ap.add_argument(
        "--game-vpsid",
        default="",
    )
    ap.add_argument(
        "--parent-version",
        default="",
    )
    ap.add_argument(
        "--target-version",
        default="",
    )
    ap.add_argument(
        "--resources-json",
        default="",
    )
    ap.add_argument(
        "--target-existing",
        action="store_true",
    )
    ap.add_argument(
        "--rom",
        default="",
    )
    ap.add_argument(
        "--ipdbid",
        default="",
    )

    args = ap.parse_args()

    batch_dir = Path(
        args.batch_dir
    )

    if not batch_dir.exists():
        raise SystemExit(
            "Batch introuvable: "
            f"{batch_dir}"
        )

    incoming_title = (
        standard_table_folder_name(
            safe_name(
                args.title
                or batch_dir.name
            )
        )
    )

    manufacturer = (
        args.manufacturer.strip()
    )

    year = str(
        args.year or ""
    ).strip()

    vpsid = (
        args.vpsid.strip()
    )

    parent_vpsid = (
        args.parent_vpsid.strip()
    )

    game_vpsid = (
        args.game_vpsid.strip()
    )

    parent_version = (
        args.parent_version.strip()
    )

    target_version = (
        args.target_version.strip()
    )

    resource_manifest = {}
    target_existing = bool(args.target_existing)

    if args.resources_json.strip():
        resource_manifest = pincabos_load_resource_manifest(
            args.resources_json.strip(),
            batch_dir,
        )

        manifest_game_vpsid = str(
            resource_manifest.get("game_vpsid", "")
            or ""
        ).strip()

        if game_vpsid and game_vpsid != manifest_game_vpsid:
            raise RuntimeError(
                "NOGO: game VPSId différent entre la commande "
                "et l'inventaire par fichier."
            )

        game_vpsid = manifest_game_vpsid

    ipdbid = (
        args.ipdbid.strip()
    )

    TABLES_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    log(
        "================================"
        "=================="
    )
    log(
        " PinCabOS Import - "
        "Portable VPX table complete"
    )
    log(
        "================================"
        "=================="
    )
    log(
        f"Batch       : {batch_dir}"
    )
    log(
        f"Tables root : {TABLES_ROOT}"
    )
    log(
        f"Title       : {incoming_title}"
    )

    with PINCABOS_SMART_IMPORT_LOCK.open(
        "a+"
    ) as lock_handle:

        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            if target_existing:
                table_dir = pincabos_find_existing_table_dir(
                    incoming_title
                )
            else:
                table_dir = (
                    pincabos_find_existing_table_dir_by_game(
                        game_vpsid,
                        incoming_title,
                    )
                    if resource_manifest
                    else pincabos_find_existing_table_dir(
                        incoming_title
                    )
                )

            existed_before = (
                table_dir.is_dir()
            )

            if target_existing and not existed_before:
                raise RuntimeError(
                    "NOGO: table de destination explicitement choisie absente."
                )

            if existed_before and (resource_manifest or target_existing):
                incoming_title = table_dir.name

                if not vpsid:
                    preliminary_identity = (
                        pincabos_read_existing_table_identity(
                            table_dir
                        )
                    )
                    vpsid = str(
                        preliminary_identity.get("vpsid", "")
                        or ""
                    ).strip()

                    if not vpsid and not target_existing:
                        raise RuntimeError(
                            "NOGO: ressource auxiliaire destinée à une "
                            "table existante sans VPSId principal fiable."
                        )

            if (
                not existed_before
                and resource_manifest
                and not vpsid
                and resource_manifest.get("association_mode") != "partial_vpsid"
            ):
                raise RuntimeError(
                    "NOGO: les ressources VPSDB ne contiennent pas de "
                    "tableFile et aucune table correspondante n'est installée."
                )

            if existed_before:
                existing_identity = (
                    pincabos_validate_existing_identity(
                        table_dir,
                        incoming_title,
                        vpsid,
                        parent_vpsid=parent_vpsid,
                        game_vpsid=game_vpsid,
                        allow_missing_vpsid=target_existing,
                    )
                )

                title = (
                    table_dir.name
                )

                if existing_identity.get("relation") in {
                    "vpu_parent",
                    "vpu_game",
                }:
                    source_identity = existing_identity.get("vpsid", "")
                    log(
                        "MODE UPDATE VPSDB      : "
                        f"source VPSId {source_identity} "
                        f"-> cible VPSId {vpsid}; "
                        "type de contenu déterminé après extraction"
                    )
                else:
                    log(
                        "MODE UPDATE            : "
                        "nom normalisé identique "
                        f"+ VPSId {vpsid}"
                    )

            else:
                existing_identity = {
                    "vpsid": "",
                    "title": (
                        incoming_title
                    ),
                    "manifest": {},
                    "manifest_path": (
                        table_dir
                        / (
                            "pincabos-table-"
                            "manifest.json"
                        )
                    ),
                    "info_path": None,
                }

                title = incoming_title

                log(
                    "MODE INSTALL           : "
                    "nouvelle table"
                )

            with tempfile.TemporaryDirectory(
                prefix=(
                    "pincabos-portable-"
                    "table-import-"
                )
            ) as td:

                work_root = Path(td)

                extract_root = (
                    work_root
                    / "extract"
                )

                extract_all_inputs(
                    batch_dir,
                    extract_root,
                    resource_manifest=(
                        resource_manifest
                    ),
                )

                bundled_vpxs = sorted(
                    item
                    for item in list_files(extract_root)
                    if item.suffix.lower() == ".vpx"
                    and not should_skip_file(item)
                )
                has_vpu_patch = bool(pincabos_vpu_patch_files(extract_root))

                if len(bundled_vpxs) > 1 and not has_vpu_patch:
                    raise RuntimeError(
                        "NOGO: plusieurs VPX complets ont été détectés dans le "
                        "lot; Smart Import refuse de choisir le plus gros fichier "
                        "comme table principale."
                    )

                bundled_main_vpx = choose_main_vpx(extract_root)

                patch_info = pincabos_apply_vpu_patch(
                    extract_root,
                    existing_table_dir=(
                        table_dir
                        if existed_before
                        else None
                    ),
                    existing_vpsid=(
                        existing_identity.get("vpsid", "")
                        if existed_before
                        else ""
                    ),
                    incoming_vpsid=vpsid,
                    expected_parent_version=parent_version,
                )

                if (
                    existed_before
                    and existing_identity.get("relation") in {
                        "vpu_parent",
                        "vpu_game",
                    }
                    and not patch_info
                    and not bundled_main_vpx
                ):
                    raise RuntimeError(
                        "NOGO: transition VPSId parent -> mod refusée "
                        "car aucun patch VPU Remix .dif et aucun VPX complet "
                        "n'ont été détectés."
                    )

                if (
                    existed_before
                    and existing_identity.get("relation") in {
                        "vpu_parent",
                        "vpu_game",
                    }
                    and not patch_info
                    and bundled_main_vpx
                ):
                    log(
                        "MODE VPX COMPLET       : relation parent/mod VPSDB, "
                        "VPX complet fourni; aucun .dif requis"
                    )

                if patch_info:
                    patch_info["parent_vpsid"] = parent_vpsid
                    patch_info["parent_version"] = parent_version
                    patch_info["target_vpsid"] = vpsid
                    patch_info["target_version"] = target_version

                main_vpx = (
                    Path(patch_info["output_path"])
                    if patch_info
                    else bundled_main_vpx
                )

                identity_vpx = main_vpx

                if (
                    not identity_vpx
                    and existed_before
                    and (resource_manifest or target_existing)
                ):
                    installed_vpxs = sorted(
                        item
                        for item in table_dir.glob("*.vpx")
                        if item.is_file() and not item.is_symlink()
                    )

                    if len(installed_vpxs) != 1:
                        raise RuntimeError(
                            "NOGO: ressource auxiliaire détectée, mais la "
                            "table installée ne contient pas exactement un VPX "
                            "fiable: "
                            + " | ".join(str(item) for item in installed_vpxs)
                        )

                    identity_vpx = installed_vpxs[0]
                    log(
                        "MODE RESSOURCE         : VPX existant conservé "
                        f"({identity_vpx})"
                    )

                if not identity_vpx:
                    raise RuntimeError(
                        "NOGO: aucune table VPX source et aucune table "
                        "correspondante déjà installée. Import refusé."
                    )

                provided_rom = args.rom

                if (
                    not provided_rom
                    and existed_before
                    and isinstance(existing_identity.get("manifest"), dict)
                ):
                    provided_rom = str(
                        existing_identity["manifest"].get("rom", "")
                        or ""
                    ).strip()

                identity = (
                    detect_import_identity(
                        extract_root,
                        provided_rom,
                        main_vpx=identity_vpx,
                    )
                )

                rom = identity["rom"]

                pup_pack = (
                    identity["pup_pack"]
                )

                if pup_pack:
                    bundled_roms = [
                        item
                        for item
                        in list_files(
                            extract_root
                        )
                        if (
                            item.suffix.lower()
                            == ".zip"
                            and archive_kind(
                                item
                            )
                            == "rom_zip"
                        )
                    ]

                    if (
                        not bundled_roms
                        and not (
                            resource_manifest
                            and existed_before
                            and provided_rom
                        )
                    ):
                        if (
                            str(
                                rom or ""
                            ).casefold()
                            != str(
                                pup_pack
                            ).casefold()
                        ):
                            log(
                                "ROM corrigée "
                                "par alias PuP : "
                                f"{rom or '(vide)'} "
                                f"-> {pup_pack}"
                            )

                        rom = pup_pack

                staged_table = (
                    work_root
                    / "staged-tables"
                    / title
                )

                ensure_table_tree(
                    staged_table
                )

                final_vbs = (
                    extract_vbs_from_vpx(
                        main_vpx,
                        staged_table,
                    )
                    if main_vpx
                    else None
                )

                if final_vbs:
                    log(
                        "VBS staging extrait    : "
                        f"{final_vbs}"
                    )
                else:
                    log(
                        "WARNING: VBS non "
                        "extrait dans staging."
                    )

                log("")
                log(
                    "================================"
                    "=================="
                )
                log(
                    " Préparation portable "
                    "VPX en staging"
                )
                log(
                    "================================"
                    "=================="
                )
                log(
                    "VPX principal détecté : "
                    f"{main_vpx or '(VPX existant conservé)'}"
                )
                log(
                    "ROM détectée          : "
                    f"{rom or '(aucune)'}"
                )
                log(
                    "PuP-Pack détecté       : "
                    f"{pup_pack or '(aucun)'}"
                )
                log(
                    "Staging table         : "
                    f"{staged_table}"
                )
                log(
                    "Table réelle          : "
                    f"{table_dir}"
                )

                staged_installed = (
                    classify_and_install(
                        extract_root,
                        staged_table,
                        rom,
                        pup_pack=pup_pack,
                        main_vpx=main_vpx,
                        resource_manifest=(
                            resource_manifest
                        ),
                    )
                )

                if final_vbs:
                    final_vbs_text = str(final_vbs)
                    if final_vbs_text not in staged_installed["root"]:
                        staged_installed["root"].append(final_vbs_text)

                    primary_key = str(vpsid or "").strip().casefold()
                    for resource in resource_manifest.get("resources", []):
                        if (
                            isinstance(resource, dict)
                            and resource.get("resource_type") == "tableFile"
                            and str(resource.get("vpsid", "") or "")
                            .strip().casefold() == primary_key
                        ):
                            resource.setdefault("_staged_installed", {}) \
                                .setdefault("root", []).append(final_vbs_text)
                            break

                incoming_installed = (
                    pincabos_remap_installed_to_relative(
                        staged_installed,
                        staged_table,
                    )
                )

                for resource in resource_manifest.get("resources", []):
                    if not isinstance(resource, dict):
                        continue

                    resource["_incoming_installed"] = (
                        pincabos_remap_installed_to_relative(
                            resource.get("_staged_installed", {}),
                            staged_table,
                        )
                    )

                if existed_before:
                    existing_identity = (
                        pincabos_validate_existing_identity(
                            table_dir,
                            incoming_title,
                            vpsid,
                            parent_vpsid=parent_vpsid,
                            game_vpsid=game_vpsid,
                            allow_missing_vpsid=target_existing,
                        )
                    )

                elif table_dir.exists():
                    raise RuntimeError(
                        "NOGO: la table est "
                        "apparue pendant l'import."
                    )

                plan = (
                    pincabos_build_staged_plan(
                        staged_table,
                        table_dir,
                    )
                )

                transaction = (
                    pincabos_new_transaction(
                        table_dir,
                        existed_before,
                    )
                )

                try:
                    stats = (
                        pincabos_apply_staged_plan(
                            plan,
                            transaction,
                        )
                    )

                    previous_manifest = (
                        existing_identity.get(
                            "manifest",
                            {},
                        )
                        if existed_before
                        else {}
                    )

                    if existed_before:
                        installed = (
                            pincabos_merge_installed(
                                previous_manifest,
                                incoming_installed,
                            )
                        )
                    else:
                        installed = (
                            incoming_installed
                        )

                    annotated_resource_manifest = (
                        pincabos_annotate_resource_inventory(
                            resource_manifest,
                            incoming_installed,
                            plan,
                        )
                    )

                    existing_info_path = (
                        existing_identity.get(
                            "info_path"
                        )
                        if existed_before
                        else None
                    )

                    info_target = (
                        Path(
                            existing_info_path
                        )
                        if existing_info_path
                        else (
                            table_dir
                            / (
                                f"{safe_name(title)}"
                                ".info"
                            )
                        )
                    )

                    manifest_target = (
                        table_dir
                        / (
                            "pincabos-table-"
                            "manifest.json"
                        )
                    )

                    pincabos_tx_prepare_write(
                        transaction,
                        info_target,
                    )

                    pincabos_tx_prepare_write(
                        transaction,
                        manifest_target,
                    )

                    write_info_and_manifest(
                        table_dir,
                        title,
                        manufacturer,
                        year,
                        rom,
                        vpsid,
                        ipdbid,
                        installed,
                        info_path_override=(
                            existing_info_path
                        ),
                        existing_manifest=(
                            previous_manifest
                        ),
                        patch_info=patch_info,
                        resource_manifest=(
                            annotated_resource_manifest
                        ),
                    )

                    pincabos_write_transaction_record(
                        transaction,
                        stats,
                        vpsid,
                    )

                except Exception:
                    log("")
                    log(
                        "ERREUR: commit "
                        "Smart Import échoué — "
                        "rollback."
                    )

                    pincabos_rollback_transaction(
                        transaction
                    )

                    log(
                        "ROLLBACK [OK] "
                        "table restaurée."
                    )

                    raise

                import_log_path = (
                    write_import_tree_log(
                        table_dir,
                        title,
                        rom,
                        installed,
                    )
                )

                try:
                    subprocess.run(
                        [
                            "chown",
                            "-R",
                            "pinball:pinball",
                            str(table_dir),
                        ],
                        timeout=60,
                        check=False,
                    )

                    subprocess.run(
                        [
                            "chmod",
                            "-R",
                            "u+rwX,g+rwX,o+rX",
                            str(table_dir),
                        ],
                        timeout=60,
                        check=False,
                    )

                except Exception:
                    pass

                pincabos_log_update_summary(
                    stats
                )

                if transaction.get(
                    "backup_root"
                ):
                    log(
                        "BACKUP UPDATE          : "
                        f"{transaction['backup_root']}"
                    )

                log("")
                log(
                    "=== Résultat table ==="
                )

                subprocess.run(
                    [
                        "find",
                        str(table_dir),
                        "-maxdepth",
                        "5",
                        "-print",
                    ],
                    check=False,
                )

                log("")
                log(
                    f"LOG TXT: "
                    f"{import_log_path}"
                )

                # Conserve le comportement
                # LIVE ciblé existant.
                try:
                    tree_result = (
                        subprocess.run(
                            [
                                (
                                    "/opt/pincabos/"
                                    "tools/"
                                    "pincabos-table-tree.sh"
                                ),
                                "--apply",
                                "--quiet",
                                (
                                    f"--table="
                                    f"{table_dir}"
                                ),
                            ],
                            capture_output=True,
                            text=True,
                            timeout=120,
                            check=False,
                        )
                    )

                    if (
                        tree_result.returncode
                        != 0
                    ):
                        detail = (
                            (
                                tree_result.stdout
                                or ""
                            )
                            + "\n"
                            + (
                                tree_result.stderr
                                or ""
                            )
                        ).strip()

                        log(
                            "WARNING: "
                            "normalisation ciblée "
                            "table-tree "
                            "retour="
                            f"{tree_result.returncode}"
                        )

                        if detail:
                            log(detail)

                    else:
                        log(
                            "Table-tree ciblé       : "
                            f"{table_dir}"
                        )

                except Exception as exc:
                    log(
                        "WARNING: "
                        "normalisation ciblée "
                        "table-tree impossible: "
                        f"{exc}"
                    )

                log(
                    "IMPORT OK - modèle "
                    "portable VPX complet "
                    "avec update sécurisé"
                )

                return 0

        finally:
            fcntl.flock(
                lock_handle.fileno(),
                fcntl.LOCK_UN,
            )



# PINCABOS_FULLDMD_SMART_IMPORT_HOOK_V4
# Ajouté par l'installateur V4 après audit de la garde __main__ et du marqueur portable V2.
# Le hook est volontairement différé à la fin du processus : il ne traite que les B2S
# FullDMD modifiés pendant l'import. Il ne modifie aucun fichier de table source.
def _pincabos_fulldmd_after_smart_import() -> None:
    try:
        import atexit
        import os
        import subprocess
        from pathlib import Path

        def _run() -> None:
            dispatcher = Path('/opt/pincabos/bin/pincabos-fulldmd-process-table.py')
            if not dispatcher.is_file():
                return
            subprocess.Popen(
                [str(dispatcher), '--recent-minutes', '20'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        atexit.register(_run)
    except Exception:
        pass

_pincabos_fulldmd_after_smart_import()
# PINCABOS_FULLDMD_SMART_IMPORT_HOOK_V4_END


# PINCABOS_TABLE_TREE_IMPORT_TARGETED_V5_ENTRYPOINT
if __name__ == "__main__":
    raise SystemExit(main())
