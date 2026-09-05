#!/usr/bin/env python3
"""PinCabOS GUI Installer — wizard Flask (charte WebApp).

Deux modes :
  PCO_DEMO=1  -> disques factices, installation simulee (demo navigateur / dev)
  reel        -> ecrit les reponses puis pilote le moteur d'install existant
                 (contrat "answers file" partage TUI/GUI).
"""
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

import screens as pco_screens  # PINCABOS_INSTALLEUR_ECRANS_V1
import dmd as pco_dmd  # PINCABOS_INSTALLEUR_DMD_V1
import disks as pco_disks  # PINCABOS_INSTALLEUR_DISQUE_V1

# PINCABOS_INSTALLEUR_RESEAU_V1 : le moteur réseau du cab (nmcli) sert aussi à
# l'assistant. Absent de la session (ISO au modèle classique) : l'étape se
# présente comme indisponible et laisse continuer.
import sys as _sys
for _d in ("/opt/pincabos/tools", str(Path(__file__).resolve().parent.parent / "tools")):
    if _d not in _sys.path:
        _sys.path.insert(0, _d)
try:
    import pincabos_network as pco_net
except Exception:  # pragma: no cover
    pco_net = None
# PINCABOS_INSTALLEUR_SON_DOF_V1 : son (ALSA en session live, PipeWire au
# premier démarrage) et DOF (cartes de sortie), modules du cab
try:
    import pincabos_audio as pco_audio
    import pincabos_dof as pco_dof
except Exception:  # pragma: no cover
    pco_audio = pco_dof = None

BASE = Path(__file__).resolve().parent
DEMO = os.environ.get("PCO_DEMO") == "1"
RUN_DIR = Path(os.environ.get("PCO_RUN_DIR", "/run/pincabos"))
ANSWERS = RUN_DIR / "gui-answers.env"
INSTALL_LOG = RUN_DIR / "install.log"
ENGINE = "/usr/local/sbin/pincabos-live-installer"

app = Flask(__name__)
I18N = json.loads((BASE / "i18n.json").read_text(encoding="utf-8"))

REGIONAL_DEFAULTS = {
    "fr": {"locale": "fr_FR.UTF-8", "xkb": "fr", "tz": "Europe/Paris"},
    "en": {"locale": "en_US.UTF-8", "xkb": "us", "tz": "America/New_York"},
    "de": {"locale": "de_DE.UTF-8", "xkb": "de", "tz": "Europe/Berlin"},
    "it": {"locale": "it_IT.UTF-8", "xkb": "it", "tz": "Europe/Rome"},
    "es": {"locale": "es_ES.UTF-8", "xkb": "es", "tz": "Europe/Madrid"},
}


@app.route("/")
def index():
    return render_template("wizard.html", i18n=json.dumps(I18N),
                           defaults=json.dumps(REGIONAL_DEFAULTS), demo=DEMO)


def disques_reels():
    """Disques que cette machine porte reellement.

    PINCABOS_WIZARD_LOCAL_ONLY_V1

    Sert a la fois a remplir la liste et a valider le choix : une expression
    reguliere accepte /dev/nvme0n1 sur une machine qui n'en a pas, une
    enumeration decrit la machine devant soi.
    """
    # PINCABOS_INSTALLEUR_DISQUE_V1 : chaque disque dit s il porte deja un PinCabOS
    if DEMO:
        return [
            {"dev": "/dev/nvme0n1", "size": "931,5G", "model": "Samsung 980 PRO 1TB", "pincabos": None},
            {"dev": "/dev/sda", "size": "223,6G", "model": "Crucial BX500 240GB", "pincabos": {"version": "Alpha 3.55", "partition": "/dev/sda2"}},
        ]
    return [{"dev": d["dev"], "size": d["size"], "model": d["model"], "pincabos": d.get("pincabos")} for d in pco_disks.detecter()]


@app.route("/api/disks")
def disks():
    return jsonify(disques_reels())


# PINCABOS_INSTALLEUR_ECRANS_V1
# L'étape Écrans : la session d'installation voit les mêmes dalles que le
# système installé. On les numérote, on attribue les rôles, on applique la
# disposition tout de suite (le propriétaire voit), et le résultat part sur la
# cible au format que lit tout PinCabOS (screens.json + liaisons EDID).
ECRANS_DEMO = [
    {"app_index": 0, "name": "HDMI-0", "x": 0, "y": 0, "width": 3840, "height": 2160, "area": 3840 * 2160, "is_primary": True,
     "raw": "HDMI-0 connected primary 3840x2160+0+0", "rotation": 0, "preferred": "3840x2160", "modes": ["3840x2160", "1920x1080"], "mm": (1600, 900), "edid_sha256": "demo-pf"},
    {"app_index": 1, "name": "DP-0", "x": 5760, "y": 0, "width": 1920, "height": 480, "area": 1920 * 480, "is_primary": False,
     "raw": "DP-0 connected 1920x480+5760+0", "rotation": 0, "preferred": "1920x480", "modes": ["1920x480"], "mm": (600, 150), "edid_sha256": "demo-dmd"},
    {"app_index": 2, "name": "DP-2", "x": 3840, "y": 0, "width": 1920, "height": 1080, "area": 1920 * 1080, "is_primary": False,
     "raw": "DP-2 connected 1920x1080+3840+0", "rotation": 0, "preferred": "1920x1080", "modes": ["1920x1080"], "mm": (600, 340), "edid_sha256": "demo-bg"},
]
KIOSK_TARGET = RUN_DIR / "kiosk-target"


def ecrans_detectes():
    if DEMO:
        return [dict(m) for m in ECRANS_DEMO]
    return pco_screens.decouvrir()


def _roles_depuis(a):
    roles = a.get("roles") if isinstance(a, dict) else None
    if not isinstance(roles, dict):
        return None
    return {r: str(roles.get(r) or "") for r in pco_screens.ROLES}


def _rotation_depuis(a):
    try:
        rot = int(a.get("rotation", 0))
    except (TypeError, ValueError):
        return None
    return rot if rot in pco_screens.ROTATIONS else None


@app.route("/api/screens")
def screens_list():
    try:
        mons = ecrans_detectes()
    except Exception as exc:
        return jsonify({"error": "no-x", "detail": str(exc), "monitors": [], "roles": {}}), 200
    roles = pco_screens.proposer_roles(mons)
    pf = next((m for m in mons if m["name"] == roles.get("playfield")), None)
    return jsonify({"monitors": mons, "roles": roles, "usage": pco_screens.usage_propose(roles),
                    "rotation": pf["rotation"] if pf else 0, "demo": DEMO})


@app.route("/api/screens/identify", methods=["POST"])
def screens_identify():
    a = request.get_json(force=True, silent=True) or {}
    roles = _roles_depuis(a) or {}
    try:
        mons = ecrans_detectes()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200
    if DEMO:
        return jsonify({"ok": True, "demo": True})
    libelles = a.get("labels") if isinstance(a.get("labels"), dict) else None
    res = pco_screens.identifier(mons, roles, int(a.get("seconds", 6)), libelles=libelles)
    return jsonify(res)


@app.route("/api/screens/apply", methods=["POST"])
def screens_apply():
    """Le bouton « Tester la disposition » : applique réellement, l'assistant suit le playfield."""
    a = request.get_json(force=True, silent=True) or {}
    roles, rotation = _roles_depuis(a), _rotation_depuis(a)
    if roles is None or rotation is None:
        return jsonify({"ok": False, "erreurs": ["rôles ou rotation invalides"]}), 400
    try:
        mons = ecrans_detectes()
    except Exception as exc:
        return jsonify({"ok": False, "erreurs": [str(exc)]}), 200
    erreurs = pco_screens.valider_roles(roles, mons)
    usage = pco_screens.usage_depuis(a)
    if usage is not None:
        erreurs += pco_screens.valider_usage(usage, roles)
    if erreurs:
        return jsonify({"ok": False, "erreurs": erreurs}), 200
    if DEMO:
        return jsonify({"ok": True, "demo": True, "disposition": pco_screens.disposition(mons, roles, rotation)})
    # PINCABOS_INSTALLEUR_LECTURE_V1 : la rotation de lecture ne vaut que pour cette session
    try:
        lecture = int(a.get("lecture") or 0)
    except (TypeError, ValueError):
        lecture = -1
    if lecture not in pco_screens.LECTURES:
        return jsonify({"ok": False, "erreurs": [f"rotation de lecture invalide : {a.get('lecture')}"]}), 200
    res = pco_screens.appliquer(mons, roles, rotation, lecture=lecture)
    if res.get("ok"):
        # PINCABOS_INSTALLEUR_DECOR_V1 : backglass, full DMD, topper habilles des visuels de la galerie
        try:
            res["decor"] = pco_screens.lancer_decor(mons, roles)
        except Exception as exc:
            res["decor"] = {"ok": False, "erreur": str(exc)}
        try:
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            KIOSK_TARGET.write_text(roles["playfield"] + "\n", encoding="utf-8")
        except OSError:
            pass
    return jsonify(res)


# ---------------------------------------------------------------- Réseau
# PINCABOS_INSTALLEUR_DMD_V1 : en démo, un ZeDMD S3 (ESP32 natif) est branché
DMD_DEMO = {
    "serie": [{"device": "/dev/ttyACM0", "vendor_id": "303a", "product_id": "1001", "model": "USB_JTAG_serial_debug_unit",
               "serial": "A0:B1:C2", "family": "esp32", "label": "ESP32 natif (Espressif) — ZeDMD probable", "candidate": True,
               "by_id": "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_A0B1C2-if00"}],
    "pin2dmd": [],
}


def dmd_detection():
    if DEMO:
        c = DMD_DEMO["serie"]
        return {"serie": c, "candidats": c, "pin2dmd": [], "disponible": True,
                "proposition": pco_dmd.proposer(c, [])}
    return pco_dmd.detecter()


@app.route("/api/dmd")
def dmd_status():
    try:
        d = dmd_detection()
    except Exception as exc:
        d = {"serie": [], "candidats": [], "pin2dmd": [], "disponible": False, "error": str(exc),
             "proposition": pco_dmd.proposer([], [])}
    d["types"] = [t["id"] for t in pco_dmd.TYPES]
    return jsonify(d)


@app.route("/api/dmd/test", methods=["POST"])
def dmd_test():
    a = request.get_json(force=True, silent=True) or {}
    if DEMO:
        erreurs, _ = pco_dmd.valider(a)
        return jsonify({"ok": not erreurs, "sortie": " ; ".join(erreurs) or "mire affichée (démo)"})
    return jsonify(pco_dmd.tester(a))


def dmd_vers_fichier(choix):
    """Le choix validé devient le zedmd.json de la cible (fichier sous RUN_DIR)."""
    erreurs, ok = pco_dmd.valider(choix)
    if erreurs:
        return {"error": "bad-dmd", "detail": erreurs}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    f = RUN_DIR / "gui-zedmd.json"
    f.write_text(json.dumps(pco_dmd.config_json(ok), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"dmd_file": str(f)}


# PINCABOS_INSTALLEUR_SON_DOF_V1 : en démo, le cab de Yann (Intel analogique + HDMI NVIDIA, DudesCab + Teensy)
APLAY_DEMO = """**** List of PLAYBACK Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC1220 Analog [ALC1220 Analog]
card 0: PCH [HDA Intel PCH], device 1: ALC1220 Digital [ALC1220 Digital]
card 1: NVidia [HDA NVidia], device 3: HDMI 0 [RTK FHD]
card 1: NVidia [HDA NVidia], device 7: HDMI 1 [LG TV SSCR2]
"""
DOF_DEMO = [
    {"dev": "/dev/hidraw5", "vid": "2e8a", "model": "DudesCab", "serial": "DE646CC2", "kind": "DudesCab", "auto_config": True},
    {"dev": "/dev/ttyACM0", "vid": "16c0", "model": "USB_Serial", "serial": "15672630", "kind": "TeensyStripController (strip adressable)", "auto_config": False},
]


def son_detection():
    """Sorties audio et cartes DOF de la machine (ou de la démo)."""
    if pco_audio is None or pco_dof is None:
        return {"disponible": False, "audio": {"devices": [], "proposition": {}, "modes": []}, "dof": {"detected": [], "proposition": {"enabled": False}}}
    if not DEMO:
        # Le media d installation demarre avec snd_hda_intel sur liste noire
        # (ligne de commande du noyau) : sans lui, ni HDMI ni analogique interne
        # ne sont visibles. On le charge a la demande, ici seulement.
        pco_audio.charger_pilotes()
    devs = pco_audio.peripheriques_alsa(APLAY_DEMO) if DEMO else pco_audio.detecter()
    det = DOF_DEMO if DEMO else pco_dof.detecter()
    return {"disponible": True,
            "audio": {"devices": devs, "proposition": pco_audio.proposer(devs), "modes": [list(m) for m in pco_audio.SOUND3D]},
            "dof": {"detected": pco_dof.resume(det), "proposition": pco_dof.proposer(det)}}


@app.route("/api/sound")
def sound_status():
    try:
        return jsonify(son_detection())
    except Exception as exc:
        return jsonify({"disponible": False, "error": str(exc), "audio": {"devices": [], "proposition": {}, "modes": []},
                        "dof": {"detected": [], "proposition": {"enabled": False}}})


@app.route("/api/sound/test-channel", methods=["POST"])
def sound_test_channel():
    """PINCABOS_AUDIO_HP_UN_PAR_UN_V1 : speaker-test sur un seul canal (la voix annonce le haut-parleur)."""
    a = request.get_json(force=True, silent=True) or {}
    ident = str(a.get("device") or "")
    if pco_audio is None:
        return jsonify({"ok": False, "sortie": "module audio absent"})
    if not pco_audio.HW_RE.match(ident):
        return jsonify({"ok": False, "sortie": "sortie invalide"})
    try:
        canaux, canal = int(a.get("channels", 2)), int(a.get("channel", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "sortie": "canal invalide"})
    if DEMO:
        return jsonify({"ok": True, "sortie": f"canal {canal + 1}/{canaux} joué (démo) sur {ident}"})
    return jsonify(pco_audio.tester_canal(ident, canaux, canal))


@app.route("/api/sound/test", methods=["POST"])
def sound_test():
    a = request.get_json(force=True, silent=True) or {}
    ident = str(a.get("device") or "")
    if pco_audio is None:
        return jsonify({"ok": False, "sortie": "module audio absent"})
    if not pco_audio.HW_RE.match(ident):
        return jsonify({"ok": False, "sortie": "sortie invalide"})
    if DEMO:
        return jsonify({"ok": True, "sortie": "son joué (démo) sur " + ident})
    return jsonify(pco_audio.tester(ident))


@app.route("/api/sound/volume", methods=["POST"])
def sound_volume():
    a = request.get_json(force=True, silent=True) or {}
    ident = str(a.get("device") or "")
    try:
        vol = max(0, min(100, int(a.get("volume", 70))))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "sortie": "volume invalide"})
    if pco_audio is None or not pco_audio.HW_RE.match(ident):
        return jsonify({"ok": False, "sortie": "sortie invalide"})
    if DEMO:
        return jsonify({"ok": True, "sortie": f"volume {vol} % (démo)"})
    return jsonify(pco_audio.volume_alsa(ident, vol))


def son_vers_fichiers(a):
    """Les choix Son et DOF deviennent audio-router.json et dof/installer.json pour la cible."""
    if pco_audio is None or pco_dof is None:
        return {}
    det = son_detection()
    devs = det["audio"]["devices"]
    reponses = {}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if isinstance(a.get("sound"), dict):
        erreurs, ok = pco_audio.valider(a["sound"], devs)
        if erreurs:
            return {"error": "bad-sound", "detail": erreurs}
        f = RUN_DIR / "gui-audio.json"
        f.write_text(json.dumps(pco_audio.config_json(ok, devs), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        reponses["audio_file"] = str(f)
    if isinstance(a.get("dof"), dict):
        erreurs, ok = pco_dof.valider(a["dof"])
        if erreurs:
            return {"error": "bad-dof", "detail": erreurs}
        brut = DOF_DEMO if DEMO else pco_dof.detecter()
        f = RUN_DIR / "gui-dof.json"
        f.write_text(json.dumps(pco_dof.config_json(ok, brut), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        reponses["dof_file"] = str(f)
    return reponses


# PINCABOS_INSTALLEUR_TOYS_V1 : cartes de boutons (evdev), cartes de sortie AutoConfig, controleurs de rubans
ENTREES_DEMO = [{"name": "L'atelier d'Arnoz DudesCab", "id": "SDLJoy_0300a1eb8a2e00006f10000011010000_1", "buttons": 32, "axes": 6, "hats": 1}]
TOYS_DEMO = DOF_DEMO + [{"dev": "/dev/ttyUSB0", "vid": "10c4", "model": "CP2104", "serial": "01AA5AA5",
                         "kind": "Wemos D1 / ESP via CP210x (WemosD1MPStripController possible)", "auto_config": False}]


def entrees_detectees():
    """Cartes de boutons / plunger vues comme joysticks (pincabos_vpx_input)."""
    if DEMO:
        return list(ENTREES_DEMO)
    try:
        import pincabos_vpx_input as vi
        devs = vi.list_devices()
        ids = vi.joystick_setting_ids(devs)
        return [{"name": d.name, "id": ids.get(d.path, ("", ""))[0], "buttons": len(d.button_order()),
                 "axes": len(d.axis_order()), "hats": len(d.digital_hats())} for d in devs if d.is_joystick]
    except Exception:
        return []


def toys_detection():
    det = TOYS_DEMO if DEMO else (pco_dof.detecter() if pco_dof else [])
    return {"disponible": pco_dof is not None, "inputs": entrees_detectees(),
            "auto": pco_dof.cartes_auto(det) if pco_dof else [],
            "strips": pco_dof.controleurs_de_rubans(det) if pco_dof else [],
            "arrangements": list(pco_dof.ARRANGEMENTS) if pco_dof else [], "color_orders": list(pco_dof.ORDRES_COULEUR) if pco_dof else [],
            "proposition": pco_dof.proposer_toys(det) if pco_dof else {"controllers": []}, "_det": det}


@app.route("/api/toys")
def toys_status():
    try:
        d = toys_detection()
        d.pop("_det", None)
        return jsonify(d)
    except Exception as exc:
        return jsonify({"disponible": False, "error": str(exc), "inputs": [], "auto": [], "strips": [], "arrangements": [],
                        "color_orders": [], "proposition": {"controllers": []}})


def toys_vers_fichiers(a):
    """Les contrôleurs de rubans déclarés deviennent l'inventaire de la page DOF (gui-toys.json)."""
    if pco_dof is None or not isinstance(a.get("toys"), dict):
        return {}
    det = toys_detection()["_det"]
    erreurs, ok = pco_dof.valider_toys(a["toys"], det)
    if erreurs:
        return {"error": "bad-toys", "detail": erreurs}
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    f = RUN_DIR / "gui-toys.json"
    f.write_text(json.dumps(pco_dof.inventaire_json(ok, det), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"toys_file": str(f)}


RESEAU_DEMO = {
    "interfaces": [
        {"device": "eno1", "type": "ethernet", "state": "100 (connected)", "method": "auto", "address": "172.18.40.80/24",
         "gateway": "172.18.40.254", "dns": ["172.18.41.254"], "hwaddr": "04:D4:C4:A8:65:ED",
         "proposition": {"address": "172.18.40.80/24", "gateway": "172.18.40.254", "dns": ["172.18.41.254"], "source": "dhcp"}},
        {"device": "wlp3s0", "type": "wifi", "state": "30 (disconnected)", "method": "", "address": "", "gateway": "", "dns": [], "hwaddr": "",
         "proposition": {"address": "", "gateway": "", "dns": ["9.9.9.9", "1.1.1.1"], "source": "aucune"}},
    ],
    "wifi": {"present": True, "radio": "enabled", "devices": ["wlp3s0"], "capacites": {"2ghz": True, "5ghz": False, "wpa2": True}},
    "hostname": "pincabos-installer", "legacy": False, "disponible": True,
}
RESEAU_SCAN_DEMO = [
    {"ssid": "Maison", "signal": 82, "security": "WPA2", "mode": "wpa-psk", "in_use": False, "freq": 2437, "compatible": True, "raison": ""},
    {"ssid": "Cafe", "signal": 70, "security": "", "mode": "open", "in_use": False, "freq": 2462, "compatible": True, "raison": ""},
    {"ssid": "Neuf", "signal": 66, "security": "WPA3", "mode": "sae", "in_use": False, "freq": 5240, "compatible": False, "raison": "réseau 5 GHz, carte 2,4 GHz seulement"},
]


def reseau_etat():
    if DEMO:
        return json.loads(json.dumps(RESEAU_DEMO))
    if pco_net is None:
        return {"interfaces": [], "wifi": {"present": False, "devices": []}, "hostname": "", "legacy": False, "disponible": False}
    r = pco_net.resume(run=pco_net.executer)
    r["disponible"] = True
    return r


@app.route("/api/network")
def network_status():
    try:
        return jsonify(reseau_etat())
    except Exception as exc:
        return jsonify({"interfaces": [], "wifi": {"present": False, "devices": []}, "disponible": False, "error": str(exc)})


@app.route("/api/network/wifi-scan")
def network_wifi_scan():
    if DEMO:
        return jsonify({"present": True, "reseaux": RESEAU_SCAN_DEMO})
    if pco_net is None:
        return jsonify({"present": False, "reseaux": []})
    mat = pco_net.wifi_materiel(run=pco_net.executer)
    if not mat["present"] or not mat["devices"]:
        return jsonify({"present": False, "reseaux": []})
    caps = pco_net.wifi_capacites(mat["devices"][0], run=pco_net.executer)
    return jsonify({"present": True, "reseaux": pco_net.wifi_scan(run=pco_net.executer, rescan=True, caps=caps), "capacites": caps})


@app.route("/api/network/apply", methods=["POST"])
def network_apply():
    """DHCP ou IP fixe, appliqué tout de suite dans la session : le résultat se voit."""
    a = request.get_json(force=True, silent=True) or {}
    iface = str(a.get("iface", "")).strip()
    mode = str(a.get("mode", "dhcp")).strip()
    if DEMO:
        if mode == "static":
            v = pco_net_valider(a)
            if v["erreurs"]:
                return jsonify({"ok": False, "journal": ["NOGO: " + e for e in v["erreurs"]]})
        return jsonify({"ok": True, "demo": True, "journal": [f"GO: {iface} en {'IP fixe' if mode == 'static' else 'DHCP'} (démo)"]})
    if pco_net is None:
        return jsonify({"ok": False, "journal": ["NOGO: réseau indisponible dans cette session"]})
    if iface not in [d["device"] for d in pco_net.peripheriques(run=pco_net.executer)]:
        return jsonify({"ok": False, "journal": [f"NOGO: interface inconnue : {iface or '(vide)'}"]})
    journal = []
    if pco_net.legacy_present(iface):
        journal += pco_net.legacy_takeover(iface)
    if mode == "static":
        v = pco_net_valider(a)
        if v["erreurs"]:
            return jsonify({"ok": False, "journal": journal + ["NOGO: " + e for e in v["erreurs"]]})
        journal += pco_net.appliquer_fixe(iface, v["address"], v["gateway"], v["dns"], run=pco_net.executer)
    else:
        journal += pco_net.appliquer_dhcp(iface, run=pco_net.executer)
    ok = not any(l.startswith("NOGO") for l in journal)
    etat = pco_net.etat(iface, run=pco_net.executer) if ok else {}
    return jsonify({"ok": ok, "journal": journal, "etat": etat})


def pco_net_valider(a):
    if pco_net is not None:
        return pco_net.valider_fixe(a.get("address", ""), a.get("gateway", ""), a.get("dns", ""))
    # démo sans module : validation minimale
    import ipaddress
    erreurs = []
    try:
        ipaddress.IPv4Interface(str(a.get("address", "")))
    except ValueError:
        erreurs.append("adresse invalide")
    if not str(a.get("gateway", "")).strip():
        erreurs.append("passerelle manquante")
    return {"erreurs": erreurs, "address": a.get("address", ""), "gateway": a.get("gateway", ""), "dns": a.get("dns", "")}


@app.route("/api/network/wifi-join", methods=["POST"])
def network_wifi_join():
    a = request.get_json(force=True, silent=True) or {}
    if DEMO:
        ssid = str(a.get("ssid", "")).strip()
        if not ssid:
            return jsonify({"ok": False, "journal": ["NOGO: SSID manquant"]})
        if ssid == "Neuf":
            return jsonify({"ok": False, "journal": ["NOGO: réseau « Neuf » incompatible avec la carte : réseau 5 GHz, carte 2,4 GHz seulement"]})
        return jsonify({"ok": True, "demo": True, "journal": [f"GO: connecté à « {ssid} » (démo)"]})
    if pco_net is None:
        return jsonify({"ok": False, "journal": ["NOGO: réseau indisponible dans cette session"]})
    journal = pco_net.wifi_join(str(a.get("ssid", "")), str(a.get("password", "")), str(a.get("security", "auto") or "auto"),
                                str(a.get("identity", "")), bool(a.get("hidden")), run=pco_net.executer)
    return jsonify({"ok": not any(l.startswith("NOGO") for l in journal), "journal": journal})


def reseau_vers_fichiers():
    """Photographie les profils NetworkManager de la session (netplan 90-NM-*.yaml,
    clés Wi-Fi comprises) et la liste des interfaces configurées, pour la cible."""
    import shutil
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    dossier = RUN_DIR / "gui-netplan"
    shutil.rmtree(dossier, ignore_errors=True)
    dossier.mkdir(parents=True)
    copies = []
    if not DEMO:
        for f in sorted(Path("/etc/netplan").glob("90-NM-*.yaml")):
            shutil.copy2(f, dossier / f.name)
            copies.append(f.name)
    etat = reseau_etat()
    data = {
        "source": "PinCabOS installer network step",
        "interfaces": [{"device": i["device"], "type": i["type"], "method": i.get("method", ""), "address": i.get("address", "")}
                       for i in etat.get("interfaces", [])],
        "netplan_files": copies,
        "wifi_present": bool(etat.get("wifi", {}).get("present")),
    }
    f = RUN_DIR / "gui-network.json"
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"network_file": str(f), "netplan_dir": str(dossier)}


def ecrans_vers_fichiers(a):
    """Les choix validés deviennent screens.json + liaisons EDID, pour la cible."""
    roles, rotation = _roles_depuis(a), _rotation_depuis(a)
    if roles is None or rotation is None:
        return {"error": "bad-screens"}
    mons = ecrans_detectes()
    erreurs = pco_screens.valider_roles(roles, mons)
    usage = pco_screens.usage_depuis(a.get("screens") if isinstance(a.get("screens"), dict) else a)
    if usage is not None:
        erreurs += pco_screens.valider_usage(usage, roles)
    if erreurs:
        return {"error": "bad-screens", "detail": erreurs}
    data = pco_screens.screens_json(mons, roles, rotation)
    liaisons = pco_screens.bindings_json(data)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    f1 = RUN_DIR / "gui-screens.json"
    f2 = RUN_DIR / "gui-screens-bindings.json"
    f1.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    f2.write_text(json.dumps(liaisons, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    f3 = RUN_DIR / "gui-calibrations.json"
    f3.write_text(json.dumps(pco_screens.calibrations_json(data), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"screens_file": str(f1), "bindings_file": str(f2), "calibrations_file": str(f3), "orient": pco_screens.code_orient(rotation)}


@app.route("/api/keyboard", methods=["POST"])
def keyboard():
    """Applique le layout au serveur X du kiosk (l'utilisateur tape ce qu'il voit)."""
    a = request.get_json(force=True)
    xkb = a.get("xkb", "us")
    variant = a.get("variant", "")
    if not re.fullmatch(r"[a-z]{2,3}", xkb):
        return jsonify({"error": "bad-xkb"}), 400
    if DEMO:
        return jsonify({"ok": True, "demo": True})
    cmd = ["setxkbmap", "-display", ":1", xkb]
    if variant and re.fullmatch(r"[a-z0-9_-]+", variant):
        cmd += ["-variant", variant]
    subprocess.run(cmd, timeout=10, check=False)
    return jsonify({"ok": True})


# PINCABOS_ANSWERS_QUOTING_V1
# Ce que le moteur sait faire de chaque reponse. Une valeur hors de ce moule
# est refusee : la corriger reviendrait a deviner l'intention.
ANSWER_RULES = {
    "lang": re.compile(r"^[a-z]{2,3}$"),
    "locale": re.compile(r"^[A-Za-z][A-Za-z0-9._@-]{1,31}$"),
    # PINCABOS_ANSWERS_QUOTING_V2 — base.lst contient latam, brai, custom.
    "xkb": re.compile(r"^[a-z]{2,8}$"),
    "xkb_variant": re.compile(r"^[a-z0-9_-]{0,31}$"),
    "tz": re.compile(r"^[A-Za-z][A-Za-z0-9_+-]{0,31}(/[A-Za-z0-9_+-]{1,31}){0,2}$"),
    "orient": re.compile(r"^[1-4]$"),
    "mode": re.compile(r"^[1-3]$"),
    "disk": re.compile(r"^/dev/[a-z0-9]+$"),
    # PINCABOS_INSTALLEUR_ECRANS_V1 : fichiers produits ici même, chemins fixes
    # PINCABOS_INSTALLEUR_ECRANS_V1 : chemins fixes des fichiers produits par
    # l'étape Écrans (le vérificateur CI relit ces moules avec `re` seul).
    "screens_file": re.compile(r"^/run/pincabos/gui-screens\.json$"),
    # PINCABOS_INSTALLEUR_CALIBRATIONS_V1 : rectangles FullDMD / DMD derives de la disposition
    "calibrations_file": re.compile(r"^/run/pincabos/gui-calibrations\.json$"),
    "bindings_file": re.compile(r"^/run/pincabos/gui-screens-bindings\.json$"),
    # PINCABOS_INSTALLEUR_RESEAU_V1 : idem, produits par l'étape Réseau
    "network_file": re.compile(r"^/run/pincabos/gui-network\.json$"),
    "netplan_dir": re.compile(r"^/run/pincabos/gui-netplan$"),
    # PINCABOS_INSTALLEUR_DMD_V1 : zedmd.json produit par l'étape Écrans
    "dmd_file": re.compile(r"^/run/pincabos/gui-zedmd\.json$"),
    # PINCABOS_INSTALLEUR_SON_DOF_V1 : produits par l'étape Son et DOF
    "audio_file": re.compile(r"^/run/pincabos/gui-audio\.json$"),
    "dof_file": re.compile(r"^/run/pincabos/gui-dof\.json$"),
    # PINCABOS_INSTALLEUR_TOYS_V1 : inventaire DOF produit par l'étape Toys / LED
    "toys_file": re.compile(r"^/run/pincabos/gui-toys\.json$"),
}


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b[c()][0-9A-B]?")

# Barre de progression d'unsquashfs : [===|   ]  1234/5678  27%
UNSQUASHFS_RE = re.compile(r"\]\s+\d+\s*/\s*\d+\s+(\d+)%")
DEPLOY_FROM, DEPLOY_TO = 45, 72


@app.route("/api/install", methods=["POST"])
def install():
    a = request.get_json(force=True)
    if a.get("confirm", "").strip().upper() != "INSTALL PINCABOS":
        return jsonify({"error": "bad-confirm"}), 400
    # PINCABOS_WIZARD_LOCAL_ONLY_V1
    # Le disque demande doit figurer parmi ceux que la machine porte : la
    # forme seule ne dit pas si le disque existe.
    if a.get("disk", "") not in {d["dev"] for d in disques_reels()}:
        return jsonify({"error": "bad-disk"}), 400

    # PINCABOS_ANSWERS_QUOTING_V1
    # Toutes les reponses sont confrontees a leur moule, pas seulement le
    # disque : l'installateur charge ce fichier avec « . », en root.
    reponses = {}
    for cle, moule in ANSWER_RULES.items():
        # PINCABOS_INSTALLEUR_REPONSE_NULLE_V1 : l'assistant envoie son état
        # entier, dont des clés qu'aucune étape ne remplit plus (orient, calculé
        # ici depuis l'étape Écrans) : null = « pas de réponse », pas une réponse
        # hors moule. Vu en VM : toute installation refusée « bad-orient », en silence.
        if cle not in a or a[cle] is None:
            continue
        valeur = str(a[cle])
        if not moule.match(valeur):
            return jsonify({"error": f"bad-{cle.replace('_', '-')}"}), 400
        reponses[cle] = valeur

    # PINCABOS_INSTALLEUR_ECRANS_V1 : l'étape Écrans remplace la vignette
    # d'orientation ; le code « orient » du moteur (fbcon, splash) en dérive.
    if isinstance(a.get("screens"), dict):
        res = ecrans_vers_fichiers(a["screens"])
        if "error" in res:
            return jsonify(res), 400
        # Ces trois valeurs viennent d'ici, pas du client : les fichiers sont
        # écrits par ecrans_vers_fichiers() sous RUN_DIR, le code orient est
        # dérivé de la rotation ; shlex.quote les rend inertes comme le reste.
        for cle in ("screens_file", "bindings_file", "calibrations_file", "orient"):
            reponses[cle] = res[cle]
        # PINCABOS_INSTALLEUR_DMD_V1 : sans full DMD, le DMD matériel choisi
        # (ou « aucun ») part sur la cible ; avec un full DMD, rien n'est écrit.
        usage = pco_screens.usage_depuis(a["screens"])
        if usage is not None and not usage.get("fulldmd") and isinstance(a.get("dmd"), dict):
            res = dmd_vers_fichier(a["dmd"])
            if "error" in res:
                return jsonify(res), 400
            reponses["dmd_file"] = res["dmd_file"]

    # PINCABOS_INSTALLEUR_SON_DOF_V1 : son et DOF choisis dans l'assistant
    if isinstance(a.get("sound"), dict) or isinstance(a.get("dof"), dict):
        res = son_vers_fichiers(a)
        if "error" in res:
            return jsonify(res), 400
        reponses.update(res)

    # PINCABOS_INSTALLEUR_TOYS_V1 : contrôleurs de rubans déclarés
    if isinstance(a.get("toys"), dict):
        res = toys_vers_fichiers(a)
        if "error" in res:
            return jsonify(res), 400
        reponses.update(res)

    # PINCABOS_INSTALLEUR_RESEAU_V1 : ce que la session a configuré part sur la cible
    if a.get("network") is not False:
        try:
            reponses.update(reseau_vers_fichiers())
        except Exception as exc:
            app.logger.warning("réseau non photographié : %s", exc)

    if "mode" not in reponses:
        return jsonify({"error": "bad-mode"}), 400

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    # shlex.quote produit une chaine que le shell relit comme une donnee et
    # jamais comme du code : la seconde barriere, si la premiere cedait.
    ANSWERS.write_text("".join(
        f"PCO_ANS_{cle.upper()}={shlex.quote(valeur)}\n"
        for cle, valeur in reponses.items()), encoding="utf-8")
    if DEMO:
        return jsonify({"ok": True, "demo": True})
    subprocess.Popen(  # le moteur existant, en mode reponses (contrat partage TUI/GUI)
        ["systemd-run", "--unit=pincabos-gui-install", "--collect",
         f"--setenv=PCO_ANSWERS={ANSWERS}", "--setenv=TERM=linux",
         "sh", "-c", f"{ENGINE} >{INSTALL_LOG} 2>&1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return jsonify({"ok": True})


# Jalons du moteur -> pourcentage (marqueurs reels de ses pco_step/pco_go)
PHASES = [
    ("Regional configuration accepted", 5),
    ("Unmounting target disk", 8),
    ("Partitioning disk GPT", 12),
    ("payload", 45),
    ("Payload PinCabOS install", 72),
    ("Final boot refresh", 85),
    ("GRUB", 92),
    ("PINCABOS_INSTALL_COMPLETE", 100),
]


@app.route("/api/progress")
def progress():
    def stream():
        if DEMO:
            steps = [(5, "Vérification du payload"), (14, "Partitionnement"),
                     (30, "Extraction du payload"), (55, "Extraction du payload"),
                     (72, "Configuration régionale"), (85, "Initramfs cible"),
                     (95, "GRUB"), (100, "Terminé")]
            for pct, label in steps:
                yield f"data: {json.dumps({'pct': pct, 'label': label})}\n\n"
                time.sleep(1.6)
            return
        pos = 0
        pct = 2
        envoye = 0
        while pct < 100:
            if INSTALL_LOG.exists():
                text = INSTALL_LOG.read_text(errors="replace")
                new, pos = text[pos:], len(text)
                for line in new.splitlines():
                    for marker, p in PHASES:
                        if marker.lower() in line.lower():
                            pct = max(pct, p)
                    # progression fine pendant l'extraction du rootfs
                    if DEPLOY_FROM <= pct < DEPLOY_TO:
                        m = UNSQUASHFS_RE.search(line)
                        if m:
                            part = min(100, int(m.group(1)))
                            pct = max(pct, DEPLOY_FROM
                                      + (DEPLOY_TO - DEPLOY_FROM) * part // 100)
                    # log lisible : sans ANSI, sans lignes decoratives ni art figlet
                    clean = ANSI_RE.sub("", line).strip()
                    if not clean:
                        continue
                    readable = sum(c.isalnum() or c in " ,.:;()/'\"-_" for c in clean)
                    if readable / len(clean) < 0.6:
                        continue
                    envoye = pct
                    yield f"data: {json.dumps({'pct': pct, 'log': clean})}\n\n"
            # la barre avance meme si aucune ligne lisible n'est apparue
            if pct != envoye:
                envoye = pct
                yield f"data: {json.dumps({'pct': pct})}\n\n"
            time.sleep(1)
        yield f"data: {json.dumps({'pct': 100, 'label': 'done'})}\n\n"
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/reboot", methods=["POST"])
def reboot():
    # PINCABOS_WIZARD_LOCAL_ONLY_V1
    # Un point d'entree qui redemarre la machine ne peut pas etre plus ouvert
    # que celui qui l'installe.
    a = request.get_json(force=True, silent=True) or {}
    if a.get("confirm", "").strip().upper() != "INSTALL PINCABOS":
        return jsonify({"error": "bad-confirm"}), 400
    if not DEMO:
        subprocess.Popen(["systemctl", "reboot"])
    return jsonify({"ok": True})


if __name__ == "__main__":
    # PINCABOS_WIZARD_LOCAL_ONLY_V1
    # Le kiosk qui affiche l'assistant tourne sur cette machine et interroge
    # 127.0.0.1. Ecouter partout exposait l'installation au reseau entier.
    # Une installation pilotee a distance reste possible, mais elle se demande.
    app.run(host=os.environ.get("PCO_WIZARD_BIND", "127.0.0.1"),
            port=8046, threaded=True)
