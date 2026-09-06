# PinCabOS Dashboard Lobby V13 — modular dashboard board
from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote


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

MARKER = "PCO-DASHBOARD-LOBBY-V13"
WEB_ROOT = Path("/opt/pincabos/web")
STATIC_ROOT = WEB_ROOT / "static"
TABLES_ROOT = Path("/home/pinball/Tables")
LAYOUT_PATH = Path("/home/pinball/.config/pincabos/dashboard-layout.json")
GRID_COLUMNS = 12
MAX_GRID_ROWS = 240
_STATUS_LOCK = threading.Lock()
_STATUS_CACHE = {"at": 0.0, "value": {}}
_CPU_SAMPLE = {"total": None, "idle": None}


def _pco_engine_pincabos_kv(kv):
    """Ligne PinCabOS (version installee + statut) depuis l'etat agrege."""
    try:
        data = json.loads(Path(
            "/opt/pincabos/state/updates-available.json"
        ).read_text(encoding="utf-8"))
        c = next(x for x in (data.get("components") or [])
                 if x.get("key") == "pincabos")
    except Exception:
        return ""
    inst = c.get("installed") or "—"
    if c.get("update_available"):
        return kv("PinCabOS", f"{inst} → {c.get('available')}")
    return kv("PinCabOS", f"{inst} (à jour)")


def _pco_engine_maj_html(kv):
    """Resume des MAJ logiciels pour la tuile Moteur Pinball, depuis l'etat
    agrege ecrit par pincabos-updates-check. Un bouton mene a la page des
    mises a jour quand au moins un composant en a une."""
    try:
        data = json.loads(Path(
            "/opt/pincabos/state/updates-available.json"
        ).read_text(encoding="utf-8"))
    except Exception:
        return ""
    dispo = [c for c in (data.get("components") or [])
             if c.get("update_available")]
    if not dispo:
        return kv("Mises \u00e0 jour", "Tout \u00e0 jour")
    n = len(dispo)
    libelle = ("\u25cf %d mises \u00e0 jour \u2014 voir" % n) if n > 1 \
        else "\u25cf 1 mise \u00e0 jour \u2014 voir"
    return (
        '<a href="/tools/updates-all" '
        'style="display:inline-block;align-self:center;'
        'margin:2px 0 8px;padding:6px 12px;border-radius:8px;'
        'border:1px solid var(--accent);background:var(--panel2);'
        'color:var(--accent);text-decoration:none;font-weight:700;font-size:11px;">'
        + libelle + '</a>')


def run(command: str, fallback: str = "—", timeout: int = 3) -> str:
    try:
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", command],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        value = (result.stdout or "").strip()
        return value if value else fallback
    except Exception:
        return fallback


def x11_run(command: str, fallback: str = "", timeout: int = 4) -> str:
    shell = (
        "runuser -u pinball -- env DISPLAY=:0 XAUTHORITY=/home/pinball/.Xauthority "
        "XDG_RUNTIME_DIR=/run/user/1000 " + command
    )
    return run(shell, fallback, timeout)


def number(value, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except Exception:
        return default


def human_size(value) -> str:
    value = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit in {"B", "KiB"} else f"{value:.1f} {unit}"
        value /= 1024
    return "—"


def cpu_percent() -> float:
    try:
        values = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        before_total = _CPU_SAMPLE["total"]
        before_idle = _CPU_SAMPLE["idle"]
        _CPU_SAMPLE.update({"total": total, "idle": idle})
        if before_total is None or total <= before_total:
            return 0.0
        return max(0.0, min(100.0, (1 - ((idle - before_idle) / (total - before_total))) * 100))
    except Exception:
        return 0.0


def memory_info():
    data = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            data[key] = int(value.split()[0]) * 1024
    except Exception:
        pass
    total = data.get("MemTotal", 0)
    used = max(0, total - data.get("MemAvailable", 0))
    return total, used, round((used / total * 100) if total else 0.0, 1)


def disk_info(path: str):
    try:
        stat = shutil.disk_usage(path)
        return stat.total, stat.used, stat.free, round((stat.used / stat.total * 100) if stat.total else 0.0, 1)
    except Exception:
        return 0, 0, 0, 0.0


def service_state(unit: str):
    state = run(f"systemctl is-active {unit} 2>/dev/null", "unknown", 2).lower()
    if state == "active":
        return {"level": "ok", "label": "Actif"}
    if state == "activating":
        return {"level": "warn", "label": "Démarrage"}
    if state in {"inactive", "failed"}:
        return {"level": "bad", "label": state.capitalize()}
    return {"level": "muted", "label": "Non détecté"}


def table_count() -> int:
    try:
        return sum(1 for p in TABLES_ROOT.rglob("*.vpx") if p.is_file())
    except Exception:
        return 0


def asset(name: str) -> str:
    item = STATIC_ROOT / "pincabos-assets" / name
    return "/static/pincabos-assets/" + quote(name) if name and item.exists() else ""


def screen_specs():
    # PINCABOS_SCREEN_SPECS_HARDWARE_ADAPTIVE_V1
    # Source prioritaire : X11 actuel. Repli fiable : screens.json.
    import json
    import os
    import re
    import subprocess
    from pathlib import Path

    cfg_path = Path("/opt/pincabos/config/screens/screens.json")

    def configured_roles():
        role_order = (
            ("Playfield", "playfield"),
            ("Backglass", "backglass"),
            ("FullDMD", "fulldmd"),
        )
        result = []
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return result

        for slot, (label, key) in enumerate(role_order):
            item = data.get(key) or {}
            name = str(item.get("name") or "").strip()
            try:
                width = int(item.get("width"))
                height = int(item.get("height"))
                x = int(item.get("x"))
                y = int(item.get("y"))
            except (TypeError, ValueError):
                continue
            if not name or width <= 0 or height <= 0:
                continue
            result.append({
                "name": name,
                "width": width,
                "height": height,
                "x": x,
                "y": y,
                "primary": bool(item.get("is_primary")),
                "slot": slot,
                "role": label,
                "title": f"{label} Live · {name}",
                "subtitle": f"{width}×{height}+{x}+{y}",
            })
        return result

    def x11_screens():
        auth = ""
        try:
            proc = subprocess.run(
                ["ps", "-eo", "args="],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            match = re.search(r"Xorg .* -auth ([^ ]+)", proc.stdout)
            if match:
                auth = match.group(1)
        except Exception:
            pass

        if not auth or not os.path.isfile(auth) or not os.access(auth, os.R_OK):
            return []

        env = os.environ.copy()
        env["DISPLAY"] = ":0"
        env["XAUTHORITY"] = auth

        try:
            proc = subprocess.run(
                ["xrandr", "--query"],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return []

        if proc.returncode != 0:
            return []

        found = []
        for line in proc.stdout.splitlines():
            if " connected" not in line:
                continue
            name = line.split()[0]
            match = re.search(r"(\d+)x(\d+)\+(\d+)\+(\d+)", line)
            if not match:
                continue
            width, height, x, y = (int(value) for value in match.groups())
            found.append({
                "name": name,
                "width": width,
                "height": height,
                "x": x,
                "y": y,
                "primary": " primary " in (" " + line + " "),
            })
        return found

    configured = configured_roles()
    role_by_name = {item["name"]: item for item in configured}
    found = x11_screens() or configured

    if not found:
        return []

    for item in found:
        saved = role_by_name.get(item["name"])
        if saved:
            item["slot"] = saved["slot"]
            item["role"] = saved["role"]
        else:
            item["slot"] = 99
            item["role"] = ""

    found.sort(key=lambda item: (item["slot"], item["x"], item["y"], item["name"]))

    fallback_roles = ("Playfield", "Backglass", "FullDMD")
    for index, item in enumerate(found):
        if item["slot"] == 99:
            item["slot"] = index
        if not item["role"]:
            item["role"] = fallback_roles[index] if index < len(fallback_roles) else f"Écran {index + 1}"
        item["title"] = f'{item["role"]} Live · {item["name"]}'
        item["subtitle"] = f'{item["width"]}×{item["height"]}+{item["x"]}+{item["y"]}'

    return found


BASE_REGISTRY = {
    "system": {"title": "Système", "subtitle": "Hôte, noyau et disponibilité", "category": "Système", "kind": "system", "w": 3, "h": 3},
    "cpu": {"title": "CPU", "subtitle": "Utilisation processeur", "category": "Système", "kind": "cpu", "w": 3, "h": 3},
    "memory": {"title": "Mémoire", "subtitle": "RAM utilisée et libre", "category": "Système", "kind": "memory", "w": 3, "h": 3},
    "storage": {"title": "HDD / stockage", "subtitle": "Disques, partitions et utilisation", "category": "Système", "kind": "storage", "w": 3, "h": 3},
    "gpu": {"title": "GPU / écrans", "subtitle": "NVIDIA, VRAM et pilote", "category": "Système", "kind": "gpu", "w": 3, "h": 3},
    "services": {"title": "Services", "subtitle": "État et contrôles sécurisés", "category": "Système", "kind": "services", "w": 4, "h": 6},
    "time": {"title": "Heure / NTP", "subtitle": "Fuseau, source et synchronisation", "category": "Système", "kind": "time", "w": 4, "h": 5},
    "network": {"title": "Réseau", "subtitle": "IP, passerelle, IP Internet et lien", "category": "Système", "kind": "network", "w": 4, "h": 6},
    "journal": {"title": "Journal WebApp", "subtitle": "Derniers événements du tableau de bord", "category": "Système", "kind": "journal", "w": 4, "h": 4},
    "tables": {"title": "Bibliothèque Tables", "subtitle": "Tables VPX installées", "category": "Pinball", "kind": "tables", "w": 3, "h": 3},
    "engine": {"title": "Moteur Pinball", "subtitle": "VPX, VPinFE et disponibilité", "category": "Pinball", "kind": "engine", "w": 3, "h": 5},
    "audio": {"title": "Audio", "subtitle": "Cartes et routage attendu", "category": "Pinball", "kind": "audio", "w": 3, "h": 3},
    "dof_usb": {"title": "DOF / USB", "subtitle": "Périphériques détectés — lecture seule", "category": "Pinball", "kind": "dof_usb", "w": 3, "h": 3},
}

# PINCABOS_DASHBOARD_TOOL_CATALOG_SYNC_V1
# Catalogue synchronisé avec les cartes réelles
# de la page Outils PinCabOS.
#
# On utilise les routes canoniques afin que
# tool_registry() les détecte directement dans
# current_app.url_map.

TOOL_SPECS = (

    (
        "keyboard",
        "Clavier système",
        "Disposition US, FR et internationale",
        "/keyboard",
        "PCOSKeyboard.png",
    ),

    (
        "inputs",
        "Map Commander",
        "Boutons, axes, nudge et plunger",
        "/inputs/map-commander",
        "PCOSMapInputs.png",
    ),

    (
        "outputs",
        "DOF Commander",
        "Sorties, toys et contrôleurs DOF",
        "/dof/commander",
        "PCOSDOFOutpouts.png",
    ),

    (
        "audio",
        "Audio / SSF",
        "Cartes ALSA, rôles et routage audio",
        "/audio-ssf",
        "PCOSAudioSSF.png",
    ),

    (
        "gpu",
        "GPU / Écrans",
        "GPU, affichages et VPX",
        "/gpu",
        "PCOSEcransGPUVPX.png",
    ),

    (
        "screens",
        "Écrans",
        "Détection et réglage des écrans",
        "/gpu",
        "PCOSEcransGPUVPX.png",
    ),

    (
        "fulldmd",
        "FullDMD",
        "Affichage et configuration FullDMD",
        "/fulldmd",
        "PCOSFullDMDConfigurator.png",
    ),

    (
        "dmd",
        "DMD",
        "Cadre, calibrage et affichage DMD",
        "/fulldmd",
        "PCOSFullDMDConfigurator.png",
    ),

    (
        "auto_screens",
        "Auto-écrans",
        "Détection automatique",
        "/auto-screens",
        "PCOSEcransGPUVPX.png",
    ),

    (
        "ballcab",
        "VPX Ball Cabinet",
        "Réglages bille et cabinet",
        "/tools/vpx-ball-cabinet",
        "PCOSVPXBallCabinet.png",
    ),

    (
        "vpx_ini",
        "VPinballX INI",
        "Configuration du moteur VPinballX",
        "/tools/vpinballx/ini",
        "PCOSConfigINIVPinballX.png",
    ),

    (
        "vpinfe_ini",
        "VPinFE INI",
        "Configuration VPinFE",
        "/tools/vpinfe/ini",
        "PCOSConfigINIVPinFE.png",
    ),

    (
        "console",
        "PinCab Console",
        "Console Web PinCabOS",
        "/console",
        "PCOSConsole.png",
    ),

    (
        "explorer",
        "PinCab Explorer",
        "Fichiers et médias PinCabOS",
        "/tools/commander",
        "PCOSExplorer.png",
    ),

    (
        "import",
        "Import de Tables Smart",
        "Importer et analyser une table",
        "/tools/import-table",
        "PCOSImport.png",
    ),

    (
        "export",
        "Export de Tables Smart",
        "Exporter table, médias et dépendances",
        "/tools/export-table",
        "PCOSExport.png",
    ),

    (
        "external_disks",
        "Gestion du stockage",
        "Disque interne, USB et partages réseau",
        "/tools/external-disks",
        "PCOSDisquesExternes.png",
    ),

    (
        "tables",
        "Tables VPinFE",
        "Bibliothèque et gestion des tables",
        "/tools/vpinfe/tables",
        "PCOSVPinFETablePage.png",
    ),

    (
        "network",
        "Réseau",
        "Ethernet, Wi-Fi et connectivité",
        "/network",
        "PCOSNetwork.png",
    ),

    (
        "appearance",
        "Apparence",
        "Style et personnalisation",
        "/tools/appearance",
        "PCOSApparence.png",
    ),

    (
        "vpinfe_sample_tables",
        "Tables de démonstration",
        "Gérer les tables d’exemple VPX",
        "/tools/vpinfe/sample-tables",
        "PCOSTablesVPinFE.png",
    ),

    (
        "vpinfe_collections",
        "Collections VPinFE",
        "Organiser les collections du frontend",
        "/tools/vpinfe/collections",
        "PCOSVPinFECollections.png",
    ),

    (
        "vpinfe_media",
        "Médias VPinFE",
        "Gérer les images et médias VPinFE",
        "/tools/vpinfe/media",
        "PCOSVPinFEMediasPage.png",
    ),

    (
        "media_recorder",
        "PinCab Recorder",
        "Créer les médias Playfield, Backglass, FullDMD et Topper",
        "/tools/media-recorder",
        "PCOSRecorder.png",
    ),

    (
        "media_hunter",
        "Medias Hunter",
        "Chercher et compléter les médias manquants",
        "/tools/vpinfe/media-hunter",
        "PCOSMediaHunter.png",
    ),
)


TOOL_CATEGORIES = {

    "gpu": "Outils VPX",
    "screens": "Outils VPX",
    "fulldmd": "Outils VPX",
    "dmd": "Outils VPX",
    "auto_screens": "Outils VPX",
    "ballcab": "Outils VPX",
    "vpx_ini": "Outils VPX",

    "vpinfe_ini": "Outils VPinFE",
    "tables": "Outils VPinFE",
    "vpinfe_sample_tables": "Outils VPinFE",
    "vpinfe_collections": "Outils VPinFE",
    "vpinfe_media": "Outils VPinFE",
    "media_recorder": "Outils VPinFE",
    "media_hunter": "Outils VPinFE",
}

def available_paths():
    try:
        from flask import current_app
        return {rule.rule for rule in current_app.url_map.iter_rules() if "GET" in rule.methods}
    except Exception:
        return set()


def tool_registry():
    paths = available_paths()
    canonical_paths = {}
    for path in paths:
        canonical_paths.setdefault(path.rstrip("/") or "/", path)
    registry = {}
    for key, title, subtitle, href, image in TOOL_SPECS:
        canonical = href.rstrip("/") or "/"
        actual_href = canonical_paths.get(canonical)
        if not actual_href:
            continue
        registry[f"tool_{key}"] = {
            "title": title,
            "subtitle": subtitle,
            "category": TOOL_CATEGORIES.get(key, "Outils PinCabOS"),
            "kind": "tool",
            "w": 3,
            "h": 4,
            "href": actual_href,
            "image": image,
        }
    return registry

LIVE_SCREEN_FALLBACKS = (
    {"slot": 0, "role": "Playfield", "name": "HDMI-0", "width": 3840, "height": 2160, "x": 0, "y": 0},
    {"slot": 1, "role": "Backglass", "name": "DP-1", "width": 1920, "height": 1080, "x": 3840, "y": 0},
    {"slot": 2, "role": "FullDMD", "name": "DP-2", "width": 1024, "height": 768, "x": 5760, "y": 0},
)

def live_registry():
    detected = {int(item.get("slot", -1)): dict(item) for item in screen_specs()}
    result = {}
    for slot, fallback in enumerate(LIVE_SCREEN_FALLBACKS):
        screen = dict(fallback)
        screen.update(detected.get(slot, {}))
        role = ("Playfield", "Backglass", "FullDMD")[slot]
        screen["slot"] = slot
        screen["role"] = role
        screen["title"] = f"{role} Live · {screen['name']}"
        suffix = "" if slot in detected else " · X11 en attente"
        screen["subtitle"] = f"{screen['width']}×{screen['height']}+{screen['x']}+{screen['y']}" + suffix
        result[f"live_{slot}"] = {
            "title": screen["title"], "subtitle": screen["subtitle"], "category": "Écrans live", "kind": "live",
            "w": 4 if slot == 0 else 3, "h": 5, "slot": slot,
        }
    return result


# PINCABOS_AUDIO_VOLUME_DASHBOARD_WIDGET_V3_CONFIG START
def audio_volume_dashboard_template():
    return """<template data-pco-template="audio_volume">
  <article class="pco-card pco-audio-volume-card" data-pco-audio-volume-widget="1">
    <div class="pco-card-edit pco-edit-only">
      <button class="pco-grip" type="button" draggable="true" title="Déplacer">⋮⋮</button>
      <button class="pco-remove" type="button" title="Retirer">×</button>
    </div>
    <header class="pco-card-head">
      <div>
        <strong>Volumes audio</strong>
        <span>Cartes ALSA · sorties sélectionnées</span>
      </div>
      <div class="pco-audio-volume-head-actions">
        <button class="pco-audio-volume-refresh" type="button" title="Rafraîchir">↻</button>
        <button class="pco-audio-volume-gear" type="button" title="Configurer les sorties affichées">⚙</button>
      </div>
    </header>
    <div class="pco-audio-volume-config" data-pco-audio-volume-config hidden>
      <div class="pco-av-config-title">Sorties affichées</div>
      <div class="pco-av-config-list" data-pco-audio-volume-config-list>
        <div class="pco-audio-volume-loading">Chargement des sorties…</div>
      </div>
      <div class="pco-av-config-actions">
        <button type="button" data-pco-av-select-all>Tout</button>
        <button type="button" data-pco-av-select-none>Aucun</button>
        <button type="button" class="pco-av-config-save" data-pco-av-save>Enregistrer</button>
      </div>
    </div>
    <div class="pco-audio-volume-body" data-pco-audio-volume-body>
      <div class="pco-audio-volume-loading">Chargement audio…</div>
    </div>
    <button class="pco-resize pco-edit-only" type="button" title="Redimensionner">◢</button>
  </article>
</template>"""
# PINCABOS_AUDIO_VOLUME_DASHBOARD_WIDGET_V3_CONFIG END

def registry_for_request():
    result = {key: dict(value) for key, value in BASE_REGISTRY.items()}
    result.update(live_registry())
    result.update(tool_registry())

    # === PINCABOS_DASHBOARD_SHORTCUTS_FAMILIES_LOGOS_V1 START ===
    shortcut_overrides = {
        "tool_appearance": ("Outils PinCabOS", "PCOSApparence.png"),
        "tool_audio": ("Outils PinCabOS", "PCOSAudioSSF.png"),
        "tool_console": ("Outils PinCabOS", "PCOSConsole.png"),
        "tool_explorer": ("Outils PinCabOS", "PCOSExplorer.png"),
        "tool_export": ("Outils PinCabOS", "PCOSExport.png"),
        "tool_external_disks": ("Outils PinCabOS", "PCOSDisquesExternes.png"),
        "tool_import": ("Outils PinCabOS", "PCOSImport.png"),
        "tool_inputs": ("Outils PinCabOS", "PCOSMapInputs.png"),
        "tool_keyboard": ("Outils PinCabOS", "PCOSKeyboard.png"),
        "tool_network": ("Outils PinCabOS", "PCOSNetwork.png"),
        "tool_outputs": ("Outils PinCabOS", "PCOSDOFOutpouts.png"),

        "tool_ballcab": ("Outils VPX", "PCOSVPXBallCabinet.png"),
        "tool_dmd": ("Outils VPX", "PCOSEcransGPUVPX.png"),
        "tool_fulldmd": ("Outils VPX", "PCOSFullDMDConfigurator.png"),
        "tool_gpu": ("Outils VPX", "PCOSEcransGPUVPX.png"),
        "tool_screens": ("Outils VPX", "PCOSEcransGPUVPX.png"),

        "tool_tables": ("Outils VPinFE", "PCOSTablesVPinFE.png"),
        "tool_vpinfe_ini": ("Outils VPinFE", "PCOSConfigINIVPinFE.png"),
    }

    for widget_id, (category, image_name) in shortcut_overrides.items():
        meta = result.get(widget_id)
        if not isinstance(meta, dict):
            continue
        meta["category"] = category
        meta["image"] = image_name
        meta["image_url"] = f"/static/pincabos-assets/{image_name}"

    result["tool_vpinfe_update"] = {
        "title": "Update VPinFE",
        "subtitle": "Version locale, GitHub et mise à jour",
        "category": "Outils VPinFE",
        "kind": "tool",
        "w": 2,
        "h": 3,
        "href": "/tools/vpinfe/update",
        "image": "PCOSUpdateVPinFE.png",
        "image_url": "/static/pincabos-assets/PCOSUpdateVPinFE.png",
    }
    result["tool_vpxtool_update"] = {
        "title": "Update vpxtool",
        "subtitle": "Moteur .dif / VPU Remix — version et mise à jour",
        "category": "Pinball",
        "kind": "tool",
        "w": 2,
        "h": 3,
        "href": "/tools/vpxtool/update",
        "image": "PCOSUpdateVPX.png",
        "image_url": "/static/pincabos-assets/PCOSUpdateVPX.png",
    }

    # === PINCABOS_DASHBOARD_SHORTCUTS_FAMILIES_LOGOS_V1 END ===

    # PINCABOS_AUDIO_VOLUME_DASHBOARD_WIDGET_V2_REGISTRY
    result["audio_volume"] = {
        "title": "Volumes audio",
        "subtitle": "Sliders horizontaux pour les cartes ALSA",
        "category": "Audio",
        "kind": "widget",
        "w": 4,
        "h": 5,
    }
    return result


def default_layout(registry=None):
    registry = registry or registry_for_request()
    wanted = [
        ("system", 0, 0, 3, 3), ("cpu", 3, 0, 3, 3), ("memory", 6, 0, 3, 3), ("gpu", 9, 0, 3, 3),
        ("services", 0, 3, 4, 6), ("storage", 4, 3, 4, 4), ("tables", 8, 3, 4, 4),
        ("time", 4, 7, 4, 5), ("network", 8, 7, 4, 6), ("engine", 8, 13, 4, 3),
        ("audio", 0, 9, 3, 3), ("dof_usb", 0, 12, 3, 3), ("journal", 4, 12, 4, 4),
        ("live_0", 0, 16, 6, 6), ("live_1", 6, 16, 3, 5), ("live_2", 9, 16, 3, 5),
    ]
    result = []
    for widget_id, x, y, w, h in wanted:
        if widget_id in registry:
            result.append({"id": widget_id, "x": x, "y": y, "w": w, "h": h})
    return result


def sanitize_layout(layout, registry=None):
    registry = registry or registry_for_request()
    if not isinstance(layout, list):
        return default_layout(registry)
    legacy = {"hdd": "storage", "dofusb": "dof_usb", "live_pf": "live_0", "live_bg": "live_1", "live_dmd": "live_2"}
    result, seen = [], set()
    for raw in layout[:80]:
        if not isinstance(raw, dict):
            continue
        widget_id = legacy.get(str(raw.get("id", "")), str(raw.get("id", "")))
        if widget_id not in registry or widget_id in seen:
            continue
        meta = registry[widget_id]
        try:
            width = max(1, min(GRID_COLUMNS, int(raw.get("w", meta["w"]))))
            height = max(1, min(20, int(raw.get("h", meta["h"]))))
            x = max(0, min(GRID_COLUMNS - width, int(raw.get("x", 0))))
            y = max(0, min(MAX_GRID_ROWS, int(raw.get("y", 0))))
        except Exception:
            continue
        seen.add(widget_id)
        result.append({"id": widget_id, "x": x, "y": y, "w": width, "h": height})
    return result or default_layout(registry)


def load_layout(registry=None):
    registry = registry or registry_for_request()
    try:
        return sanitize_layout(json.loads(LAYOUT_PATH.read_text(encoding="utf-8")), registry)
    except Exception:
        return default_layout(registry)


def save_layout(layout, registry=None):
    registry = registry or registry_for_request()
    safe = sanitize_layout(layout, registry)
    LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = LAYOUT_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    try:
        shutil.chown(temporary, user="pinball", group="pinball")
    except Exception:
        pass
    os.replace(temporary, LAYOUT_PATH)
    return safe


# === PINCABOS_DASHBOARD_MODES_V1 START ===
#
# Deux vues, chacune avec sa grille. Les libelles sont ici et nulle part
# ailleurs.
MODE_PATH = Path("/home/pinball/.config/pincabos/dashboard-mode.json")
MODE_DEFAUT = "pro"
MODE_LABELS = {
    "simple": "Simple",
    "pro": "Pro",
}


def mode_layout_path(mode: str) -> Path:
    return LAYOUT_PATH.with_name(f"dashboard-layout-{mode}.json")


def simple_layout(registry=None):
    """Gabarit Simple : ce qu'un proprietaire regarde la premiere semaine.

    Ses ecrans, et les six outils du quotidien. Rien sur la charge
    processeur ni les services : une vue simple se voit a l'oeil nu.
    """
    registry = registry or registry_for_request()
    wanted = [
        ("live_0", 0, 0, 6, 6), ("live_1", 6, 0, 3, 5), ("live_2", 9, 0, 3, 5),
        ("tool_import", 0, 6, 2, 4), ("tool_tables", 2, 6, 2, 4), ("tool_screens", 4, 6, 2, 4),
        ("tool_external_disks", 6, 6, 2, 4), ("tool_network", 8, 6, 2, 4), ("tool_audio", 10, 6, 2, 4),
    ]
    result = []
    for widget_id, x, y, w, h in wanted:
        if widget_id in registry:
            result.append({"id": widget_id, "x": x, "y": y, "w": w, "h": h})
    return result or default_layout(registry)


def preset_layout(mode, registry=None):
    """Le gabarit d'origine d'une vue — ce que « Disposition par defaut » retablit."""
    registry = registry or registry_for_request()
    if mode == "simple":
        return simple_layout(registry)
    return default_layout(registry)


def _meme_disposition(a, b) -> bool:
    cle = lambda d: sorted((x["id"], x["x"], x["y"], x["w"], x["h"]) for x in d)
    try:
        return cle(a) == cle(b)
    except Exception:
        return False


def load_mode() -> str:
    try:
        value = json.loads(MODE_PATH.read_text(encoding="utf-8")).get("mode", "")
    except Exception:
        value = ""
    if value in MODE_LABELS:
        return value
    # Pas de fichier de mode : on reconnait la vue a sa disposition. Une
    # grille deja rangee a la main, sans etre un gabarit, est une vue Pro
    # personnalisee — on ne remplace jamais ce que le proprietaire a range.
    if LAYOUT_PATH.exists():
        registry = registry_for_request()
        actuelle = load_layout(registry)
        for mode in MODE_LABELS:
            if _meme_disposition(actuelle, preset_layout(mode, registry)):
                return mode
    return MODE_DEFAUT


def _ecrire_json_pinball(chemin: Path, contenu) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporary = chemin.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(contenu, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    try:
        shutil.chown(temporary, user="pinball", group="pinball")
    except Exception:
        pass
    os.replace(temporary, chemin)


def save_mode(mode: str) -> str:
    if mode not in MODE_LABELS:
        mode = MODE_DEFAUT
    _ecrire_json_pinball(MODE_PATH, {"mode": mode})
    return mode


def save_mode_layout(mode: str, layout, registry=None) -> None:
    """Memorise la grille d'une vue, pour la retrouver au prochain passage."""
    registry = registry or registry_for_request()
    _ecrire_json_pinball(mode_layout_path(mode), sanitize_layout(layout, registry))


def layout_for_mode(mode: str, registry=None):
    """La grille d'une vue : celle que le proprietaire a rangee, sinon le gabarit."""
    registry = registry or registry_for_request()
    try:
        return sanitize_layout(json.loads(mode_layout_path(mode).read_text(encoding="utf-8")), registry)
    except Exception:
        return preset_layout(mode, registry)


def modes_public():
    return [{"id": key, "label": label} for key, label in MODE_LABELS.items()]
# === PINCABOS_DASHBOARD_MODES_V1 END ===


def uptime() -> str:
    try:
        seconds = int(float(Path("/proc/uptime").read_text().split()[0]))
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        return f"{days}j {hours}h {seconds // 60}m"
    except Exception:
        return "—"


# === PINCABOS_DASHBOARD_VPX_SERVICE_V1 ===
def vpx_process_state():
    running = run(
        "pgrep -u pinball -f '(^|/)VPinballX(_BGFX)?([[:space:]]|$)' >/dev/null 2>&1 && echo running || true",
        "",
        2,
    ).strip() == "running"
    return {"level": "ok", "label": "Actif"} if running else {"level": "muted", "label": "Inactif"}


# === PINCABOS_DASHBOARD_REALTIME_HDD_NETWORK_V1 ===
# PINCABOS_STORAGE_MACOS_V2
#
# Stockage PinCabOS :
# - inventaire des disques physiques par lsblk
# - connecteur NVMe / SATA / USB / autre
# - partitions visibles sur une seule ligne
# - utilisation REELLE de Tables / logs / backups
# - autres partitions réservées séparément
# - cache 60 secondes afin de ne pas lancer du -sb
#   à chaque refresh du Dashboard.

_PCO_STORAGE_CACHE = {
    "at": 0.0,
    "value": None,
}


def storage_inventory(force=False):
    import json
    import os
    import shutil
    import subprocess
    import time

    now = time.monotonic()

    cached = _PCO_STORAGE_CACHE.get("value")

    if (
        not force
        and cached is not None
        and now - float(
            _PCO_STORAGE_CACHE.get("at") or 0.0
        ) < 60.0
    ):
        return cached


    def _run(args, timeout=15):
        try:
            result = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=timeout,
                check=False,
            )

            if result.returncode != 0:
                return ""

            return result.stdout.strip()

        except Exception:
            return ""


    def _json(args, timeout=15):
        raw = _run(
            args,
            timeout=timeout,
        )

        if not raw:
            return {}

        try:
            return json.loads(raw)
        except Exception:
            return {}


    def _human(value):
        try:
            value = int(value or 0)
        except Exception:
            value = 0

        units = (
            "B",
            "KiB",
            "MiB",
            "GiB",
            "TiB",
            "PiB",
        )

        amount = float(value)
        index = 0

        while (
            amount >= 1024.0
            and index < len(units) - 1
        ):
            amount /= 1024.0
            index += 1

        if index == 0:
            return f"{int(amount)} {units[index]}"

        if amount >= 100:
            return f"{amount:.0f} {units[index]}"

        if amount >= 10:
            return f"{amount:.1f} {units[index]}"

        return f"{amount:.2f} {units[index]}"


    def _du(pathname):
        if not os.path.isdir(pathname):
            return 0

        raw = _run(
            [
                "du",
                "-sbx",
                pathname,
            ],
            timeout=20,
        )

        if not raw:
            return 0

        try:
            return int(
                raw.split()[0]
            )
        except Exception:
            return 0


    def _normalize_source(source):
        source = str(
            source or ""
        ).strip()

        if "[" in source:
            source = source.split(
                "[",
                1,
            )[0]

        return source


    def _source_for(pathname):
        if not os.path.exists(pathname):
            return ""

        return _normalize_source(
            _run(
                [
                    "findmnt",
                    "-n",
                    "-o",
                    "SOURCE",
                    "-T",
                    pathname,
                ],
                timeout=5,
            )
        )


    def _mounts(node):
        raw = node.get("mountpoints")

        if raw is None:
            raw = node.get("mountpoint")

        if raw is None:
            return []

        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, list):
            values = raw
        else:
            values = []

        result = []

        for item in values:
            item = str(
                item or ""
            ).strip()

            if item and item not in result:
                result.append(item)

        return result


    def _connector(node):
        name = str(
            node.get("name") or ""
        )

        tran = str(
            node.get("tran") or ""
        ).strip().lower()

        if name.startswith("nvme"):
            return "NVMe"

        if tran in {
            "sata",
            "ata",
        }:
            return "SATA"

        if tran == "usb":
            return "USB"

        if tran in {
            "sas",
            "scsi",
        }:
            return tran.upper()

        if name.startswith("mmcblk"):
            return "eMMC / SD"

        if tran:
            return tran.upper()

        return "Autre"


    raw = _json(
        [
            "lsblk",
            "-bJ",
            "-o",
            (
                "NAME,PATH,TYPE,SIZE,MODEL,TRAN,"
                "FSTYPE,LABEL,PARTLABEL,MOUNTPOINTS"
            ),
        ],
        timeout=10,
    )


    blockdevices = list(
        raw.get("blockdevices")
        or []
    )


    # --------------------------------------------------------
    # Catégories PinCabOS connues.
    # --------------------------------------------------------

    known_paths = (
        (
            "tables",
            "/home/pinball/Tables",
        ),
        (
            "logs",
            "/opt/pincabos/logs",
        ),
        (
            "logs",
            "/var/log",
        ),
        (
            "backup",
            "/opt/pincabos/backups",
        ),
    )


    known_by_source = {}

    category_totals = {
        "tables": 0,
        "logs": 0,
        "backup": 0,
    }


    for category, pathname in known_paths:

        source = _source_for(
            pathname
        )

        size = _du(
            pathname
        )

        category_totals[
            category
        ] += size

        if not source:
            continue

        known_by_source.setdefault(
            source,
            {
                "tables": 0,
                "logs": 0,
                "backup": 0,
            },
        )

        known_by_source[
            source
        ][category] += size


    root_source = _source_for(
        "/"
    )


    boot_sources = set()

    for pathname in (
        "/boot",
        "/boot/efi",
    ):
        source = _source_for(
            pathname
        )

        if source:
            boot_sources.add(
                source
            )


    colors = {
        "system": "#ff453a",
        "tables": "#30d158",
        "logs": "#ffd60a",
        "backup": "#0a84ff",
        "unknown": "#ff6a3d",
        "other": "#bf5af2",
        "free": "rgba(255,255,255,.16)",
    }


    labels = {
        "system": "Fichiers système",
        "tables": "Tables",
        "logs": "Logs",
        "backup": "Backups",
        "unknown": "Inconnu",
        "other": "Autre partition",
        "free": "Libre",
    }


    disks = []


    for disk in blockdevices:

        if str(
            disk.get("type") or ""
        ) != "disk":
            continue


        disk_name = str(
            disk.get("name") or ""
        )

        disk_path = str(
            disk.get("path")
            or f"/dev/{disk_name}"
        )

        disk_size = int(
            disk.get("size")
            or 0
        )

        model = str(
            disk.get("model")
            or ""
        ).strip()

        if not model:
            model = disk_name


        connector = _connector(
            disk
        )


        partitions = []
        volumes = []


        def _walk(node):
            children = list(
                node.get("children")
                or []
            )

            node_type = str(
                node.get("type")
                or ""
            )

            if node_type == "part":

                part_name = str(
                    node.get("name")
                    or ""
                )

                part_path = str(
                    node.get("path")
                    or f"/dev/{part_name}"
                )

                part_size = int(
                    node.get("size")
                    or 0
                )

                fstype = str(
                    node.get("fstype")
                    or ""
                )

                label = str(
                    node.get("label")
                    or ""
                ).strip()

                partlabel = str(
                    node.get("partlabel")
                    or ""
                ).strip()

                mounts = _mounts(
                    node
                )

                partitions.append(
                    {
                        "name": part_name,
                        "path": part_path,
                        "size": part_size,
                        "size_human": _human(
                            part_size
                        ),
                        "fstype": fstype,
                        "label": label,
                        "partlabel": partlabel,
                        "mountpoints": mounts,
                    }
                )


            # Un volume feuille correspond à l'espace
            # que nous devons classifier.
            if (
                node_type != "disk"
                and not children
            ):
                volumes.append(
                    node
                )

            # Cas disque sans table de partitions.
            elif (
                node_type == "disk"
                and not children
                and (
                    node.get("fstype")
                    or _mounts(node)
                )
            ):
                volumes.append(
                    node
                )


            for child in children:
                _walk(
                    child
                )


        _walk(
            disk
        )


        segments = {
            "system": 0,
            "tables": 0,
            "logs": 0,
            "backup": 0,
            "unknown": 0,
            "other": 0,
        }


        for volume in volumes:

            source = _normalize_source(
                volume.get("path")
                or ""
            )

            size = int(
                volume.get("size")
                or 0
            )

            fstype = str(
                volume.get("fstype")
                or ""
            ).strip().lower()

            name_text = " ".join(
                [
                    str(
                        volume.get("name")
                        or ""
                    ),
                    str(
                        volume.get("label")
                        or ""
                    ),
                    str(
                        volume.get("partlabel")
                        or ""
                    ),
                ]
            ).lower()

            mounts = _mounts(
                volume
            )


            # Windows / Microsoft / partition étrangère
            # identifiable : toute la partition est mauve,
            # car cette capacité est réservée hors PinCabOS.
            other_partition = (
                fstype
                in {
                    "ntfs",
                    "ntfs3",
                    "exfat",
                }
                or "windows" in name_text
                or "winre" in name_text
                or "microsoft" in name_text
            )


            if other_partition:

                segments[
                    "other"
                ] += size

                continue


            # Volume non monté : impossible d'en connaître
            # l'utilisation réelle.
            if not mounts:

                if (
                    fstype == "swap"
                    or "efi" in name_text
                    or "bios" in name_text
                ):

                    segments[
                        "system"
                    ] += size

                else:

                    segments[
                        "unknown"
                    ] += size

                continue


            # Préférer / puis le point de montage le plus court.
            mounts = sorted(
                mounts,
                key=lambda value: (
                    0
                    if value == "/"
                    else 1,
                    len(value),
                ),
            )

            mountpoint = mounts[0]


            try:

                used = int(
                    shutil.disk_usage(
                        mountpoint
                    ).used
                )

            except Exception:

                used = 0


            known = known_by_source.get(
                source,
                {
                    "tables": 0,
                    "logs": 0,
                    "backup": 0,
                },
            )


            remaining = max(
                0,
                used,
            )


            # L'ordre empêche les valeurs du -sb de dépasser
            # le "used" réel du filesystem en présence de
            # fichiers sparse.
            for category in (
                "tables",
                "logs",
                "backup",
            ):

                value = min(
                    max(
                        0,
                        int(
                            known.get(category)
                            or 0
                        ),
                    ),
                    remaining,
                )

                segments[
                    category
                ] += value

                remaining -= value


            # Le reste de la partition racine / EFI fait partie
            # du système PinCabOS.
            if (
                source == root_source
                or source in boot_sources
                or mountpoint == "/"
                or mountpoint.startswith(
                    "/boot"
                )
            ):

                segments[
                    "system"
                ] += remaining

            else:

                # Filesystem monté mais non classifiable.
                segments[
                    "unknown"
                ] += remaining


        occupied = sum(
            int(value or 0)
            for value
            in segments.values()
        )


        # Tout ce qui n'est pas occupé par les catégories
        # ci-dessus est réellement disponible ou non alloué.
        free = max(
            0,
            disk_size - occupied,
        )


        ordered = (
            "system",
            "tables",
            "logs",
            "backup",
            "unknown",
            "other",
            "free",
        )


        segment_list = []

        for key in ordered:

            value = (
                free
                if key == "free"
                else int(
                    segments.get(key)
                    or 0
                )
            )

            percent = (
                (value / disk_size) * 100.0
                if disk_size > 0
                else 0.0
            )

            segment_list.append(
                {
                    "key": key,
                    "label": labels[key],
                    "bytes": value,
                    "human": _human(
                        value
                    ),
                    "percent": percent,
                    "color": colors[key],
                }
            )


        part_text = []

        for part in partitions:

            bits = [
                part["name"],
            ]

            if part["label"]:
                bits.append(
                    part["label"]
                )

            elif part["partlabel"]:
                bits.append(
                    part["partlabel"]
                )

            if part["fstype"]:
                bits.append(
                    part["fstype"].upper()
                    if part["fstype"].lower()
                    in {
                        "vfat",
                        "ntfs",
                        "exfat",
                    }
                    else part["fstype"]
                )

            bits.append(
                part["size_human"]
            )

            if part["mountpoints"]:
                bits.append(
                    ", ".join(
                        part["mountpoints"]
                    )
                )

            part_text.append(
                " · ".join(
                    bits
                )
            )


        disks.append(
            {
                "name": disk_name,
                "path": disk_path,
                "model": model,
                "connector": connector,
                "size": disk_size,
                "size_human": _human(
                    disk_size
                ),
                "partitions": partitions,
                "partitions_line": (
                    "   |   ".join(
                        part_text
                    )
                    if part_text
                    else "Aucune partition détectée"
                ),
                "segments": segment_list,
            }
        )


    models = " · ".join(
        disk["model"]
        for disk in disks
    ) or "Modèle non lu"


    # Clés historiques conservées afin de ne pas casser
    # d'éventuels bindings JavaScript existants.
    try:
        root_usage = shutil.disk_usage(
            "/"
        )

        root_total = int(
            root_usage.total
        )

        root_used = int(
            root_usage.used
        )

        root_free = int(
            root_usage.free
        )

    except Exception:

        root_total = 0
        root_used = 0
        root_free = 0


    root_percent = (
        root_used
        / root_total
        * 100.0
        if root_total
        else 0.0
    )


    tables_used = int(
        category_totals["tables"]
    )

    tables_percent = (
        tables_used
        / root_total
        * 100.0
        if root_total
        else 0.0
    )


    value = {
        "models": models,
        "disks": disks,
        "categories": category_totals,

        "root_percent": root_percent,
        "root_used": _human(
            root_used
        ),
        "root_free": _human(
            root_free
        ),

        "tables_percent": tables_percent,
        "tables_used": _human(
            tables_used
        ),
        "tables_free": _human(
            root_free
        ),
    }


    _PCO_STORAGE_CACHE.update(
        {
            "at": now,
            "value": value,
        }
    )

    return value


def storage_models():
    return storage_inventory().get(
        "models",
        "Modèle non lu",
    )


def storage_widget_html(item):
    import html as _html

    def esc(value):
        return _html.escape(
            str(
                value
                if value is not None
                else ""
            )
        )


    disks = list(
        item.get("disks")
        or []
    )


    style = """
<style>
/* PINCABOS_STORAGE_MACOS_V2_VISUAL */
.pco-storage-mac{
  display:grid;
  gap:14px;
  min-width:0;
}
.pco-storage-disk{
  display:grid;
  gap:7px;
  min-width:0;
}
.pco-storage-disk + .pco-storage-disk{
  padding-top:13px;
  border-top:1px solid rgba(255,255,255,.10);
}
.pco-storage-disk-head{
  display:flex;
  align-items:baseline;
  gap:8px;
  min-width:0;
  white-space:nowrap;
}
.pco-storage-disk-name{
  color:#fff;
  font-size:14px;
  font-weight:800;
  overflow:hidden;
  text-overflow:ellipsis;
}
.pco-storage-disk-bus{
  flex:0 0 auto;
  color:#c6b5ff;
  font-size:12px;
  font-weight:800;
}
.pco-storage-disk-size{
  flex:0 0 auto;
  margin-left:auto;
  color:rgba(255,255,255,.72);
  font-size:11px;
}
.pco-storage-parts{
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  color:rgba(255,255,255,.68);
  font-size:10px;
}
.pco-storage-bar{
  display:flex;
  width:100%;
  height:15px;
  overflow:hidden;
  border-radius:999px;
  background:rgba(255,255,255,.08);
  box-shadow:
    inset 0 0 0 1px rgba(255,255,255,.08),
    0 3px 12px rgba(0,0,0,.20);
}
.pco-storage-segment{
  height:100%;
  min-width:0;
}
.pco-storage-legend{
  display:flex;
  flex-wrap:wrap;
  gap:5px 11px;
  align-items:center;
  color:rgba(255,255,255,.78);
  font-size:9px;
  line-height:1.35;
}
.pco-storage-legend-item{
  display:inline-flex;
  align-items:center;
  gap:4px;
  white-space:nowrap;
}
.pco-storage-dot{
  display:inline-block;
  width:7px;
  height:7px;
  border-radius:50%;
  box-shadow:0 0 6px rgba(255,255,255,.08);
}
.pco-storage-legend-value{
  color:rgba(255,255,255,.48);
}
</style>
"""


    if not disks:

        return (
            style
            + '<div class="pco-storage-mac" '
              'data-pco-storage-mac="2">'
              '<span>Aucun disque détecté.</span>'
              '</div>'
        )


    blocks = []


    for disk in disks:

        segment_html = []

        legend_html = []


        for segment in (
            disk.get("segments")
            or []
        ):

            percent = max(
                0.0,
                min(
                    100.0,
                    float(
                        segment.get("percent")
                        or 0.0
                    ),
                ),
            )

            if percent > 0.0:

                segment_html.append(
                    '<span '
                    'class="pco-storage-segment" '
                    f'style="width:{percent:.5f}%;'
                    f'background:{esc(segment["color"])}" '
                    f'title="{esc(segment["label"])} : '
                    f'{esc(segment["human"])}">'
                    '</span>'
                )


            legend_html.append(
                '<span class="pco-storage-legend-item">'
                '<i class="pco-storage-dot" '
                f'style="background:{esc(segment["color"])}">'
                '</i>'
                f'<span>{esc(segment["label"])}</span>'
                '<span class="pco-storage-legend-value">'
                f'{esc(segment["human"])}'
                '</span>'
                '</span>'
            )


        blocks.append(
            '<div class="pco-storage-disk" '
            f'data-pco-storage-disk="{esc(disk["name"])}">'

            '<div class="pco-storage-disk-head">'

            '<span class="pco-storage-disk-name">'
            f'{esc(disk["model"])}'
            '</span>'

            '<span class="pco-storage-disk-bus">'
            f'{esc(disk["connector"])}'
            '</span>'

            '<span class="pco-storage-disk-size">'
            f'{esc(disk["size_human"])}'
            '</span>'

            '</div>'

            '<div class="pco-storage-parts" '
            f'title="{esc(disk["partitions_line"])}">'
            f'{esc(disk["partitions_line"])}'
            '</div>'

            '<div class="pco-storage-bar">'
            + "".join(
                segment_html
            )
            + '</div>'

            '<div class="pco-storage-legend">'
            + "".join(
                legend_html
            )
            + '</div>'

            '</div>'
        )


    return (
        style
        + '<div class="pco-storage-mac" '
          'data-pco-storage-mac="2">'
        + "".join(
            blocks
        )
        + '</div>'
    )





# PINCABOS_NETWORK_TRAFFIC_LIVE_V2
# Lecture seule des compteurs de l'interface réseau active.
import time as _pco_network_time

_PCO_NETWORK_TRAFFIC_LAST = {}

def _pco_network_traffic_live(interface):
    if not interface:
        return "Interface non lue"

    stats = Path("/sys/class/net") / interface / "statistics"

    try:
        rx_bytes = int((stats / "rx_bytes").read_text().strip())
        tx_bytes = int((stats / "tx_bytes").read_text().strip())
    except Exception:
        return "Compteurs indisponibles"

    now = _pco_network_time.monotonic()
    previous = _PCO_NETWORK_TRAFFIC_LAST.get(interface)
    _PCO_NETWORK_TRAFFIC_LAST[interface] = (now, rx_bytes, tx_bytes)

    if not previous:
        return "Mesure en cours…"

    previous_time, previous_rx, previous_tx = previous
    elapsed = now - previous_time

    if elapsed <= 0:
        return "Mesure en cours…"

    rx_mbps = max(0.0, (rx_bytes - previous_rx) * 8 / elapsed / 1_000_000)
    tx_mbps = max(0.0, (tx_bytes - previous_tx) * 8 / elapsed / 1_000_000)

    return f"↓ {rx_mbps:.1f} · ↑ {tx_mbps:.1f} Mb/s"




# === PINCABOS_NETWORK_TRUECHART_V1 ===
# Read-only realtime measurements for the Network Dashboard widget.
_PCO_NETWORK_TRUECHART_LOCK = threading.Lock()
_PCO_NETWORK_TRUECHART_LAST = {}


# === PINCABOS_NETWORK_LAN_WAN_V6 ===
#
# IPv4 Internet publique du cabinet.
# Lecture seule.
# Cache 5 minutes pour l'API appelée chaque seconde.

_PCO_NETWORK_WAN_LOCK = threading.Lock()

_PCO_NETWORK_WAN_CACHE = {
    "value": "Indisponible",
    "expires": 0.0,
}


def _pco_public_wan_ip() -> str:
    now = time.monotonic()

    with _PCO_NETWORK_WAN_LOCK:
        cached = str(
            _PCO_NETWORK_WAN_CACHE.get("value")
            or "Indisponible"
        )

        expires = float(
            _PCO_NETWORK_WAN_CACHE.get("expires")
            or 0.0
        )

        if now < expires:
            return cached

        detected = ""

        for url in (
            "https://api.ipify.org",
            "https://checkip.amazonaws.com",
            "https://icanhazip.com",
        ):
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent":
                            "PinCabOS-Dashboard-Network/6",
                        "Accept": "text/plain",
                    },
                )

                with urllib.request.urlopen(
                    request,
                    timeout=2.5,
                ) as response:
                    candidate = (
                        response
                        .read(128)
                        .decode("ascii", "ignore")
                        .strip()
                    )

                address = ipaddress.ip_address(
                    candidate
                )

                if (
                    address.version == 4
                    and address.is_global
                ):
                    detected = candidate
                    break

            except Exception:
                continue

        if detected:
            _PCO_NETWORK_WAN_CACHE.update({
                "value": detected,
                "expires": now + 300.0,
            })

            return detected

        if cached not in (
            "",
            "—",
            "Indisponible",
        ):
            _PCO_NETWORK_WAN_CACHE.update({
                "value": cached,
                "expires": now + 60.0,
            })

            return cached

        _PCO_NETWORK_WAN_CACHE.update({
            "value": "Indisponible",
            "expires": now + 30.0,
        })

        return "Indisponible"


# === PINCABOS_NETWORK_LAN_WAN_V6 END ===


def _pco_network_truechart_interface() -> str:
    value = primary_network_info().get("interface_label", "")
    value = str(value or "").strip()
    return value if re.fullmatch(r"[A-Za-z0-9_.:-]+", value) else ""


def network_traffic_snapshot() -> dict:
    """Return live counter rates and current network facts without changing networking."""
    base = status_snapshot().get("network", {})
    interface = _pco_network_truechart_interface()
    result = {
        "ok": bool(interface),
        "interface": interface or "Interface non lue",
        "ip": str(base.get("ip") or "—"),
        "gateway": str(base.get("gateway") or "—"),
        "dns": str(base.get("dns") or "—"),
        "wan_ip": _pco_public_wan_ip(),
        "addressing": str(base.get("addressing") or "—"),
        "internet": str(base.get("internet") or "Indisponible"),
        "mask": "—",
        "link": "DOWN",
        "speed": "—",
        "rx_mbps": 0.0,
        "tx_mbps": 0.0,
    }
    if not interface:
        return result

    stats = Path("/sys/class/net") / interface / "statistics"
    try:
        rx_bytes = int((stats / "rx_bytes").read_text().strip())
        tx_bytes = int((stats / "tx_bytes").read_text().strip())
    except Exception:
        result["ok"] = False
        return result

    cidr = run(
        f"ip -o -4 addr show dev {interface} scope global 2>/dev/null | "
        "awk 'NR==1 {print $4}'",
        "",
        2,
    ).strip()
    if "/" in cidr:
        ip_value, prefix = cidr.split("/", 1)
        try:
            result["ip"] = ip_value
            result["mask"] = str(ipaddress.ip_network(f"0.0.0.0/{int(prefix)}").netmask)
        except Exception:
            pass

    try:
        operstate = (Path("/sys/class/net") / interface / "operstate").read_text().strip().lower()
        carrier = (Path("/sys/class/net") / interface / "carrier").read_text().strip()
        result["link"] = "UP" if operstate == "up" and carrier == "1" else "DOWN"
    except Exception:
        pass
    try:
        speed = (Path("/sys/class/net") / interface / "speed").read_text().strip()
        result["speed"] = f"{speed} Mb/s" if speed.isdigit() and int(speed) > 0 else "—"
    except Exception:
        pass

    now = time.monotonic()
    with _PCO_NETWORK_TRUECHART_LOCK:
        previous = _PCO_NETWORK_TRUECHART_LAST.get(interface)
        _PCO_NETWORK_TRUECHART_LAST.clear()
        _PCO_NETWORK_TRUECHART_LAST[interface] = (now, rx_bytes, tx_bytes)

    if previous:
        previous_time, previous_rx, previous_tx = previous
        elapsed = now - previous_time
        if elapsed > 0:
            result["rx_mbps"] = round(max(0.0, (rx_bytes - previous_rx) * 8 / elapsed / 1_000_000), 3)
            result["tx_mbps"] = round(max(0.0, (tx_bytes - previous_tx) * 8 / elapsed / 1_000_000), 3)
    return result


def primary_network_info():
    interface = run(
        "ip -o route show default 2>/dev/null | "
        "sed -n 's/.* dev \\([^ ]*\\).*/\\1/p' | head -n1",
        "",
        2,
    ).strip()

    # PINCABOS_NETWORK_ADDRESSING_NETPLAN_V1
    # PINCABOS_NETWORK_ADDRESSING_ESCAPE_FIX_V1
    # Priorité : Netplan → NetworkManager → route réellement active.
    # Ceci lit uniquement la configuration, sans jamais la modifier.
    default_dev = run(
        "ip -o route show default 2>/dev/null | "
        "sed -n 's/.* dev \\([^ ]*\\).*/\\1/p' | head -n1",
        "",
        3,
    ).strip()

    netplan_dhcp4 = ""
    if default_dev:
        netplan_dhcp4 = run(
            "DEV=$(ip -o route show default 2>/dev/null | "
            "sed -n 's/.* dev \\([^ ]*\\).*/\\1/p' | head -n1); "
            "command -v netplan >/dev/null 2>&1 || exit 0; "
            "for KEY in \"ethernets.${DEV}.dhcp4\" "
            "\"network.ethernets.${DEV}.dhcp4\"; do "
            "VALUE=$(netplan get \"$KEY\" 2>/dev/null | tr -d '[:space:]'); "
            "case \"$VALUE\" in true|false) printf '%s' \"$VALUE\"; exit 0;; esac; "
            "done",
            "",
            3,
        ).strip().lower()

    nm_method = run(
        "DEV=$(ip -o route show default 2>/dev/null | "
        "sed -n 's/.* dev \\([^ ]*\\).*/\\1/p' | head -n1); "
        "[ -n \"$DEV\" ] && "
        "nmcli -g IP4.METHOD device show \"$DEV\" 2>/dev/null | head -n1",
        "",
        3,
    ).strip().lower()

    route_proto = run(
        "ip -4 route show default 2>/dev/null | "
        "sed -n 's/.* proto \\([^ ]*\\).*/\\1/p' | head -n1",
        "",
        3,
    ).strip().lower()

    if (
        netplan_dhcp4 == "true"
        or nm_method in ("auto", "dhcp")
        or route_proto == "dhcp"
    ):
        addressing = "DHCP (automatique)"
    elif (
        netplan_dhcp4 == "false"
        or nm_method in ("manual", "disabled")
        or route_proto == "static"
    ):
        addressing = "IP fixe (manuelle)"
    else:
        addressing = "Mode non lu"

    interface_label = interface or "Interface non lue"
    traffic_summary = _pco_network_traffic_live(interface)

    return {
        "interface_label": interface_label,
        "addressing": addressing,
        "traffic_summary": f"{interface_label} · {traffic_summary}",
    }


def vpx_runtime_available():
    try:
        return any(
            item.is_file() and item.stat().st_size > 0
            for item in Path("/home/pinball").glob("VPinballX*/VPinballX*")
        )
    except Exception:
        return False


def vpx_available():
    return vpx_runtime_available() or any(
        Path(candidate).exists()
        for candidate in (
            "/opt/pincabos/bin/vpx-vpinfe-default.sh",
            "/opt/pincabos/bin/vpx-vpinfe-default.sh",
        )
    )


def realtime_clock(item):
    timezone = html.escape(str(item.get("timezone") or "Etc/UTC"))
    epoch_ms = int(time.time() * 1000)
    return (
        f'<div data-pco-live-clock="1" '
        f'data-pco-server-epoch="{epoch_ms}" '
        f'data-pco-timezone="{timezone}" '
        f'style="margin:0 0 14px;color:#ffb000;font-size:27px;'
        f'font-weight:900;letter-spacing:.03em;line-height:1.15;'
        f'font-variant-numeric:tabular-nums;">'
        f'—</div>'
    )



# === PINCABOS_VPINFE_UPDATE_DASHBOARD_V1 START ===
_VPINFE_STATUS_CACHE = {"at": 0.0, "signature": None, "remote_at": 0.0, "value": {}}
_VPINFE_STATUS_SCRIPT = Path("/opt/pincabos/tools/vpinfeupdate.py")
_VPINFE_STATUS_STATE = Path("/opt/pincabos/state/vpinfe-update-state.json")
_VPINFE_STATUS_BIN = Path(_pco_chemin("vpinfe_bin", "/opt/pinball/vpinfe/vpinfe"))


def vpinfe_update_info():
    now = time.monotonic()

    def signature_for(path):
        try:
            st = path.stat()
            return (st.st_size, st.st_mtime_ns)
        except Exception:
            return None

    signature = (signature_for(_VPINFE_STATUS_BIN), signature_for(_VPINFE_STATUS_STATE))
    cached = _VPINFE_STATUS_CACHE
    if cached["value"] and cached["signature"] == signature and now - cached["at"] < 12:
        return cached["value"]

    ask_remote = signature != cached["signature"] or now - cached["remote_at"] >= 900
    command = ["/usr/bin/python3", str(_VPINFE_STATUS_SCRIPT), "--status"]
    if ask_remote:
        command.append("--remote")
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=35)
        payload = json.loads((result.stdout or "").strip() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON statut invalide")
        local = payload.get("local", {}) if isinstance(payload.get("local"), dict) else {}
        remote = payload.get("remote", {}) if isinstance(payload.get("remote"), dict) else {}
        update = payload.get("update", {}) if isinstance(payload.get("update"), dict) else {}
        value = {
            "present": bool(local.get("present")),
            "local_display": str(local.get("display") or "non détectée"),
            "remote_tag": str(remote.get("tag") or ("non vérifiée" if not remote.get("ok") else "—")),
            "update_label": str(update.get("label") or "Statut indisponible"),
        }
        if ask_remote and remote.get("ok"):
            cached["remote_at"] = now
    except Exception:
        value = {
            "present": _VPINFE_STATUS_BIN.exists(),
            "local_display": "non détectée",
            "remote_tag": "non vérifiée",
            "update_label": "Statut indisponible",
        }
    cached.update({"at": now, "signature": signature, "value": value})
    return value
# === PINCABOS_VPINFE_UPDATE_DASHBOARD_V1 END ===

def status_snapshot(force=False):
    now = time.monotonic()
    with _STATUS_LOCK:
        if not force and _STATUS_CACHE["value"] and now - _STATUS_CACHE["at"] < 4:
            return _STATUS_CACHE["value"]
        mem_total, mem_used, mem_pct = memory_info()
        root_total, root_used, root_free, root_pct = disk_info("/")
        table_total, table_used, table_free, table_pct = disk_info(str(TABLES_ROOT))
        network_info = primary_network_info()
        gpu = [part.strip() for part in run(
            "nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,driver_version --format=csv,noheader,nounits 2>/dev/null",
            "", 3).split(",")]
        if len(gpu) < 6:
            gpu = [run("lspci | grep -Ei 'vga|3d|display' | head -1 | sed 's/^.*: //'", "GPU non détecté", 2), "—", "—", "—", "—", "—"]
        services = {key: service_state(unit) for key, unit in {
            "webapp": "pincabos-webapp.service", "vpinfe": "pincabos-vpinfe.service", "chrony": "chrony.service",
            "network": "NetworkManager.service", "ssh": "ssh.service",
            "media_recorder": "pincabos-media-recorder-worker.service",
        }.items()}
        services["vpx"] = vpx_process_state()
        vpinfe_info = vpinfe_update_info()
        logs = [line.strip() for line in run("journalctl -u pincabos-webapp.service -n 4 --no-pager -o short-iso 2>/dev/null", "", 3).splitlines() if line.strip()][-4:]
        data = {
            "system": {"host": run("hostname", "PinCabOS", 2), "kernel": run("uname -r", "—", 2), "uptime": uptime()},
            "cpu": {"percent": round(cpu_percent(), 1), "cores": run("nproc", "—", 2), "load": run("cut -d' ' -f1-3 /proc/loadavg", "—", 2)},
            "memory": {"percent": mem_pct, "used": human_size(mem_used), "total": human_size(mem_total)},
            "storage": storage_inventory(),
            "gpu": {"name": gpu[0], "temp": gpu[1], "util": gpu[2], "vram_used": gpu[3], "vram_total": gpu[4], "driver": gpu[5]},
            "services": services,
            "time": {"local": run("date '+%Y-%m-%d %H:%M:%S %Z'", "—", 2), "timezone": run("timedatectl show -p Timezone --value", "—", 2), "sync": run("timedatectl show -p NTPSynchronized --value", "no", 2), "source": run("chronyc -n sources 2>/dev/null | awk '$1 ~ /^\\^\\*/ {print $2; exit}'", "Aucune source", 3)},
            "network": {"interface_label": network_info["interface_label"], "addressing": network_info["addressing"], "traffic_summary": network_info["traffic_summary"], "ip": run("hostname -I | awk '{print $1}'", "—", 2), "gateway": run("ip route | awk '/^default/{print $3; exit}'", "—", 2), "dns": run("grep -E '^nameserver ' /etc/resolv.conf | awk '{print $2; exit}'", "—", 2), "internet": run("ping -c1 -W1 1.1.1.1 >/dev/null 2>&1 && echo Accessible || echo Indisponible", "Indisponible", 3)},
            "tables": {"count": table_count(), "used": human_size(table_used), "total": human_size(table_total), "free": human_size(table_free)},
            "engine": {"vpx": vpx_available(), "vpinfe": vpinfe_info["present"], "runtime": vpx_runtime_available(), "vpinfe_version": vpinfe_info["local_display"], "vpinfe_available": vpinfe_info["remote_tag"], "vpinfe_update": vpinfe_info["update_label"]},
            "audio": [line.strip() for line in run("aplay -l 2>/dev/null", "", 3).splitlines() if line.lstrip().startswith("card ")][:3],
            "usb": [line.strip() for line in run("lsusb 2>/dev/null", "", 3).splitlines() if line.strip()][:4],
            "journal": logs,
        }
        _STATUS_CACHE.update({"at": now, "value": data})
        return data


def meter(label, value, detail=""):
    value = max(0.0, min(100.0, number(value)))
    level = "bad" if value >= 85 else ("warn" if value >= 65 else "ok")
    return f'''<div class="pco-meter"><div><span>{html.escape(str(label))}</span><b data-pco-meter-value="{value:.1f}">{value:.0f}%</b></div><i><em class="{level}" data-pco-meter="{value:.1f}" style="width:{value:.1f}%"></em></i><small>{html.escape(str(detail))}</small></div>'''


def kv(label, value, bind=""):
    attribute = f' data-pco-bind="{html.escape(bind)}"' if bind else ""
    return f'<div class="pco-kv"><span>{html.escape(str(label))}</span><b{attribute}>{html.escape(str(value))}</b></div>'


def action(path, label, csrf, css="", confirm=""):
    confirm_attr = f' data-confirm="{html.escape(confirm)}"' if confirm else ""
    return f'<form method="post" action="{html.escape(path)}"><input type="hidden" name="csrf" value="{html.escape(csrf)}"><button class="pco-action {html.escape(css)}" type="submit"{confirm_attr}>{html.escape(label)}</button></form>'


def service_line(name, key, status):
    item = status.get("services", {}).get(key, {"level": "muted", "label": "—"})
    return f'<div class="pco-service"><i class="{html.escape(item["level"])}"></i><span>{html.escape(name)}</span><b data-pco-service="{html.escape(key)}">{html.escape(item["label"])}</b></div>'


_FIT_SCROLL_STYLE = (
    "<style>"
    ".pco-fit-scroll{overflow-y:auto;overflow-x:hidden;min-height:0;flex:1 1 auto;"
    "scrollbar-width:thin;scrollbar-color:var(--accent) rgba(255,174,0,.14)}"
    ".pco-fit-scroll::-webkit-scrollbar{width:8px}"
    ".pco-fit-scroll::-webkit-scrollbar-thumb{background:var(--accent);border-radius:8px;"
    "border:2px solid rgba(25,5,40,.6)}"
    ".pco-fit-scroll::-webkit-scrollbar-track{background:rgba(255,174,0,.10);border-radius:8px}"
    "</style>"
)


def _fit_scroll(inner):
    """Enveloppe un contenu dans un conteneur qui defile SEULEMENT s'il deborde,
    avec une barre fine sur charte (comme le widget Services). Evite de couper le
    bas des tuiles a contenu variable (disques, versions) sans toucher au layout."""
    return (_FIT_SCROLL_STYLE
            + '<div class="pco-fit-scroll">' + inner + '</div>')


def widget_content(widget_id, meta, data, csrf):
    kind = meta["kind"]
    if kind == "system":
        return kv("Hôte", data["system"]["host"], "system.host") + kv("Noyau", data["system"]["kernel"], "system.kernel") + kv("Uptime", data["system"]["uptime"], "system.uptime")
    if kind == "cpu":
        item = data["cpu"]
        return f'<div class="pco-value" data-pco-bind="cpu.percent" data-pco-format="percent">{item["percent"]:.0f}%</div><p class="pco-caption">CPU utilisé</p>' + meter("Charge", item["percent"], f'{item["cores"]} cœurs · load {item["load"]}')
    if kind == "memory":
        item = data["memory"]
        return f'<div class="pco-value" data-pco-bind="memory.percent" data-pco-format="percent">{item["percent"]:.0f}%</div><p class="pco-caption">RAM utilisée</p>' + meter("RAM", item["percent"], f'{item["used"]} / {item["total"]}')
    if kind == "storage":
        item = data["storage"]
        return _fit_scroll(storage_widget_html(item))
    if kind == "gpu":
        item = data["gpu"]
        percent = number(item["vram_used"]) / number(item["vram_total"]) * 100 if number(item["vram_total"]) else 0
        return kv("GPU", item["name"], "gpu.name") + kv("Température", f'{item["temp"]} °C', "gpu.temp") + kv("Utilisation", f'{item["util"]} %', "gpu.util") + meter("VRAM", percent, f'{item["vram_used"]} / {item["vram_total"]} MiB')
    if kind == "services":
        # PINCABOS_SERVICES_SCROLL_V2
        html_out = (
            '<style>'
            '.pco-services-scroll{'
            'height:min(58vh,560px);'
            'overflow-y:auto;overflow-x:hidden;'
            'padding-right:10px;'
            'scrollbar-width:thin;'
            'scrollbar-color:#ffae00 rgba(255,174,0,.16);'
            'overscroll-behavior:contain;'
            '}'
            '.pco-services-scroll::-webkit-scrollbar{width:11px;}'
            '.pco-services-scroll::-webkit-scrollbar-track{'
            'background:rgba(255,174,0,.10);border-radius:12px;'
            '}'
            '.pco-services-scroll::-webkit-scrollbar-thumb{'
            'background:#ffae00;border-radius:12px;'
            'border:2px solid rgba(25,5,40,.75);'
            '}'
            '.pco-services-scroll::-webkit-scrollbar-thumb:hover{'
            'background:#ffd15c;'
            '}'
            '@media (max-width:820px){'
            '.pco-services-scroll{height:52vh;}'
            '}'
            '</style>'
            '<div class="pco-services-scroll" aria-label="Services défilants">'
        )
        html_out += service_line("WebApp", "webapp", data) + action("/dashboard/control/service/webapp/restart", "Redémarrer WebApp", csrf, "warn", "Le Dashboard sera indisponible quelques secondes.")
        html_out += service_line("VPinFE", "vpinfe", data)
        html_out += '<div class="pco-actions">' + action("/dashboard/control/service/vpinfe/start", "Démarrer", csrf, "good") + action("/dashboard/control/service/vpinfe/stop", "Arrêter", csrf, "danger", "Arrêter VPinFE? Aucun jeu ne doit être actif.") + action("/dashboard/control/service/vpinfe/restart", "Restart", csrf, "warn", "Redémarrer VPinFE?") + action("/dashboard/control/service/vpinfe/freeze", "Pause", csrf, "warn", "Mettre VPinFE en pause?") + action("/dashboard/control/service/vpinfe/thaw", "Reprendre", csrf, "good") + '</div>'
        # PINCABOS_DASHBOARD_MEDIA_RECORDER_SERVICE_V1
        html_out += service_line(
            "PinCab Recorder Worker",
            "media_recorder",
            data,
        )
        html_out += (
            '<div class="pco-actions">'
            + action(
                "/dashboard/control/service/media_recorder/start",
                "Démarrer",
                csrf,
                "good",
            )
            + action(
                "/dashboard/control/service/media_recorder/stop",
                "Arrêter",
                csrf,
                "danger",
                "Arrêter le worker PinCab Recorder ? "
                "Les nouveaux jobs resteront en attente.",
            )
            + action(
                "/dashboard/control/service/media_recorder/restart",
                "Restart",
                csrf,
                "warn",
                "Redémarrer le worker PinCab Recorder ?",
            )
            + '</div>'
        )

        # PINCABOS_DASHBOARD_VPX_SERVICE_V1
        html_out += service_line("Visual Pinball X", "vpx", data)
        html_out += '<div class="pco-actions">' + action("/dashboard/control/service/vpx/stop", "Arrêter la table", csrf, "danger", "Arrêter la table Visual Pinball X en cours ? VPinFE restera ouvert.") + action("/dashboard/control/service/vpx/restart", "Retour VPinFE", csrf, "warn", "Fermer la table puis redémarrer VPinFE ?") + '</div>'
        # BEGIN PINCABOS_DASHBOARD_BATCH_CONTROLS_V2
        html_out += r'''
<style>
#pco-dashboard-batch-controls{
  display:grid;
  gap:10px;
  margin:14px 0 12px;
  padding-top:12px;
  border-top:1px solid rgba(255,255,255,.14);
}
#pco-dashboard-batch-controls .pco-batch-row{
  display:grid;
  grid-template-columns:minmax(0,1fr) auto;
  gap:10px;
  align-items:center;
  padding:10px;
  border:1px solid rgba(110,220,255,.24);
  border-radius:10px;
  background:rgba(4,20,30,.38);
}
#pco-dashboard-batch-controls .pco-batch-row.is-active{
  border-color:rgba(0,224,255,.75);
}
#pco-dashboard-batch-controls .pco-batch-main{min-width:0;}
#pco-dashboard-batch-controls .pco-batch-title{
  display:flex;
  align-items:center;
  gap:7px;
  color:#eefbff;
  font-size:.88rem;
  font-weight:850;
}
#pco-dashboard-batch-controls .pco-batch-title i{
  width:8px;
  height:8px;
  border-radius:50%;
  background:#7f8d98;
}
#pco-dashboard-batch-controls .is-active .pco-batch-title i{
  background:#19e3ff;
  box-shadow:0 0 0 4px rgba(25,227,255,.15);
  animation:pco-batch-pulse 1.2s ease-in-out infinite;
}
#pco-dashboard-batch-controls .pco-batch-detail{
  display:block;
  overflow:hidden;
  margin-top:3px;
  color:rgba(231,244,250,.74);
  font-size:.73rem;
  text-overflow:ellipsis;
  white-space:nowrap;
}
#pco-dashboard-batch-controls .pco-batch-actions{
  display:flex;
  flex-wrap:wrap;
  justify-content:flex-end;
  gap:6px;
}
#pco-dashboard-batch-controls .pco-batch-actions a,
#pco-dashboard-batch-controls .pco-batch-actions button{
  border:0;
  border-radius:8px;
  padding:7px 9px;
  background:rgba(0,197,226,.16);
  color:#8ef5ff;
  cursor:pointer;
  font:inherit;
  font-size:.73rem;
  font-weight:800;
  text-decoration:none;
}
#pco-dashboard-batch-controls .pco-batch-actions [data-pco-batch-stop]{
  background:rgba(220,55,68,.20);
  color:#ffb5bd;
}
#pco-dashboard-batch-controls .pco-batch-actions a:hover,
#pco-dashboard-batch-controls .pco-batch-actions button:hover{
  background:#00cfe8;
  color:#00141a;
}
#pco-dashboard-batch-controls .pco-batch-actions [data-pco-batch-stop]:hover{
  background:#d93243;
  color:#fff;
}
#pco-dashboard-batch-controls button[disabled]{
  opacity:.28;
  cursor:not-allowed;
  filter:grayscale(1);
  box-shadow:none;
}
@keyframes pco-batch-pulse{50%{opacity:.5;}}
@media(max-width:620px){
  #pco-dashboard-batch-controls .pco-batch-row{grid-template-columns:1fr;}
  #pco-dashboard-batch-controls .pco-batch-actions{justify-content:flex-start;}
}
</style>

<section id="pco-dashboard-batch-controls" aria-label="Batch Import et Batch Export">
  <div class="pco-batch-row" data-pco-batch-kind="import">
    <div class="pco-batch-main">
      <div class="pco-batch-title">
        <i></i><span>Batch Import</span><b data-pco-batch-state>Disponible</b>
      </div>
      <small class="pco-batch-detail" data-pco-batch-detail>Aucun job en cours.</small>
    </div>
    <div class="pco-batch-actions">
      <a href="/tools/batch-import" data-pco-batch-open>Ouvrir</a>
      <button type="button" data-pco-batch-pause>Pause</button>
      <button type="button" data-pco-batch-resume>Reprendre</button>
      <button type="button" data-pco-batch-skip>Skip</button>
      <button type="button" data-pco-batch-stop hidden>Stop</button>
      <button type="button" data-pco-batch-refresh>Actualiser</button>
    </div>
  </div>

  <div class="pco-batch-row" data-pco-batch-kind="export">
    <div class="pco-batch-main">
      <div class="pco-batch-title">
        <i></i><span>Batch Export</span><b data-pco-batch-state>Disponible</b>
      </div>
      <small class="pco-batch-detail" data-pco-batch-detail>Aucun job en cours.</small>
    </div>
    <div class="pco-batch-actions">
      <a href="/tools/batch-export" data-pco-batch-open>Ouvrir</a>
      <button type="button" data-pco-batch-pause>Pause</button>
      <button type="button" data-pco-batch-resume>Reprendre</button>
      <button type="button" data-pco-batch-skip>Skip</button>
      <button type="button" data-pco-batch-stop hidden>Stop</button>
      <button type="button" data-pco-batch-refresh>Actualiser</button>
    </div>
  </div>
</section>

<script>
/* PINCABOS_DASHBOARD_BATCH_CONTROLS_V3 */
(() => {
  "use strict";

  if (window.__pcoDashboardBatchControlsV3) return;
  window.__pcoDashboardBatchControlsV3 = true;

  const root = document.getElementById("pco-dashboard-batch-controls");
  if (!root) return;

  const cache = {import: null, export: null};

  const row = kind =>
    root.querySelector(`[data-pco-batch-kind="${kind}"]`);

  const api = (kind, suffix) =>
    `/api/batch-${kind}/live/${suffix}`;

  async function json(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      headers: {"Accept": "application/json"},
      ...options
    });

    let data = {};
    try {
      data = await response.json();
    } catch (_) {}

    if (!response.ok || data.ok === false) {
      throw new Error(
        data.error || `HTTP ${response.status}`
      );
    }

    return data;
  }

  function label(state) {
    return ({
      uploading: "Téléversement",
      queued: "En file",
      running: "Actif",
      pausing: "Pause demandée",
      paused: "En pause",
      stopping: "Arrêt demandé",
      completed: "Terminé",
      completed_with_warning: "Avertissement",
      failed: "Erreur",
      stopped: "Arrêté",
      cancelled: "Annulé"
    })[state] || "Disponible";
  }

  function currentName(job) {
    const progress = job?.progress || {};
    return String(
      progress.current_item ||
      progress.current_table ||
      job?.current_item ||
      job?.current_table ||
      ""
    );
  }

  function done(job) {
    const progress = job?.progress || {};
    return Number(
      progress.completed ??
      job?.processed_archives ??
      job?.completed_tables ??
      0
    );
  }

  function total(job) {
    const progress = job?.progress || {};
    return Number(
      progress.total ??
      job?.total_archives ??
      job?.total_tables ??
      0
    );
  }

  async function load(kind) {
    if (kind === "import") {
      const active = await json(
        "/api/batch-import/live/active"
      );

      if (active.job) {
        return {
          id: String(active.job.id || ""),
          job: active.job,
          resumable: Boolean(active.resumable),
          remaining: Number(active.remaining || 0)
        };
      }

      /*
       * PINCABOS_BATCH_IMPORT_STALE_WIDGET_V31
       *
       * /active est la source de verite pour Import.
       * Si aucun job n'est rattache mais que le dernier historique
       * porte encore un etat transitoire, il s'agit d'un etat
       * orphelin/stale et non d'un job actuellement pilotable.
       */
      const history = await json(
        "/api/batch-import/live/history"
      );

      const latest = (history.jobs || [])[0] || null;

      if (!latest) {
        return {
          id: "",
          job: null,
          resumable: false,
          remaining: 0
        };
      }

      const latestState = String(
        latest.state || ""
      ).toLowerCase();

      const staleStates = new Set([
        "uploading",
        "queued",
        "running",
        "pausing",
        "paused",
        "stopping"
      ]);

      if (staleStates.has(latestState)) {
        return {
          id: "",
          job: null,
          resumable: false,
          remaining: 0
        };
      }

      return {
        id: String(latest.id || ""),
        job: latest,
        resumable: false,
        remaining: 0
      };
    }

    const history = await json(
      api(kind, "history")
    );

    const activeId = String(
      history.active_job_id || ""
    );

    if (activeId) {
      const status = await json(
        api(
          kind,
          `status/${encodeURIComponent(activeId)}`
        )
      );

      return {
        id: activeId,
        job: status.job || null,
        resumable: Boolean(status.job?.resumable)
      };
    }

    const latest = (history.jobs || [])[0] || null;

    return {
      id: String(latest?.id || ""),
      job: latest,
      resumable: Boolean(latest?.resumable)
    };
  }

  function render(kind, packet, error = "") {
    /* PINCABOS_DASHBOARD_STAGING_V35D */

    const target = row(kind);
    if (!target) return;

    const job = packet?.job || null;

    const state = String(
      job?.state || ""
    ).toLowerCase();

    const progress = job?.progress || {};

    const totalUploads = Number(
      job?.total_archives
      ?? progress.total
      ?? 0
    );

    const uploaded = Number(
      job?.uploaded_archives
      ?? progress.uploaded
      ?? 0
    );

    /*
     * Staging = tous les fichiers locaux ne sont pas encore
     * confirmes physiquement sur le cab.
     */
    const staging = Boolean(
      kind === "import"
      && job
      && job.uploads_complete === false
      && totalUploads > 0
      && ![
        "stopped",
        "failed",
        "cancelled",
        "completed",
        "completed_with_warning"
      ].includes(state)
    );

    const working = [
      "uploading",
      "queued",
      "running",
      "pausing",
      "paused",
      "stopping"
    ].includes(state);

    target.classList.toggle(
      "is-active",
      working && state !== "paused"
    );

    const status = target.querySelector(
      "[data-pco-batch-state]"
    );

    const detail = target.querySelector(
      "[data-pco-batch-detail]"
    );

    const open = target.querySelector(
      "[data-pco-batch-open]"
    );

    const pause = target.querySelector(
      "[data-pco-batch-pause]"
    );

    const resume = target.querySelector(
      "[data-pco-batch-resume]"
    );

    const skip = target.querySelector(
      "[data-pco-batch-skip]"
    );

    const stop = target.querySelector(
      "[data-pco-batch-stop]"
    );

    if (status) {
      status.textContent = error
        ? "API indisponible"
        : staging
          ? "Téléversement"
          : label(state);
    }

    if (detail) {

      if (error) {

        detail.textContent = error;

      } else if (!job) {

        detail.textContent = kind === "import"
          ? "Worker prêt · aucun job."
          : "Aucun job en cours.";

      } else if (staging) {

        detail.textContent =
          `Téléversement vers le cab `
          + `${uploaded}/${totalUploads} · `
          + `garde la page Import ouverte jusqu'à `
          + `${totalUploads}/${totalUploads}`;

      } else {

        const count = total(job);
        const completed = done(job);
        const name = currentName(job);

        const skipped = Number(
          progress.skipped
          ?? job.skipped_archives
          ?? job.skipped_tables
          ?? 0
        );

        detail.textContent = [
          progress.label || label(state),
          count ? `${completed}/${count}` : "",
          skipped ? `Skip ${skipped}` : "",
          name,
          job.error || ""
        ].filter(Boolean).join(" · ");
      }

      detail.title = detail.textContent;
    }

    if (open) {
      open.textContent = staging
        ? "Voir transfert"
        : working
          ? "Voir tâche"
          : "Ouvrir";
    }

    /*
     * Pendant staging :
     * seul STOP est autorise.
     */
    const canPause =
      !staging
      && ["queued", "running"].includes(state);

    const canResume =
      !staging
      && ["paused", "pausing"].includes(state)
      && (
        kind === "import"
          ? Boolean(packet?.resumable)
          : Boolean(job?.resumable)
      );

    const canSkip =
      !staging
      && state === "paused"
      && Boolean(job?.error)
      && (
        kind === "import"
        || Boolean(job?.skippable)
      );

    /* PINCABOS_BATCH_BUTTON_LABELS_V35D */

    if (pause) {
      pause.hidden = false;
      pause.disabled = !canPause;
      pause.textContent =
        state === "pausing"
          ? "Pause…"
          : "Pause";
    }

    if (resume) {
      resume.hidden = false;
      resume.disabled = !canResume;
      resume.textContent = "Reprendre";
    }

    if (skip) {
      skip.hidden = false;
      skip.disabled = !canSkip;
      skip.textContent = "Skip";
    }

    if (stop) {

      const canStop =
        staging
        || [
          "uploading",
          "queued",
          "running",
          "pausing",
          "stopping"
        ].includes(state);

      stop.hidden = !canStop;
      stop.disabled = state === "stopping";

      stop.textContent =
        state === "stopping"
          ? "Arrêt…"
          : "Stop";
    }
  }

  async function refresh(kind) {
    try {
      cache[kind] = await load(kind);
      render(kind, cache[kind]);
    } catch (error) {
      cache[kind] = null;
      render(
        kind,
        null,
        `État indisponible : ${error.message}`
      );
    }
  }

  async function refreshAll() {
    await Promise.all([
      refresh("import"),
      refresh("export")
    ]);
  }

  async function act(kind, action, button) {
    const packet = cache[kind];

    if (!packet?.id || button.disabled) return;

    const original = button.textContent;
    button.disabled = true;
    button.textContent = "…";

    try {
      const data = await json(
        api(
          kind,
          `${action}/${encodeURIComponent(packet.id)}`
        ),
        {method: "POST"}
      );

      cache[kind] = {
        id: packet.id,
        job: data.job || packet.job,
        resumable: Boolean(
          data.resumable ??
          data.job?.resumable
        )
      };

      render(kind, cache[kind]);
      await refreshAll();

    } catch (error) {
      button.textContent = original;

      const detail = row(kind)?.querySelector(
        "[data-pco-batch-detail]"
      );

      if (detail) {
        detail.textContent =
          `${action} impossible : ${error.message}`;
        detail.title = detail.textContent;
      }

      await refresh(kind);
    }
  }

  root.addEventListener("click", event => {
    const target = event.target;
    const targetRow = target.closest(
      "[data-pco-batch-kind]"
    );

    if (!targetRow) return;

    const kind = String(
      targetRow.dataset.pcoBatchKind || ""
    );

    if (!["import", "export"].includes(kind)) return;

    const refreshButton = target.closest(
      "[data-pco-batch-refresh]"
    );

    if (refreshButton) {
      event.preventDefault();
      refresh(kind);
      return;
    }

    const pauseButton = target.closest(
      "[data-pco-batch-pause]"
    );

    if (pauseButton) {
      event.preventDefault();
      act(kind, "pause", pauseButton);
      return;
    }

    const resumeButton = target.closest(
      "[data-pco-batch-resume]"
    );

    if (resumeButton) {
      event.preventDefault();
      act(kind, "resume", resumeButton);
      return;
    }

    const skipButton = target.closest(
      "[data-pco-batch-skip]"
    );

    if (skipButton) {
      event.preventDefault();

      if (
        window.confirm(
          "Ignorer l'élément fautif et passer au suivant ?"
        )
      ) {
        act(kind, "skip", skipButton);
      }
      return;
    }

    const stopButton = target.closest(
      "[data-pco-batch-stop]"
    );

    if (stopButton) {
      event.preventDefault();

      if (
        window.confirm(
          "Arrêter ce Batch après l'élément en cours ?"
        )
      ) {
        act(kind, "stop", stopButton);
      }
    }
  });

  refreshAll();
  window.setInterval(refreshAll, 2500);
})();
</script>
'''
        # END PINCABOS_DASHBOARD_BATCH_CONTROLS_V2
        html_out += service_line("Chrony / NTP", "chrony", data) + '<div class="pco-actions">' + action("/dashboard/control/service/chrony/start", "Démarrer", csrf, "good") + action("/dashboard/control/service/chrony/restart", "Restart", csrf, "warn") + '</div>'
        # PINCABOS_SCREEN_TOPOLOGY_CARD_V1
        topology_boot = run(
            "systemctl is-enabled pincabos-screen-topology-boot.service 2>/dev/null || true",
            "",
            2,
        ).strip() == "enabled"
        topology_timer = run(
            "systemctl is-enabled pincabos-screen-topology.timer 2>/dev/null || true",
            "",
            2,
        ).strip() == "enabled"
        topology_label = "Préflight au boot" if topology_boot else "À vérifier"
        topology_class = "ok" if topology_boot else "bad"
        topology_hint = (
            "Polling désactivé pour les performances."
            if not topology_timer
            else "Polling actif — peut affecter les performances."
        )
        html_out += (
            f'<div class="pco-service"><i class="{topology_class}"></i>'
            f'<span>Topologie écrans</span><b>{topology_label}</b></div>'
        )
        html_out += f'<p class="pco-protected">{topology_hint}</p>'
        html_out += (
            '<div class="pco-actions">'
            + action(
                "/dashboard/control/service/screens/apply",
                "Appliquer maintenant",
                csrf,
                "warn",
                "Rechercher et appliquer la topologie des écrans maintenant ? "
                "Cela ne réactive pas le polling.",
            )
            + "</div>"
        )

        html_out += service_line("Réseau", "network", data) + service_line("SSH", "ssh", data)
        return html_out + '<p class="pco-protected">SSH et réseau sont protégés : aucun arrêt distant.</p></div>'
    if kind == "time":
        item = data["time"]
        # PINCABOS_TIMEZONE_WORLD_LIST_V1
        zones = sorted(
            {
                zone.strip()
                for zone in run(
                    "timedatectl list-timezones 2>/dev/null",
                    "",
                    8,
                ).splitlines()
                if zone.strip()
            },
            key=str.casefold,
        )

        current_zone = str(
            item.get("timezone") or "Etc/UTC"
        ).strip()

        if current_zone and current_zone not in zones:
            zones.insert(0, current_zone)

        timezone_group_labels = {
            "Africa": "Afrique",
            "America": "Amérique",
            "Antarctica": "Antarctique",
            "Arctic": "Arctique",
            "Asia": "Asie",
            "Atlantic": "Atlantique",
            "Australia": "Australie",
            "Europe": "Europe",
            "Indian": "Océan Indien",
            "Pacific": "Pacifique",
            "Etc": "UTC et décalages fixes",
        }

        timezone_group_order = (
            "Africa",
            "America",
            "Antarctica",
            "Arctic",
            "Asia",
            "Atlantic",
            "Australia",
            "Europe",
            "Indian",
            "Pacific",
            "Etc",
        )

        timezone_groups = {
            group: []
            for group in timezone_group_order
        }

        timezone_groups["Other"] = []

        for zone in zones:
            if "/" in zone:
                prefix = zone.split("/", 1)[0]
            else:
                prefix = "Other"

            if prefix not in timezone_groups:
                prefix = "Other"

            timezone_groups[prefix].append(zone)

        timezone_option_groups = []

        for group in (*timezone_group_order, "Other"):
            group_zones = timezone_groups.get(group, [])

            if not group_zones:
                continue

            label = timezone_group_labels.get(
                group,
                "Autres fuseaux officiels",
            )

            group_options = "".join(
                f'<option value="{html.escape(zone)}"'
                f'{" selected" if zone == current_zone else ""}>'
                f'{html.escape(zone)}</option>'
                for zone in group_zones
            )

            timezone_option_groups.append(
                f'<optgroup label="{html.escape(label)}">'
                f'{group_options}</optgroup>'
            )

        options = "".join(timezone_option_groups)
        local_now = run("date '+%Y-%m-%dT%H:%M'", "", 2)
        return realtime_clock(item) + kv("Heure", item["local"], "time.local") + kv("Fuseau", item["timezone"], "time.timezone") + kv("Synchro", item["sync"], "time.sync") + kv("Source", item["source"], "time.source") + f'''<div class="pco-time-controls"><form method="post" action="/dashboard/control/time/timezone"><input type="hidden" name="csrf" value="{html.escape(csrf)}"><select name="timezone">{options}</select><button class="pco-action good">Fuseau</button></form><form method="post" action="/dashboard/control/time/set"><input type="hidden" name="csrf" value="{html.escape(csrf)}"><input type="datetime-local" name="value" value="{html.escape(local_now)}"><button class="pco-action warn" data-confirm="Ajuster manuellement l heure système?">Heure</button></form>{action('/dashboard/control/time/sync-google', 'Google NTP', csrf, 'good', 'Ajouter time.google.com à Chrony et synchroniser?')}</div>'''
    if kind == "network":
        item = data["network"]
        value = lambda key, fallback="—": html.escape(str(item.get(key) or fallback))
        return f'''<div class="pco-network-truechart" data-pco-network-widget="1">
  <div class="pco-network-row pco-network-primary"><span>Adresse IP (LAN)</span><strong data-pco-network-ip data-pco-bind="network.ip">{value("ip")}</strong></div>
  <div class="pco-network-row"><span>Passerelle / masque</span><strong><b data-pco-network-gateway data-pco-bind="network.gateway">{value("gateway")}</b><i> / </i><b data-pco-network-mask>—</b></strong></div>
  <div class="pco-network-row"><span>Adressage</span><strong data-pco-network-addressing data-pco-bind="network.addressing">{value("addressing")}</strong></div>
  <div class="pco-network-row"><span>IP Internet (WAN)</span><strong data-pco-network-wan>Lecture…</strong></div>
  <div class="pco-network-row pco-network-state"><span>Internet / lien</span><strong><b data-pco-network-internet data-pco-bind="network.internet">{value("internet")}</b><i> · </i><b data-pco-network-link>—</b></strong></div>
  <section class="pco-network-traffic" aria-label="Trafic réseau en direct">
    <div class="pco-network-traffic-head"><strong><span class="pco-network-dot"></span><span data-pco-network-interface>{value("interface_label")}</span></strong><small data-pco-network-speed>Trafic live</small></div>
    <div class="pco-network-traffic-body">
      <div class="pco-network-metrics"><span class="pco-network-in">↓ Entrant <b data-pco-network-rx>—</b></span><span class="pco-network-out">↑ Sortant <b data-pco-network-tx>—</b></span></div>
      <canvas data-pco-network-chart role="img" aria-label="Graphique du trafic entrant et sortant"></canvas>
    </div>
  </section>
</div>'''

    if kind == "tables":
        item = data["tables"]
        return f'<div class="pco-value" data-pco-bind="tables.count">{item["count"]}</div><p class="pco-caption">tables VPX installées</p>' + kv("Utilisé", f'{item["used"]} / {item["total"]}') + kv("Libre", item["free"])
    if kind == "engine":
        item = data["engine"]
        value = lambda flag: "OK" if flag else "Absent"

        try:
            from pincabos_pinball_engine_vpx_version import (
                _comparison,
                _local_vpx,
                _remote_vpx,
            )

            local_vpx = _local_vpx()
            github_vpx = _remote_vpx()
            vpx_status = _comparison(local_vpx, github_vpx)

            local_text = str(local_vpx.get("display") or "Version locale non détectée")
            github_text = str(github_vpx.get("display") or "GitHub indisponible")
            status_text = str(vpx_status.get("label") or "Comparaison indisponible")

            if local_text.startswith("VPX · "):
                local_text = local_text[6:]

            if github_text.startswith("GitHub stable · "):
                github_text = github_text[16:]

        except Exception:
            local_text = "Lecture locale indisponible"
            github_text = "GitHub indisponible"
            status_text = "Comparaison indisponible"

        return (
            _pco_engine_maj_html(kv)
            + _fit_scroll(
                _pco_engine_pincabos_kv(kv)
            + kv("Disponibilité", "VPX " + value(item["vpx"])
                 + " · Runtime " + value(item["runtime"])
                 + " · VPinFE " + value(item["vpinfe"]))
            + kv("Version VPinFE", item.get("vpinfe_version", "—"))
            + kv("VPX local", local_text)
            + kv("Statut VPX", status_text)
            )
        )

    if kind == "audio":
        lines = "".join(f'<li>{html.escape(line)}</li>' for line in data["audio"]) or "<li>Aucune carte lue.</li>"
        return f'<ul class="pco-list">{lines}</ul>'
    if kind == "dof_usb":
        lines = "".join(f'<li>{html.escape(line)}</li>' for line in data["usb"]) or "<li>Aucun périphérique USB lu.</li>"
        return f'<ul class="pco-list">{lines}</ul><p class="pco-protected">Lecture seule : aucun mapping n’est modifié.</p>'
    if kind == "journal":
        lines = "".join(f'<li>{html.escape(line)}</li>' for line in data["journal"]) or "<li>Aucune entrée récente.</li>"
        return f'<ul class="pco-log">{lines}</ul>'
    # PINCABOS_DASHBOARD_JPEG_X11_V16
    if kind == "live":
        slot = int(meta["slot"])
        title = html.escape(meta["title"])
        subtitle = html.escape(meta["subtitle"])
        return (
            f'<div class="pco-live pco-live-jpeg" data-pco-live-jpeg="{slot}">'
            f'<img data-pco-live-jpeg-slot="{slot}" alt="{title}">'
            f'<div class="pco-live-state">'
            f'<strong>Caméra X11 légère · JPEG · 5 images/s</strong>'
            f'<small data-pco-live-jpeg-status="{slot}">{subtitle} · en attente de capture</small>'
            f'</div>'
            f'</div>'
        )
    if kind == "tool":
        visual = asset(meta.get("image", ""))
        if visual:
            image = f'<img src="{html.escape(visual)}" alt="">'
        elif widget_id == "tool_fulldmd":
            image = '<span class="pco-tool-glyph pco-tool-glyph-fulldmd"><b>FULL</b><i>DMD</i><small>Display</small></span>'
        else:
            image = '<span class="pco-tool-glyph">OUTIL</span>'
        return f'<a class="pco-tool" href="{html.escape(meta["href"])}"><span class="pco-tool-image">{image}</span><strong>Ouvrir l’outil</strong><small>{html.escape(meta["href"])}</small></a>'
    return '<p class="pco-caption">Widget indisponible.</p>'


def widget_template(widget_id, meta, data, csrf):
    title = html.escape(meta["title"])
    subtitle = html.escape(meta.get("subtitle", ""))
    content = widget_content(widget_id, meta, data, csrf)
    return f'''<template data-pco-template="{html.escape(widget_id)}"><article class="pco-card" data-pco-widget="{html.escape(widget_id)}" data-pco-kind="{html.escape(meta["kind"])}"><header class="pco-card-head"><button class="pco-grip pco-edit-only" type="button" draggable="true" title="Déplacer">⋮⋮</button><div class="pco-title"><h2>{title}</h2><p>{subtitle}</p></div><button class="pco-remove pco-edit-only" type="button" title="Retirer">×</button></header><div class="pco-card-body">{content}</div><button class="pco-resize pco-edit-only" type="button" title="Redimensionner">◢</button></article></template>'''


def render_dashboard(page, esc, get_ip, service_status, pincabos_version):
    try:
        from flask import request, session
        csrf = session.get("pco_dashboard_lobby_csrf", "")
        if not csrf:
            csrf = secrets.token_urlsafe(32)
            session["pco_dashboard_lobby_csrf"] = csrf
        notice = request.args.get("dashboard_notice", "")[:220]
    except Exception:
        csrf, notice = "preview", ""
    registry = registry_for_request()
    layout = load_layout(registry)
    data = status_snapshot()
    templates = "".join(widget_template(widget_id, meta, data, csrf) for widget_id, meta in registry.items())
    public_registry = {key: {**{field: value.get(field, "") for field in ("title", "subtitle", "category", "w", "h", "kind", "href")}, "image_url": asset(value.get("image", ""))} for key, value in registry.items()}
    config = json.dumps({"marker": MARKER, "csrf": csrf, "layout": layout, "registry": public_registry, "mode": load_mode(), "modes": modes_public()}, ensure_ascii=False)
    notice_html = f'<div class="pco-toast server">{html.escape(notice)}</div>' if notice else ''
    # PINCABOS_AUDIO_VOLUME_DASHBOARD_WIDGET_V2_1B_TEMPLATE_FORCE START
    # Force le vrai template audio_volume et retire le fallback générique.
    if "audio_volume" in registry:
        try:
            templates = re.sub(
                r'<template\s+data-pco-template=["\\\']audio_volume["\\\'][\s\S]*?</template>',
                '',
                templates,
                flags=re.S,
            )
            templates += audio_volume_dashboard_template()
        except Exception:
            pass
    # PINCABOS_AUDIO_VOLUME_DASHBOARD_WIDGET_V2_1B_TEMPLATE_FORCE END

    body = f'''<link rel="stylesheet" href="/static/pincabos-dashboard-lobby.css?v=dashboard-modes-v1"><link rel="stylesheet" href="/static/pincabos-live-jpeg-x11-v16.css?v=jpeg-x11-v16-playstop3"><section id="pco-lobby" data-marker="{MARKER}"><header class="pco-lobby-head"><div><h1>Dashboard</h1><p>Widgets PinCabOS indépendants · ajoute, déplace, redimensionne et sauvegarde.</p></div><div class="pco-lobby-actions"><div class="pco-lobby-mode" role="group" aria-label="Vue du Dashboard" title="Deux vues, chacune avec sa grille : modifiez celle que vous utilisez.">{''.join(f'<button type="button" data-pco-mode="{k}">{html.escape(v)}</button>' for k, v in MODE_LABELS.items())}</div><button id="pco-lobby-edit" type="button">Modifier le Dashboard</button><button id="pco-lobby-add" class="pco-edit-only" type="button">Ajouter un widget</button><button id="pco-lobby-save" class="pco-edit-only pco-good" type="button">Appliquer et enregistrer</button><button id="pco-lobby-cancel" class="pco-edit-only" type="button">Annuler</button><button id="pco-lobby-default" class="pco-edit-only pco-warn" type="button">Disposition par défaut</button><button id="pco-lobby-refresh" type="button">Actualiser</button></div></header>{notice_html}<div id="pco-lobby-board" class="pco-board" aria-label="Widgets PinCabOS"></div><div id="pco-lobby-catalog" class="pco-modal" hidden><div class="pco-modal-panel" role="dialog" aria-modal="true" aria-label="Ajouter un widget"><header><div><h2>Ajouter un widget</h2><p>Choisis ou glisse un widget directement sur le Dashboard. Les widgets retirés reviennent ici; les widgets présents ne sont pas listés.</p></div><button id="pco-lobby-catalog-close" class="pco-modal-close" type="button" aria-label="Fermer le catalogue"><span aria-hidden="true">×</span><span>Fermer</span></button></header><div id="pco-lobby-catalog-list"></div></div></div>{templates}<script>window.PCO_LOBBY={config};</script><script>
(function() {{
  function drawClock(node) {{
    var zone = node.dataset.pcoTimezone || "Etc/UTC";
    var base = Number(node.dataset.pcoServerEpoch || Date.now());

    if (!node.dataset.pcoClockStarted) {{
      node.dataset.pcoClockStarted = String(performance.now());
    }}

    var started = Number(node.dataset.pcoClockStarted);
    var value = new Date(base + (performance.now() - started));

    try {{
      var formatter = new Intl.DateTimeFormat("fr-CA", {{
        timeZone: zone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZoneName: "short"
      }});
      var parts = {{}};
      formatter.formatToParts(value).forEach(function(part) {{
        parts[part.type] = part.value;
      }});
      node.textContent =
        (parts.year || "—") + "-" +
        (parts.month || "—") + "-" +
        (parts.day || "—") + " " +
        (parts.hour || "—") + ":" +
        (parts.minute || "—") + ":" +
        (parts.second || "—") + " " +
        (parts.timeZoneName || zone);
    }} catch (error) {{
      node.textContent = value.toLocaleTimeString();
    }}
  }}

  function refreshClocks() {{
    document.querySelectorAll("[data-pco-live-clock]").forEach(drawClock);
  }}

  refreshClocks();
  window.setInterval(refreshClocks, 250);
}})();
</script><script src="/static/pincabos-dashboard-lobby.js?v=dashboard-network-lan-wan-v6" defer></script><script src="/static/pincabos-live-jpeg-x11-v16.js?v=jpeg-x11-v16-playstop3" defer></script></section>'''
    return page("Dashboard", body)

# === PINCABOS_DASHBOARD_DIRECT_FUNCTION_LINKS_V1 START ===
# Les widgets fonctionnels ne doivent jamais renvoyer vers le hub générique /tools.
# Une destination est appliquée seulement si la route GET existe réellement.

_PCO_DIRECT_FUNCTION_WIDGET_TARGETS_V1 = {

    "tool_import":
        ("/tools/import-table",),

    "tool_export":
        ("/tools/export-table",),

    "tool_network":
        ("/network",),

    "tool_appearance":
        ("/tools/appearance",),

    "tool_console":
        ("/console",),

    "tool_explorer":
        ("/tools/commander",),

    "tool_external_disks":
        (
            "/tools/external-disks",
            "/external-disks",
        ),

    "tool_inputs":
        (
            "/inputs/map-commander",
            "/inputs",
        ),

    "tool_outputs":
        (
            "/dof/commander",
            "/outputs",
        ),

    "tool_keyboard":
        (
            "/inputs/keyboard",
            "/keyboard",
        ),

    "tool_audio":
        (
            "/audio-ssf",
            "/audio",
        ),

    "tool_vpinfe_ini":
        ("/tools/vpinfe/ini",),

    "tool_vpinfe_update":
        ("/tools/vpinfe/update",),

    "tool_tables":
        ("/tools/vpinfe/tables",),

    "tool_vpinfe_sample_tables":
        ("/tools/vpinfe/sample-tables",),

    "tool_vpinfe_collections":
        ("/tools/vpinfe/collections",),

    "tool_vpinfe_media":
        ("/tools/vpinfe/media",),

    "tool_media_recorder":
        ("/tools/media-recorder",),

    "tool_media_hunter":
        ("/tools/vpinfe/media-hunter",),

    "tool_vpx_ini":
        (
            "/tools/vpinballx/ini",
            "/tools/vpinball/ini",
        ),

    "tool_gpu":
        ("/gpu",),

    "tool_screens":
        (
            "/gpu",
            "/screens",
        ),

    "tool_auto_screens":
        ("/auto-screens",),

    "tool_ballcab":
        ("/tools/vpx-ball-cabinet",),

    "tool_fulldmd":
        ("/fulldmd",),

    "tool_dmd":
        (
            "/fulldmd",
            "/dmd-screen",
        ),
}

try:
    _pco_registry_for_request_before_direct_links_v1 = registry_for_request

    def registry_for_request():
        result = _pco_registry_for_request_before_direct_links_v1()

        try:
            from flask import current_app

            route_map = {}
            for rule in current_app.url_map.iter_rules():
                if "GET" in rule.methods:
                    canonical = rule.rule.rstrip("/") or "/"
                    route_map.setdefault(canonical, rule.rule)

            for widget_key, candidates in _PCO_DIRECT_FUNCTION_WIDGET_TARGETS_V1.items():
                item = result.get(widget_key)
                if not isinstance(item, dict):
                    continue

                for target in candidates:
                    actual = route_map.get(target.rstrip("/") or "/")
                    if actual:
                        item["href"] = actual
                        break

        except Exception:
            pass

        return result

except Exception:
    pass
# === PINCABOS_DASHBOARD_DIRECT_FUNCTION_LINKS_V1 END ===
