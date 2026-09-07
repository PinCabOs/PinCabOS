"""PinCabOS WebApp — page ZeDMD (USB ou Wi-Fi) pour VPX et VPinFE.

PINCABOS_ZEDMD_WEB_V2

La page n'ecrit jamais les INI elle-meme : elle modifie /opt/pincabos/config/zedmd.json
puis appelle /opt/pincabos/tools/pincabos-zedmd (detect / status / apply / test),
l'unique ecrivain des sections [Plugin.DMDUtil] (VPX) et [libdmdutil] (VPinFE).
"""
import json
import os  # noqa: F401
import subprocess

from flask import request

TOOL = "/opt/pincabos/tools/pincabos-zedmd"
CONFIG = "/opt/pincabos/config/zedmd.json"


def _run(*args, timeout=30, privileged=False):
    # /opt/pincabos/config et les INI cibles sont accessibles a pinball.
    # `privileged` reste reserve aux operations systeme futures.
    cmd = [TOOL, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 99, f"ERREUR: {exc}"


def _status():
    rc, out = _run("status")
    try:
        return json.loads(out)
    except ValueError:
        return {"config": {"mode": "off", "device": "", "wifi_addr": "", "brightness": -1,
                           "targets": "both"}, "vpx": {}, "vpinfe": {}, "warnings": [out.strip()],
                "test_available": False}


def _detect():
    rc, out = _run("detect")
    try:
        return json.loads(out)
    except ValueError:
        return []


def _save_config(cfg):
    rc, out = _run("set", json.dumps(cfg, ensure_ascii=False), privileged=False)
    if rc != 0:
        raise OSError(out.strip() or f"rc={rc}")


def _restart_vpinfe():
    try:
        proc = subprocess.run(
            ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "restart", "pincabos-vpinfe.service"],
            capture_output=True, text=True, timeout=60,
        )
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def register(app, page, esc):

    def _page(st, ports, notice=""):
        cfg = st.get("config", {})
        vpx = st.get("vpx", {})
        fe = st.get("vpinfe", {})
        mode = cfg.get("mode", "off")
        targets = cfg.get("targets", "both")

        def checked(name, value):
            return " checked" if str(cfg.get(name, "")) == value else ""

        port_options = ['<option value="">Auto (VPX + VPinFE/libdmdutil detectent le ZeDMD)</option>']
        for p in ports:
            path = p.get("by_id") or p["device"]
            sel = " selected" if cfg.get("device") in (path, p["device"]) else ""
            tag = "✅ " if p.get("candidate") else "⛔ "
            port_options.append(
                f'<option value="{esc(path)}"{sel}>{tag}{esc(p["device"])} — {esc(p.get("label", ""))}'
                f'{(" (" + esc(p["model"]) + ")") if p.get("model") else ""}</option>'
            )
        if cfg.get("device") and not any(cfg["device"] in (p.get("by_id"), p["device"]) for p in ports):
            port_options.append(f'<option value="{esc(cfg["device"])}" selected>{esc(cfg["device"])} — (non detecte actuellement)</option>')

        bright = ['<option value="-1"%s>Par defaut (reglage de la carte)</option>' % (" selected" if int(cfg.get("brightness", -1)) < 0 else "")]
        for i in range(16):
            bright.append('<option value="%d"%s>%d</option>' % (i, " selected" if int(cfg.get("brightness", -1)) == i else "", i))

        def yesno(v):
            return "oui" if v else "non"

        vpx_line = (
            f"plugin DMDUtil actif : <b>{yesno(vpx.get('enable'))}</b> · ZeDMD : <b>{yesno(vpx.get('zedmd'))}</b> · "
            f"Wi-Fi : <b>{yesno(vpx.get('wifi'))}</b> · port : <code>{esc(vpx.get('device') or 'auto')}</code> · "
            f"adresse : <code>{esc(vpx.get('wifi_addr') or '-')}</code> · luminosite : <code>{esc(vpx.get('brightness') or 'defaut')}</code>"
            if vpx else "VPinballX.ini introuvable"
        )
        fe_line = (
            f"libdmdutil actif : <b>{yesno(fe.get('enabled'))}</b> · port : <code>{esc(fe.get('device') or 'auto')}</code> · "
            f"adresse : <code>{esc(fe.get('wifi_addr') or '-')}</code>"
            if fe else "vpinfe.ini introuvable"
        )
        warnings = "".join(f'<p class="warn">⚠️ {esc(w)}</p>' for w in st.get("warnings", []) if w)
        p2 = st.get("pin2dmd") or {}
        p2_devs = p2.get("devices") or []
        if p2_devs:
            p2_line = " · ".join(
                f"<b>{esc(d.get('product') or 'PIN2DMD')}</b> (<code>{esc(d.get('node') or '?')}</code>, "
                f"acces pinball : {'✅ ok' if d.get('writable') else '⛔ refuse'})"
                for d in p2_devs
            )
        else:
            p2_line = "aucun PIN2DMD branche (USB 0314:e457)"
        p2_line += f" · regle udev : {'✅ presente' if p2.get('udev_rule') else '⛔ absente'}"
        p2_line += f" · VPX : <b>{yesno(vpx.get('pin2dmd'))}</b>"
        rows = "".join(
            f"<tr><td style='padding:4px 8px'><code>{esc(p['device'])}</code></td>"
            f"<td style='padding:4px 8px'>{'✅ candidat' if p.get('candidate') else '⛔'}</td>"
            f"<td style='padding:4px 8px'>{esc(p.get('label',''))}</td>"
            f"<td style='padding:4px 8px'>{esc(p.get('model',''))} {esc(p.get('vendor_id',''))}:{esc(p.get('product_id',''))}</td>"
            f"<td style='padding:4px 8px'><code>{esc(p.get('by_id') or '')}</code></td></tr>"
            for p in ports
        ) or "<tr><td colspan='5' style='padding:6px 8px;opacity:.8'>Aucun port serie USB detecte.</td></tr>"

        body = f"""
{notice}
<div class="grid" style="display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:20px;align-items:start;">
  <div class="card">
    <h2>DMD LED reel — configuration</h2>
    <p class="pco-mini">ZeDMD (USB ou Wi-Fi) ou PIN2DMD (USB). Le FullDMD a l'ecran reste actif independamment.</p>
    <form method="post" action="/dmd/zedmd/apply">
      <p><b>Mode</b><br>
        <label><input type="radio" name="mode" value="off"{checked('mode','off')}> Desactive</label> &nbsp;
        <label><input type="radio" name="mode" value="usb"{checked('mode','usb')}> ZeDMD USB</label> &nbsp;
        <label><input type="radio" name="mode" value="wifi"{checked('mode','wifi')}> ZeDMD Wi-Fi</label> &nbsp;
        <label><input type="radio" name="mode" value="pin2dmd"{checked('mode','pin2dmd')}> PIN2DMD (USB)</label>
      </p>
      <p><b>Port USB</b><br>
        <select name="device" style="width:100%;padding:6px;">{''.join(port_options)}</select><br>
        <span class="pco-mini"><b>Auto est recommande.</b> Un chemin <code>/dev/serial/by-id/…</code> peut etre force comme override stable. Les ports declares pour DOF (Teensy, DudesCab) sont exclus de la liste des candidats.</span>
      </p>
      <p><b>Adresse Wi-Fi du ZeDMD</b><br>
        <input name="wifi_addr" value="{esc(cfg.get('wifi_addr',''))}" placeholder="ex. 192.168.1.50 ou zedmd-wifi.local" style="width:100%;padding:6px;">
      </p>
      <p><b>Luminosite</b><br>
        <select name="brightness" style="padding:6px;">{''.join(bright)}</select>
      </p>
      <p><b>Ou l'utiliser</b><br>
        <label><input type="radio" name="targets" value="game"{' checked' if targets=='game' else ''}> En jeu seulement (VPX)</label><br>
        <label><input type="radio" name="targets" value="both"{' checked' if targets=='both' else ''}> Au menu VPinFE et en jeu</label><br>
        <span class="pco-mini">En USB, VPinFE/libdmdutil peut maintenant fonctionner en <b>auto-detection</b>. Au lancement d'une table, VPinFE libere le ZeDMD avant VPX puis le reprend au retour au menu. <b>PIN2DMD reste en jeu seulement.</b></span>
      </p>
      <p>
        <button class="button" type="submit">Enregistrer et appliquer</button>
        <a class="button secondary" href="/dmd/zedmd">Rafraichir la detection</a>
      </p>
    </form>
    <form method="post" action="/dmd/zedmd/test" style="margin-top:8px;">
      <button class="button secondary" type="submit"{'' if st.get('test_available') else ' disabled'}>Tester : afficher une mire 4 s sur le ZeDMD</button>
      <span class="pco-mini"> (ZeDMD seulement. Le test utilise le meme bridge libdmdutil et le meme mode Auto/port force que la configuration.)</span>
    </form>
  </div>

  <div>
    <div class="card">
      <h2>Etat actuel</h2>
      {warnings}
      <p><b>VPX</b> (<code>{esc(vpx.get('ini',''))}</code>)<br>{vpx_line}</p>
      <p><b>VPinFE</b> (<code>{esc(fe.get('ini',''))}</code>)<br>{fe_line}</p>
      <p><b>PIN2DMD</b><br>{p2_line}</p>
      <p class="pco-mini">Source de verite : <code>/opt/pincabos/config/zedmd.json</code>. Les sections <code>[Plugin.DMDUtil]</code> (VPX) et <code>[libdmdutil]</code> (VPinFE) sont regenerees a chaque application ; VPX relit son INI a chaque table, VPinFE est redemarre si sa configuration change.</p>
    </div>
    <div class="card">
      <h2>Ports serie USB detectes</h2>
      <table style="width:100%;border-collapse:collapse;font-size:.92em;">
        <tr><th style="text-align:left;padding:4px 8px">Port</th><th style="text-align:left;padding:4px 8px">ZeDMD ?</th><th style="text-align:left;padding:4px 8px">Famille</th><th style="text-align:left;padding:4px 8px">Modele</th><th style="text-align:left;padding:4px 8px">Chemin stable</th></tr>
        {rows}
      </table>
      <p class="pco-mini">Un ZeDMD est un ESP32 : port natif Espressif (303a) ou pont serie CP210x / CH340. Ces identifiants servent de candidats ; libdmdutil effectue la connexion reelle.</p>
    </div>
    <div class="card">
      <h2>Rappels</h2>
      <p class="pco-mini">• ZeDMD USB : laisser le port sur <b>Auto</b> dans la majorite des cabinets.<br>
      • Si un port doit etre verrouille : utiliser de preference <code>/dev/serial/by-id/…</code>.<br>
      • PIN2DMD : pris en charge par VPX (en jeu) uniquement.<br>
      • Le FullDMD (ecran) reste actif independamment du ZeDMD.<br>
      • Retour : <a href="/fulldmd">FullDMD / DMD</a> · <a href="/tools">Outils</a></p>
    </div>
  </div>
</div>
"""
        return page("FullDMD / DMD — DMD LED reel (ZeDMD / PIN2DMD)", body)

    @app.route("/dmd/zedmd")
    def zedmd_page():
        return _page(_status(), _detect())

    @app.route("/dmd/zedmd/apply", methods=["POST"])
    def zedmd_apply():
        mode = (request.form.get("mode") or "off").strip().lower()
        if mode not in ("off", "usb", "wifi", "pin2dmd"):
            mode = "off"
        try:
            brightness = int(request.form.get("brightness") or -1)
        except ValueError:
            brightness = -1
        targets = (request.form.get("targets") or "").strip().lower()
        if targets not in ("game", "both"):
            targets = "game" if mode == "pin2dmd" else "both"
        cfg = {
            "mode": mode,
            "device": (request.form.get("device") or "").strip(),
            "wifi_addr": (request.form.get("wifi_addr") or "").strip(),
            "brightness": brightness,
            "targets": targets,
        }
        try:
            _save_config(cfg)
        except OSError as exc:
            return _page(_status(), _detect(), f'<div class="card"><p class="warn">Impossible d\'enregistrer la configuration : {esc(str(exc))}</p></div>')
        rc, out = _run("apply", privileged=False)
        restarted = ""
        if rc == 0 and "RESTART_VPINFE=1" in out:
            ok, msg = _restart_vpinfe()
            restarted = "<br>VPinFE redemarre." if ok else f"<br><span class='warn'>Redemarrage VPinFE impossible : {esc(msg)}</span>"
        css = "" if rc == 0 else "warn"
        notice = (
            f'<div class="card"><h2>{"Configuration appliquee" if rc == 0 else "Application refusee"}</h2>'
            f'<pre class="{css}" style="white-space:pre-wrap;">{esc(out.strip())}</pre>{restarted}</div>'
        )
        return _page(_status(), _detect(), notice)

    @app.route("/dmd/zedmd/test", methods=["POST"])
    def zedmd_test():
        rc, out = _run("test", "4", timeout=40)
        css = "" if rc == 0 else "warn"
        notice = (
            f'<div class="card"><h2>{"Test reussi" if rc == 0 else "Test echoue"}</h2>'
            f'<pre class="{css}" style="white-space:pre-wrap;">{esc(out.strip())}</pre></div>'
        )
        return _page(_status(), _detect(), notice)

    @app.route("/api/zedmd/status")
    def zedmd_api_status():
        from flask import jsonify
        return jsonify(_status())
