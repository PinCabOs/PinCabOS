"""Alias et compatibilité de la WebApp PinCabOS : anciennes URL de menu (/wifi, /screens, /outputs, /external-disks, /import, /tables), /api/dof/manager/ et fermeture de l'onglet Chrome actif (/api/menu/close-tab).

Code déplacé tel quel depuis app.py (PINCABOS_WEBAPP_MODULES_V1) ; les routes gardent
leurs chemins et leurs noms de fonction. `page()` (gabarit commun) est fourni par app.py
à l'enregistrement : `register(app, page)`.
"""
from __future__ import annotations


from flask import Blueprint, jsonify, redirect, request


alias_bp = Blueprint("alias", __name__)

page = None  # gabarit HTML commun, posé par register()


@alias_bp.route("/wifi")
def pincabos_alias_wifi():
    return redirect("/network", code=302)

@alias_bp.route("/screens")
def pincabos_alias_screens():
    # La vraie gestion écrans est maintenant dans GPU / Screens.
    try:
        return redirect("/gpu/screens", code=302)
    except Exception:
        return redirect("/gpu", code=302)

@alias_bp.route("/outputs")
def pincabos_alias_outputs():
    # Outputs = ancien DOF côté menu.
    return redirect("/dof", code=302)


@alias_bp.route("/api/dof/manager/")
def pincabos_api_dof_manager_slash_alias():
    # Compatibilité avec fetch('/api/dof/manager/').
    return jsonify({"ok": True, "status": "available", "message": "DOF manager route alias active"})

# === PINCABOS LEGACY ROUTE ALIASES - BGFX MIGRATION ===
# Created by Karots Sugarpie
# Purpose:
#   Keep Alpha15/old menu URLs working after Alpha16 tools route migration.
# Safety:
#   Redirect-only aliases. No filesystem or config mutation.

@alias_bp.route("/external-disks")
@alias_bp.route("/external-disks/")
def pincabos_legacy_external_disks_alias():
    return redirect("/tools/external-disks", code=302)

@alias_bp.route("/import")
@alias_bp.route("/import/")
def pincabos_legacy_import_alias():
    return redirect("/tools", code=302)

@alias_bp.route("/tables")
@alias_bp.route("/tables/")
def pincabos_legacy_tables_alias():
    return redirect("/tools", code=302)

# === PINCABOS LEGACY ROUTE ALIASES - END ===


# === PINCABOS MENU CLOSE ACTIVE CHROME TAB START ===
@alias_bp.route("/api/menu/close-tab", methods=["POST"])
def pincabos_menu_close_tab_api():
    import os
    import subprocess
    from flask import jsonify

    helper = "/opt/pincabos/bin/pincabos-close-active-chrome-tab.sh"

    if not os.path.exists(helper):
        return jsonify({"ok": False, "error": "helper_missing", "helper": helper}), 500

    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")

    # Best effort Xauthority discovery for the pinball desktop session.
    for xa in (
        "/home/pinball/.Xauthority",
        "/var/run/lightdm/root/:0",
        "/run/user/1000/gdm/Xauthority",
        "/run/user/1000/Xauthority",
    ):
        if os.path.exists(xa):
            env.setdefault("XAUTHORITY", xa)
            break

    try:
        proc = subprocess.run(
            [helper],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=3,
        )
        return jsonify({
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": proc.stdout[-2000:],
        }), (200 if proc.returncode == 0 else 500)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
# === PINCABOS MENU CLOSE ACTIVE CHROME TAB END ===


# === PINCABOS ABOUT SYSTEM AUDIT V1 START ===
@alias_bp.after_app_request
def pincabos_about_system_audit_button(response):
    """Ajoute le bouton System Audit à About sans modifier son gros module historique."""
    try:
        if request.path.rstrip("/") != "/about":
            return response
        if response.status_code != 200 or response.is_streamed:
            return response
        if response.mimetype != "text/html":
            return response

        body = response.get_data(as_text=True)
        if 'href="/system-audit"' in body:
            return response

        anchor = '<a class="button" href="/dev">🧪 Développeur / rapport testeur</a>'
        button = '<a class="button" href="/system-audit">🩺 System Audit</a>'

        if anchor in body:
            body = body.replace(anchor, anchor + "\n  " + button, 1)
        else:
            marker = "<!-- PINCABOS_ABOUT_AUDIT_OVERVIEW_V1_START -->"
            if marker in body:
                body = body.replace(
                    marker,
                    '<div style="margin:10px 0 16px;">' + button + "</div>\n" + marker,
                    1,
                )
            else:
                return response

        response.set_data(body)
        response.headers["Content-Length"] = str(len(response.get_data()))
        return response
    except Exception:
        return response
# === PINCABOS ABOUT SYSTEM AUDIT V1 END ===


def register(app, page_fn):
    """Enregistre les alias historiques, System Audit et la fermeture d'onglet."""
    global page
    page = page_fn
    app.register_blueprint(alias_bp)

    # PINCABOS_SYSTEM_AUDIT_UI_V1
    try:
        from pincabos_system_audit_ui import register as _register_system_audit
        _register_system_audit(app, page_fn)
    except Exception as exc:
        try:
            app.logger.exception("PinCabOS System Audit registration failed: %s", exc)
        except Exception:
            pass
