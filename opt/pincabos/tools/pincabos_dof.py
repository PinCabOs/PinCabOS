"""DOF du cab : cartes de sortie détectées, activation, application au premier démarrage.

PINCABOS_DOF_MODULE_V1

Détection par l'outil dof-cabinet (identifiants USB des contrôleurs : DudesCab,
LedWiz, Pinscape, Ultimarc, Teensy et Wemos pour les rubans adressables).
L'installeur enregistre le choix « DOF activé » et les cartes vues dans
/opt/pincabos/config/dof/installer.json ; le premier démarrage pose les deux
interrupteurs que PinCabOS connaît : [Plugin.DOF] Enable de VPinballX.ini et
[DOF] enabledof de vpinfe.ini. Les toys carte par carte viennent à l'étape
Toys / LED (lot 2c) et sur la page /dof/hardware du cab.
"""
from __future__ import annotations

import glob
import importlib.util
import json
import re
try:
    import pincabos_ini
except ImportError:   # hors /opt (tests, depot) : le module vit a cote des outils
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    import pincabos_ini
import os
import shutil
from datetime import datetime
from pathlib import Path

OUTIL = Path("/opt/pincabos/tools/dof-cabinet/dof-cabinet.py")
CONFIG = Path("/opt/pincabos/config/dof/installer.json")
VPX_INI = Path("/home/pinball/.pincabos/vpx/VPinballX.ini")
VPINFE_INI = Path("/home/pinball/.config/vpinfe/vpinfe.ini")

_outil = None


def outil(chemin: Path = OUTIL):
    """Le module dof-cabinet.py chargé une fois (None s'il manque)."""
    global _outil
    if _outil is not None:
        return _outil
    if not chemin.is_file():
        return None
    spec = importlib.util.spec_from_file_location("pincabos_dofcab_outil", str(chemin))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _outil = mod
    return mod


def detecter(mod=None) -> list:
    mod = mod or outil()
    if mod is None:
        return []
    try:
        return [d for d in mod.detect() if isinstance(d, dict)]
    except Exception:
        return []


def resume(detectes: list) -> list:
    """Une ligne lisible par carte, et si DOF sait la configurer seul."""
    out = []
    for d in detectes:
        out.append({
            "dev": d.get("dev", ""), "kind": d.get("kind", ""), "model": d.get("model", ""),
            "serial": d.get("serial", ""), "vid": d.get("vid", ""),
            "auto_config": bool(d.get("auto_config")),
            "strip": d.get("auto_config") is False,          # Teensy / Wemos : rubans a declarer (lot 2c)
        })
    return out


def proposer(detectes: list) -> dict:
    return {"enabled": bool(detectes)}


def valider(choix) -> tuple[list, dict]:
    if not isinstance(choix, dict):
        return ["choix DOF invalide"], {}
    return [], {"enabled": bool(choix.get("enabled"))}


def config_json(choix: dict, detectes: list) -> dict:
    return {"enabled": bool(choix.get("enabled")), "detected": resume(detectes),
            "written_at": datetime.now().isoformat(timespec="seconds"), "source": "PinCabOS installer"}


# ---------------------------------------------------------------- interrupteurs
def poser_cle_ini(texte: str, section: str, cle: str, valeur: str) -> str:
    """Pose `cle = valeur` dans [section] (créée en fin de fichier si absente), sans rien d'autre.
    PINCABOS_INI_UNIQUE_V1 : délégué à l'écrivain INI unique."""
    ini = pincabos_ini.Ini(texte)
    ini.poser(section, cle, valeur)
    return ini.texte()


def appliquer_premier_demarrage(cfg: dict, vpx_ini: Path = VPX_INI, vpinfe_ini: Path = VPINFE_INI) -> list:
    actif = bool(cfg.get("enabled"))
    journal = []
    for chemin, section, cle, val in ((vpx_ini, "Plugin.DOF", "Enable", "1" if actif else "0"),
                                      (vpinfe_ini, "DOF", "enabledof", "true" if actif else "false")):
        if not chemin.is_file():
            journal.append(f"{chemin.name} absent, rien écrit")
            continue
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        nouveau = poser_cle_ini(texte, section, cle, val)
        if nouveau != texte:
            chemin.write_text(nouveau, encoding="utf-8")
        journal.append(f"{chemin.name} : [{section}] {cle} = {val}")
    return journal


def charger(chemin: Path = CONFIG) -> dict:
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ======================================================================
# PINCABOS_INSTALLEUR_TOYS_V1 — étape Toys / LED de l'assistant
#
# Les cartes de sortie « AutoConfig » (DudesCab, LedWiz, Pinscape, Ultimarc)
# sont prises en charge par DOF sans déclaration. Les contrôleurs de rubans
# adressables (Teensy, Wemos) doivent être déclarés : soit une MATRICE
# (backboard : largeur × hauteur, arrangement, ordre des couleurs), soit des
# RUBANS (un toy LedStrip par sortie utilisée). Le tout devient l'inventaire
# de la page /dof/hardware du cab (hardware-inventory.json) et, au premier
# démarrage, le cabinet.xml généré par dof-cabinet.
# ======================================================================
INVENTAIRE = Path("/opt/pincabos/config/dof/hardware-inventory.json")
CABINETS_GLOB = "/home/pinball/.local/share/VPinballX/*/directoutputconfig"
SAUVEGARDES = Path("/opt/pincabos/backups/dof-cabinet")
ARRANGEMENTS = (
    "LeftRightTopDown", "LeftRightBottomUp", "RightLeftTopDown", "RightLeftBottomUp",
    "TopDownLeftRight", "TopDownRightLeft", "BottomUpLeftRight", "BottomUpRightLeft",
    "LeftRightAlternateTopDown", "LeftRightAlternateBottomUp",
    "RightLeftAlternateTopDown", "RightLeftAlternateBottomUp",
    "TopDownAlternateLeftRight", "TopDownAlternateRightLeft",
    "BottomUpAlternateLeftRight", "BottomUpAlternateRightLeft",
)
ORDRES_COULEUR = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")
MODES = ("matrice", "rubans")
MAX_SORTIES = 10
MAX_LEDS_SORTIE = 1100


def type_controleur(d: dict) -> str | None:
    """TeensyStripController / WemosD1MPStripController pour une carte « à déclarer », sinon None."""
    if d.get("auto_config") is not False:
        return None
    kind = (d.get("kind") or "").lower()
    if "teensy" in kind:
        return "TeensyStripController"
    if "wemos" in kind or "esp" in kind:
        return "WemosD1MPStripController"
    return None


def controleurs_de_rubans(detectes: list) -> list:
    out = []
    for d in detectes:
        t = type_controleur(d)
        if t:
            out.append({"serial": d.get("serial", ""), "dev": d.get("dev", ""), "type": t, "kind": d.get("kind", "")})
    return out


def cartes_auto(detectes: list) -> list:
    return [{"dev": d.get("dev", ""), "kind": d.get("kind", ""), "serial": d.get("serial", "")}
            for d in detectes if d.get("auto_config") is True]


def repartir(total: int, par_sortie: int = 512) -> list:
    """Découpe une matrice en sorties pleines (144×16 = 2304 → 512,512,512,512,256)."""
    total = max(0, int(total))
    out = []
    while total > 0 and len(out) < MAX_SORTIES:
        n = min(par_sortie, total)
        out.append(n)
        total -= n
    return out


def proposer_toys(detectes: list) -> dict:
    """Premier contrôleur = backboard (matrice 144×16, le cas courant), les suivants = rubans."""
    ctrls = []
    for i, c in enumerate(controleurs_de_rubans(detectes)):
        base = {"serial": c["serial"], "type": c["type"], "enabled": True, "ledwiz_number": 30 + i,
                "brightness": 25, "color_order": "GRB"}
        if i == 0:
            base.update({"mode": "matrice", "width": 144, "height": 16, "arrangement": "TopDownAlternateLeftRight",
                         "strips": repartir(144 * 16)})
        else:
            base.update({"mode": "rubans", "width": 0, "height": 0, "arrangement": "LeftRightTopDown", "strips": [144]})
        ctrls.append(base)
    return {"controllers": ctrls}


def _entier(v, defaut, lo, hi):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return defaut, False
    return n, lo <= n <= hi


def valider_toys(choix, detectes: list) -> tuple[list, dict]:
    erreurs = []
    if not isinstance(choix, dict) or not isinstance(choix.get("controllers"), list):
        return ["choix Toys invalide"], {}
    connus = {c["serial"]: c for c in controleurs_de_rubans(detectes)}
    ok = []
    for i, c in enumerate(choix["controllers"]):
        if not isinstance(c, dict):
            erreurs.append(f"contrôleur {i + 1} : forme invalide"); continue
        serial = str(c.get("serial") or "")
        if serial not in connus:
            erreurs.append(f"contrôleur {i + 1} : carte inconnue ({serial or 'sans numéro de série'})"); continue
        mode = str(c.get("mode") or "matrice")
        if mode not in MODES:
            erreurs.append(f"contrôleur {i + 1} : mode inconnu {mode}"); continue
        strips = c.get("strips") if isinstance(c.get("strips"), list) else []
        strips_ok = []
        for s in strips[:MAX_SORTIES]:
            n, bon = _entier(s, -1, 0, MAX_LEDS_SORTIE)
            if not bon:
                erreurs.append(f"contrôleur {i + 1} : LEDs par sortie hors de 0..{MAX_LEDS_SORTIE}"); break
            strips_ok.append(n)
        prop = {"serial": serial, "type": connus[serial]["type"], "enabled": bool(c.get("enabled", True)), "mode": mode,
                "strips": strips_ok}
        prop["ledwiz_number"], bon = _entier(c.get("ledwiz_number", 30 + i), 30 + i, 1, 128)
        if not bon:
            erreurs.append(f"contrôleur {i + 1} : numéro LedWiz hors de 1..128")
        prop["brightness"], bon = _entier(c.get("brightness", 25), 25, 1, 100)
        if not bon:
            erreurs.append(f"contrôleur {i + 1} : luminosité hors de 1..100")
        prop["color_order"] = str(c.get("color_order") or "GRB")
        if prop["color_order"] not in ORDRES_COULEUR:
            erreurs.append(f"contrôleur {i + 1} : ordre des couleurs inconnu")
        prop["arrangement"] = str(c.get("arrangement") or "TopDownAlternateLeftRight")
        if prop["arrangement"] not in ARRANGEMENTS:
            erreurs.append(f"contrôleur {i + 1} : arrangement inconnu")
        if mode == "matrice":
            prop["width"], b1 = _entier(c.get("width", 144), 144, 1, 1024)
            prop["height"], b2 = _entier(c.get("height", 16), 16, 1, 1024)
            if not (b1 and b2):
                erreurs.append(f"contrôleur {i + 1} : dimensions de matrice hors de 1..1024")
            elif prop["enabled"] and sum(strips_ok) != prop["width"] * prop["height"]:
                erreurs.append(f"contrôleur {i + 1} : {sum(strips_ok)} LEDs sur les sorties pour une matrice de {prop['width']}×{prop['height']} = {prop['width'] * prop['height']}")
        else:
            prop["width"], prop["height"] = 0, 0
            if prop["enabled"] and not any(strips_ok):
                erreurs.append(f"contrôleur {i + 1} : aucun ruban déclaré")
        ok.append(prop)
    return erreurs, {"controllers": ok}


def inventaire_json(choix: dict, detectes: list) -> dict:
    """Le hardware-inventory.json de la page /dof/hardware, un équipement par contrôleur."""
    par_serial = {c["serial"]: c for c in controleurs_de_rubans(detectes)}
    devices = []
    for i, c in enumerate(choix.get("controllers", [])):
        t = c["type"]
        d = {"id": f"{t.lower()}-{c['serial']}", "source": "detected", "type": t,
             "label": f"{t} {i + 1}", "enabled": bool(c["enabled"]), "serial": c["serial"], "com_port": "auto",
             "host": "", "leds_per_strip": (list(c["strips"]) + [0] * MAX_SORTIES)[:MAX_SORTIES],
             "ledwiz_number": c["ledwiz_number"]}
        if c["mode"] == "matrice":
            d["toy"] = {"name": "Backboard HD" if i == 0 else f"Matrice {i + 1}", "width": c["width"], "height": c["height"],
                        "arrangement": c["arrangement"], "color_order": c["color_order"], "first_led": 1,
                        "brightness": c["brightness"], "fading_curve": "Linear"}
            d["ledwiz_outputs"] = 9
        else:
            toys, premier, k = [], 1, 0
            for s in c["strips"]:
                if s > 0:
                    k += 1
                    toys.append({"name": f"Ruban {i + 1}.{k}", "width": s, "height": 1, "arrangement": "LeftRightTopDown",
                                 "color_order": c["color_order"], "first_led": premier, "brightness": c["brightness"],
                                 "fading_curve": "Linear"})
                premier += s
            d["toys"] = toys
            d["toy"] = toys[0] if toys else None
            d["ledwiz_outputs"] = max(1, len(toys))
        d["dev"] = par_serial.get(c["serial"], {}).get("dev", "")
        devices.append(d)
    return {"cab_name": "PinCabOS Cabinet", "auto_config": True, "devices": devices,
            "source": "PinCabOS installer", "updated_at": datetime.now().isoformat(timespec="seconds")}


def config_dof_cabinet(inv: dict) -> dict:
    """Config déclarative dof-cabinet depuis les équipements ACTIFS (même règle que la page du cab)."""
    cfg = {"name": inv.get("cab_name") or "PinCabOS Cabinet", "auto_config": bool(inv.get("auto_config", True)),
           "strips": [], "artnet": [], "pinone": []}
    for d in inv.get("devices", []):
        if not d.get("enabled"):
            continue
        t = d.get("type")
        if t in ("TeensyStripController", "WemosD1MPStripController"):
            strip = {"controller": t, "name": d.get("label") or f"{t} 1", "com_port": d.get("com_port") or "auto",
                     "serial": d.get("serial") or "", "baud": 9600,
                     "leds_per_strip": d.get("leds_per_strip") or [0] * MAX_SORTIES, "test_on_connect": False,
                     "toy": d.get("toy") or {"name": "Backboard", "width": 144, "height": 16, "arrangement": "TopDownAlternateLeftRight",
                                             "color_order": "GRB", "first_led": 1, "brightness": 25, "fading_curve": "Linear"},
                     "ledwiz_number": int(d.get("ledwiz_number") or 30), "ledwiz_outputs": int(d.get("ledwiz_outputs") or 9)}
            if d.get("toys"):
                strip["toys"] = d["toys"]
            cfg["strips"].append(strip)
        elif t == "ArtNet":
            a = {"name": d.get("label") or "ArtNet 1", "universe": int(d.get("universe") or 0)}
            if d.get("broadcast_address"):
                a["broadcast_address"] = d["broadcast_address"]
            cfg["artnet"].append(a)
        elif t == "PinOne":
            p = {"name": d.get("label") or "PinOne 1"}
            if d.get("com_port"):
                p["com_port"] = d["com_port"]
            cfg["pinone"].append(p)
    return cfg


def dossier_cabinet(motif: str = CABINETS_GLOB) -> Path | None:
    dossiers = sorted(glob.glob(motif))
    return Path(dossiers[-1]) if dossiers else None


# PINCABOS_DOF_GLOBALCONFIG_V1
# Cab de Yann, installation neuve 4.29 (06/09/2026) : cabinet.xml genere, Teensy
# declare, et pourtant « No cabinet config file loaded. Will use AutoConfig » dans
# VPX comme dans VPinFE. libdof ne lit cabinet.xml que si GlobalConfig_B2SServer.xml
# le designe ; sans lui il ne garde que ce qu'il detecte seul (DudesCab, LedWiz), et
# un controleur de rubans n'est pas detectable. Personne n'ecrivait ce fichier.
# VPX (PrefPath) et VPinFE lisent chacun leur dossier directoutputconfig : les deux
# recoivent cabinet.xml et son GlobalConfig. Chemins absolus : libdof ne connait pas
# de variable {GlobalConfigDir}.
GLOBAL_CONFIG = "GlobalConfig_B2SServer.xml"
DOSSIERS_DOF_SUPPLEMENTAIRES = (Path("/home/pinball/.pincabos/vpx/directoutputconfig"),)


def global_config_xml(dossier: Path) -> str:
    d = str(dossier)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<!-- PinCabOS (PINCABOS_DOF_GLOBALCONFIG_V1) : dit a DOF (libdof) ou sont cabinet.xml\n"
        "     et les directoutputconfig*.ini. Sans ce fichier DOF passe en AutoConfig et ignore\n"
        "     les controleurs de rubans (Teensy, Wemos) declares dans cabinet.xml. -->\n"
        "<GlobalConfig>\n"
        f"  <IniFilesPath>{d}</IniFilesPath>\n"
        f"  <CabinetConfigFilePattern>{d}/cabinet.xml</CabinetConfigFilePattern>\n"
        "  <EnableLogging>true</EnableLogging>\n"
        "  <ClearLogOnSessionStart>true</ClearLogOnSessionStart>\n"
        f"  <LogFilePattern>{d}/DirectOutput.log</LogFilePattern>\n"
        "</GlobalConfig>\n"
    )


def _meme_proprietaire(fichier: Path, dossier: Path) -> None:
    try:
        st = dossier.stat()
        os.chown(fichier, st.st_uid, st.st_gid)
    except OSError:
        pass


def poser_global_config(dossier: Path, sauvegardes: Path = SAUVEGARDES) -> str:
    """GlobalConfig_B2SServer.xml a cote de cabinet.xml. Un fichier qui designe deja un
    cabinet.xml (reglage de l'utilisateur) est garde ; un autre est sauvegarde puis remplace."""
    gc = dossier / GLOBAL_CONFIG
    if gc.is_file():
        texte = gc.read_text(encoding="utf-8", errors="replace")
        if "<CabinetConfigFilePattern>" in texte and "cabinet.xml" in texte:
            return f"GlobalConfig DOF en place : {gc}"
        sauvegardes.mkdir(parents=True, exist_ok=True)
        copie = sauvegardes / (GLOBAL_CONFIG + ".bak-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        copie.write_bytes(gc.read_bytes())
    gc.write_text(global_config_xml(dossier), encoding="utf-8")
    _meme_proprietaire(gc, dossier)
    return f"GlobalConfig DOF pose : {gc}"


def propager_cabinet(dossier: Path, sauvegardes: Path = SAUVEGARDES,
                     supplementaires: tuple = DOSSIERS_DOF_SUPPLEMENTAIRES) -> list:
    """cabinet.xml de `dossier` copie dans les autres dossiers DOF existants (PrefPath de VPX),
    et GlobalConfig_B2SServer.xml pose partout ou il y a un cabinet.xml."""
    journal = [poser_global_config(dossier, sauvegardes)]
    cab = dossier / "cabinet.xml"
    for autre in supplementaires:
        autre = Path(autre)
        if not autre.is_dir() or autre.resolve() == dossier.resolve():
            continue
        cible = autre / "cabinet.xml"
        if cab.is_file() and (not cible.is_file() or cible.read_bytes() != cab.read_bytes()):
            if cible.is_file():
                sauvegardes.mkdir(parents=True, exist_ok=True)
                copie = sauvegardes / ("cabinet.xml.bak-" + autre.parent.parent.name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
                copie.write_bytes(cible.read_bytes())
            shutil.copyfile(cab, cible)
            _meme_proprietaire(cible, autre)
            journal.append(f"cabinet.xml copie : {cible}")
        if cible.is_file():
            journal.append(poser_global_config(autre, sauvegardes))
    return journal


def dossiers_dof(supplementaires: tuple = DOSSIERS_DOF_SUPPLEMENTAIRES) -> list:
    """Les dossiers directoutputconfig existants (VPinFE, PrefPath de VPX), sans doublon."""
    out = []
    for d in [dossier_cabinet()] + [Path(p) for p in supplementaires]:
        if d and d.is_dir() and d.resolve() not in [o.resolve() for o in out]:
            out.append(d)
    return out


def reparer_global_config(supplementaires: tuple = DOSSIERS_DOF_SUPPLEMENTAIRES, sauvegardes: Path = SAUVEGARDES) -> list:
    """Doctor / CLI : chaque dossier DOF qui a un cabinet.xml recoit son GlobalConfig."""
    journal = []
    for d in dossiers_dof(supplementaires):
        if (d / "cabinet.xml").is_file():
            journal.append(poser_global_config(d, sauvegardes))
    return journal or ["aucun cabinet.xml : rien a faire (AutoConfig DOF)"]


def appliquer_toys_premier_demarrage(inv: dict, inventaire: Path = INVENTAIRE, dossier: Path | None = None,
                                     sauvegardes: Path = SAUVEGARDES, mod=None,
                                     supplementaires: tuple = DOSSIERS_DOF_SUPPLEMENTAIRES) -> list:
    """Pose l'inventaire de la page DOF et, s'il y a un contrôleur de rubans actif, le cabinet.xml."""
    journal = []
    inventaire.parent.mkdir(parents=True, exist_ok=True)
    inventaire.write_text(json.dumps(inv, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    journal.append(f"inventaire écrit : {inventaire} ({len(inv.get('devices', []))} équipement(s))")
    cfg = config_dof_cabinet(inv)
    if not cfg["strips"]:
        journal.append("aucun contrôleur de rubans actif : cabinet.xml inchangé (AutoConfig DOF)")
        return journal
    mod = mod or outil()
    if mod is None:
        journal.append("outil dof-cabinet absent : cabinet.xml non généré")
        return journal
    dossier = dossier or dossier_cabinet()
    if dossier is None:
        journal.append("dossier directoutputconfig introuvable : cabinet.xml non généré")
        return journal
    dossier.mkdir(parents=True, exist_ok=True)
    cab = dossier / "cabinet.xml"
    if cab.exists():
        sauvegardes.mkdir(parents=True, exist_ok=True)
        copie = sauvegardes / ("cabinet.xml.bak-installer-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        copie.write_bytes(cab.read_bytes())
        journal.append(f"ancien cabinet.xml sauvegardé : {copie}")
    cab.write_text(mod.gen(cfg), encoding="utf-8")
    _meme_proprietaire(cab, dossier)
    journal.append(f"cabinet.xml généré : {cab} ({len(cfg['strips'])} contrôleur(s) de rubans)")
    # PINCABOS_DOF_GLOBALCONFIG_V1 : sans GlobalConfig, DOF n'aurait jamais lu ce cabinet.xml
    journal += propager_cabinet(dossier, sauvegardes, supplementaires)
    return journal
