# PinCabOS-File created by Karots Sugarpie
import urllib.error
import urllib.request
import sqlite3
import tempfile
try:
    import pincabos_ini
except ImportError:   # hors /opt (tests, depot) : le module vit a cote des outils
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    import pincabos_ini
import zipfile
import mimetypes
import urllib.parse
from flask import send_file, request, redirect, session
from screen import screen_bp
from internal_disk import internal_disk_bp
import shutil
import uuid
import shlex
from werkzeug.utils import secure_filename
from dashboard_plus import render_dashboard
from pincabos_webapp_keyboard_tools_v6 import register_keyboard_tools_v6 as pco_register_keyboard_tools_v6
from pincabos_webapp_keyboard import register_keyboard_routes as pco_register_keyboard_routes
from pincabos_webapp_dashboard_control import register_dashboard_control_routes as pco_register_dashboard_control_routes
from flask import Flask, redirect, url_for, jsonify, request
from pathlib import Path
from tools import register_tools_routes

# === PINCABOS MODULAR ROUTES START ===
import pincabos_webapp_audio as pco_audio_routes
import pincabos_webapp_inputs as pco_inputs_routes
import pincabos_webapp_firstrun as pco_firstrun_routes
import pincabos_webapp_dev_admin as pco_dev_admin_routes
import pincabos_webapp_exports as pco_exports_routes
import pincabos_backupcfg as pco_backupcfg_routes
# === PINCABOS MODULAR ROUTES END ===
from pincabos_webapp_import_metadata import pincabos_write_imported_table_metadata

# === PINCABOS WEBAPP CORE CLEAN IMPORT START ===
from pincabos_webapp_core import (
    esc,
    run_cmd,
    shlex_quote,
    service_status,
    pincabos_meta,
    pincabos_backup_config_file,
    pincabos_write_json_with_meta,
    get_ip,
    pincabos_version,
    pincabos_get_vpinfe_paths_for_tools,
    PCO_PATHS,
    PCO_SERVICES,
    pco_path,
    pco_script,
    pco_sudo_script_cmd,
    pco_systemctl_cmd,
    pco_service,
    pco_service_status,
    pco_vpinfe_service_name,
    pco_frontend_compat_service_name,
    pco_path_text,
    pco_script_text,
    pco_vpx_kill_pattern,
    pco_vpx_version_command,
    pco_vpinfe_version_command,
    pco_launch_webapp_screen_command,
    pincabos_vpx_executable_path,
    pincabos_vpx_tables_dir,
    pincabos_vpx_ini_path,
    pincabos_vpinfe_ini_path,
    pincabos_vpinfe_config_ini_path,
    PINCABOS_VPX_EXECUTABLE,
    PINCABOS_VPX_TABLES_DIR,
    PINCABOS_VPX_INI,
    PINCABOS_VPINFE_ROOT,
    PINCABOS_VPINFE_CURRENT,
    PINCABOS_VPINFE_INI,
    PINCABOS_VPINFE_CONFIG_INI,
    PINCABOS_VPINFE_TEMPLATE_INI,
    PINCABOS_VPINFE_BIN,
)
# === PINCABOS WEBAPP CORE CLEAN IMPORT END ===
# === PINCABOS WEBAPP ADMIN MODULE IMPORT START ===
from pincabos_webapp_admin import (
    pco_admin_cmd_for_script,
    pco_admin_cmd_for_systemctl,
    pco_admin_shell_join,
    pco_admin_run_capture,
    pco_admin_now_stamp,
    pco_admin_tail_text,
    pco_admin_existing_scripts,
    pco_admin_iframe_body,
)
# === PINCABOS WEBAPP ADMIN MODULE IMPORT END ===

# === PINCABOS OFFICIAL VPX PATHS START ===
# Stage2 clean:
# Les chemins VPX/VPinball sont centralises dans pincabos_webapp_core.py.
# VPX officiel: pco_path('vpx_dir')
# Wrapper officiel: pco_path('vpx_wrapper')
# Tables officielles: /home/pinball/Tables
PINNED_VPX_EXECUTABLE = PINCABOS_VPX_EXECUTABLE
PINNED_VPX_TABLES_DIR = PINCABOS_VPX_TABLES_DIR
PINNED_VPX_INI = PINCABOS_VPX_INI
# === PINCABOS OFFICIAL VPX PATHS END ===

# Stage2 clean:
# Les chemins VPinFE sont centralises dans pincabos_webapp_core.py.
# VPinFE current: pco_path('vpinfe_current')
# Runtime ini: chemin runtime officiel résolu depuis version.json / manifest PinCabOS
# Config ini: /home/pinball/.config/vpinfe/vpinfe.ini
# Template ini: /opt/pincabos/essentials/VPinFEfiles/vpinfe.ini


from datetime import datetime
import socket
import subprocess
import psutil
import json
import time
import os
import html
import re
import hashlib


# PINCABOS_WEBAPP_MODULES_V1 : gabarit commun page() (passé aux modules par register(app, page)) et état
# d'achèvement de la première exécution (redirection ci-dessous).
from pincabos_webapp_gabarit import page, pincabos_firstrun_is_complete  # noqa: E402


def pincabos_webapp_secret_key():
    """Load a persistent session secret without falling back to a public value."""
    configured = os.environ.get("PINCABOS_SECRET_KEY", "").strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError("PINCABOS_SECRET_KEY doit contenir au moins 32 caractères.")
        return configured

    secret_path = Path("/opt/pincabos/config/webapp-secret.key")
    try:
        if secret_path.is_file():
            saved = secret_path.read_text(encoding="utf-8").strip()
            if len(saved) >= 32:
                return saved
            raise RuntimeError(f"Secret WebApp invalide: {secret_path}")

        import secrets
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_urlsafe(48)
        try:
            fd = os.open(str(secret_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            saved = secret_path.read_text(encoding="utf-8").strip()
            if len(saved) >= 32:
                return saved
            raise RuntimeError(f"Secret WebApp invalide: {secret_path}")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(generated + "\n")
        try:
            os.chmod(secret_path, 0o600)
        except OSError:
            pass
        return generated
    except OSError as exc:
        raise RuntimeError("Impossible de charger ou créer le secret de session PinCabOS.") from exc


# PINCABOS_STOCKAGE_LIBELLE_V1
app = Flask(__name__)
# === PINCABOS DASHBOARD V7 CONTROL ROUTES ===
pco_register_dashboard_control_routes(app)
# === PINCABOS DASHBOARD V7 CONTROL ROUTES END ===
app.register_blueprint(screen_bp)
app.register_blueprint(internal_disk_bp)

# PINCABOS_PUPPACK_PAGE_V1
# Page de choix de la disposition d'ecrans d'un PuP-Pack. Aucun privilege :
# les fichiers du pack appartiennent deja a pinball.
try:
    from puppack_options import puppack_bp as _pco_puppack_bp
    app.register_blueprint(_pco_puppack_bp)
except Exception as _pco_puppack_e:
    print("WARN: PinCabOS PuP-Pack module load failed:", _pco_puppack_e)
app.secret_key = pincabos_webapp_secret_key()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# PINCABOS_WEBAPP_SECURITY_V1_REGISTER
from pincabos_webapp_security import install_pincabos_security
install_pincabos_security(app)
# PINCABOS_WEBAPP_SECURITY_V1_REGISTER_END
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024 * 1024

BASE = Path("/opt/pincabos")
LOG_DIR = BASE / "logs" / "jobs"
JOB_DIR = LOG_DIR
LOG_DIR.mkdir(parents=True, exist_ok=True)
JOB_DIR.mkdir(parents=True, exist_ok=True)


# === FIRST RUN WIZARD - PINCABOS START ===
# Tools hub routes are registered after the main page() layout helper is available.
# PINCABOS_IMPEXP_NATIVE_V1: native Import / Export Centers; no iframe and no response injection.
app.config["PINCABOS_IMPEXP_NATIVE_UI"] = True
register_tools_routes(app, page)
from pincabos_impexp import register_pincabos_impexp_routes
register_pincabos_impexp_routes(app)


# === FIRST RUN WIZARD - PINCABOS END ===

# === PINCABOS FIRST RUN AUTO REDIRECT START ===


# === PINCABOS KEYBOARD TOOLS V6 BEGIN ===
pco_register_keyboard_tools_v6(app)
# === PINCABOS KEYBOARD TOOLS V6 END ===

# === PINCABOS KEYBOARD WIDGET ROUTES BEGIN ===
pco_register_keyboard_routes(app, page)
# === PINCABOS KEYBOARD WIDGET ROUTES END ===


@app.before_request
def pincabos_first_run_auto_redirect():
    try:
        path = request.path or "/"

        allowed_prefixes = (
            "/first-run",
            "/static",
            "/api",
            "/admin",
            "/dev",
            "/service-control",
        )

        if path != "/":
            return None

        if any(path.startswith(p) for p in allowed_prefixes):
            return None

        if not pincabos_firstrun_is_complete():
            return redirect("/first-run")

        return None
    except Exception:
        return None
# === PINCABOS FIRST RUN AUTO REDIRECT END ===


# === PINCABOS_ABOUT_HELP_REFACTOR_V1 ===
# Route help_page déplacée vers /opt/pincabos/web/PinCabOS-AboutHelp.py


# === PINCABOS_ABOUT_HELP_REFACTOR_V1 ===
# Route about_page déplacée vers /opt/pincabos/web/PinCabOS-AboutHelp.py


@app.route("/")
def dashboard():
    return render_dashboard(page, esc, get_ip, service_status, pincabos_version)


# PINCABOS_WEBAPP_MODULES_V1 : pages GPU / Écrans et DOF / Outputs dans leurs modules.
import pincabos_webapp_gpu as pco_gpu_routes
import pincabos_webapp_dof as pco_dof_routes

pco_gpu_routes.register(app, page)
pco_dof_routes.register(app, page)


# PINCABOS_WEBAPP_MODULES_V1 : contrôle des services, du processus VPX et versions dans leur module.
import pincabos_webapp_systeme as pco_systeme_routes

pco_systeme_routes.register(app, page)


# PINCABOS_WEBAPP_MODULES_V1 : pages DMD / FullDMD dans leur module.
import pincabos_webapp_dmd as pco_dmd_routes

pco_dmd_routes.register(app, page)


# PINCABOS_WEBAPP_MODULES_V1 : console, réseau, écran WebApp et mot de passe root dans leur module.
import pincabos_webapp_console as pco_console_routes

pco_console_routes.register(app, page)


# === PINCABOS AUDIO SYSTEM VOLUME BALANCE START ===


# === PINCABOS AUDIO VU HTML ROUTE START ===


# === SSF COMMANDER V1 - PINCABOS START ===


# === PINCABOS AUDIO WAV ROUTES REAL START ===


# PINCABOS_WEBAPP_MODULES_V1 : identifiants admin, page admin composée, supporters, version.json dans leur module.
import pincabos_webapp_admin_pages as pco_admin_pages_routes

pco_admin_pages_routes.register(app, page)


# Stage5B.4B: legacy route disabled, real iframe route is pincabos_admin_frame_cleanup_dry_run.

# Stage5B.4B: legacy route disabled, real iframe route is pincabos_admin_frame_cleanup_apply.


# Stage5B.4B: legacy route disabled, real iframe route is pincabos_admin_frame_cleanup_dry_run.

# Stage5B.4B: legacy route disabled, real iframe route is pincabos_admin_frame_cleanup_apply.


# PINCABOS_WEBAPP_MODULES_V1 : bille VPX (cabinet, simple, UserBalls) dans son module.
import pincabos_webapp_vpxball as pco_vpxball_routes

pco_vpxball_routes.register(app, page)


# /tools route is registered from tools.py


# PINCABOS_WEBAPP_MODULES_V1 : import de tables (pages et API) dans son module.
import pincabos_webapp_import as pco_import_routes

pco_import_routes.register(app, page)


# PINCABOS_WEBAPP_MODULES_V1 : gestion du stockage (USB, SMB) dans son module, une seule vue par chemin.
import pincabos_webapp_disques as pco_disques_routes

pco_disques_routes.register(app, page)


# PINCABOS_WEBAPP_MODULES_V1 : Commander (gestionnaire de fichiers, visionneuse live) dans son module.
import pincabos_webapp_commander as pco_commander_routes

pco_commander_routes.register(app, page)


# PINCABOS_WEBAPP_MODULES_V1 : export de tables dans son module.
import pincabos_webapp_export as pco_export_routes

pco_export_routes.register(app, page)


# Stage5A.3: route legacy retirée pour éviter doublon avec pcos_update_api_status.


# --- PinCabOS update channel check patch ---


# --- /PinCabOS update channel check patch ---


# === PinCabOS cab-current route aliases ===
# Compatibilité routes/menu après nettoyage Alpha 1.1.
# Ces routes ne remplacent pas les fonctions existantes; elles évitent les 404 de boutons/menu.

# PINCABOS_WEBAPP_MODULES_V1 : alias historiques et fermeture d'onglet dans leur module.
import pincabos_webapp_alias as pco_alias_routes

pco_alias_routes.register(app, page)


# PinCabOS dashboard-plus final display correction
# Corrects stale dashboard-plus display values without rewriting the whole dashboard.
def _pco_dashboard_plus_final_detect_vpx():
    import os
    import subprocess
    import re

    import pincabos_webapp_core as _core

    candidates = [
        "/opt/pincabos/bin/vpx-vpinfe-default.sh",
        str(_core.PCO_PATHS.vpx_dir / "VPinballX_BGFX"),
    ]

    existing = [x for x in candidates if os.path.exists(x)]
    if not existing:
        return "non détecté"

    for exe in existing:
        for arg in ("--version", "-version", "-h", "--help"):
            try:
                r = subprocess.run(
                    [exe, arg],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=3,
                    env=dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0")),
                )
                out = (r.stdout or "").strip()
                if not out:
                    continue

                lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
                for ln in lines[:12]:
                    if re.search(r"(VPinball|Visual Pinball|VPX|VPinballX|version|standalone)", ln, re.I):
                        ln = re.sub(r"\s+", " ", ln)
                        if len(ln) > 96:
                            ln = ln[:93] + "..."
                        return ln

                # If command responded but no clear version line.
                return "installé / version non lisible"
            except Exception:
                continue

    if "/opt/pincabos/bin/vpx-vpinfe-default.sh" in existing:
        return "installé / wrapper vpx.sh"
    return "installé / version non lisible"


def _pco_dashboard_plus_final_audio_message():
    import os
    import subprocess

    cards = ""
    try:
        if os.path.exists("/proc/asound/cards"):
            cards = open("/proc/asound/cards", "r", errors="replace").read().strip()
    except Exception:
        cards = ""

    if cards and "no soundcards" not in cards.lower():
        try:
            r = subprocess.run(["aplay", "-l"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=3)
            out = (r.stdout or "").strip()
            if out and "no soundcards" not in out.lower():
                return None
        except Exception:
            return None

    return "Aucune carte audio ALSA détectée par Linux dans cette VM/session. Ce n’est pas une erreur PinCabOS si la VM n’a pas de périphérique audio attaché. Sur un cabinet réel, vérifier avec aplay -l, pactl list short sinks et wpctl status."


def _pco_dashboard_plus_final_html_fix(html):
    if not isinstance(html, str):
        return html

    vpx_label = _pco_dashboard_plus_final_detect_vpx()
    audio_msg = _pco_dashboard_plus_final_audio_message()

    # Correct stale service name.
    html = html.replace("pincabos-webapp.service", "pincabos-webapp.service")

    # Correct old VPX runtime path.
    html = html.replace("/opt/pincabos/apps/vpinball", "/opt/pincabos/apps/vpinball")

    # Correct rendered VPX version text.
    html = html.replace("VPX : non détecté", "VPX : " + vpx_label)
    html = html.replace("VPX&nbsp;: non détecté", "VPX&nbsp;: " + vpx_label)

    # Correct common HTML separated VPX value patterns.
    html = re.sub(
        r"(VPX\s*</[^>]+>\s*<[^>]+>)(non détecté|non detecte|not detected)(</[^>]+>)",
        r"\1" + vpx_label + r"\3",
        html,
        flags=re.I,
    )

    # Clarify audio if Linux has no audio device.
    if audio_msg:
        html = html.replace(
            "Aucune sortie audio ALSA détectée par le dashboard.",
            audio_msg,
        )
        html = html.replace(
            "Aucune configuration audio sauvegardée.",
            "Aucune configuration audio sauvegardée. Le dashboard ne peut pas mapper SSF V2 tant qu’aucune carte audio Linux n’est visible.",
        )

    # Make essential path labels current.
    html = html.replace("VPX runtime", "VPX runtime")
    html = html.replace("VPinFE runtime", "VPinFE runtime")

    return html


def _pco_dashboard_plus_final_install_wrapper():
    try:
        dashboard_rules = []
        for rule in list(app.url_map.iter_rules()):
            r = str(rule.rule).lower()
            if "dashboard" in r or "dashbord" in r or r == "/":
                dashboard_rules.append(rule)

        for rule in dashboard_rules:
            endpoint = rule.endpoint
            old_view = app.view_functions.get(endpoint)
            if not old_view or getattr(old_view, "_pco_dashboard_plus_final_wrapped", False):
                continue

            def _make_wrapper(fn):
                def _wrapped(*args, **kwargs):
                    resp = fn(*args, **kwargs)

                    try:
                        flask_resp = app.make_response(resp)
                        ctype = flask_resp.headers.get("Content-Type", "")
                        if "text/html" in ctype or ctype.startswith("text/") or ctype == "":
                            data = flask_resp.get_data(as_text=True)
                            fixed = _pco_dashboard_plus_final_html_fix(data)
                            if fixed != data:
                                flask_resp.set_data(fixed)
                                flask_resp.headers["Content-Length"] = str(len(flask_resp.get_data()))
                        return flask_resp
                    except Exception:
                        return resp

                _wrapped._pco_dashboard_plus_final_wrapped = True
                _wrapped.__name__ = getattr(fn, "__name__", "dashboard_plus_final_wrapped")
                return _wrapped

            app.view_functions[endpoint] = _make_wrapper(old_view)

        print("GO: dashboard-plus final correction wrapper installed")
    except Exception as exc:
        print("NOGO: dashboard-plus final correction wrapper failed:", exc)


_pco_dashboard_plus_final_install_wrapper()


# === PINCABOS MODULAR ROUTES REGISTRATION START ===
# Registration occurs after the core helpers are defined so modules can reuse the one canonical layout and services.
for _pco_module in (
    pco_audio_routes,
    pco_inputs_routes,
    pco_firstrun_routes,
    pco_dev_admin_routes,
    pco_exports_routes,
    pco_backupcfg_routes,
):
    _pco_module.register(app)
del _pco_module
# === PINCABOS MODULAR ROUTES REGISTRATION END ===


# PINCABOS_LIVE_TABLE_STATUS_CARD_V2
from pincabos_live_table_status import register_live_table_status
register_live_table_status(app)


# PINCABOS_PCX_LIVE_VIEWER_V1
# Vue en nouvelle fenetre + lecture media + editeur texte securise.


# PINCABOS_FULLDMD_EQUAL_CARDS_V1
# Rend les deux cartes Calibration FullDMD / DMD global égales.
@app.after_request
def pincabos_fulldmd_equal_calibration_cards(response):
    try:
        from flask import request as _request

        if _request.path.rstrip("/") != "/fulldmd":
            return response

        if response.status_code != 200 or response.is_streamed:
            return response

        if response.mimetype != "text/html":
            return response

        body = response.get_data(as_text=True)

        if 'id="pincabos-fulldmd-equal-cards-v1"' in body:
            return response

        style = """
<style id="pincabos-fulldmd-equal-cards-v1">
.fulldmd-calibration-grid {
  align-items: stretch !important;
}

.fulldmd-calibration-grid > .card {
  height: 100%;
  min-height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}

.fulldmd-calibration-grid > .card .fulldmd-actions-column {
  margin-top: auto;
}

@media (max-width: 900px) {
  .fulldmd-calibration-grid > .card {
    height: auto;
    min-height: 0;
  }
}
</style>
"""

        if "</head>" in body:
            body = body.replace("</head>", style + "\n</head>", 1)
        elif "</body>" in body:
            body = body.replace("</body>", style + "\n</body>", 1)
        else:
            body += style

        response.set_data(body)
        return response

    except Exception:
        return response

# PINCABOS_FOOTER_LAYOUT_V14_2

# PINCABOS_FULLDMD_AUTOARRANGE_WEB_V1
try:
    from pincabos_fulldmd_autoarrange import register_fulldmd_autoarrange
    register_fulldmd_autoarrange(app, page, esc)
except Exception as _pincabos_fulldmd_autoarrange_error:
    try:
        print(f"WARN: FullDMD AutoArrange routes unavailable: {_pincabos_fulldmd_autoarrange_error}")
    except Exception:
        pass
# PINCABOS_FULLDMD_AUTOARRANGE_WEB_V1_END

# PINCABOS_APPEARANCE_GLOBAL_INJECTOR_V1
from pincabos_appearance_global import install_appearance_global
install_appearance_global(app)


# PINCABOS_BATCH_TRANSFER_V1_REGISTER
try:
    from pincabos_batch_transfer import register_pincabos_batch_transfer
    register_pincabos_batch_transfer(app)
except Exception:
    app.logger.exception("PinCabOS Batch Import/Export registration failed")


# PINCABOS_AUDIO_VOLUME_API_ONLY_V2 BEGIN
try:
    from pincabos_audio_volume_widget import register as _pincabos_audio_volume_widget_register
    _pincabos_audio_volume_widget_register(app)
except Exception as _pincabos_audio_volume_widget_error:
    try:
        app.logger.exception("PinCabOS audio volume API registration failed: %s", _pincabos_audio_volume_widget_error)
    except Exception:
        pass
# PINCABOS_AUDIO_VOLUME_API_ONLY_V2 END

# === PINCABOS WEBAPP MAIN ENTRYPOINT END-OF-FILE V1 ===

# === PINCABOS_IMAGE_STUDIO_V11_REGISTER START ===
try:
    from pincabos_image_studio import register as _pincabos_image_studio_register
    _pincabos_image_studio_register(app)
except Exception as _pincabos_image_studio_error:
    try:
        app.logger.exception("PinCabOS Image Studio registration failed: %s", _pincabos_image_studio_error)
    except Exception:
        pass
# === PINCABOS_IMAGE_STUDIO_V11_REGISTER END ===


# === PINCABOS_ABOUT_HELP_REFACTOR_V1_REGISTER START ===
try:
    import importlib.util as _pco_ah_importlib_util
    from pathlib import Path as _pco_ah_Path

    _pco_ah_path = _pco_ah_Path(__file__).with_name("PinCabOS-AboutHelp.py")
    _pco_ah_spec = _pco_ah_importlib_util.spec_from_file_location("pincabos_abouthelp", str(_pco_ah_path))

    if _pco_ah_spec and _pco_ah_spec.loader:
        _pco_ah_mod = _pco_ah_importlib_util.module_from_spec(_pco_ah_spec)
        _pco_ah_spec.loader.exec_module(_pco_ah_mod)
        _pco_ah_mod.register(
            app,
            page_func=page,
            esc_func=esc,
            pco_path_text_func=pco_path_text,
            pincabos_version_func=pincabos_version,
        )
    else:
        raise RuntimeError("Unable to load PinCabOS-AboutHelp.py")
except Exception as _pco_ah_error:
    try:
        app.logger.exception("PinCabOS About/Help registration failed: %s", _pco_ah_error)
    except Exception:
        pass
# === PINCABOS_ABOUT_HELP_REFACTOR_V1_REGISTER END ===

# PINCABOS_ZEDMD_REGISTER BEGIN
try:
    from pincabos_zedmd import register as _pincabos_zedmd_register
    _pincabos_zedmd_register(app, page, esc)
except Exception as _pincabos_zedmd_error:
    try:
        app.logger.exception("PinCabOS ZeDMD registration failed: %s", _pincabos_zedmd_error)
    except Exception:
        pass
# PINCABOS_ZEDMD_REGISTER END

# PINCABOS_VPS_REGISTER BEGIN
try:
    from pincabos_webapp_vps import register as _pincabos_vps_register
    _pincabos_vps_register(app, page, esc)
except Exception as _pincabos_vps_error:
    try:
        app.logger.exception("PinCabOS VPS registration failed: %s", _pincabos_vps_error)
    except Exception:
        pass
# PINCABOS_VPS_REGISTER END

# PINCABOS_RESEAU_REGISTER BEGIN
try:
    from pincabos_webapp_network import register as _pincabos_network_register
    _pincabos_network_register(app, page, esc)
except Exception as _pincabos_network_error:
    try:
        app.logger.exception("PinCabOS network registration failed: %s", _pincabos_network_error)
    except Exception:
        pass
# PINCABOS_RESEAU_REGISTER END

# PINCABOS_DUDESCAB_CONFIG_PAGE_V3_REGISTER BEGIN
try:
    from pincabos_dudescab_config import register as _pincabos_dudescab_config_register
    _pincabos_dudescab_config_register(app, page, esc)
    from pincabos_dudescab_protocol import register as _pincabos_dudescab_protocol_register
    _pincabos_dudescab_protocol_register(app)
except Exception as _pincabos_dudescab_config_error:
    try:
        app.logger.exception("PinCabOS DudesCabConfig V3 registration failed: %s", _pincabos_dudescab_config_error)
    except Exception:
        pass
# PINCABOS_DUDESCAB_CONFIG_PAGE_V3_REGISTER END

# PINCABOS_DOF_HARDWARE_PAGE_V1_REGISTER BEGIN
try:
    from pincabos_dof_hardware import register as _pincabos_dof_hardware_register
    _pincabos_dof_hardware_register(app, page, esc)
except Exception as _pincabos_dof_hardware_error:
    try:
        app.logger.exception("PinCabOS DOF hardware page registration failed: %s", _pincabos_dof_hardware_error)
    except Exception:
        pass
# PINCABOS_DOF_HARDWARE_PAGE_V1_REGISTER END


# PINCABOS_EXPLORER_INSTALL_PINCABOS_LOADER_V1
try:
    import importlib.util as _pco_explorer_install_importlib_util
    from pathlib import Path as _pco_explorer_install_Path

    _pco_explorer_install_path = _pco_explorer_install_Path(__file__).with_name("PinCabOS-ExplorerInstall.py")
    _pco_explorer_install_spec = _pco_explorer_install_importlib_util.spec_from_file_location(
        "pincabos_explorer_install_external",
        str(_pco_explorer_install_path),
    )
    _pco_explorer_install_mod = _pco_explorer_install_importlib_util.module_from_spec(_pco_explorer_install_spec)
    _pco_explorer_install_spec.loader.exec_module(_pco_explorer_install_mod)
    _pco_explorer_install_mod.register(
        app=app,
        page=page,
        esc=esc,
    )
except Exception as _pco_explorer_install_e:
    print("WARN: PinCabOS ExplorerInstall module load failed:", _pco_explorer_install_e)

# PINCABOS_PUPPACK_EXPLORER_V1
# Bouton "Options d'ecrans", affiche uniquement dans un dossier de PuP-Pack.
# Pose apres l'Explorateur pour envelopper la vue deja enveloppee par lui.
try:
    from puppack_options import install_puppack_explorer_button as _pco_puppack_explorer
    print("GO: PinCabOS PuP-Pack explorer button", _pco_puppack_explorer(app))
except Exception as _pco_puppack_explorer_e:
    print("WARN: PinCabOS PuP-Pack explorer button failed:", _pco_puppack_explorer_e)

# PINCABOS_PACKAGE_ICON_LOADER_V1
try:
    import importlib.util as _pco_package_icon_importlib_util
    from pathlib import Path as _pco_package_icon_Path

    _pco_package_icon_path = _pco_package_icon_Path(__file__).with_name("PinCabOS-PackageIcon.py")
    _pco_package_icon_spec = _pco_package_icon_importlib_util.spec_from_file_location(
        "pincabos_package_icon_external",
        str(_pco_package_icon_path),
    )
    _pco_package_icon_mod = _pco_package_icon_importlib_util.module_from_spec(_pco_package_icon_spec)
    _pco_package_icon_spec.loader.exec_module(_pco_package_icon_mod)
    _pco_package_icon_mod.register(app)
except Exception as _pco_package_icon_e:
    print("WARN: PinCabOS PackageIcon module load failed:", _pco_package_icon_e)

# PINCABOS_EXPLORER_TABLE_TEST_CENTER_V1_REGISTER
try:
    import pincabos_explorer_table_test as _pco_explorer_table_test
    from pincabos_webapp_import import pincabos_detect_batch as _pco_detect_batch
    _pco_explorer_table_test.register(
        app,
        detect_batch=_pco_detect_batch,
    )
except Exception as _pco_explorer_table_test_error:
    print(
        "WARN: Explorer Table Test Center load failed:",
        _pco_explorer_table_test_error,
    )

# PINCABOS_MAIN_ENTRYPOINT_LAST_V1

# PINCABOS_LINK_UI_V1_START
from pincaboslink import register_pincaboslink
register_pincaboslink(app, page)
# PINCABOS_LINK_UI_V1_END

if __name__ == "__main__":
    app.run(
        host=os.environ.get("PINCABOS_WEB_HOST", os.environ.get("PCO_WEB_HOST", "127.0.0.1")),
        port=int(os.environ.get("PINCABOS_WEB_PORT", os.environ.get("PCO_WEB_PORT", "5055"))),
        debug=False,
    )
