#!/usr/bin/env python3
"""
dof-cabinet.py — détection matérielle + génération de cabinet.xml pour DOF (libdof) / PinCabOS.

Le cabinet.xml de DOF ne contient (côté parseur libdof) que :
  - <AutoConfigEnabled> : laisse DOF auto-détecter les contrôleurs standards
    (DudesCab, LedWiz, Pinscape, PacLed64/PacDrive/PacUIO, ...).
  - <OutputControllers>  : les contrôleurs à déclarer explicitement — surtout les
    strips LED adressables (TeensyStripController, WemosD1MPStripController) et
    ArtNet / PinOne. Les contrôleurs auto-configurables n'ont PAS besoin d'y figurer.
  - <Toys> : uniquement LedWizEquivalent (mapping) et LedStrip (matrice adressable).
    Les autres toys (flashers, contacteurs, RGB...) viennent du DOF config tool
    (directoutputconfig), pas du cabinet.xml.

Sous-commandes :
  detect [--json]                 Liste les contrôleurs DOF détectés (USB).
  gen <config.json> <out.xml>     Génère cabinet.xml depuis une config déclarative.
  sample [<out.json>]             Écrit un exemple de config commenté.
  arrangements                    Liste les arrangements de strip valides.

Contrôleurs reconnus par libdof (balises XML) : NullOutputController, Pinscape,
PinscapePico, LedWiz, DudesCab, UMXController, PacLed64, PacDrive, PacUIO,
FT245RBitbangController, TeensyStripController, WemosD1MPStripController,
PinControl, PinOne, ArtNet.
"""
import sys, json, os, glob, subprocess, re

# --- détection USB : VID -> (type de contrôleur, auto-configurable par DOF ?) ---
VID_MAP = {
    "16c0": ("Teensy/PJRC (TeensyStripController, Pinscape, ...)", False),
    "2e8a": ("DudesCab / RP2040", True),
    "fafa": ("LedWiz", True),
    "d209": ("Ultimarc PacLed64/PacDrive/PacUIO", True),
    "1209": ("Pinscape (generic)", True),
    "0403": ("FTDI (FT245R bitbang)", False),
    # puces USB-serie des Wemos D1 / ESP : candidats WemosD1MPStripController.
    # VID generiques (d'autres adaptateurs serie les utilisent) -> "possible".
    "10c4": ("Wemos D1 / ESP via CP210x (WemosD1MPStripController possible)", False),
    "1a86": ("Wemos D1 / ESP via CH340 (WemosD1MPStripController possible)", False),
    "303a": ("ESP32 Espressif natif (WemosD1MPStripController possible)", False),
}
ADDRESSABLE_ARRANGEMENTS = [
    "LeftRightTopDown", "LeftRightBottomUp", "RightLeftTopDown", "RightLeftBottomUp",
    "TopDownLeftRight", "TopDownRightLeft", "BottomUpLeftRight", "BottomUpRightLeft",
    "LeftRightAlternateTopDown", "LeftRightAlternateBottomUp",
    "RightLeftAlternateTopDown", "RightLeftAlternateBottomUp",
    "TopDownAlternateLeftRight", "TopDownAlternateRightLeft",
    "BottomUpAlternateLeftRight", "BottomUpAlternateRightLeft",
]
COLOR_ORDERS = ["RGB", "RBG", "GRB", "GBR", "BRG", "BGR"]


def _udev(dev):
    try:
        out = subprocess.run(["udevadm", "info", "-q", "property", "-n", dev],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return {}
    d = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def detect():
    found = []
    seen = set()
    for dev in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/hidraw*")):
        p = _udev(dev)
        vid = (p.get("ID_VENDOR_ID") or "").lower()
        model = p.get("ID_MODEL") or p.get("ID_SERIAL") or ""
        serial = p.get("ID_SERIAL_SHORT") or ""
        key = (vid, serial, p.get("ID_MODEL", ""))
        kind, autocfg = VID_MAP.get(vid, ("inconnu / non-DOF", None))
        if "dudescab" in model.lower():
            kind, autocfg = "DudesCab", True
        if vid == "16c0" and "teensy" in (p.get("ID_SERIAL", "") + model).lower():
            kind, autocfg = "TeensyStripController (strip adressable)", False
        entry = {"dev": dev, "vid": vid, "model": model, "serial": serial,
                 "kind": kind, "auto_config": autocfg}
        # dédup par (vid,serial) pour ne pas lister 5x la DudesCab (multi hidraw)
        dk = (vid, serial, kind)
        if dk in seen:
            continue
        seen.add(dk)
        if autocfg is not None:      # ne garde que les contrôleurs DOF plausibles
            found.append(entry)
    return found


# VID des puces serie que porte une Wemos D1 / ESP (cf. VID_MAP).
ESP_VIDS = ("1a86", "10c4", "303a")


def _teensy_port(exclus=()):
    for dev in sorted(glob.glob("/dev/ttyACM*")):
        if dev in exclus:
            continue
        p = _udev(dev)
        if "teensy" in (p.get("ID_SERIAL", "") + p.get("ID_MODEL", "")).lower():
            return dev
    return None


def _esp_port(exclus=()):
    """Port d une Wemos D1 / ESP. Elles sortent sur /dev/ttyUSB* via CH340 ou
    CP210x ; un ESP32 natif (303a) peut sortir sur /dev/ttyACM*."""
    for dev in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")):
        if dev in exclus:
            continue
        if (_udev(dev).get("ID_VENDOR_ID") or "").lower() in ESP_VIDS:
            return dev
    return None


def _resoudre_ports(strips):
    """Un port serie par controleur, jamais le meme deux fois.

    PINCABOS_DOF_PORT_PAR_FAMILLE_V1 — remonte le 09/09/2026 par Patrick : sa
    Wemos n allumait aucune LED. La resolution de « auto » etait la meme pour
    les deux familles :

        _tty_by_serial(serial) or _teensy_port() or "/dev/ttyACM0"

    Sans numero de serie enregistre — et l inventaire n en attribuait qu aux
    Teensy — une Wemos tombait donc sur _teensy_port(), c est-a-dire le port de
    la TEENSY. Les deux controleurs se retrouvaient sur le meme /dev/ttyACM1 :
    la Wemos ne recevait rien, et la Teensy recevait le trafic des deux.
    """
    pris, resolus = [], []
    for s in strips:
        wemos = s.get("controller") == "WemosD1MPStripController"
        port = s.get("com_port", "auto")
        if port == "auto":
            port = _tty_by_serial(s.get("serial")) or ""
        if not port:
            port = (_esp_port(pris) if wemos else _teensy_port(pris)) or ""
        if not port:
            # aucun materiel de cette famille branche : on ecrit un port par
            # defaut de la BONNE famille, pas celui de l autre.
            port = "/dev/ttyUSB0" if wemos else "/dev/ttyACM0"
        if port in pris:
            sys.stderr.write(
                "ATTENTION: %s et un autre controleur visent %s. "
                "Renseignez le numero de serie de chaque carte "
                "(page DOF > Materiel) pour les distinguer.\n"
                % (s.get("name", s.get("controller", "?")), port))
        pris.append(port)
        resolus.append(dict(s, com_port=port))
    return resolus


def _tty_by_serial(serial):
    """Retrouve le /dev/tty* d'une carte par son numero de serie USB.
    Indispensable avec plusieurs Teensy : 'auto' seul serait ambigu."""
    if not serial:
        return None
    for dev in sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")):
        if _udev(dev).get("ID_SERIAL_SHORT") == serial:
            return dev
    return None


# ----------------------------- génération XML -----------------------------
def _el(tag, val):
    return "      <%s>%s</%s>" % (tag, val, tag)


def _strip_controller(s, tag):
    """Bloc controleur de strips adressables. WemosD1MPStripController HERITE
    de TeensyStripController dans libdof : memes tags serie (ComPortName...),
    PAS de HostName. Strips 1..10 (9-10 emis seulement si non nuls, pour
    rester octet-identique aux cabinet.xml existants a 8 entrees)."""
    # _resoudre_ports() a normalement deja fige le port ; ce repli sert aux
    # appels directs et reste fidele a la FAMILLE du controleur.
    port = s.get("com_port", "auto")
    if port == "auto":
        wemos = tag == "WemosD1MPStripController"
        port = (_tty_by_serial(s.get("serial"))
                or (_esp_port() if wemos else _teensy_port())
                or ("/dev/ttyUSB0" if wemos else "/dev/ttyACM0"))
    leds = (s.get("leds_per_strip", []) + [0] * 10)[:10]
    lines = ["    <%s>" % tag,
             _el("Name", s.get("name", "%s 1" % tag))]
    for i in range(10):
        if i < 8 or leds[i]:
            lines.append(_el("NumberOfLedsStrip%d" % (i + 1), leds[i]))
    lines += [
        _el("ComPortName", port),
        _el("ComPortTimeOutMs", s.get("timeout_ms", 200)),
        _el("ComPortBaudRate", s.get("baud", 9600)),
        _el("ComPortOpenWaitMs", 50),
        _el("ComPortHandshakeStartWaitMs", 20),
        _el("ComPortHandshakeEndWaitMs", 50),
        _el("SendPerLedstripLength", "true"),
        _el("UseCompression", "true"),
        _el("TestOnConnect", "true" if s.get("test_on_connect", False) else "false"),
        "    </%s>" % tag,
    ]
    return "\n".join(lines)


def _teensy_controller(s):
    return _strip_controller(s, "TeensyStripController")


def _wemos_controller(s):
    return _strip_controller(s, "WemosD1MPStripController")


def _artnet(a):
    lines = ["    <ArtNet>", _el("Name", a.get("name", "ArtNet 1"))]
    if a.get("broadcast_address"):
        lines.append(_el("BroadCastAddress", a["broadcast_address"]))
    if "universe" in a:
        lines.append(_el("Universe", a["universe"]))
    lines.append("    </ArtNet>")
    return "\n".join(lines)


def _pinone(p):
    lines = ["    <PinOne>", _el("Name", p.get("name", "PinOne 1"))]
    if p.get("com_port"):
        lines.append(_el("ComPortName", p["com_port"]))
    lines.append("    </PinOne>")
    return "\n".join(lines)


def _ledstrip_toy(s, t=None):
    # PINCABOS_DOF_TOYS_MULTIPLES_V1 : un controleur peut porter plusieurs toys
    # (mode « rubans » de l installeur : un LedStrip par sortie utilisee)
    t = t or s["toy"]
    return "\n".join([
        "    <LedStrip>",
        _el("Name", t["name"]),
        _el("Width", t["width"]),
        _el("Height", t["height"]),
        _el("LedStripArrangement", t.get("arrangement", "LeftRightTopDown")),
        _el("ColorOrder", t.get("color_order", "RGB")),
        _el("FirstLedNumber", t.get("first_led", 1)),
        _el("FadingCurveName", t.get("fading_curve", "Linear")),
        _el("Brightness", t.get("brightness", 100)),
        _el("OutputControllerName", s.get("name", "TeensyStripController 1")),
        "    </LedStrip>",
    ])


def _ledwiz_equivalent(s):
    toys = s.get("toys") or [s["toy"]]
    num = s.get("ledwiz_number", 30)
    nout = s.get("ledwiz_outputs", 9) if len(toys) == 1 else len(toys)
    lines = ["    <LedWizEquivalent>", _el("Name", "LedWizEquivalent %d" % num), "      <Outputs>"]
    for i in range(1, nout + 1):
        # un seul toy (matrice) : toutes les sorties le visent ; plusieurs (rubans) : une sortie par toy
        nom = toys[0]["name"] if len(toys) == 1 else toys[i - 1]["name"]
        lines += ["        <LedWizEquivalentOutput>",
                  "          <OutputName>%s</OutputName>" % nom,
                  "          <LedWizEquivalentOutputNumber>%d</LedWizEquivalentOutputNumber>" % i,
                  "        </LedWizEquivalentOutput>"]
    lines += ["      </Outputs>", _el("LedWizNumber", num), "    </LedWizEquivalent>"]
    return "\n".join(lines)


def gen(config):
    strips = _resoudre_ports(config.get("strips", []))
    controllers, toys = [], []
    for s in strips:
        ctype = s.get("controller", "TeensyStripController")
        controllers.append(_wemos_controller(s) if ctype == "WemosD1MPStripController" else _teensy_controller(s))
        for t in (s.get("toys") or [s["toy"]]):
            toys.append(_ledstrip_toy(s, t))
        toys.append(_ledwiz_equivalent(s))
    for a in config.get("artnet", []):
        controllers.append(_artnet(a))
    for p in config.get("pinone", []):
        controllers.append(_pinone(p))

    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<Cabinet xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">',
           "  <Name>%s</Name>" % config.get("name", "PinCabOS Cabinet"),
           "  <AutoConfigEnabled>%s</AutoConfigEnabled>" % ("true" if config.get("auto_config", True) else "false")]
    if controllers:
        out.append("  <OutputControllers>")
        out += controllers
        out.append("  </OutputControllers>")
    if toys:
        out.append("  <Toys>")
        out += toys
        out.append("  </Toys>")
    out.append("</Cabinet>")
    return "\n".join(out) + "\n"


SAMPLE = {
    "name": "PinCabOS Cabinet",
    "auto_config": True,
    "_commentaire": "auto_config=true laisse DOF détecter DudesCab/LedWiz/Pinscape/Pac. Ci-dessous seulement les strips adressables + ArtNet/PinOne.",
    "strips": [{
        "controller": "TeensyStripController",
        "name": "TeensyStripController 1",
        "com_port": "auto",
        "baud": 9600,
        "leds_per_strip": [512, 512, 512, 512, 256, 0, 0, 0],
        "test_on_connect": False,
        "toy": {
            "name": "Backboard HD",
            "width": 144, "height": 16,
            "arrangement": "TopDownAlternateLeftRight",
            "color_order": "GRB",
            "first_led": 1, "brightness": 25, "fading_curve": "Linear"
        },
        "ledwiz_number": 30,
        "ledwiz_outputs": 9
    }],
    "artnet": [],
    "pinone": []
}


def _ask(prompt, default):
    if not sys.stdin.isatty():
        return default
    try:
        v = input("%s [%s]: " % (prompt, default)).strip()
        return v if v else default
    except EOFError:
        return default


def cmd_wizard(config_out, xml_out):
    d = detect()
    print("Contrôleurs DOF détectés :")
    for e in d:
        ac = {True: "AutoConfig (rien à déclarer)", False: "à déclarer", None: "?"}[e["auto_config"]]
        print("  - %-13s %s [%s]" % (e["dev"], e["kind"], ac))
    strips_hw = [e for e in d if e["auto_config"] is False and "Teensy" in e["kind"]]
    cfg = {"name": _ask("Nom du cabinet", "PinCabOS Cabinet"), "auto_config": True,
           "strips": [], "artnet": [], "pinone": []}
    if not strips_hw:
        print("Aucun strip adressable (Teensy) détecté → cabinet.xml = AutoConfig seul.")
    for i, e in enumerate(strips_hw, 1):
        print("--- Strip adressable #%d (%s) ---" % (i, e["dev"]))
        leds = []
        for o in range(1, 9):
            dflt = "512" if o <= 4 else ("256" if o == 5 else "0")
            leds.append(int(_ask("  LEDs sur la sortie %d (0=aucune)" % o, dflt)))
        toyname = _ask("  Nom du toy", "Backboard HD")
        w = int(_ask("  Largeur matrice (LEDs)", "144"))
        h = int(_ask("  Hauteur matrice (LEDs)", "16"))
        arr = _ask("  Arrangement (cf. 'arrangements')", "TopDownAlternateLeftRight")
        co = _ask("  Ordre couleur", "GRB")
        br = int(_ask("  Luminosité 1-100 (garder BAS = courant)", "25"))
        lwn = int(_ask("  Numéro LedWiz équivalent", "30"))
        lwo = int(_ask("  Nb de sorties LedWiz équiv.", "9"))
        cfg["strips"].append({
            "controller": "TeensyStripController", "name": "TeensyStripController %d" % i,
            "com_port": "auto", "baud": 9600, "leds_per_strip": leds, "test_on_connect": False,
            "toy": {"name": toyname, "width": w, "height": h, "arrangement": arr,
                    "color_order": co, "first_led": 1, "brightness": br, "fading_curve": "Linear"},
            "ledwiz_number": lwn, "ledwiz_outputs": lwo})
    json.dump(cfg, open(config_out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    open(xml_out, "w", encoding="utf-8").write(gen(cfg))
    print("config     : %s" % config_out)
    print("cabinet.xml: %s" % xml_out)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "detect":
        d = detect()
        if "--json" in a:
            print(json.dumps(d, indent=2))
        else:
            for e in d:
                ac = {True: "AutoConfig", False: "à déclarer", None: "?"}[e["auto_config"]]
                print("  %-14s vid=%s  %-30s -> %s [%s]" % (e["dev"], e["vid"], e["model"][:30], e["kind"], ac))
            if not d:
                print("  aucun contrôleur DOF détecté")
    elif cmd == "gen":
        cfg = json.load(open(a[1], encoding="utf-8"))
        xml = gen(cfg)
        if len(a) > 2:
            open(a[2], "w", encoding="utf-8").write(xml)
            print("cabinet.xml écrit : %s" % a[2])
        else:
            sys.stdout.write(xml)
    elif cmd == "wizard":
        cmd_wizard(a[1], a[2])
    elif cmd == "sample":
        out = json.dumps(SAMPLE, indent=2, ensure_ascii=False)
        if len(a) > 1:
            open(a[1], "w", encoding="utf-8").write(out)
            print("exemple écrit : %s" % a[1])
        else:
            print(out)
    elif cmd == "arrangements":
        print("\n".join(ADDRESSABLE_ARRANGEMENTS))
        print("--- color orders ---")
        print(" ".join(COLOR_ORDERS))
    else:
        sys.exit("commande inconnue: " + cmd)


if __name__ == "__main__":
    main()
