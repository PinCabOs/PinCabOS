#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


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

REPO_API = "https://api.github.com/repos/superhac/vpinfe/releases/latest"
TARGET = Path(_pco_chemin("vpinfe_dir", "/opt/pinball/vpinfe"))  # PINCABOS_RUNTIMES_OPT_V1
BACKUPS = Path("/opt/pincabos/backups/vpinfe-update")
RUNTIME = Path("/opt/pincabos/runtime/vpinfe-update")
STATE_DIR = Path("/opt/pincabos/state")
STATE = STATE_DIR / "vpinfe-update-state.json"
LOCK = Path("/run/lock/pincabos-vpinfeupdate.lock")
SERVICE = "pincabos-vpinfe.service"
USER = "pinball"
GROUP = "pinball"
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 6 * 1024 * 1024 * 1024

def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

def log(message: str) -> None:
    print(message, flush=True)

def fail(message: str) -> None:
    raise RuntimeError(message)

def require_root() -> None:
    if os.geteuid() != 0:
        fail("Cette opération doit être exécutée par root.")

def read_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def write_state(data: dict[str, Any]) -> None:
    require_root()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o755)
    fd, temp_name = tempfile.mkstemp(prefix=".vpinfe-state-", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, STATE)
        os.chown(STATE, 0, 0)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def static_build_id(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except Exception:
        return None
    for pattern in (
        rb"Version:\s*([A-Za-z0-9._+\-]+)",
        rb"\b(dev-[0-9]+)\b",
    ):
        found = re.search(pattern, raw)
        if found:
            return found.group(1).decode("utf-8", errors="replace")
    return None

def binary_fingerprint(path: Path, state: dict[str, Any]) -> tuple[str | None, int | None, int | None]:
    if not path.is_file():
        return None, None, None
    st = path.stat()
    prior = state.get("installed", {}) if isinstance(state.get("installed"), dict) else {}
    if (
        prior.get("binary_size") == st.st_size
        and prior.get("binary_mtime_ns") == st.st_mtime_ns
        and isinstance(prior.get("binary_sha256"), str)
        and prior["binary_sha256"]
    ):
        return prior["binary_sha256"], st.st_size, st.st_mtime_ns
    return sha256_file(path), st.st_size, st.st_mtime_ns

def detect_local(state: dict[str, Any]) -> dict[str, Any]:
    exe = TARGET / "vpinfe"
    if not exe.is_file() or not os.access(exe, os.X_OK):
        return {
            "present": False, "display": "non détectée", "release": None,
            "build": None, "binary_sha256": None, "binary_size": None,
            "binary_mtime_ns": None,
        }
    digest, size, mtime_ns = binary_fingerprint(exe, state)
    recorded = state.get("installed", {}) if isinstance(state.get("installed"), dict) else {}
    release = None
    if digest and digest == recorded.get("binary_sha256"):
        tag = recorded.get("tag")
        if isinstance(tag, str) and tag.strip():
            release = tag.strip()
    build = static_build_id(exe)
    return {
        "present": True,
        "display": release or build or "installée",
        "release": release,
        "build": build,
        "binary_sha256": digest,
        "binary_size": size,
        "binary_mtime_ns": mtime_ns,
    }

def api_request(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PinCabOS-VPinFE-Updater/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()

def is_linux_x64_slim_archive(name: str) -> bool:
    low = name.lower()
    archive = low.endswith(".zip") or low.endswith(".tar.gz") or low.endswith(".tgz")
    linux = "linux" in low
    x64 = any(token in low for token in ("x64", "x86_64", "amd64"))
    slim = "slim" in low
    not_arm = not any(token in low for token in ("aarch64", "arm64", "armv", "linux-arm"))
    return archive and linux and x64 and slim and not_arm

def fetch_remote() -> dict[str, Any]:
    try:
        data = json.loads(api_request(REPO_API).decode("utf-8", errors="replace"))
        if not isinstance(data, dict):
            fail("Réponse GitHub invalide.")
        if data.get("draft") or data.get("prerelease"):
            fail("La release latest GitHub n'est pas une release stable.")
        tag = str(data.get("tag_name") or "").strip()
        if not tag:
            fail("Release GitHub sans tag.")
        candidates = [
            asset for asset in data.get("assets", [])
            if isinstance(asset, dict)
            and is_linux_x64_slim_archive(str(asset.get("name") or ""))
        ]
        if len(candidates) != 1:
            names = ", ".join(
                str(a.get("name") or "?") for a in data.get("assets", [])
                if isinstance(a, dict)
            )
            fail(
                f"Asset Linux x64 slim ambigu ou absent ({len(candidates)} trouvé). "
                f"Assets: {names}"
            )
        asset = candidates[0]
        url = str(asset.get("browser_download_url") or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            fail("URL de téléchargement GitHub invalide.")
        size = int(asset.get("size") or 0)
        if size <= 0 or size > MAX_ARCHIVE_BYTES:
            fail(f"Taille d'archive invalide: {size} octets.")
        return {
            "ok": True,
            "tag": tag,
            "published_at": str(data.get("published_at") or ""),
            "asset_name": str(asset.get("name") or ""),
            "asset_url": url,
            "asset_size": size,
            "asset_digest": str(asset.get("digest") or ""),
            "html_url": str(data.get("html_url") or ""),
            "checked_at": utc_now(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "checked_at": utc_now()}

def version_key(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", value.strip())
    return tuple(int(item) for item in match.groups()) if match else None

def update_summary(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    if not local.get("present"):
        return {"status": "missing", "label": "VPinFE absent"}
    if not remote.get("ok"):
        return {"status": "unknown", "label": "GitHub non vérifié"}
    local_key = version_key(local.get("release"))
    remote_key = version_key(remote.get("tag"))
    if local_key is None or remote_key is None:
        return {"status": "available", "label": f"{remote.get('tag')} disponible"}
    if remote_key > local_key:
        return {"status": "available", "label": f"{remote.get('tag')} disponible"}
    if remote_key == local_key:
        return {"status": "current", "label": "À jour"}
    return {"status": "local_newer", "label": "Version locale plus récente"}

def status_payload(with_remote: bool) -> dict[str, Any]:
    state = read_state()
    local = detect_local(state)
    if with_remote:
        remote = fetch_remote()
    else:
        last_check = state.get("last_check", {}) if isinstance(state.get("last_check"), dict) else {}
        remote = (
            last_check.get("remote")
            if isinstance(last_check.get("remote"), dict)
            else {"ok": False, "error": "GitHub non vérifié"}
        )
    return {
        "schema": 1,
        "generated_at": utc_now(),
        "local": local,
        "remote": remote,
        "update": update_summary(local, remote),
        "last_operation": state.get("last_operation", {}),
    }

def ensure_safe_member(name: str) -> None:
    item = Path(name)
    if item.is_absolute() or ".." in item.parts:
        fail(f"Archive non sûre: {name}")

def extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    extracted_total = 0
    low = archive.name.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                ensure_safe_member(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    fail(f"Archive ZIP contient un lien symbolique: {info.filename}")
                extracted_total += int(info.file_size)
                if extracted_total > MAX_EXTRACTED_BYTES:
                    fail("Archive trop volumineuse une fois extraite.")
            zf.extractall(destination)
        return
    if low.endswith(".tar.gz") or low.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                ensure_safe_member(member.name)
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    fail(f"Archive TAR contient un type interdit: {member.name}")
                extracted_total += max(0, int(member.size))
                if extracted_total > MAX_EXTRACTED_BYTES:
                    fail("Archive trop volumineuse une fois extraite.")
            tf.extractall(destination, filter="data")
        return
    fail("Format archive non supporté.")

def validate_install_root(root: Path) -> None:
    exe = root / "vpinfe"
    internal = root / "_internal"
    # PINCABOS_VPINFE_UPDATE_ZIP_MODE_FIX_V1
    if not exe.is_file():
        fail("Archive invalide: binaire vpinfe absent.")

    # GitHub ZIP peut perdre le bit exécutable pendant extractall().
    # On le restaure seulement sur le binaire VPinFE validé.
    try:
        os.chmod(
            exe,
            exe.stat().st_mode
            | stat.S_IXUSR
            | stat.S_IXGRP
            | stat.S_IXOTH,
        )
    except OSError as exc:
        fail(f"Archive invalide: permissions du binaire vpinfe: {exc}")

    if not os.access(exe, os.X_OK):
        fail("Archive invalide: binaire vpinfe exécutable absent.")
    if not internal.is_dir():
        fail("Archive invalide: répertoire _internal absent.")
    head = exe.read_bytes()[:20]
    if head[:4] != b"\x7fELF" or len(head) < 20:
        fail("Archive invalide: vpinfe n'est pas un ELF.")
    if head[4] != 2 or int.from_bytes(head[18:20], "little") != 0x3E:
        fail("Archive invalide: vpinfe n'est pas un binaire Linux x86_64.")

def locate_install_root(extract_root: Path) -> Path:
    candidates: list[Path] = []
    for candidate in extract_root.rglob("vpinfe"):
        if candidate.is_file() and (candidate.parent / "_internal").is_dir():
            candidates.append(candidate.parent)
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    if len(unique) != 1:
        fail(f"Archive invalide: {len(unique)} répertoires VPinFE candidats trouvés.")
    return unique[0]

def chown_tree(root: Path) -> None:
    import grp
    import pwd
    uid = pwd.getpwnam(USER).pw_uid
    gid = grp.getgrnam(GROUP).gr_gid
    for current, dirs, files in os.walk(root):
        os.chown(current, uid, gid)
        for name in dirs:
            os.chown(Path(current, name), uid, gid)
        for name in files:
            os.chown(Path(current, name), uid, gid)
    os.chmod(root / "vpinfe", 0o755)

def systemctl(*args: str, check: bool = True, timeout: int = 40) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["/bin/systemctl", *args],
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        detail = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        fail(f"systemctl {' '.join(args)} a échoué: {detail}")
    return result

def service_active() -> bool:
    return systemctl("is-active", "--quiet", SERVICE, check=False, timeout=10).returncode == 0

def wait_service_active(seconds: int = 30) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if service_active():
            return True
        time.sleep(1)
    return False

def same_filesystem() -> None:
    for path in (TARGET.parent, BACKUPS, RUNTIME):
        path.mkdir(parents=True, exist_ok=True)
    device = TARGET.parent.stat().st_dev
    for path in (BACKUPS, RUNTIME):
        if path.stat().st_dev != device:
            fail(f"Bascule atomique impossible: {path} est sur un autre système de fichiers.")

def download(remote: dict[str, Any], destination: Path) -> str:
    request = urllib.request.Request(
        str(remote["asset_url"]),
        headers={"User-Agent": "PinCabOS-VPinFE-Updater/1.0"},
    )
    total = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as fh:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_ARCHIVE_BYTES:
                fail("Téléchargement dépasse la taille maximale permise.")
            digest.update(block)
            fh.write(block)
    if total != int(remote["asset_size"]):
        fail(f"Téléchargement incomplet: {total} != {remote['asset_size']} octets.")
    actual = digest.hexdigest()
    upstream = str(remote.get("asset_digest") or "")
    if upstream.startswith("sha256:") and actual.lower() != upstream.split(":", 1)[1].lower():
        fail("SHA-256 GitHub ne correspond pas à l'archive téléchargée.")
    return actual

def operation_state(
    ok: bool,
    stage: str,
    message: str,
    remote: dict[str, Any] | None = None,
    installed: dict[str, Any] | None = None,
) -> None:
    data = read_state()
    if remote is not None:
        data["last_check"] = {"at": utc_now(), "remote": remote}
    if installed is not None:
        data["installed"] = installed
    data["last_operation"] = {
        "at": utc_now(),
        "ok": bool(ok),
        "stage": stage,
        "message": message,
    }
    write_state(data)

def run_check() -> int:
    require_root()
    remote = fetch_remote()
    operation_state(
        bool(remote.get("ok")),
        "check",
        "GitHub vérifié" if remote.get("ok") else str(remote.get("error") or "GitHub indisponible"),
        remote=remote,
    )
    print(json.dumps(status_payload(False), sort_keys=True))
    return 0 if remote.get("ok") else 1

def run_update() -> int:
    require_root()
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("Une mise à jour VPinFE est déjà en cours.")

        remote = fetch_remote()
        if not remote.get("ok"):
            operation_state(False, "remote", str(remote.get("error") or "GitHub indisponible"), remote=remote)
            fail(str(remote.get("error") or "GitHub indisponible"))

        local = detect_local(read_state())
        if update_summary(local, remote)["status"] == "current":
            operation_state(True, "noop", "VPinFE est déjà à jour.", remote=remote)
            log("VPinFE est déjà à jour.")
            return 0

        same_filesystem()
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = BACKUPS / stamp
        backup_dir.mkdir(parents=True, exist_ok=False)
        stage = RUNTIME / f"{stamp}-{os.getpid()}"
        stage.mkdir(parents=True, exist_ok=False)
        archive = stage / str(remote["asset_name"])
        extracted = stage / "extract"
        candidate_install = stage / "install"
        was_active = service_active()
        old_moved = False
        candidate_moved = False

        try:
            log(f"Release GitHub: {remote['tag']}")
            log(f"Asset validé: {remote['asset_name']}")
            log("Téléchargement officiel GitHub…")
            archive_sha = download(remote, archive)
            log(f"SHA-256 archive: {archive_sha}")
            log("Extraction contrôlée…")
            extract_archive(archive, extracted)
            source_root = locate_install_root(extracted)
            validate_install_root(source_root)
            shutil.move(str(source_root), str(candidate_install))
            validate_install_root(candidate_install)
            chown_tree(candidate_install)

            if was_active:
                log("Arrêt contrôlé de VPinFE…")
                systemctl("stop", SERVICE, timeout=40)
                if service_active():
                    fail("VPinFE demeure actif après arrêt contrôlé.")

            log(f"Backup: {backup_dir / 'vpinfe'}")
            os.rename(TARGET, backup_dir / "vpinfe")
            old_moved = True
            os.rename(candidate_install, TARGET)
            candidate_moved = True

            exe = TARGET / "vpinfe"
            binary_sha = sha256_file(exe)
            st = exe.stat()
            installed = {
                "tag": str(remote["tag"]),
                "asset_name": str(remote["asset_name"]),
                "asset_sha256": archive_sha,
                "binary_sha256": binary_sha,
                "binary_size": st.st_size,
                "binary_mtime_ns": st.st_mtime_ns,
                "installed_at": utc_now(),
                "backup": str(backup_dir / "vpinfe"),
            }

            if was_active:
                log("Démarrage contrôlé de VPinFE…")
                systemctl("start", SERVICE, timeout=40)
                if not wait_service_active(30):
                    journal = systemctl("status", "--no-pager", "--full", SERVICE, check=False, timeout=20)
                    detail = ((journal.stdout or "") + "\n" + (journal.stderr or "")).strip()
                    fail(f"Le nouveau VPinFE ne devient pas actif.\n{detail}")

            operation_state(True, "complete", f"VPinFE mis à jour vers {remote['tag']}.", remote=remote, installed=installed)
            log(f"SUCCÈS : VPinFE est maintenant {remote['tag']}.")
            log(f"Backup conservé : {backup_dir / 'vpinfe'}")
            return 0

        except Exception as exc:
            log(f"ERREUR : {exc}")
            notes: list[str] = []
            try:
                if candidate_moved and TARGET.exists():
                    failed = backup_dir / "vpinfe-failed"
                    os.rename(TARGET, failed)
                    notes.append(f"nouvelle version déplacée vers {failed}")
                if old_moved and (backup_dir / "vpinfe").exists() and not TARGET.exists():
                    os.rename(backup_dir / "vpinfe", TARGET)
                    notes.append("ancienne version restaurée")
                if was_active and TARGET.exists():
                    systemctl("start", SERVICE, check=False, timeout=40)
                    notes.append("démarrage de l'ancienne version demandé")
            except Exception as rollback_error:
                notes.append(f"rollback partiel: {rollback_error}")
            operation_state(False, "rollback", f"{exc} | {'; '.join(notes)}", remote=remote)
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--version-text", action="store_true")
    parser.add_argument("--remote-version", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    selected = sum(bool(item) for item in (
        args.status,
        args.version_text,
        args.remote_version,
        args.check,
        args.update,
    ))
    if selected > 1:
        parser.error("Choisir une seule opération principale.")
    if args.update:
        return run_update()
    if args.check:
        return run_check()
    if args.remote_version:
        remote = fetch_remote()
        print(remote.get("tag") if remote.get("ok") else "non détectée")
        return 0 if remote.get("ok") else 1
    if args.version_text:
        print(detect_local(read_state()).get("display") or "non détectée")
        return 0
    print(json.dumps(status_payload(bool(args.remote)), sort_keys=True))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        raise SystemExit(1)
