#!/usr/bin/env python3
# PinCabOs-File
"""PinCabOS — Matériel DOF & cabinet.xml (/dof/hardware). V2 : inventaire.

Inventaire matériel DOF persistant avec activation/désactivation par
équipement : le cabinet.xml est généré depuis la COMBINAISON de tout le
matériel actif (plusieurs Teensy, Wemos réseau, ArtNet, PinOne...).

Réalité du schéma libdof (ce que cabinet.xml déclare vraiment) :
  - contrôleurs de strips adressables (TeensyStripController,
    WemosD1MPStripController), ArtNet, PinOne -> À DÉCLARER, un bloc par
    unité active, chacun avec son toy LedStrip + LedWizEquivalent ;
  - DudesCab, LedWiz, Pinscape (KL25Z/Pico), PacLed/PacDrive -> AutoConfig :
    rien à déclarer, DOF les trouve tout seul. Leurs EXTENSIONS (MOSLight,
    barres MX, splits sur la Dude's Cab) se configurent dans le firmware de
    la carte (page DudesCabConfig) + le DOF Config Tool, PAS dans
    cabinet.xml — la page l'affiche pour que l'inventaire soit complet.

Premier lancement : l'inventaire est amorcé automatiquement depuis le
cabinet.xml existant (continuité des cabs déjà configurés).

La détection/génération vit dans /opt/pincabos/tools/dof-cabinet/ (partagée
avec la CLI) ; cette page n'est qu'une façade web.
"""

import glob
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from flask import request, redirect, jsonify

MARKER = "PINCABOS_DOF_HARDWARE_PAGE_V2"

TOOL_PATH = Path(os.environ.get(
    "PINCABOS_DOF_CABINET_TOOL",
    "/opt/pincabos/tools/dof-cabinet/dof-cabinet.py"
))
STATE_DIR = Path("/opt/pincabos/config/dof/cabinet-wizard")
INVENTORY_FILE = Path("/opt/pincabos/config/dof/hardware-inventory.json")
BACKUP_DIR = Path("/opt/pincabos/backups/dof-cabinet")
GENERATED_XML = STATE_DIR / "cabinet-generated.xml"
GENERATED_CFG = STATE_DIR / "config.json"

DECLARED_TYPES = {
    "TeensyStripController": "Teensy — strips adressables (USB série)",
    "WemosD1MPStripController": "Wemos D1 — strips adressables (USB série, protocole Teensy + compression)",
    "ArtNet": "ArtNet / DMX (réseau)",
    "PinOne": "PinOne (USB série)",
}

_tool = None


def _load_tool():
    global _tool
    if _tool is not None:
        return _tool
    if not TOOL_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("pincabos_dofcab_tool", str(TOOL_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _tool = mod
    return mod


def _cfgdir():
    dirs = sorted(glob.glob("/home/pinball/.local/share/VPinballX/*/directoutputconfig"))
    return Path(dirs[-1]) if dirs else None


def _cabinet_path():
    d = _cfgdir()
    return (d / "cabinet.xml") if d else None


def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return "erreur: %s" % e


def _detect():
    tool = _load_tool()
    if tool is None:
        return []
    try:
        return tool.detect()
    except Exception:
        return []


# ------------------------------ inventaire ------------------------------

def _default_toy(name="Backboard"):
    return {"name": name, "width": 144, "height": 16,
            "arrangement": "TopDownAlternateLeftRight", "color_order": "GRB",
            "first_led": 1, "brightness": 25, "fading_curve": "Linear"}


def _new_device(dtype, label, serial=""):
    d = {"id": "%s-%s" % (dtype.lower(), serial or datetime.now().strftime("%H%M%S%f")),
         "source": "manual", "type": dtype, "label": label, "enabled": True,
         "serial": serial}
    if dtype in ("TeensyStripController", "WemosD1MPStripController"):
        d.update({"com_port": "auto",
                  "leds_per_strip": [512, 512, 512, 512, 256, 0, 0, 0, 0, 0],
                  "toy": _default_toy(), "ledwiz_number": 30, "ledwiz_outputs": 9})
    elif dtype == "ArtNet":
        d.update({"broadcast_address": "", "universe": 0})
    elif dtype == "PinOne":
        d.update({"com_port": ""})
    return d


def _seed_from_cabinet():
    """Amorce l'inventaire depuis le cabinet.xml existant (continuité)."""
    import xml.etree.ElementTree as ET
    inv = {"cab_name": "PinCabOS Cabinet", "auto_config": True, "devices": []}
    cab = _cabinet_path()
    if cab is None or not cab.exists():
        return inv
    try:
        root = ET.parse(str(cab)).getroot()
    except Exception:
        return inv
    inv["cab_name"] = (root.findtext("Name") or "PinCabOS Cabinet").strip()
    ac = (root.findtext("AutoConfigEnabled") or "true").strip().lower()
    inv["auto_config"] = ac != "false"

    toys = root.find("Toys")
    ledstrips, ledwiz_eq = [], []
    if toys is not None:
        for t in toys:
            if t.tag == "LedStrip":
                ledstrips.append(t)
            elif t.tag == "LedWizEquivalent":
                ledwiz_eq.append(t)

    def toy_for(controller_name):
        for t in ledstrips:
            if (t.findtext("OutputControllerName") or "").strip() == controller_name:
                return t
        return None

    def ledwiz_for(toy_name):
        for lw in ledwiz_eq:
            outs = lw.find("Outputs")
            if outs is None:
                continue
            for o in outs:
                if (o.findtext("OutputName") or "").strip() == toy_name:
                    return int((lw.findtext("LedWizNumber") or "30").strip() or 30), len(list(outs))
        return 30, 9

    detected = _detect()
    teensy_serials = [d["serial"] for d in detected
                      if d.get("auto_config") is False and "Teensy" in d.get("kind", "")]

    oc = root.find("OutputControllers")
    idx = 0
    if oc is not None:
        for c in oc:
            if c.tag not in DECLARED_TYPES:
                continue
            name = (c.findtext("Name") or c.tag).strip()
            serial = teensy_serials[idx] if (c.tag == "TeensyStripController" and idx < len(teensy_serials)) else ""
            dev = _new_device(c.tag, name, serial)
            dev["source"] = "detected" if serial else "manual"
            if c.tag in ("TeensyStripController", "WemosD1MPStripController"):
                leds = []
                for i in range(1, 11):
                    try:
                        leds.append(int((c.findtext("NumberOfLedsStrip%d" % i) or "0").strip() or 0))
                    except ValueError:
                        leds.append(0)
                dev["leds_per_strip"] = leds
                dev["com_port"] = "auto"  # robuste : le port réel change au boot
                t = toy_for(name)
                if t is not None:
                    toy_name = (t.findtext("Name") or "Backboard").strip()
                    dev["toy"] = {
                        "name": toy_name,
                        "width": int((t.findtext("Width") or "144").strip() or 144),
                        "height": int((t.findtext("Height") or "16").strip() or 16),
                        "arrangement": (t.findtext("LedStripArrangement") or "TopDownAlternateLeftRight").strip(),
                        "color_order": (t.findtext("ColorOrder") or "GRB").strip(),
                        "first_led": int((t.findtext("FirstLedNumber") or "1").strip() or 1),
                        "brightness": int((t.findtext("Brightness") or "25").strip() or 25),
                        "fading_curve": (t.findtext("FadingCurveName") or "Linear").strip(),
                    }
                    dev["ledwiz_number"], dev["ledwiz_outputs"] = ledwiz_for(toy_name)
            elif c.tag == "ArtNet":
                dev["broadcast_address"] = (c.findtext("BroadCastAddress") or "").strip()
                try:
                    dev["universe"] = int((c.findtext("Universe") or "0").strip() or 0)
                except ValueError:
                    dev["universe"] = 0
            elif c.tag == "PinOne":
                dev["com_port"] = (c.findtext("ComPortName") or "").strip()
            inv["devices"].append(dev)
            if c.tag == "TeensyStripController":
                idx += 1
    return inv


def _load_inventory():
    if INVENTORY_FILE.exists():
        try:
            data = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("devices"), list):
                return data
        except Exception:
            pass
    inv = _seed_from_cabinet()
    _save_inventory(inv)
    return inv


def _save_inventory(inv):
    INVENTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    inv["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = INVENTORY_FILE.with_name(INVENTORY_FILE.name + ".tmp")
    tmp.write_text(json.dumps(inv, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, INVENTORY_FILE)


def _build_config(inv):
    """Config déclarative dof-cabinet depuis les équipements ACTIFS."""
    cfg = {"name": inv.get("cab_name") or "PinCabOS Cabinet",
           "auto_config": bool(inv.get("auto_config", True)),
           "strips": [], "artnet": [], "pinone": []}
    for d in inv.get("devices", []):
        if not d.get("enabled"):
            continue
        t = d.get("type")
        if t in ("TeensyStripController", "WemosD1MPStripController"):
            strip = {
                "controller": t,
                "name": d.get("label") or "%s 1" % t,
                "com_port": d.get("com_port") or "auto",
                "serial": d.get("serial") or "",
                "baud": 9600,
                "leds_per_strip": (d.get("leds_per_strip") or [0] * 10),
                "test_on_connect": False,
                "toy": d.get("toy") or _default_toy(),
                "ledwiz_number": int(d.get("ledwiz_number") or 30),
                "ledwiz_outputs": int(d.get("ledwiz_outputs") or 9),
            }
            if d.get("toys"):   # PINCABOS_DOF_TOYS_MULTIPLES_V1 : mode « rubans » de l'installeur
                strip["toys"] = d["toys"]
            cfg["strips"].append(strip)
        elif t == "ArtNet":
            a = {"name": d.get("label") or "ArtNet 1"}
            if d.get("broadcast_address"):
                a["broadcast_address"] = d["broadcast_address"]
            a["universe"] = int(d.get("universe") or 0)
            cfg["artnet"].append(a)
        elif t == "PinOne":
            p = {"name": d.get("label") or "PinOne 1"}
            if d.get("com_port"):
                p["com_port"] = d["com_port"]
            cfg["pinone"].append(p)
    return cfg


# ------------------------------ rendu ------------------------------

def register(app, page, esc):
    """Enregistre les routes /dof/hardware sur l'app Flask PinCabOS."""

    def presence_badge(dev, detected):
        t = dev.get("type")
        if t in ("TeensyStripController", "WemosD1MPStripController"):
            for x in detected:
                if dev.get("serial") and x.get("serial") == dev["serial"]:
                    return '<span class="ok">branché (%s)</span>' % esc(x["dev"])
            if t == "TeensyStripController":
                for x in detected:
                    if x.get("auto_config") is False and "Teensy" in x.get("kind", ""):
                        return '<span class="warn">un Teensy est branché (série différente)</span>'
                return '<span class="bad">non branché</span>'
            return '<span class="warn">USB série — renseigner le n° de série pour suivre la présence</span>'
        if t == "PinOne":
            return '<span class="warn">USB série — vérifier le port</span>'
        return '<span class="ok">réseau — non détectable USB</span>'

    def device_edit_form(dev):
        t = dev.get("type")
        did = esc(dev["id"])
        common = """
        <table>
          <tr><td>Nom (bloc cabinet.xml)</td>
              <td><input type="text" name="label" value="%s"></td></tr>""" % esc(dev.get("label", ""))
        if t in ("TeensyStripController", "WemosD1MPStripController"):
            tool = _load_tool()
            arrangements = getattr(tool, "ADDRESSABLE_ARRANGEMENTS", []) if tool else []
            color_orders = getattr(tool, "COLOR_ORDERS", ["RGB", "GRB"]) if tool else ["RGB", "GRB"]
            toy = dev.get("toy") or _default_toy()
            arr_opts = "".join('<option value="%s"%s>%s</option>' % (
                a, " selected" if a == toy.get("arrangement") else "", a) for a in arrangements)
            co_opts = "".join('<option value="%s"%s>%s</option>' % (
                c, " selected" if c == toy.get("color_order") else "", c) for c in color_orders)
            leds = (dev.get("leds_per_strip") or [0] * 10)
            led_inputs = "".join(
                '<label style="display:inline-block;margin:4px 8px 4px 0;">S%d '
                '<input type="number" name="leds_%d" value="%s" min="0" max="1100" style="width:75px;"></label>'
                % (i + 1, i + 1, leds[i] if i < len(leds) else 0) for i in range(10))
            extra = """
          <tr><td>Port série</td>
              <td><input type="text" name="com_port" value="%s">
                  <small>« auto » = résolution par n° de série au démarrage (recommandé)</small></td></tr>
          <tr><td>N° de série USB</td>
              <td><input type="text" name="serial" value="%s">
                  <small>sert à distinguer plusieurs cartes (résolution du port au boot)</small></td></tr>
          <tr><td>LEDs par sortie (S1-S10)</td><td>%s</td></tr>
          <tr><td>Toy — nom</td><td><input type="text" name="toy_name" value="%s"></td></tr>
          <tr><td>Toy — largeur × hauteur</td>
              <td><input type="number" name="toy_width" value="%s" min="1" max="1024" style="width:80px;"> ×
                  <input type="number" name="toy_height" value="%s" min="1" max="1024" style="width:80px;"></td></tr>
          <tr><td>Arrangement</td><td><select name="arrangement">%s</select></td></tr>
          <tr><td>Ordre couleurs</td><td><select name="color_order">%s</select></td></tr>
          <tr><td>Luminosité (1-100)</td>
              <td><input type="number" name="brightness" value="%s" min="1" max="100" style="width:80px;">
                  <span class="warn">garder BAS (courant de l'alim)</span></td></tr>
          <tr><td>N° LedWiz équiv. / sorties</td>
              <td><input type="number" name="ledwiz_number" value="%s" min="1" max="128" style="width:80px;"> /
                  <input type="number" name="ledwiz_outputs" value="%s" min="1" max="64" style="width:80px;">
                  <small>doit matcher le device du DOF Config Tool</small></td></tr>""" % (
                esc(dev.get("com_port", "auto")), esc(dev.get("serial", "")),
                led_inputs,
                esc(toy.get("name", "")), toy.get("width", 144), toy.get("height", 16),
                arr_opts, co_opts, toy.get("brightness", 25),
                dev.get("ledwiz_number", 30), dev.get("ledwiz_outputs", 9))
        elif t == "ArtNet":
            extra = """
          <tr><td>Adresse broadcast</td>
              <td><input type="text" name="broadcast_address" value="%s"></td></tr>
          <tr><td>Universe</td>
              <td><input type="number" name="universe" value="%s" min="0" max="255" style="width:80px;"></td></tr>""" % (
                esc(dev.get("broadcast_address", "")), dev.get("universe", 0))
        else:  # PinOne
            extra = """
          <tr><td>Port série</td>
              <td><input type="text" name="com_port" value="%s"></td></tr>""" % esc(dev.get("com_port", ""))
        return """
      <details style="margin-top:6px;">
        <summary>Réglages</summary>
        <form method="post" action="/dof/hardware/device/save">
          <input type="hidden" name="id" value="%s">
          %s%s
          </table>
          <p><button class="button secondary" type="submit">Enregistrer</button></p>
        </form>
      </details>""" % (did, common, extra)

    def inventory_card(inv, detected):
        rows = []
        for dev in inv.get("devices", []):
            did = esc(dev["id"])
            enabled = bool(dev.get("enabled"))
            toggle_label = "Désactiver" if enabled else "Activer"
            state = ('<span class="ok">● actif — sera dans cabinet.xml</span>' if enabled
                     else '<span class="warn">● désactivé — ignoré à la génération</span>')
            rows.append("""
        <tr>
          <td>
            <strong>%s</strong><br><small>%s</small>
            %s
          </td>
          <td>%s</td>
          <td>%s</td>
          <td style="white-space:nowrap;">
            <form method="post" action="/dof/hardware/device/toggle" style="display:inline;">
              <input type="hidden" name="id" value="%s">
              <button class="button secondary" type="submit">%s</button>
            </form>
            <form method="post" action="/dof/hardware/device/delete" style="display:inline;"
                  onsubmit="return confirm('Retirer cet équipement de l\\'inventaire ?');">
              <input type="hidden" name="id" value="%s">
              <button class="button secondary" type="submit">Retirer</button>
            </form>
          </td>
        </tr>""" % (esc(dev.get("label", dev["id"])),
                    esc(DECLARED_TYPES.get(dev.get("type"), dev.get("type", "?"))),
                    device_edit_form(dev), state, presence_badge(dev, detected),
                    did, toggle_label, did))
        if not rows:
            rows.append('<tr><td colspan="4"><span class="warn">Aucun équipement déclaré. '
                        'Un cab sans strip adressable n\'en a pas besoin : AutoConfig suffit.</span></td></tr>')

        # matériel AutoConfig détecté (info, pas de toggle : DOF le gère seul)
        auto_rows = []
        for x in detected:
            if x.get("auto_config") is not True:
                continue
            note = ""
            if "DudesCab" in x.get("kind", ""):
                note = ('<br><small>Extensions (MOSLight, barres MX, splits) : à configurer dans '
                        '<a href="/DudesCabConfig">DudesCabConfig</a> + le DOF Config Tool — '
                        'rien à déclarer dans cabinet.xml.</small>')
            auto_rows.append(
                "<tr><td><strong>%s</strong><br><small>%s · série %s</small>%s</td>"
                "<td><span class=\"ok\">AutoConfig — pris en charge automatiquement par DOF</span></td>"
                "<td><span class=\"ok\">branché</span></td><td>—</td></tr>" % (
                    esc(x.get("kind", "?")), esc(x.get("dev", "")), esc(x.get("serial") or "-"), note))
        if not auto_rows:
            auto_rows.append('<tr><td colspan="4"><small>aucun contrôleur AutoConfig détecté</small></td></tr>')

        # détectés « à déclarer » absents de l'inventaire → proposition d'ajout
        known_serials = {d.get("serial") for d in inv.get("devices", []) if d.get("serial")}
        propose = []
        for x in detected:
            if x.get("auto_config") is not False or not x.get("serial") or x["serial"] in known_serials:
                continue
            kind = x.get("kind", "")
            if "Teensy" in kind:
                dtype, human = "TeensyStripController", "le Teensy"
            elif "Wemos" in kind or "ESP" in kind:
                dtype, human = "WemosD1MPStripController", "la Wemos/ESP"
            else:
                continue  # FTDI bitbang etc. : pas un controleur de strips
            propose.append("""
        <form method="post" action="/dof/hardware/device/add" style="display:inline;">
          <input type="hidden" name="dtype" value="%s">
          <input type="hidden" name="serial" value="%s">
          <input type="hidden" name="label" value="%s %d">
          <button class="button" type="submit">Ajouter %s détecté(e) (série %s)</button>
        </form>""" % (esc(dtype), esc(x["serial"]), esc(dtype),
                      len(inv.get("devices", [])) + 1, esc(human), esc(x["serial"])))
        propose_html = ('<p class="warn">Matériel détecté non déclaré : %s</p>' % "".join(propose)) if propose else ""

        type_opts = "".join('<option value="%s">%s</option>' % (esc(k), esc(v))
                            for k, v in DECLARED_TYPES.items())
        return """
<div class="card" style="margin-top:20px;">
  <h2>Inventaire matériel DOF</h2>
  <p>
    Active/désactive chaque équipement : le cabinet.xml est généré depuis la
    <strong>combinaison de tout ce qui est actif</strong>. Un équipement débranché
    temporairement peut rester déclaré mais désactivé.
  </p>
  %s
  <h3>Équipements déclarés (dans cabinet.xml)</h3>
  <table>
    <tr><th style="text-align:left;">Équipement</th><th style="text-align:left;">État</th>
        <th style="text-align:left;">Présence</th><th style="text-align:left;">Actions</th></tr>
    %s
  </table>

  <h3 style="margin-top:14px;">Matériel AutoConfig (géré tout seul par DOF)</h3>
  <table>
    <tr><th style="text-align:left;">Carte</th><th style="text-align:left;">État</th>
        <th style="text-align:left;">Présence</th><th style="text-align:left;">Actions</th></tr>
    %s
  </table>

  <details style="margin-top:14px;">
    <summary>Ajouter un équipement manuellement (2ᵉ Teensy, Wemos D1, ArtNet, PinOne...)</summary>
    <form method="post" action="/dof/hardware/device/add" style="margin-top:8px;">
      <table>
        <tr><td>Type</td><td><select name="dtype">%s</select></td></tr>
        <tr><td>Nom</td><td><input type="text" name="label" value=""></td></tr>
        <tr><td>N° de série USB (si connu)</td><td><input type="text" name="serial" value=""></td></tr>
      </table>
      <p><button class="button secondary" type="submit">Ajouter à l'inventaire</button></p>
    </form>
  </details>
</div>""" % (propose_html, "".join(rows), "".join(auto_rows), type_opts)

    def globals_card(inv):
        ac_checked = "checked" if inv.get("auto_config", True) else ""
        return """
<div class="card" style="margin-top:20px;">
  <h2>Réglages globaux</h2>
  <form method="post" action="/dof/hardware/settings">
    <table>
      <tr><td>Nom du cabinet</td>
          <td><input type="text" name="cab_name" value="%s"></td></tr>
      <tr><td>AutoConfig</td>
          <td><label><input type="checkbox" name="auto_config" value="1" %s>
              laisser DOF détecter tout seul DudesCab, LedWiz, Pinscape, PacLed
              (recommandé — à désactiver uniquement si tu sais pourquoi)</label></td></tr>
    </table>
    <p><button class="button secondary" type="submit">Enregistrer</button></p>
  </form>
</div>""" % (esc(inv.get("cab_name", "PinCabOS Cabinet")), ac_checked)

    def current_cabinet_card():
        cab = _cabinet_path()
        if cab is None or not cab.exists():
            return """
<div class="card" style="margin-top:20px;">
  <h2>cabinet.xml actuel</h2>
  <p class="warn">Aucun cabinet.xml. La génération ci-dessous en créera un.</p>
</div>"""
        raw = ""
        try:
            raw = cab.read_text(errors="replace")
        except Exception:
            pass
        backups = sorted(BACKUP_DIR.glob("cabinet.xml.bak-*"), reverse=True)
        restore_html = ""
        if backups:
            restore_html = """
  <form method="post" action="/dof/hardware/restore" style="margin-top:10px;"
        onsubmit="return confirm('Restaurer la dernière sauvegarde du cabinet.xml ?');">
    <button class="button secondary" type="submit">Restaurer la dernière sauvegarde (%s)</button>
  </form>""" % esc(backups[0].name)
        return """
<div class="card" style="margin-top:20px;">
  <h2>cabinet.xml actuel</h2>
  <p><code>%s</code></p>
  <details><summary>Contenu</summary><pre style="max-height:400px;overflow:auto;">%s</pre></details>
  %s
</div>""" % (esc(str(cab)), esc(raw), restore_html)

    def generate_card(inv):
        active = [d for d in inv.get("devices", []) if d.get("enabled")]
        summary = ", ".join(esc(d.get("label", "?")) for d in active) or "aucun équipement déclaré (AutoConfig seul)"
        return """
<div class="card" style="margin-top:20px;">
  <h2>Générer le cabinet.xml</h2>
  <p>Sera généré depuis le matériel actif : <strong>%s</strong>%s.</p>
  <form method="post" action="/dof/hardware/generate">
    <details style="margin-bottom:10px;">
      <summary>Mode avancé : config JSON brute (remplace l'inventaire si rempli)</summary>
      <textarea name="raw_json" rows="8" style="width:100%%;font-family:monospace;"></textarea>
    </details>
    <button class="button" type="submit">Générer l'aperçu</button>
  </form>
  <p><small>Aperçu d'abord, rien n'est appliqué sans confirmation. Sauvegarde
  automatique de l'ancien fichier à l'application.</small></p>
</div>""" % (summary, " + AutoConfig" if inv.get("auto_config", True) else " (AutoConfig désactivé !)")

    @app.route("/dof/hardware")
    def dof_hardware_page():
        tool = _load_tool()
        if tool is None:
            return page("Matériel DOF", '<div class="card"><p class="bad">Outil dof-cabinet absent (%s).</p></div>'
                        % esc(str(TOOL_PATH)))
        inv = _load_inventory()
        detected = _detect()
        raw_usb = _run(["lsusb"])
        body = """
<div class="card">
  <h2>Matériel DOF &amp; cabinet.xml</h2>
  <p>
    Inventaire du matériel DOF du cab avec activation par équipement, et
    génération du <code>cabinet.xml</code> depuis la combinaison active.
    Chaque cab est différent : Dude's Cab (+ MOSLight), Teensy, Wemos, KL25Z,
    LedWiz... tout est optionnel.
  </p>
  <p>
    <a class="button secondary" href="/dof">Retour DOF</a>
    <a class="button secondary" href="/dof/commander">DOF Commander</a>
    <a class="button secondary" href="/dof/hardware">Rafraîchir la détection</a>
  </p>
  <details><summary>lsusb brut</summary><pre>%s</pre></details>
</div>
%s
%s
%s
%s
""" % (esc(raw_usb), inventory_card(inv, detected), globals_card(inv),
       generate_card(inv), current_cabinet_card())
        return page("Matériel DOF", body)

    @app.route("/dof/hardware/detect.json")
    def dof_hardware_detect_json():
        tool = _load_tool()
        if tool is None:
            return jsonify({"ok": False, "error": "outil dof-cabinet absent"}), 500
        try:
            inv = _load_inventory()
            return jsonify({"ok": True, "devices": tool.detect(),
                            "inventory": inv})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/dof/hardware/settings", methods=["POST"])
    def dof_hardware_settings():
        inv = _load_inventory()
        inv["cab_name"] = (request.form.get("cab_name") or "PinCabOS Cabinet").strip()
        inv["auto_config"] = request.form.get("auto_config") == "1"
        _save_inventory(inv)
        return redirect("/dof/hardware")

    @app.route("/dof/hardware/device/add", methods=["POST"])
    def dof_hardware_device_add():
        dtype = request.form.get("dtype") or "TeensyStripController"
        if dtype not in DECLARED_TYPES:
            return redirect("/dof/hardware")
        inv = _load_inventory()
        label = (request.form.get("label") or "").strip() or "%s %d" % (
            dtype, sum(1 for d in inv["devices"] if d.get("type") == dtype) + 1)
        dev = _new_device(dtype, label, (request.form.get("serial") or "").strip())
        if request.form.get("serial"):
            dev["source"] = "detected"
        if dtype in ("TeensyStripController", "WemosD1MPStripController"):
            # n° LedWiz distinct par équipement (collision = deux strips sur le
            # même fichier directoutputconfigNN.ini du config tool)
            used = [int(x.get("ledwiz_number") or 0) for x in inv["devices"]
                    if x.get("type") in ("TeensyStripController", "WemosD1MPStripController")]
            dev["ledwiz_number"] = max(used + [29]) + 1
        inv["devices"].append(dev)
        _save_inventory(inv)
        return redirect("/dof/hardware")

    def _find_device(inv, did):
        for d in inv.get("devices", []):
            if d.get("id") == did:
                return d
        return None

    @app.route("/dof/hardware/device/toggle", methods=["POST"])
    def dof_hardware_device_toggle():
        inv = _load_inventory()
        d = _find_device(inv, request.form.get("id"))
        if d is not None:
            d["enabled"] = not bool(d.get("enabled"))
            _save_inventory(inv)
        return redirect("/dof/hardware")

    @app.route("/dof/hardware/device/delete", methods=["POST"])
    def dof_hardware_device_delete():
        inv = _load_inventory()
        did = request.form.get("id")
        n = len(inv.get("devices", []))
        inv["devices"] = [d for d in inv.get("devices", []) if d.get("id") != did]
        if len(inv["devices"]) != n:
            _save_inventory(inv)
        return redirect("/dof/hardware")

    @app.route("/dof/hardware/device/save", methods=["POST"])
    def dof_hardware_device_save():
        inv = _load_inventory()
        d = _find_device(inv, request.form.get("id"))
        if d is None:
            return redirect("/dof/hardware")
        f = request.form

        def _int(name, default, lo=None, hi=None):
            try:
                v = int(f.get(name, default) or default)
            except (TypeError, ValueError):
                v = default
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return v

        d["label"] = (f.get("label") or d.get("label") or "").strip()
        if d.get("type") in ("TeensyStripController", "WemosD1MPStripController"):
            d["com_port"] = (f.get("com_port") or "auto").strip() or "auto"
            d["serial"] = (f.get("serial") or "").strip()
            d["leds_per_strip"] = [_int("leds_%d" % i, 0, 0, 1100) for i in range(1, 11)]
            d["toy"] = {
                "name": (f.get("toy_name") or "Backboard").strip(),
                "width": _int("toy_width", 144, 1, 1024),
                "height": _int("toy_height", 16, 1, 1024),
                "arrangement": f.get("arrangement") or "TopDownAlternateLeftRight",
                "color_order": f.get("color_order") or "GRB",
                "first_led": 1,
                "brightness": _int("brightness", 25, 1, 100),
                "fading_curve": "Linear",
            }
            d["ledwiz_number"] = _int("ledwiz_number", 30, 1, 128)
            d["ledwiz_outputs"] = _int("ledwiz_outputs", 9, 1, 64)
        elif d.get("type") == "ArtNet":
            d["broadcast_address"] = (f.get("broadcast_address") or "").strip()
            d["universe"] = _int("universe", 0, 0, 255)
        elif d.get("type") == "PinOne":
            d["com_port"] = (f.get("com_port") or "").strip()
        _save_inventory(inv)
        return redirect("/dof/hardware")

    @app.route("/dof/hardware/generate", methods=["POST"])
    def dof_hardware_generate():
        tool = _load_tool()
        if tool is None:
            return page("Matériel DOF", '<div class="card"><p class="bad">Outil dof-cabinet absent.</p></div>')
        try:
            raw = (request.form.get("raw_json") or "").strip()
            cfg = json.loads(raw) if raw else _build_config(_load_inventory())
            xml = tool.gen(cfg)
        except Exception as e:
            return page("Matériel DOF", """
<div class="card"><h2>Erreur de génération</h2><p class="bad">%s</p>
<p><a class="button" href="/dof/hardware">Retour</a></p></div>""" % esc(str(e)))
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        GENERATED_CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        GENERATED_XML.write_text(xml, encoding="utf-8")
        cab = _cabinet_path()
        cur = ""
        if cab and cab.exists():
            try:
                cur = cab.read_text(errors="replace")
            except Exception:
                pass
        same = (cur.strip() == xml.strip()) if cur else False
        status = ('<p class="ok">Identique au cabinet.xml actuel — rien à appliquer.</p>' if same else
                  ('<p class="warn">Différent du cabinet.xml actuel. L\'appliquer le remplacera '
                   '(sauvegarde automatique).</p>' if cur else
                   '<p class="warn">Aucun cabinet.xml actuel : celui-ci sera installé.</p>'))
        body = """
<div class="card">
  <h2>Aperçu du cabinet.xml généré</h2>
  %s
  <pre style="max-height:480px;overflow:auto;background:#050007;border:1px solid #5f2a91;border-radius:12px;padding:12px;">%s</pre>
  <form method="post" action="/dof/hardware/apply"
        onsubmit="return confirm('Remplacer le cabinet.xml ? (sauvegarde automatique)');">
    <label style="display:block;margin:8px 0;">
      <input type="checkbox" name="restart_vpinfe" value="1" checked>
      Redémarrer VPinFE après application (nécessaire pour recharger DOF)
    </label>
    <button class="button" type="submit">Appliquer ce cabinet.xml</button>
    <a class="button secondary" href="/dof/hardware">Retour / modifier</a>
  </form>
</div>""" % (status, esc(xml))
        return page("Matériel DOF", body)

    @app.route("/dof/hardware/apply", methods=["POST"])
    def dof_hardware_apply():
        if not GENERATED_XML.exists():
            return page("Matériel DOF", '<div class="card"><p class="bad">Aucun aperçu généré.</p>'
                        '<p><a class="button" href="/dof/hardware">Retour</a></p></div>')
        d = _cfgdir()
        if d is None:
            return page("Matériel DOF", '<div class="card"><p class="bad">Dossier directoutputconfig '
                        'introuvable.</p><p><a class="button" href="/dof/hardware">Retour</a></p></div>')
        cab = d / "cabinet.xml"
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_note = "aucun fichier précédent"
        if cab.exists():
            backup = BACKUP_DIR / ("cabinet.xml.bak-" + stamp)
            shutil.copy2(cab, backup)
            backup_note = str(backup)
        shutil.copy2(GENERATED_XML, cab)
        try:
            shutil.chown(str(cab), user="pinball", group="pinball")
        except Exception:
            pass
        # PINCABOS_DOF_GLOBALCONFIG_V1 : GlobalConfig a cote, et le PrefPath de VPX servi aussi
        try:
            import sys as _sys
            if "/opt/pincabos/tools" not in _sys.path:
                _sys.path.insert(0, "/opt/pincabos/tools")
            import pincabos_dof as _pd
            global_note = " ; ".join(_pd.propager_cabinet(d))
        except Exception as e:   # la page ne doit pas tomber pour un dossier absent
            global_note = "GlobalConfig DOF non pose : %s" % e
        restart_log = ""
        if request.form.get("restart_vpinfe") == "1":
            restart_log = _run(["systemctl", "restart", "pincabos-vpinfe.service"], timeout=30)
        body = """
<div class="card">
  <h2>cabinet.xml appliqué</h2>
  <table>
    <tr><td>Fichier</td><td><code>%s</code></td></tr>
    <tr><td>Sauvegarde</td><td><code>%s</code></td></tr>
    <tr><td>GlobalConfig DOF</td><td><code>%s</code></td></tr>
    <tr><td>Redémarrage VPinFE</td><td><code>%s</code></td></tr>
  </table>
  <p><a class="button" href="/dof/hardware">Retour Matériel DOF</a>
     <a class="button secondary" href="/dof">Page DOF</a></p>
</div>""" % (esc(str(cab)), esc(backup_note), esc(global_note),
             esc(restart_log.strip() or ("demandé" if request.form.get("restart_vpinfe") == "1" else "non demandé")))
        return page("Matériel DOF", body)

    @app.route("/dof/hardware/restore", methods=["POST"])
    def dof_hardware_restore():
        backups = sorted(BACKUP_DIR.glob("cabinet.xml.bak-*"), reverse=True)
        cab = _cabinet_path()
        if not backups or cab is None:
            return page("Matériel DOF", '<div class="card"><p class="bad">Aucune sauvegarde à restaurer.</p>'
                        '<p><a class="button" href="/dof/hardware">Retour</a></p></div>')
        shutil.copy2(backups[0], cab)
        try:
            shutil.chown(str(cab), user="pinball", group="pinball")
        except Exception:
            pass
        return redirect("/dof/hardware")

    return True
