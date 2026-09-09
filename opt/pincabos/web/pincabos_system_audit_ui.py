#!/usr/bin/env python3
"""PinCabOS WebApp — System Audit launched from the About page."""

from __future__ import annotations

import html
import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from flask import Blueprint, Response, jsonify, make_response, request

bp = Blueprint("pincabos_system_audit_v1", __name__)

_page = None

BRIDGE = "/usr/local/sbin/pincabos-account-bridge"
LAUNCHER = "/opt/pincabos/tools/pincabos-system-audit-launcher.sh"
RUN_DIR = Path("/home/pinball/.cache/pincabos-tester-report/web")
STATE = RUN_DIR / "state.json"
CSRF = secrets.token_urlsafe(32)


def _identity():
    sudo = shutil.which("sudo")
    if not sudo:
        return None, "sudo indisponible"

    try:
        result = subprocess.run(
            [sudo, "-n", BRIDGE, "context"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=25,
            check=False,
        )
        data = json.loads(result.stdout or "{}")
    except subprocess.TimeoutExpired:
        return None, "pincabos.cc ne répond pas"
    except Exception:
        return None, "réponse du bridge invalide"

    if (
        result.returncode != 0
        or not isinstance(data, dict)
        or data.get("ok") is not True
    ):
        return None, str(data.get("error") or "cabinet non jumelé")[:120]

    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    device = data.get("device") if isinstance(data.get("device"), dict) else {}
    cabinets = data.get("cabinets") if isinstance(data.get("cabinets"), list) else []

    cabinet_id = device.get("cabinet_id")
    cabinet = next(
        (
            item
            for item in cabinets
            if isinstance(item, dict) and str(item.get("id")) == str(cabinet_id)
        ),
        {},
    )

    display_name = str(user.get("display_name") or user.get("username") or "").strip()
    if not display_name:
        return None, "nom du compte absent"

    return (
        {
            "display_name": display_name[:160],
            "username": str(user.get("username") or "")[:120],
            "cabinet_name": str(cabinet.get("cabinet_name") or "PinCabOS")[:160],
            "cabinet_id": cabinet_id,
            "online": bool(cabinet.get("device_online")),
        },
        "",
    )


def _load():
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUN_DIR, 0o700)

    temp = STATE.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    os.replace(temp, STATE)


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _tail(path, maximum=120000):
    try:
        target = Path(path)
        with target.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - maximum))
            return handle.read(maximum).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _status():
    state_data = _load()
    if not state_data:
        return {"ok": True, "state": "idle", "running": False, "log": ""}

    status_file = Path(str(state_data.get("status_file") or "/nonexistent"))
    return_code = None

    if status_file.is_file():
        try:
            return_code = int(status_file.read_text(encoding="utf-8").strip())
        except Exception:
            return_code = 1

    running = return_code is None and _alive(state_data.get("pid"))

    if running:
        state_name = "running"
    elif return_code == 0:
        state_name = "success"
    else:
        state_name = "failed"

    return {
        "ok": True,
        "state": state_name,
        "running": running,
        "return_code": return_code,
        "started_at": state_data.get("started_at"),
        "identity": state_data.get("identity"),
        "log": _tail(str(state_data.get("log_file") or "")),
    }


@bp.get("/system-audit")
def audit_page():
    if _page is None:
        return Response("renderer unavailable", 500)

    identity, error = _identity()

    if identity:
        cabinet_id = (
            "Cab" + str(identity["cabinet_id"])
            if identity["cabinet_id"] is not None
            else "—"
        )
        username = (
            "@" + html.escape(identity["username"])
            if identity["username"]
            else "—"
        )
        identity_html = (
            '<div class="aud-id ok">'
            "<b>GO — Cabinet jumelé à PinCabOS.cc</b>"
            "<span>Utilisateur : "
            + html.escape(identity["display_name"])
            + "</span>"
            "<span>Username : "
            + username
            + "</span>"
            "<span>Cabinet : "
            + html.escape(identity["cabinet_name"])
            + " — "
            + html.escape(cabinet_id)
            + "</span>"
            "</div>"
        )
    else:
        identity_html = (
            '<div class="aud-id bad">'
            "<b>NOGO — PinCabOS.cc</b>"
            "<span>"
            + html.escape(error)
            + "</span>"
            "</div>"
        )

    body = r"""
<style>
.aud{display:grid;gap:14px}
.aud-id{display:grid;gap:5px;padding:13px;border:1px solid #555;border-radius:12px}
.aud-id.ok{border-color:#2ed18a;background:rgba(46,209,138,.08)}
.aud-id.bad{border-color:#ff5a68;background:rgba(255,90,104,.08)}
.aud-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.aud-status{font-weight:900}
.aud-bar{height:12px;border-radius:99px;overflow:hidden;background:#20222a}
.aud-fill{height:100%;width:0;background:linear-gradient(90deg,#ff7900,#ffb000);transition:.3s}
.aud-log{min-height:390px;max-height:62vh;overflow:auto;white-space:pre-wrap;background:#06070b;border:1px solid rgba(255,176,0,.3);border-radius:12px;padding:12px;font:13px/1.45 ui-monospace,Consolas,monospace}
</style>

<div class="card aud">
  <div>
    <h2>🩺 PinCabOS — System Audit</h2>
    <p>Lecture seule • Cloudflare Worker → GitHub • aucun token GitHub sur le cabinet.</p>
  </div>

  __IDENTITY__

  <div class="aud-actions">
    <button id="audStart" class="button" type="button">LANCER SYSTEM AUDIT</button>
    <a class="button secondary" href="/about">RETOUR ABOUT</a>
    <span id="audStatus" class="aud-status">PRÊT</span>
  </div>

  <div class="aud-bar"><div id="audFill" class="aud-fill"></div></div>
  <pre id="audLog" class="aud-log">Aucun audit lancé.</pre>
</div>

<script>
(() => {
"use strict";

const B=document.getElementById("audStart");
const S=document.getElementById("audStatus");
const L=document.getElementById("audLog");
const F=document.getElementById("audFill");
let progress=8;

function draw(data){
  B.disabled=!!data.running;

  if(data.state==="running"){
    S.textContent="AUDIT EN COURS";
    progress=progress>92?18:progress+7;
    F.style.width=progress+"%";
  }else if(data.state==="success"){
    S.textContent="GO — TERMINÉ ET TRANSMIS";
    F.style.width="100%";
  }else if(data.state==="failed"){
    S.textContent="NOGO — ÉCHEC";
    F.style.width="100%";
  }else{
    S.textContent="PRÊT";
    F.style.width="0%";
  }

  if(data.log){
    const bottom=(L.scrollTop+L.clientHeight)>=(L.scrollHeight-40);
    L.textContent=data.log;
    if(bottom){L.scrollTop=L.scrollHeight;}
  }
}

async function poll(){
  try{
    const response=await fetch("/api/system-audit/status",{cache:"no-store"});
    const data=await response.json();
    draw(data);
  }catch(error){
    S.textContent="NOGO — API";
  }
}

B.onclick=async()=>{
  B.disabled=true;
  S.textContent="PRÉPARATION...";
  L.textContent="Résolution du compte PinCabOS.cc...\n";

  try{
    const response=await fetch("/api/system-audit/run",{
      method:"POST",
      headers:{"X-PinCabOS-Audit-CSRF":"__CSRF__"},
      cache:"no-store"
    });
    const data=await response.json();
    if(!response.ok||data.ok===false){
      throw new Error(data.error||("HTTP "+response.status));
    }
    draw(data);
  }catch(error){
    S.textContent="NOGO — "+error.message;
    B.disabled=false;
  }
};

poll();
setInterval(poll,1000);
})();
</script>
"""

    body = body.replace("__IDENTITY__", identity_html).replace(
        "__CSRF__",
        html.escape(CSRF, quote=True),
    )

    response = make_response(_page("PinCabOS System Audit", body))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/api/system-audit/run")
def run_audit():
    supplied = str(request.headers.get("X-PinCabOS-Audit-CSRF") or "")
    if not secrets.compare_digest(supplied, CSRF):
        return jsonify({"ok": False, "error": "invalid_csrf"}), 403

    current = _status()
    if current.get("running"):
        return jsonify(current), 409

    identity, error = _identity()
    if not identity:
        return jsonify({"ok": False, "error": error}), 409

    if not Path(LAUNCHER).is_file():
        return jsonify({"ok": False, "error": "launcher local absent"}), 500

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RUN_DIR, 0o700)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_file = RUN_DIR / f"audit-{stamp}.log"
    status_file = RUN_DIR / f"audit-{stamp}.status"
    runner = RUN_DIR / f"runner-{stamp}.sh"

    runner.write_text(
        "#!/usr/bin/env bash\n"
        "set +e\n"
        "umask 077\n"
        "bash \"$PINCABOS_AUDIT_LAUNCHER\"\n"
        "rc=$?\n"
        "printf '%s\\n' \"$rc\" > \"$PINCABOS_AUDIT_STATUS\"\n"
        "exit \"$rc\"\n",
        encoding="utf-8",
    )
    os.chmod(runner, 0o700)

    env = os.environ.copy()
    env["PINCABOS_SESSION_NAME"] = identity["display_name"]
    env["PINCABOS_TESTER_NAME"] = identity["display_name"]
    env["PINCABOS_AUDIT_LAUNCHER"] = LAUNCHER
    env["PINCABOS_AUDIT_STATUS"] = str(status_file)

    with log_file.open("ab", buffering=0) as output:
        process = subprocess.Popen(
            [str(runner)],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            cwd="/home/pinball",
            env=env,
            start_new_session=True,
            close_fds=True,
        )

    _save(
        {
            "pid": process.pid,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "log_file": str(log_file),
            "status_file": str(status_file),
            "identity": identity,
        }
    )

    return jsonify(_status()), 202


@bp.get("/api/system-audit/status")
def audit_status():
    return jsonify(_status())


def register(app, page_renderer=None):
    global _page

    if page_renderer is not None:
        _page = page_renderer

    if "pincabos_system_audit_v1.audit_page" not in app.view_functions:
        app.register_blueprint(bp)
