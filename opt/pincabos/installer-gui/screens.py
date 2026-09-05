#!/usr/bin/env python3
"""Étape « Écrans » de l'assistant d'installation (PINCABOS_INSTALLEUR_ECRANS_V1).

La session d'installation voit le même matériel que le système installé :
même noyau, mêmes pilotes, mêmes noms de sorties, mêmes EDID. On règle donc
les écrans ici, une fois, et le premier démarrage arrive déjà configuré :

  1. découverte par xrandr (géométrie, mode natif, empreinte EDID) ;
  2. chaque dalle affiche son numéro (identify.py, fenêtres GTK) ;
  3. le propriétaire attribue les rôles : playfield, backglass, DMD, topper ;
  4. le sens du playfield est appliqué tout de suite par xrandr : il voit ;
  5. le résultat est écrit au format de /opt/pincabos/config/screens/screens.json,
     celui que lisent la topologie au boot (rôles par EDID), la rotation
     physique (lot 0), VPinFE, VPX et le splash.

Aucune dépendance Flask : testable avec de vraies sorties xrandr.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROLES = ("playfield", "backglass", "fulldmd", "topper")
ROTATIONS = (0, 90, 180, 270)
XRANDR_ROTATE = {0: "normal", 90: "right", 180: "inverted", 270: "left"}
ROTATE_XRANDR = {v: k for k, v in XRANDR_ROTATE.items()}
# code « orient » historique de l'installateur (fbcon / splash) : 1 paysage, 2 = 90° horaire, 3 = 90° antihoraire, 4 = 180°
ORIENT_CODE = {0: "1", 90: "2", 270: "3", 180: "4"}
DISPLAY = os.environ.get("PCO_KIOSK_DISPLAY", ":1")
IDENTIFY = Path(__file__).resolve().parent / "identify.py"


def executer(args, timeout=20):
    env = dict(os.environ, DISPLAY=DISPLAY)
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"commande absente : {args[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "délai dépassé"


# ---------------------------------------------------------------- xrandr
LIGNE_SORTIE = re.compile(
    r"^(?P<name>\S+) (?P<state>connected|disconnected)(?P<primary> primary)?"
    r"(?: (?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+))?(?: \([^)]*\))?(?: (?P<rot>normal|left|inverted|right))?"
)
LIGNE_MODE = re.compile(r"^\s+(?P<w>\d+)x(?P<h>\d+)(?:i)?\s+(?P<rates>.*)$")


def parse_query(texte: str) -> list:
    """Sorties de `xrandr --query` : géométrie active, rotation, modes, mode préféré."""
    sorties, courante = [], None
    for ligne in texte.splitlines():
        m = LIGNE_SORTIE.match(ligne)
        if m:
            d = m.groupdict()
            courante = {
                "name": d["name"], "connected": d["state"] == "connected", "primary": bool(d["primary"]),
                "width": int(d["w"]) if d["w"] else 0, "height": int(d["h"]) if d["h"] else 0,
                "x": int(d["x"]) if d["x"] else 0, "y": int(d["y"]) if d["y"] else 0,
                "rotation": ROTATE_XRANDR.get(d["rot"] or "normal", 0), "modes": [], "preferred": "", "raw": ligne.strip(),
                "preferred_rate": "",
            }
            mm = re.search(r"(\d+)mm x (\d+)mm", ligne)
            courante["mm"] = (int(mm.group(1)), int(mm.group(2))) if mm else (0, 0)
            sorties.append(courante)
            continue
        m = LIGNE_MODE.match(ligne)
        if m and courante is not None:
            mode = f"{m.group('w')}x{m.group('h')}"
            rates = m.group("rates")
            if mode not in courante["modes"]:
                courante["modes"].append(mode)
            if "+" in rates and not courante["preferred"]:
                courante["preferred"] = mode
                # PINCABOS_INSTALLEUR_CADENCE_V1 : la cadence marquee « + » (preferee EDID),
                # sinon la premiere ; sans elle, le cab tirait 23,98 Hz sur un backglass.
                m_rate = re.search(r"(\d+(?:\.\d+)?)[*]?\+", rates)
                courante["preferred_rate"] = m_rate.group(1) if m_rate else (re.findall(r"\d+(?:\.\d+)?", rates) or [""])[0]
    for s in sorties:
        if not s["preferred"] and s["modes"]:
            s["preferred"] = s["modes"][0]
    return sorties


def parse_edids(texte: str) -> dict:
    """{sortie: sha256(EDID)} depuis `xrandr --prop` ou `--verbose` (même règle que la topologie)."""
    result = {}
    for chunk in re.split(r"(?m)^(?=\S+\s+(?:connected|disconnected)\b)", texte):
        m = re.match(r"^(\S+)\s+(?:connected|disconnected)\b", chunk)
        if not m:
            continue
        edid = re.search(r"(?ms)^\s*EDID:\s*$\n((?:\s*[0-9A-Fa-f]{32}\s*\n)+)", chunk)
        if not edid:
            continue
        hexdata = re.sub(r"\s+", "", edid.group(1))
        if len(hexdata) >= 256:
            result[m.group(1)] = hashlib.sha256(bytes.fromhex(hexdata)).hexdigest()
    return result


def moniteurs(query: str, props: str) -> list:
    """Sorties connectées et allumées, dans l'ordre où X les déclare (identifiant VPinFE)."""
    edids = parse_edids(props)
    out = []
    for s in parse_query(query):
        if not s["connected"]:
            continue
        w, h = s["width"], s["height"]
        if not w or not h:
            # connectée mais éteinte : on prend le mode préféré, position à la suite
            if not s["preferred"]:
                continue
            w, h = (int(v) for v in s["preferred"].split("x"))
        out.append({
            "app_index": len(out), "name": s["name"], "x": s["x"], "y": s["y"], "width": w, "height": h,
            "area": w * h, "is_primary": s["primary"], "raw": s["raw"], "rotation": s["rotation"],
            "preferred": s["preferred"] or f"{w}x{h}", "preferred_rate": s.get("preferred_rate", ""), "modes": s["modes"], "mm": s["mm"],
            "edid_sha256": edids.get(s["name"], f"connector:{s['name']}"),
        })
    return out


def decouvrir(run=executer) -> list:
    rc, query, err = run(["xrandr", "--query"])
    if rc != 0:
        raise RuntimeError(f"xrandr indisponible sur {DISPLAY} : {err.strip() or rc}")
    _, props, _ = run(["xrandr", "--prop"])
    return moniteurs(query, props)


# ---------------------------------------------------------------- proposition de rôles
def proposer_roles(monitors: list) -> dict:
    """Playfield = la plus grande dalle ; un écran très allongé = DMD ; puis
    backglass ; le quatrième = topper. Le propriétaire corrige dans la page."""
    roles = {r: "" for r in ROLES}
    if not monitors:
        return roles
    tri = sorted(monitors, key=lambda m: (-m["area"], m["x"], m["name"]))
    roles["playfield"] = tri[0]["name"]
    reste = tri[1:]
    dmd = next((m for m in reste if m["height"] and m["width"] / m["height"] >= 3.0), None)
    if dmd:
        roles["fulldmd"] = dmd["name"]
        reste = [m for m in reste if m["name"] != dmd["name"]]
    if reste:
        roles["backglass"] = reste[0]["name"]
        reste = reste[1:]
    if reste and not roles["fulldmd"]:
        roles["fulldmd"] = reste[0]["name"]
        reste = reste[1:]
    if reste:
        roles["topper"] = reste[0]["name"]
    return roles


# PINCABOS_INSTALLEUR_CAB_USAGE_V1
# Le propriétaire déclare ce que son cab possède (backglass, full DMD, topper) ;
# les rôles proposés, la disposition et, en aval, les réglages d'affichage
# (disabled_roles des liaisons → topologie → VPX/VPinFE/DMD) en découlent.
USAGE_ROLES = tuple(r for r in ROLES if r != "playfield")


# PINCABOS_INSTALLEUR_MINIMUM_V1 (Yann, 05/09/2026) : le fonctionnement minimal
# d'un cab est playfield + backglass ; sans ces deux écrans, pas d'installation.
ROLES_MINIMUM = ("playfield", "backglass")


def usage_propose(roles: dict) -> dict:
    """Ce qui a reçu un écran est réputé utilisé ; le backglass l'est toujours (minimum)."""
    u = {r: bool(roles.get(r)) for r in USAGE_ROLES}
    u["backglass"] = True
    return u


def usage_depuis(a) -> dict | None:
    """La déclaration envoyée par la page ; None si absente ou mal formée."""
    u = a.get("usage") if isinstance(a, dict) else None
    if not isinstance(u, dict):
        return None
    return {r: bool(u.get(r)) for r in USAGE_ROLES}


def valider_usage(usage: dict, roles: dict) -> list:
    """Chaque rôle déclaré utilisé a un écran ; un rôle déclaré absent n'en a pas."""
    erreurs = []
    if not usage.get("backglass"):
        erreurs.append("backglass : obligatoire (fonctionnement minimal = playfield + backglass)")
    for role in USAGE_ROLES:
        attribue = bool(roles.get(role))
        if usage.get(role) and not attribue:
            erreurs.append(f"{role} : déclaré utilisé mais aucun écran attribué")
        if not usage.get(role) and attribue:
            erreurs.append(f"{role} : déclaré absent mais un écran lui est attribué")
    return erreurs


def valider_roles(roles: dict, monitors: list) -> list:
    """Erreurs : playfield obligatoire, sorties existantes, une sortie par rôle."""
    noms = {m["name"] for m in monitors}
    erreurs = []
    if not roles.get("playfield"):
        erreurs.append("le playfield est obligatoire")
    if not roles.get("backglass"):
        erreurs.append("le backglass est obligatoire (fonctionnement minimal = playfield + backglass)")
    vus = {}
    for role in ROLES:
        nom = roles.get(role) or ""
        if not nom:
            continue
        if nom not in noms:
            erreurs.append(f"{role} : sortie inconnue {nom}")
        if nom in vus:
            erreurs.append(f"{nom} ne peut pas être à la fois {vus[nom]} et {role}")
        vus[nom] = role
    return erreurs


# ---------------------------------------------------------------- disposition
def tourne(w: int, h: int, rot: int) -> tuple:
    return (h, w) if rot in (90, 270) else (w, h)


def mode_de(m: dict) -> tuple[int, int]:
    """Le mode à appliquer et à écrire : le mode NATIF de la dalle (préféré EDID).

    PINCABOS_INSTALLEUR_MODE_NATIF_V1 (Yann, cab 4K) : la session d'installation
    peut tourner en 1920x1080 sur une dalle 4K ; écrire ce mode courant aurait
    installé un cab en 1080p. Le préféré EDID est le natif. Sans préféré : le
    mode courant, côtés remis dans le sens de la dalle si elle est déjà tournée.
    """
    pref = m.get("preferred") or ""
    if "x" in pref:
        return tuple(int(v) for v in pref.split("x"))
    modes = m.get("modes") or []
    w, h = int(m.get("width") or 0), int(m.get("height") or 0)
    if w and h and modes and f"{w}x{h}" not in modes and f"{h}x{w}" in modes:
        return h, w
    return w, h


def disposition(monitors: list, roles: dict, rotation: int) -> dict:
    """Positions canoniques : playfield en 0,0, puis backglass, DMD et topper à sa
    droite, alignés en haut, avec la largeur du playfield telle que X la verra
    après rotation. Renvoie {sortie: {x, y, width, height, mode, rotation, primary}}."""
    par_nom = {m["name"]: m for m in monitors}
    ordre = [roles.get(r) for r in ROLES if roles.get(r)]
    out, x = {}, 0
    for i, nom in enumerate(ordre):
        m = par_nom[nom]
        w, h = mode_de(m)
        rot = rotation if nom == roles.get("playfield") else 0
        vw, vh = tourne(w, h, rot)
        out[nom] = {"x": x, "y": 0, "width": vw, "height": vh, "mode": f"{w}x{h}", "rotation": rot, "primary": i == 0}
        x += vw
    return out


def commande_xrandr(dispo: dict, eteindre: list = ()) -> list:
    cmd = ["xrandr"]
    for nom, d in dispo.items():
        cmd += ["--output", nom, "--mode", d["mode"], "--pos", f"{d['x']}x{d['y']}", "--rotate", XRANDR_ROTATE[d["rotation"]]]
        if d["primary"]:
            cmd.append("--primary")
    for nom in eteindre:
        cmd += ["--output", nom, "--off"]
    return cmd


LECTURES = (0, 90, 270)


def appliquer(monitors: list, roles: dict, rotation: int, run=executer, lecture: int = 0) -> dict:
    """Applique la disposition dans la session live (le propriétaire voit le résultat).

    PINCABOS_INSTALLEUR_LECTURE_V1 (Yann) : `rotation` est la rotation PHYSIQUE
    du playfield (0 ou 180), la seule écrite dans screens.json : VPX et VPinFE
    tournent la table eux-mêmes dans un écran X resté en paysage. `lecture`
    (0, 90, 270) tourne en plus la session d'installation pour que l'assistant
    se lise sur une dalle montée en portrait ; elle n'est jamais conservée.
    """
    erreurs = valider_roles(roles, monitors)
    if rotation not in ROTATIONS:
        erreurs.append(f"rotation invalide : {rotation}")
    if lecture not in LECTURES:
        erreurs.append(f"rotation de lecture invalide : {lecture}")
    if erreurs:
        return {"ok": False, "erreurs": erreurs}
    dispo = disposition(monitors, roles, (rotation + lecture) % 360)
    inutilises = [m["name"] for m in monitors if m["name"] not in dispo]
    cmd = commande_xrandr(dispo, inutilises)
    rc, out, err = run(cmd, timeout=30)
    if rc != 0:
        return {"ok": False, "erreurs": [f"xrandr : {err.strip() or out.strip() or rc}"], "commande": cmd}
    pointeurs = cadrer_pointeurs_absolus(roles["playfield"], run)
    return {"ok": True, "commande": cmd, "disposition": dispo, "pointeurs": pointeurs}


# PINCABOS_INSTALLEUR_POINTEUR_ABSOLU_V1
# Un pointeur absolu (écran tactile sur le playfield, tablette, souris
# « tablet » d'une VM) se répartit par défaut sur TOUT l'écran X ; dès que la
# disposition met deux dalles côte à côte, chaque clic tombe deux fois trop
# loin (vu en VM : plus aucun clic possible après l'application). On le cadre
# sur la dalle du playfield, la seule qu'on touche.
POINTEUR_ABSOLU = re.compile(r"(?i)tablet|touch|stylus|pen\b|wacom|elan|goodix|ilitek|egalax")


def pointeurs_absolus(liste_xinput: str) -> list:
    """Identifiants des pointeurs esclaves dont le nom dit « absolu » (xinput list --short)."""
    ids = []
    for ligne in liste_xinput.splitlines():
        if "slave" not in ligne or "pointer" not in ligne or "XTEST" in ligne:
            continue
        m = re.search(r"id=(\d+)", ligne)
        nom = ligne.split("id=")[0]
        if m and POINTEUR_ABSOLU.search(nom):
            ids.append(int(m.group(1)))
    return ids


def cadrer_pointeurs_absolus(sortie: str, run=executer) -> list:
    """xinput map-to-output <id> <sortie playfield> pour chaque pointeur absolu ; renvoie les ids cadrés."""
    rc, out, _ = run(["xinput", "list", "--short"], timeout=10)
    if rc != 0:
        return []
    cadres = []
    for ident in pointeurs_absolus(out):
        rc, _, _ = run(["xinput", "map-to-output", str(ident), sortie], timeout=10)
        if rc == 0:
            cadres.append(ident)
    return cadres


# ---------------------------------------------------------------- screens.json
def screens_json(monitors: list, roles: dict, rotation: int) -> dict:
    """Le fichier que lit tout PinCabOS, au schéma de la page Écran et de la topologie."""
    dispo = disposition(monitors, roles, rotation)
    par_nom = {m["name"]: m for m in monitors}
    data = {
        "mode": "installer",
        "source": "PinCabOS installer screens step",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "cabinet_mode": True,
        "playfield_orientation": "landscape",
        "playfield_rotation": str(rotation),
        "roles": {},
    }
    for role in ROLES:
        nom = roles.get(role) or ""
        if not nom or nom not in dispo:
            continue
        m, d = par_nom[nom], dispo[nom]
        data["roles"][role] = {"output": nom, "mode": d["mode"], "rate": str(m.get("preferred_rate") or "")}
        data[role] = {
            "name": nom, "output": nom, "x": d["x"], "y": d["y"], "width": d["width"], "height": d["height"],
            "area": d["width"] * d["height"], "is_primary": d["primary"], "raw": m["raw"],
            "edid_sha256": m["edid_sha256"], "geometry": f"{d['width']}x{d['height']}+{d['x']}+{d['y']}",
            "id": m["app_index"], "screen_id": m["app_index"], "available": True,
        }
    return data


def calibrations_json(data: dict) -> dict:
    """PINCABOS_INSTALLEUR_CALIBRATIONS_V1 : les rectangles FullDMD et DMD derives de la disposition.

    La topologie recopie ces rectangles (coordonnees X11 ABSOLUES) dans les
    INI de VPinFE et VPX. Sans eux, un cab neuf heritait de la calibration du
    cab source de l image (vu chez Yann : full DMD en 1016x619 sur le playfield).
    Full DMD = toute sa dalle ; DMD PinMAME = centre du full DMD (ratio 4:1,
    deux tiers de la largeur), sinon haut du backglass (moitie de la largeur).
    """
    def rect(role):
        e = data.get(role)
        return e if isinstance(e, dict) and e.get("width") and e.get("height") else None

    def dico(screen_id, x, y, w, h, note):
        return {"screen_id": str(screen_id), "x": int(x), "y": int(y), "width": int(w), "height": int(h),
                "geometry": f"{int(x)},{int(y)},{int(w)},{int(h)}", "geometry_x11": f"{int(w)}x{int(h)}+{int(x)}+{int(y)}",
                "note": note, "source": "PinCabOS installer screens step"}

    fd, bg = rect("fulldmd"), rect("backglass")
    out = {"fulldmd": None, "dmd": None}
    if fd:
        out["fulldmd"] = dico(fd["id"], fd["x"], fd["y"], fd["width"], fd["height"], "PinCabOS FullDMD visible area calibration")
        w = (fd["width"] * 2) // 3
        h = w // 4
        out["dmd"] = dico(fd["id"], fd["x"] + (fd["width"] - w) // 2, fd["y"] + (fd["height"] - h) // 2, w, h,
                          "PinCabOS DMD window (centre du full DMD)")
    elif bg:
        w = bg["width"] // 2
        h = w // 4
        out["dmd"] = dico(bg["id"], bg["x"] + (bg["width"] - w) // 2, bg["y"] + max(20, bg["height"] // 20), w, h,
                          "PinCabOS DMD window (haut du backglass)")
    return out


def bindings_json(data: dict) -> dict:
    """Liaisons rôle → empreinte EDID : la topologie retrouve les écrans même si
    les noms de sorties changent (autre port, autre pilote)."""
    return {
        "version": 1, "bound_at": data.get("updated_at", ""), "source": "PinCabOS installer screens step",
        "roles": {r: data[r]["edid_sha256"] for r in ROLES if isinstance(data.get(r), dict)},
        "disabled_roles": [r for r in ROLES if r != "playfield" and not isinstance(data.get(r), dict)],
    }


def code_orient(rotation: int) -> str:
    return ORIENT_CODE.get(int(rotation), "1")


# ---------------------------------------------------------------- identification
DECOR = Path(__file__).resolve().parent / "decor.py"
GALERIE_DECOR = Path("/opt/pincabos/media/splash")


def images_decor(monitors: list, roles: dict, galerie: Path = GALERIE_DECOR, tirage=None) -> dict:
    """PINCABOS_INSTALLEUR_DECOR_V1 : un visuel paysage de la galerie pour chaque dalle qui n'est pas le playfield."""
    import random
    paysages = sorted(p for p in galerie.glob("paysage*") if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not paysages:
        return {}
    tirage = tirage or random.Random()
    pf = roles.get("playfield") or ""
    out = {}
    for m in monitors:
        if m["name"] == pf:
            continue
        out[m["name"]] = str(tirage.choice(paysages))
    return out


def lancer_decor(monitors: list, roles: dict, run_dir: Path = Path("/run/pincabos")) -> dict:
    """Pose (ou repose) les fonds des dalles secondaires ; le precedent decor est arrete."""
    import signal
    import subprocess
    pid_file = run_dir / "decor.pid"
    try:
        os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    images = images_decor(monitors, roles)
    if not images or not DECOR.exists():
        return {"ok": False, "dalles": 0}
    env = dict(os.environ, DISPLAY=DISPLAY)
    p = subprocess.Popen(["python3", str(DECOR), "--monitors", json.dumps(images)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(p.pid), encoding="utf-8")
    return {"ok": True, "dalles": len(images), "images": images}


def identifier(monitors: list, roles: dict, secondes: int = 6, run=executer, libelles: dict | None = None) -> dict:
    """Affiche sur chaque dalle son numéro (1 = première sortie), son nom et son rôle."""
    libelles = libelles or {"playfield": "Playfield", "backglass": "Backglass", "fulldmd": "DMD", "topper": "Topper"}
    role_de = {nom: role for role, nom in roles.items() if nom}
    etiquettes = {m["name"]: {"number": m["app_index"] + 1, "role": libelles.get(role_de.get(m["name"], ""), "")}
                  for m in monitors}
    if not IDENTIFY.exists():
        return {"ok": False, "erreur": f"{IDENTIFY} absent"}
    rc, out, err = run(["python3", str(IDENTIFY), "--seconds", str(int(secondes)), "--labels", json.dumps(etiquettes)], timeout=int(secondes) + 10)
    return {"ok": rc == 0, "erreur": (err.strip() or out.strip()) if rc != 0 else "", "labels": etiquettes}


if __name__ == "__main__":
    import sys
    mons = decouvrir()
    roles = proposer_roles(mons)
    if "--json" in sys.argv:
        print(json.dumps({"monitors": mons, "roles": roles}, indent=2, ensure_ascii=False))
    else:
        for m in mons:
            print(f"{m['app_index'] + 1}. {m['name']:<8} {m['width']}x{m['height']}+{m['x']}+{m['y']} {'primary ' if m['is_primary'] else ''}rot={m['rotation']} edid={m['edid_sha256'][:12]}")
        print("proposition :", roles)
