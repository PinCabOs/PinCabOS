#!/usr/bin/env python3
# PinCabOS-File created by Karots Sugarpie
"""
PinCabOS WebApp core.

Source de verite pour:
- chemins officiels PinCabOS
- chemins VPX / VPinball
- chemins VPinFE
- services systemd
- scripts shell appeles par la WebApp

Ce module ne lance rien au moment de l'import.
"""

from __future__ import annotations

import html
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

# PINCABOS_RUNTIMES_OPT_V1 : VPX et VPinFE vivent sous /opt/pinball (pincabos_paths,
# source de verite ; un cabinet pas encore migre y est ramene a son compte).
try:
    from pincabos_paths import PATHS as _PCO_PATHS
    _PCO_VPX_LINK, _PCO_VPINFE_DIR = _PCO_PATHS.vpx_link, _PCO_PATHS.vpinfe_dir
except Exception:  # hors cab (tests, banc)
    _PCO_VPX_LINK, _PCO_VPINFE_DIR = "/opt/pinball/vpx", "/opt/pinball/vpinfe"


@dataclass(frozen=True)
class PinCabOSPaths:
    base: Path = Path("/opt/pincabos")
    home: Path = Path("/home/pinball")

    @property
    def web(self) -> Path:
        return self.base / "web"

    @property
    def tools(self) -> Path:
        return self.base / "tools"

    @property
    def bin(self) -> Path:
        return self.base / "bin"

    @property
    def config(self) -> Path:
        return self.base / "config"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    @property
    def state(self) -> Path:
        return self.base / "state"

    @property
    def download(self) -> Path:
        return self.base / "download"

    @property
    def stage(self) -> Path:
        return self.base / "stage"

    @property
    def apps(self) -> Path:
        return self.base / "apps"

    @property
    def essentials(self) -> Path:
        return self.base / "essentials"

    @property
    def backups(self) -> Path:
        return self.base / "backups"

    @property
    def media(self) -> Path:
        return self.base / "media"

    @property
    def dof_dir(self) -> Path:
        return self.apps / "dof"

    # VPX / VPinball officiel
    @property
    def vpx_dir(self) -> Path:
        return Path(_PCO_VPX_LINK)

    @property
    def vpx_compat_dir(self) -> Path:
        return self.apps / "vpx"

    @property
    def vpx_wrapper(self) -> Path:
        return Path('/opt/pincabos/bin/vpx-vpinfe-default.sh')

    @property
    def vpx_runner(self) -> Path:
        return Path("/usr/local/bin/pincabos-run-vpx")

    @property
    def vpx_ini(self) -> Path:
        return Path('/home/pinball/.local/share/VPinballX/10.8/VPinballX.ini')

    @property
    def tables(self) -> Path:
        return self.home / "Tables"

    @property
    def tables_compat_link(self) -> Path:
        return self.vpx_dir / "Tables"

    @property
    def roms(self) -> Path:
        return self.vpx_dir / "PinMAME" / "roms"

    # VPinFE officiel
    @property
    def vpinfe_root(self) -> Path:
        return Path(_PCO_VPINFE_DIR)

    @property
    def vpinfe_current(self) -> Path:
        return self.vpinfe_root

    @property
    def vpinfe_bin(self) -> Path:
        return self.vpinfe_current / "vpinfe"

    @property
    def vpinfe_runner(self) -> Path:
        return Path("/usr/local/bin/pincabos-run-vpinfe")

    @property
    def vpinfe_template_ini(self) -> Path:
        return self.essentials / "VPinFEfiles" / "vpinfe.ini"

    @property
    def vpinfe_runtime_ini(self) -> Path:
        return self.home / ".config" / "vpinfe" / "vpinfe.ini"

    @property
    def vpinfe_config_ini(self) -> Path:
        # VPinFE utilise son chemin runtime natif.
        # Aucun second fichier de configuration PinCabOS n'est maintenu.
        return self.vpinfe_runtime_ini

    # Configs communes
    @property
    def version_json(self) -> Path:
        return self.config / "version.json"

    @property
    def firstrun_json(self) -> Path:
        return self.config / "firstrun.json"

    @property
    def screens_json(self) -> Path:
        return self.config / "screens" / "screens.json"

    @property
    def webapp_screen_autostart_conf(self) -> Path:
        return self.config / "webapp-screen-autostart.conf"


PCO_PATHS = PinCabOSPaths()

PATH_ALIASES: Mapping[str, Path] = {
    "base": PCO_PATHS.base,
    "web": PCO_PATHS.web,
    "tools": PCO_PATHS.tools,
    "bin": PCO_PATHS.bin,
    "config": PCO_PATHS.config,
    "logs": PCO_PATHS.logs,
    "state": PCO_PATHS.state,
    "download": PCO_PATHS.download,
    "stage": PCO_PATHS.stage,
    "apps": PCO_PATHS.apps,
    "essentials": PCO_PATHS.essentials,
    "backups": PCO_PATHS.backups,
    "media": PCO_PATHS.media,
    "dof_dir": PCO_PATHS.dof_dir,
    "dof_tools": PCO_PATHS.apps / "dof-tools",
    "vpinball": PCO_PATHS.vpx_dir,
    "vpx_dir": PCO_PATHS.vpx_dir,
    "vpx_compat_dir": PCO_PATHS.vpx_compat_dir,
    "vpx_wrapper": PCO_PATHS.vpx_wrapper,
    "vpx_runner": PCO_PATHS.vpx_runner,
    "vpx_ini": PCO_PATHS.vpx_ini,
    "tables": PCO_PATHS.tables,
    "tables_compat_link": PCO_PATHS.tables_compat_link,
    "roms": PCO_PATHS.roms,
    "vpinfe_root": PCO_PATHS.vpinfe_root,
    "vpinfe_current": PCO_PATHS.vpinfe_current,
    "vpinfe_bin": PCO_PATHS.vpinfe_bin,
    "vpinfe_runner": PCO_PATHS.vpinfe_runner,
    "vpinfe_template_ini": PCO_PATHS.vpinfe_template_ini,
    "vpinfe_runtime_ini": PCO_PATHS.vpinfe_runtime_ini,
    "vpinfe_config_ini": PCO_PATHS.vpinfe_config_ini,
    "version_json": PCO_PATHS.version_json,
    "firstrun_json": PCO_PATHS.firstrun_json,
    "screens_json": PCO_PATHS.screens_json,
    "webapp_screen_autostart_conf": PCO_PATHS.webapp_screen_autostart_conf,
}


def pco_path(name: str) -> Path:
    try:
        return PATH_ALIASES[name]
    except KeyError as exc:
        raise KeyError(f"Chemin PinCabOS inconnu: {name}") from exc


@dataclass(frozen=True)
class PinCabOSServices:
    web: str = "pincabos-web.service"
    console: str = "pincabos-console.service"
    vpinfe: str = "pincabos-vpinfe.service"
    frontend_compat: str = "pincabos-vpinfe.service"
    nginx: str = "nginx"


PCO_SERVICES = PinCabOSServices()

SERVICE_ALIASES: Mapping[str, str] = {
    "web": PCO_SERVICES.web,
    "console": PCO_SERVICES.console,
    "vpinfe": PCO_SERVICES.vpinfe,
    "frontend": PCO_SERVICES.vpinfe,
    "frontend_compat": PCO_SERVICES.frontend_compat,
    "nginx": PCO_SERVICES.nginx,
}


def pco_service(name: str) -> str:
    return SERVICE_ALIASES.get(name, name)


def pco_vpinfe_service_name() -> str:
    return PCO_SERVICES.vpinfe


def pco_frontend_compat_service_name() -> str:
    return PCO_SERVICES.frontend_compat


SCRIPT_ALIASES: Mapping[str, Path] = {
    # Updates
    "update_vpinfe": PCO_PATHS.tools / "update-vpinfe.sh",
    "update_vpx": PCO_PATHS.tools / "update-vpx.sh",
    "update_system": PCO_PATHS.tools / "update-system.sh",
    "update_all": PCO_PATHS.tools / "update-all.sh",
    "update_gpu": PCO_PATHS.tools / "update-gpu-drivers.sh",
    "apply_update": PCO_PATHS.tools / "pincabos-apply-update.sh",

    # Publish / cleanup
    "cleanup": PCO_PATHS.tools / "pincabos-cleanup.sh",
    "publish": PCO_PATHS.tools / "publish.sh",
    "publish_safe_check": PCO_PATHS.tools / "pincabos-publish-safe-check.sh",
    "publish_tree": PCO_PATHS.tools / "pincabos-publish-tree.sh",

    # First-run / detection
    "network_detect": PCO_PATHS.tools / "firstrun-network-detect.sh",
    "firstrun_network_detect": PCO_PATHS.tools / "firstrun-network-detect.sh",
    "detect_gpu": PCO_PATHS.tools / "detect-gpu.sh",
    "auto_detect_screens": PCO_PATHS.tools / "auto-detect-screens.sh",
    "detect_screens": PCO_PATHS.tools / "detect-screens.sh",
    "apply_screens": PCO_PATHS.tools / "apply-screens.sh",
    "audio_ssf_apply": PCO_PATHS.tools / "audio-ssf-apply.sh",

    # Network / WiFi
    "network_current_mode": PCO_PATHS.tools / "network-current-mode.sh",
    "network_info": PCO_PATHS.tools / "network-info.sh",
    "network_set_dhcp": PCO_PATHS.tools / "network-set-dhcp.sh",
    "network_set_static": PCO_PATHS.tools / "network-set-static.sh",
    "wifi_scan": PCO_PATHS.tools / "wifi-scan.sh",
    "wifi_join": PCO_PATHS.tools / "wifi-join.sh",
    "wifi_hotspot": PCO_PATHS.tools / "wifi-hotspot.sh",
    "wifi_hotspot_stop": PCO_PATHS.tools / "wifi-hotspot-stop.sh",

    # WebApp screens / calibrators
    "launch_webapp_screen": PCO_PATHS.tools / "launch-webapp-screen.sh",
    "close_webapp_screen": PCO_PATHS.tools / "close-webapp-screen.sh",
    "launch_dmd_calibrator": PCO_PATHS.tools / "launch-dmd-calibrator.sh",
    "close_dmd_calibrator": PCO_PATHS.tools / "close-dmd-calibrator.sh",
    "launch_fulldmd_calibrator": PCO_PATHS.tools / "launch-fulldmd-calibrator.sh",
    "sync_dmd_calibrations": PCO_PATHS.tools / "pincabos-sync-dmd-calibrations.sh",

    # DOF / cabinet
    "dof_driver_status": PCO_PATHS.tools / "pincabos-dof-driver-status.sh",
    "dof_commander_test_output": PCO_PATHS.tools / "dof-commander-test-output.sh",
    "install_dof_component": PCO_PATHS.tools / "install-dof-component.sh",

    # Import / normalize / VPS
    "import_portable_normalize": PCO_PATHS.tools / "pincabos-import-portable-normalize.py",
    "smart_archive_import": PCO_PATHS.tools / "pincabos-smart-archive-import.py",
    "vpinfe_vpx_standard": PCO_PATHS.tools / "pincabos-vpinfe-vpx-standard.py",
    "vpinfe_vpsdb_match": PCO_PATHS.tools / "vpinfe-vpsdb-match.py",

    # Admin / console / SMB
    "console": PCO_PATHS.tools / "run-console.sh",
    "change_root_password": PCO_PATHS.tools / "change-root-password.sh",
    "admin_iso_game_mode": PCO_PATHS.tools / "pincabos-admin-iso-game-mode.sh",
    "smb_mount_helper": PCO_PATHS.tools / "pincabos-smb-mount-helper.sh",
}


def pco_script(name: str) -> Path:
    try:
        return SCRIPT_ALIASES[name]
    except KeyError as exc:
        raise KeyError(f"Script PinCabOS inconnu: {name}") from exc


def pco_shell_join(cmd: Sequence[str | Path]) -> str:
    return " ".join(shlex.quote(str(x)) for x in cmd)


def pco_sudo_script_cmd(name: str, *args: str | Path) -> list[str]:
    return ["/usr/bin/sudo", str(pco_script(name)), *[str(a) for a in args]]


def pco_systemctl_cmd(action: str, service: str) -> list[str]:
    return ["/usr/bin/sudo", "/usr/bin/systemctl", action, pco_service(service)]


def pco_run(cmd: Sequence[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)


def pco_cmd_text(cmd: Sequence[str], timeout: int = 8) -> str:
    try:
        result = pco_run(cmd, timeout=timeout)
        return ((result.stdout or "") + (result.stderr or "")).strip()
    except Exception as exc:
        return f"Erreur commande {pco_shell_join(cmd)}: {exc}"


def pco_service_status(service: str, timeout: int = 3) -> str:
    try:
        result = pco_run(["/bin/systemctl", "is-active", pco_service(service)], timeout=timeout)
        return (result.stdout or "unknown").strip() or "unknown"
    except Exception:
        return "unknown"


def pco_env_web_host() -> str:
    return os.environ.get("PINCABOS_WEB_HOST", os.environ.get("PCO_WEB_HOST", "127.0.0.1"))


def pco_env_web_port() -> int:
    return int(os.environ.get("PINCABOS_WEB_PORT", os.environ.get("PCO_WEB_PORT", "5055")))


# Noms compatibles avec app.py pendant transition.
PINCABOS_VPX_EXECUTABLE = PCO_PATHS.vpx_wrapper
PINCABOS_VPX_TABLES_DIR = PCO_PATHS.tables
PINCABOS_VPX_INI = PCO_PATHS.vpx_ini

PINCABOS_VPINFE_ROOT = PCO_PATHS.vpinfe_root
PINCABOS_VPINFE_CURRENT = PCO_PATHS.vpinfe_current
PINCABOS_VPINFE_INI = PCO_PATHS.vpinfe_runtime_ini
PINCABOS_VPINFE_CONFIG_INI = PCO_PATHS.vpinfe_config_ini
PINCABOS_VPINFE_TEMPLATE_INI = PCO_PATHS.vpinfe_template_ini
PINCABOS_VPINFE_BIN = PCO_PATHS.vpinfe_bin


def pincabos_vpx_executable_path() -> Path:
    return PCO_PATHS.vpx_wrapper


def pincabos_vpx_tables_dir() -> Path:
    return PCO_PATHS.tables


def pincabos_vpx_ini_path() -> Path:
    return PCO_PATHS.vpx_ini


def pincabos_vpinfe_ini_path() -> Path:
    return PCO_PATHS.vpinfe_runtime_ini


def pincabos_vpinfe_config_ini_path() -> Path:
    return PCO_PATHS.vpinfe_config_ini


def pco_path_text(name: str) -> str:
    return str(pco_path(name))


def pco_script_text(name: str) -> str:
    return str(pco_script(name))


def pco_vpx_kill_pattern() -> str:
    parts = [
        str(PCO_PATHS.vpx_wrapper),
        str(PCO_PATHS.vpx_runner),
        "VPinballX",
    ]
    return "|".join(parts)


def pco_vpx_version_command() -> str:
    exe = shlex.quote(str(PCO_PATHS.vpx_wrapper))
    return f"{exe} -version 2>/dev/null || {exe} --version 2>/dev/null || echo 'non détectée'"


def pco_vpinfe_version_command() -> str:
    # Lecture passive: ne jamais lancer le frontend pour afficher sa version.
    return "/usr/bin/python3 /opt/pincabos/tools/vpinfeupdate.py --version-text 2>/dev/null || echo 'non détectée'"


def pco_launch_webapp_screen_command(screen_id: int, url: str = "http://127.0.0.1/") -> str:
    script = shlex.quote(str(pco_script("launch_webapp_screen")))
    return f"sleep 1; /usr/bin/sudo {script} {int(screen_id)} {shlex.quote(str(url))}"


# ---- Helpers partagés par app.py et les modules de pages (PINCABOS_WEBAPP_MODULES_V1) ----

def esc(x):
    return html.escape(str(x))


def run_cmd(cmd, timeout=8):
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"Erreur commande {' '.join(cmd)}: {e}"


def shlex_quote(value):
    import shlex
    return shlex.quote(str(value))


def service_status(name):
    return pco_service_status(name)


# ---- Écritures de configuration tracées (sauvegarde + méta), partagées (PINCABOS_WEBAPP_MODULES_V1) ----

def pincabos_meta(function_name):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "modified_at": stamp,
        "modified_by": "PinCabOS",
        "function": function_name
    }


def pincabos_backup_config_file(src, function_name="config"):
    src = Path(src)
    if not src.exists():
        return None

    safe_function = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(function_name)).strip("_") or "config"
    backup_dir = Path("/opt/pincabos/backups/config-writes") / safe_function
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / f"{src.name}.backup-{stamp}"
    shutil.copy2(src, dst)
    return dst


def pincabos_write_json_with_meta(path, data, function_name):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(data, dict):
        data["_pincabos_meta"] = pincabos_meta(function_name)

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ---- Adresse IP de la machine (PINCABOS_WEBAPP_MODULES_V1) ----

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "inconnue"


# ---- Chemins VPinFE / PinCabOS utilisés par les outils (Commander, export) (PINCABOS_WEBAPP_MODULES_V1) ----

def pincabos_get_vpinfe_paths_for_tools():
    """
    Chemins utilisés par VPinFE / PinCabOS.
    On lit tablerootdir si disponible, sinon on utilise le chemin PinCabOS standard.
    """
    from pathlib import Path

    cfg_path = pincabos_vpx_ini_path()

    result = {
        "config": str(cfg_path),
        "tables": "/home/pinball/Tables",
        "roms": "/home/pinball/.vpinball/pinmame/roms",
        "altcolor": "/home/pinball/.vpinball/pinmame/altcolor",
        "altsound": "/home/pinball/.vpinball/pinmame/altsound",
        "pupvideos": "/home/pinball/.vpinball/pupvideos",
        "ultradmd": "/home/pinball/.vpinball/ultradmd",
        "exports": "/home/pinball/Exports",
    }

    if cfg_path.exists():
        try:
            for line in cfg_path.read_text(errors="replace").splitlines():
                if "=" not in line:
                    continue

                key, value = [x.strip() for x in line.split("=", 1)]

                if key.lower() == "tablerootdir" and value:
                    result["tables"] = value
        except Exception:
            pass

    tables = Path(result["tables"])
    root = tables.parent if tables.exists() else Path("/home/pinball")

    result["roms"] = str(root / "PinMAME" / "roms")
    result["altcolor"] = str(root / "PinMAME" / "altcolor")
    result["altsound"] = str(root / "PinMAME" / "altsound")

    return result


# ---- Fichier maître version.json (PINCABOS_WEBAPP_MODULES_V1) ----

def pincabos_version():
    version_file = Path("/opt/pincabos/config/version.json")
    default = {
        "name": "PinCabOS",
        "version": "Development",
        "build": "dev",
        "author": "Karots Sugarpie",
    }

    try:
        if version_file.exists():
            data = json.loads(version_file.read_text())
            default.update(data)
    except Exception:
        pass

    return default


# ---- Configuration de la première exécution (PINCABOS_WEBAPP_AUTONOMIE_V1 : lue par le gabarit et le wizard) ----

PINCABOS_FIRSTRUN_CFG = "/opt/pincabos/config/firstrun.json"


def firstrun_default_cfg():
    return {
        "show_popup": True,
        "network": False,
        "gpu": False,
        "screens": False,
    }


def firstrun_required_keys():
    return ["network", "gpu", "screens"]


def firstrun_load_cfg():
    from pathlib import Path
    import json

    cfg = firstrun_default_cfg()
    p = Path(PINCABOS_FIRSTRUN_CFG)

    if p.exists():
        try:
            data = json.loads(p.read_text(errors="replace"))
            if isinstance(data, dict):
                for key in cfg.keys():
                    if key in data:
                        cfg[key] = data[key]
        except Exception:
            pass

    return cfg
