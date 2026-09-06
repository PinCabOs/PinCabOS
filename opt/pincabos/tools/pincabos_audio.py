"""Son du cab : sorties ALSA, test, mode VPX, application au premier démarrage.

PINCABOS_AUDIO_MODULE_V1

Module importable par l'assistant d'installation (session live, root, ALSA
seul) et par le premier démarrage (PipeWire de la session pinball). Une seule
source de vérité, celle de la page Audio du cab : /opt/pincabos/config/audio-router.json
(clés playfield_device / backbox_device en identifiants ALSA hw:C,D). L'installeur
y ajoute une clé « installer » (mode Sound3D, volume, noms ALSA) que le premier
démarrage traduit en noms de sorties VPX (VPX nomme ses sorties comme PipeWire,
pas comme ALSA) et en volume de session.

Écrit dans VPinballX.ini les mêmes clés que la page Audio, avec le même
commentaire daté : [Player] SoundDeviceBG, SoundDevice, Sound3D.
"""
from __future__ import annotations

import json
import re
try:
    import pincabos_ini
except ImportError:   # hors /opt (tests, depot) : le module vit a cote des outils
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    import pincabos_ini
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

CONFIG = Path("/opt/pincabos/config/audio-router.json")
# PINCABOS_VPINFE_SON_APERCUS_V1 : le son des aperçus de tables dans VPinFE
VPINFE_INI = Path("/home/pinball/.config/vpinfe/vpinfe.ini")
MARQUEUR_SON_APERCUS = Path("/var/lib/pincabos/flags/vpinfe-son-apercus.done")
VPX_INI = Path("/home/pinball/.pincabos/vpx/VPinballX.ini")
VPX_LEGACY_INI = Path("/home/pinball/.local/share/VPinballX/10.8/VPinballX.ini")


def ini_squelette(texte: str) -> bool:
    """PINCABOS_VPX_PREF_REPARATION_V2 : l ini minimal ecrit par le premier demarrage (V2 du
    05/09) n a pas de section [Version] ; mais des que VPX a tourne dessus, il le reecrit en
    squelette complet ([Version] present, toutes les cles vides). Retex cab de Yann : BGSet et
    PlayfieldFullScreen vides = table en paysage, DOF absent, alors que le dossier complet
    attendait dans l ancien chemin. Un ini est un squelette si [Version] manque OU si ses cles
    cabinet n ont pas de valeur."""
    if "[Version]" not in texte:
        return True

    def vide(cle):
        return re.search(rf"(?m)^{cle}[ \t]*=[ \t]*\S", texte) is None
    return vide("BGSet") and vide("PlayfieldFullScreen")


def ini_complet(texte: str) -> bool:
    return "[Version]" in texte and not ini_squelette(texte)


def assurer_pref_vpx(vpx_ini: Path = VPX_INI, legacy_ini: Path = VPX_LEGACY_INI) -> str:
    """PINCABOS_VPX_PREF_MIGRATION_V1 : meme migration que VPXlauncher.pincabos-original.sh.

    Le lanceur deplace ~/.local/share/VPinballX/10.8 (ini complet du cab : mode
    cabinet, BGSet, DOF…) vers ~/.pincabos/vpx SEULEMENT si ce dossier n existe
    pas. Creer l ini nous-memes (V2, 05/09) l en empechait : VPX partait avec
    un ini minimal, table en paysage, DOF absent (retex cab de Yann). On fait
    donc la migration ici, a l identique, avant d ecrire nos cles.
    """
    pref, legacy = vpx_ini.parent, legacy_ini.parent
    if not pref.exists():
        pref.parent.mkdir(parents=True, exist_ok=True)
        if legacy.is_dir() and not legacy.is_symlink():
            shutil.move(str(legacy), str(pref))
            etat = "dossier VPX migre"
        else:
            pref.mkdir(parents=True, exist_ok=True)
            etat = "dossier VPX cree"
    else:
        etat = "dossier VPX present"
        # PINCABOS_VPX_PREF_REPARATION_V1 : un ini minimal (cree par la V2 du 05/09, sans
        # section [Version]) a cote d un dossier legacy complet -> on reprend le dossier
        # complet (ini, directoutputconfig...) et l ini minimal est garde en .minimal
        minimal = vpx_ini.is_file() and ini_squelette(vpx_ini.read_text(encoding="utf-8", errors="replace"))
        if minimal and legacy.is_dir() and not legacy.is_symlink() and legacy_ini.is_file() and ini_complet(legacy_ini.read_text(encoding="utf-8", errors="replace")):
            shutil.move(str(vpx_ini), str(vpx_ini) + ".minimal")
            for element in legacy.iterdir():
                cible = pref / element.name
                if cible.exists():
                    continue
                shutil.move(str(element), str(cible))
            shutil.rmtree(legacy, ignore_errors=True)
            etat = "dossier VPX repare depuis l ancien chemin (ini minimal ecarte)"
    # Lien de compatibilite ~/.local/share/VPinballX/10.8 -> ~/.pincabos/vpx, seulement
    # si ~/.local/share existe deja (jamais creer l arborescence d un autre compte :
    # la CI tourne sans /home/pinball et le mkdir y echouait en PermissionError).
    if not legacy.exists() and not legacy.is_symlink() and legacy.parent.parent.is_dir():
        try:
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.symlink_to(pref)
        except OSError:
            pass
    if not vpx_ini.is_file() and legacy_ini.is_file() and legacy_ini.resolve() != vpx_ini.resolve():
        shutil.copy2(legacy_ini, vpx_ini)
        etat += ", ini copie"
    return etat
FONCTION = "Audio SSF VPX Routing V2"          # même signature que la page Audio du cab
DEFAUTS = {
    "audio_mode": "dual", "audio_backend": "alsa", "backbox_device": "", "playfield_device": "",
    "surround_device": "", "bass_device": "", "ssf_mode": "7.1", "invert_lr": False,
    "invert_front_rear": False, "enable_bass": True, "night_mode": False,
}
# Intitulés VPinball : 4 et 5 sont des modes à six canaux, pas du 7.1.
SOUND3D = (
    ("0", "2 canaux, avant"), ("1", "2 canaux, arrière"),
    ("2", "jusqu'à 6 canaux, arrière au lockbar"), ("3", "jusqu'à 6 canaux, avant au lockbar"),
    ("4", "7.1 (8 canaux) : latéraux + arrière, avant = fronton, mixage historique"),
    ("5", "7.1 (8 canaux) : latéraux + arrière, avant = fronton, nouveau mixage (SSF)"),
)
APLAY_RE = re.compile(r"^(?:card|carte)\s+(\d+)\s*:\s*(.+?)\s+\[(.+?)\]\s*,\s*(?:device|périphérique|peripherique)\s+(\d+)\s*:\s*(.+?)\s+\[(.+?)\]", re.IGNORECASE)
HW_RE = re.compile(r"^hw:(\d+),(\d+)$")


def executer(args, timeout=20, **kw):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 99, str(exc)


# ---------------------------------------------------------------- détection
PILOTES = ("snd_hda_intel", "snd_usb_audio")


def charger_pilotes(run=executer, pilotes=PILOTES) -> list:
    """Charge les pilotes son absents (media d installation : snd_hda_intel est
    sur liste noire au demarrage). Best effort, attend que les cartes remontent."""
    charges = []
    for p in pilotes:
        rc, _ = run(["modprobe", p], timeout=20)
        if rc == 0:
            charges.append(p)
    if charges:
        import time
        time.sleep(1.5)
    return charges


def peripheriques_alsa(texte: str) -> list:
    """Sorties de `aplay -l` (anglais ou français)."""
    out = []
    for ligne in texte.splitlines():
        m = APLAY_RE.match(ligne.strip())
        if not m:
            continue
        card, card_short, card_name, dev, dev_short, dev_name = m.groups()
        out.append({
            "id": f"hw:{card},{dev}", "card": int(card), "device": int(dev),
            "card_name": card_name.strip(), "device_name": dev_name.strip(),
            "label": f"{card_name.strip()} · {dev_name.strip()}",
            "hdmi": "hdmi" in dev_name.lower() or "hdmi" in dev_short.lower(),
            "digital": "digital" in dev_name.lower() or "iec958" in dev_name.lower(),
        })
    return out


def detecter(run=executer) -> list:
    rc, out = run(["aplay", "-l"], env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
    return peripheriques_alsa(out) if rc == 0 else []


def proposer(devs: list) -> dict:
    """Première sortie analogique, sinon première HDMI, sinon la première ; backglass = la même."""
    choix = next((d for d in devs if not d["hdmi"] and not d["digital"]), None) \
        or next((d for d in devs if d["hdmi"]), None) or (devs[0] if devs else None)
    ident = choix["id"] if choix else ""
    return {"playfield": ident, "backbox": ident, "sound3d": "0", "volume": 70}


# ---------------------------------------------------------------- validation / config
def valider(choix, devs: list | None = None) -> tuple[list, dict]:
    erreurs = []
    if not isinstance(choix, dict):
        return ["choix audio invalide"], {}
    connus = {d["id"] for d in devs} if devs is not None else None
    ok = {}
    for cle in ("playfield", "backbox"):
        v = str(choix.get(cle) or "").strip()
        if v and not HW_RE.match(v):
            erreurs.append(f"{cle} : identifiant ALSA invalide {v}")
        elif v and connus is not None and v not in connus:
            erreurs.append(f"{cle} : sortie absente de la machine {v}")
        ok[cle] = v
    s3 = str(choix.get("sound3d", "0")).strip()
    if s3 not in {s for s, _ in SOUND3D}:
        erreurs.append(f"mode Sound3D inconnu {s3}")
    ok["sound3d"] = s3 if s3 in {s for s, _ in SOUND3D} else "0"
    try:
        vol = int(choix.get("volume", 70))
    except (TypeError, ValueError):
        vol = -1
    if not 0 <= vol <= 100:
        erreurs.append("volume hors de 0..100")
    ok["volume"] = max(0, min(100, vol))
    return erreurs, ok


def config_json(choix: dict, devs: list | None = None) -> dict:
    """Le audio-router.json de la cible (clés de la page Audio + section installer)."""
    par_id = {d["id"]: d for d in (devs or [])}
    cfg = dict(DEFAUTS)
    cfg["playfield_device"] = choix.get("playfield", "")
    cfg["backbox_device"] = choix.get("backbox", "") or choix.get("playfield", "")
    cfg["audio_mode"] = "dual" if cfg["backbox_device"] and cfg["backbox_device"] != cfg["playfield_device"] else "single"
    cfg["installer"] = {
        "sound3d": choix.get("sound3d", "0"), "volume": int(choix.get("volume", 70)),
        "playfield": par_id.get(cfg["playfield_device"], {}), "backbox": par_id.get(cfg["backbox_device"], {}),
        "written_at": datetime.now().isoformat(timespec="seconds"),
    }
    return cfg


# ---------------------------------------------------------------- test et volume (session live, ALSA)
def tester(ident: str, run=executer, canaux: int = 2) -> dict:
    if not HW_RE.match(ident or ""):
        return {"ok": False, "sortie": "identifiant ALSA invalide"}
    rc, out = run(["speaker-test", "-D", ident, "-c", str(canaux), "-t", "wav", "-l", "1"], timeout=40)
    return {"ok": rc == 0, "sortie": out.strip()[-300:]}


# PINCABOS_AUDIO_HP_UN_PAR_UN_V1 : ordre ALSA des canaux (speaker-test -s est 1-base)
CANAUX = {2: ["FL", "FR"], 4: ["FL", "FR", "RL", "RR"], 6: ["FL", "FR", "RL", "RR", "C", "LFE"],
          8: ["FL", "FR", "RL", "RR", "C", "LFE", "SL", "SR"]}
# PINCABOS_AUDIO_HP_CHMAP_V1 : sur un peripherique hw: brut, l ordre des canaux est celui du
# materiel ; en HDMI (CEA-861) c est FL FR LFE FC RL RR, et la voix « Rear Left » sortait du
# caisson (retex cab de Yann, GA104 HDMI : seul le Front Left etait coherent). La carte de
# canaux imposee a speaker-test (-m, noms ALSA : FC pour le centre) remet l ordre standard,
# comme PipeWire le fait pour VPX. Si le pilote la refuse, on rejoue sans.
CHMAP = {2: "FL,FR", 4: "FL,FR,RL,RR", 6: "FL,FR,RL,RR,FC,LFE", 8: "FL,FR,RL,RR,FC,LFE,SL,SR"}


def canaux_pour_mode(sound3d: str) -> int:
    """Nombre de canaux qu'exige le mode VPX : 2 en stereo (0, 1), 6 pour 2 et 3, 8 pour les
    modes 7.1 (4, 5 : effets avant sur les lateraux, arriere sur l arriere, fronton sur l avant).
    PINCABOS_AUDIO_71_V1 (retex cab de Yann : 3 paires + basses = 7.1, les lateraux n etaient
    meme pas sur le schema)."""
    s = str(sound3d)
    return 2 if s in ("0", "1") else 8 if s in ("4", "5") else 6


def tester_canal(ident: str, canaux: int, canal: int, run=executer) -> dict:
    """Joue la voix « Front Left »… sur UN haut-parleur : speaker-test -c <canaux> -s <canal+1>."""
    if not HW_RE.match(ident or ""):
        return {"ok": False, "sortie": "identifiant ALSA invalide"}
    if canaux not in CANAUX or not 0 <= canal < canaux:
        return {"ok": False, "sortie": f"canal {canal} hors des {canaux} canaux"}
    base = ["speaker-test", "-D", ident, "-c", str(canaux), "-t", "wav", "-s", str(canal + 1), "-l", "1"]
    rc, out = run(base + ["-m", CHMAP[canaux]], timeout=40)
    if rc != 0 and "channel map" in out.lower():
        rc, out = run(base, timeout=40)
    sortie = out.strip()[-300:]
    if rc != 0 and "not available" in sortie.lower():
        sortie = f"cette sortie n'offre pas {canaux} canaux : {sortie}"
    return {"ok": rc == 0, "canal": CANAUX[canaux][canal], "sortie": sortie}


def volume_alsa(ident: str, pourcent: int, run=executer) -> dict:
    """Volume de la carte (amixer), best effort : premier contrôle utile de la carte."""
    m = HW_RE.match(ident or "")
    if not m:
        return {"ok": False, "sortie": "identifiant ALSA invalide"}
    carte = m.group(1)
    rc, out = run(["amixer", "-c", carte, "scontrols"])
    controles = re.findall(r"Simple mixer control '([^']+)'", out) if rc == 0 else []
    nom = next((c for c in ("Master", "PCM", "Headphone", "Speaker", "IEC958") if c in controles), controles[0] if controles else "")
    if not nom:
        return {"ok": False, "sortie": "aucun contrôle de volume sur cette carte"}
    rc, out = run(["amixer", "-c", carte, "sset", nom, f"{int(pourcent)}%", "unmute"])
    return {"ok": rc == 0, "sortie": (nom + " : " + out.strip()[-200:]) if rc == 0 else out.strip()[-200:]}


# ---------------------------------------------------------------- premier démarrage (PipeWire de la session)
def sinks_pactl(texte: str) -> list:
    """[{name, description, card, device}] depuis `pactl list sinks`."""
    sinks, cur = [], None
    for ligne in texte.splitlines():
        s = ligne.strip()
        if s.startswith("Name:"):
            cur = {"name": s.split(":", 1)[1].strip(), "description": "", "card": "", "device": ""}
            sinks.append(cur)
        elif cur is not None and s.startswith("Description:"):
            cur["description"] = s.split(":", 1)[1].strip()
        elif cur is not None and s.startswith("alsa.card ="):
            cur["card"] = s.split("=", 1)[1].strip().strip('"')
        elif cur is not None and s.startswith("alsa.device ="):
            cur["device"] = s.split("=", 1)[1].strip().strip('"')
    return sinks


def sink_pour(ident: str, sinks: list) -> dict | None:
    """Le sink PipeWire d'une sortie ALSA hw:C,D : carte ET device, sinon la carte."""
    m = HW_RE.match(ident or "")
    if not m:
        return None
    card, dev = m.group(1), m.group(2)
    return next((s for s in sinks if s["card"] == card and s["device"] == dev), None) \
        or next((s for s in sinks if s["card"] == card), None)


def commentaire() -> str:
    return f"; Modifié {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} par PinCabOS fonction({FONCTION})"


def poser_cle(lines: list, section: str, cle: str, valeur: str) -> list:
    """Même contrat que la page Audio : la clé sous un commentaire daté, un seul commentaire.
    PINCABOS_INI_UNIQUE_V1 : délégué à l'écrivain INI unique."""
    ini = pincabos_ini.Ini("\n".join(lines))
    ini.poser(section, cle, valeur, commentaire())
    return ini.texte().split("\n")


def ecrire_vpx(texte: str, backglass: str, playfield: str, sound3d: str) -> str:
    lines = texte.split("\n")
    for cle, val in (("SoundDeviceBG", backglass), ("SoundDevice", playfield), ("Sound3D", sound3d)):
        lines = poser_cle(lines, "Player", cle, val)
    return "\n".join(lines)


def cartes_pactl(texte: str) -> list:
    """[{name, card, profiles: {nom: disponible}, active}] depuis `pactl list cards`."""
    cartes, cur, dans_profils = [], None, False
    for ligne in texte.splitlines():
        s = ligne.strip()
        if s.startswith("Name:"):
            cur = {"name": s.split(":", 1)[1].strip(), "card": "", "profiles": {}, "active": ""}
            cartes.append(cur)
            dans_profils = False
        elif cur is None:
            continue
        elif s.startswith("alsa.card ="):
            cur["card"] = s.split("=", 1)[1].strip().strip('"')
        elif s.startswith("Profiles:"):
            dans_profils = True
        elif s.startswith("Active Profile:"):
            cur["active"] = s.split(":", 1)[1].strip()
            dans_profils = False
        elif dans_profils:
            m = re.match(r"([\w.:+-]+):\s.*available:\s*(\w+)", s)
            if m:
                cur["profiles"][m.group(1)] = m.group(2) == "yes"
    return cartes


def profil_multicanal(carte: dict, canaux: int) -> str:
    """Le profil de sortie a `canaux` canaux (surround-51 pour 6, surround-71 pour 8), disponible d abord."""
    motif = "surround-71" if canaux >= 8 else "surround-51"
    candidats = [p for p in carte.get("profiles", {}) if p.startswith("output:") and motif in p]
    candidats.sort(key=lambda p: (not carte["profiles"][p], p))
    return candidats[0] if candidats else ""


def assurer_profil_surround(pf: dict, canaux: int, run=executer) -> list:
    """PINCABOS_AUDIO_PROFIL_SURROUND_V1 : PipeWire ouvre les cartes analogiques en stereo par
    defaut (retex cab de Yann : ALC1220 en « Analog Stereo », SSF demande, garde -> stereo).
    Si la carte de la sortie choisie offre un profil a `canaux` canaux, on l active avant la
    garde ; le sink change alors de nom (analog-stereo -> analog-surround-51)."""
    rc, out = run(commande_pinball(["/usr/bin/pactl", "list", "cards"]), timeout=15)
    if rc != 0:
        return []
    carte = next((c for c in cartes_pactl(out) if c["card"] == pf.get("card")), None)
    if not carte:
        return []
    profil = profil_multicanal(carte, canaux)
    if not profil:
        return [f"carte {carte['name']} : aucun profil a {canaux} canaux"]
    if carte["active"] == profil:
        return []
    rc, out = run(commande_pinball(["/usr/bin/pactl", "set-card-profile", carte["name"], profil]), timeout=15)
    if rc != 0:
        return [f"carte {carte['name']} : profil {profil} refuse ({out.strip()[-80:]})"]
    return [f"carte {carte['name']} : profil {profil} active pour le SSF"]


OUTIL_SURROUND = Path("/usr/local/sbin/pincabos-audio-surround")


def activer_71(run=executer, outil: Path | None = None) -> list:
    """PINCABOS_AUDIO_71_RETASK_V1 : passe la carte en 7.1 en reaffectant l'entree
    ligne en sortie laterale, exactement ce que fait la page Audio du cabinet.

    Retex du cab de Yann (07/09/2026) : le 7.1 choisi dans l'assistant restait sans
    effet sur une ALC1220, qui n'expose que six canaux tant que la prise d'entree
    n'a pas ete reaffectee. Le premier demarrage se rabattait en 5.1 avec un
    avertissement dans un journal que personne ne lit ; la sortie « centre + caisson »
    se retrouvait a alimenter des exciters et les lateraux restaient muets. La
    reaffectation est reversible et rejouee a chaque demarrage (apply-boot).

    Le marqueur « active pour le SSF » est celui qu'attend l'appelant pour relire
    les sinks : le nom du sink change (analog-surround-51 -> analog-surround-71).
    """
    # resolu a l'appel : un banc ou un test peut poser un autre chemin
    outil = Path(outil) if outil else OUTIL_SURROUND
    if not outil.is_file():
        return [f"7.1 : {outil} absent, la carte reste a six canaux"]
    rc, out = run([str(outil), "enable", "7.1"], timeout=120)
    detail = (out or "").strip().splitlines()
    detail = detail[-1][-140:] if detail else ""
    if rc != 0:
        return [f"7.1 : reaffectation refusee ({detail})"]
    return ["carte : profil 7.1 active pour le SSF, entree ligne reaffectee en sortie laterale"
            + (f" ({detail})" if detail else "")]


def canaux_du_sink(texte: str, nom: str) -> int:
    """Nombre de canaux du sink `nom` dans `pactl list sinks` (Sample Specification: s16le 2ch 48000Hz), 0 si inconnu."""
    bloc = ""
    for morceau in re.split(r"(?m)^Sink #", texte):
        if re.search(r"(?m)^\s*Name:\s*" + re.escape(nom) + r"\s*$", morceau):
            bloc = morceau
            break
    m = re.search(r"Sample Specification:.*?(\d+)ch", bloc)
    return int(m.group(1)) if m else 0


def commande_pinball(args: list) -> list:
    return ["runuser", "-u", "pinball", "--", "env", "XDG_RUNTIME_DIR=/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus", *args]


# PINCABOS_AUDIO_UNMUTE_V1 (cab de Yann, 06/09/2026, installation neuve) : le profil
# surround etait actif et le volume regle, mais la sortie restait coupee : sink PipeWire
# « Mute: yes » et commutateurs ALSA Front / Surround / Center / LFE sur off (etat de la
# carte au premier profil multicanal), mute memorise par WirePlumber et rejoue a chaque
# demarrage. On leve le mute des deux cotes, puis WirePlumber memorise l etat ouvert.
COMMUTATEURS_ALSA = ("Master", "PCM", "Front", "Surround", "Center", "LFE", "Side", "Headphone", "Speaker")
CANAUX_ALSA_PLEINS = ("PCM", "Front", "Surround", "Center", "LFE", "Side")


def sink_muet(nom: str, texte: str) -> bool:
    """Le sink `nom` est-il coupé (« Mute: yes ») dans `pactl list sinks` ?
    Sink absent ou état inconnu : on répond « coupé », le mute sera levé (sans risque)."""
    courant = None
    for ligne in texte.splitlines():
        s = ligne.strip()
        if s.startswith("Name:"):
            courant = s.split(":", 1)[1].strip()
        elif courant == nom and s.startswith("Mute:"):
            return s.split(":", 1)[1].strip() == "yes"
    return True


def reactiver_sortie(sink: dict, run=executer) -> list:
    """Leve le mute PipeWire du sink et ouvre les commutateurs ALSA de sa carte.
    PINCABOS_AUDIO_SANS_CRAQUEMENT_V1 : seulement ce qui est réellement coupé ou
    baissé. Toucher un commutateur déjà ouvert ou un volume déjà plein fait claquer
    les amplis à chaque rejeu (cab de Yann, 06/09)."""
    journal = []
    nom = str(sink.get("name") or "")
    if nom:
        rc, etat = run(commande_pinball(["/usr/bin/pactl", "list", "sinks"]), timeout=10)
        if rc == 0 and not sink_muet(nom, etat):
            journal.append(f"sortie PipeWire ouverte : {nom}")
        else:
            rc, out = run(commande_pinball(["/usr/bin/pactl", "set-sink-mute", nom, "0"]), timeout=10)
            journal.append(f"mute PipeWire leve : {nom} ({'ok' if rc == 0 else out.strip()[-80:]})")
    carte = str(sink.get("card") or "")
    if carte != "":
        ouverts, pleins, intacts = [], [], []
        for ctrl in COMMUTATEURS_ALSA:
            rc, etat = run(["amixer", "-c", carte, "sget", ctrl], timeout=5)
            if rc != 0:
                continue   # commutateur absent sur cette carte
            touche = False
            if "[on]" not in etat:   # coupé, ou état illisible : on ouvre (sans risque)
                rc, _ = run(["amixer", "-q", "-c", carte, "sset", ctrl, "unmute"], timeout=5)
                if rc == 0:
                    ouverts.append(ctrl)
                    touche = True
            if ctrl in CANAUX_ALSA_PLEINS:
                niveaux = re.findall(r"\[(\d+)%\]", etat)
                if niveaux and any(int(n) < 100 for n in niveaux):
                    run(["amixer", "-q", "-c", carte, "sset", ctrl, "100%"], timeout=5)
                    pleins.append(ctrl)
                    touche = True
            if not touche:
                intacts.append(ctrl)
        journal.append(f"commutateurs ALSA carte {carte} ouverts : {', '.join(ouverts) or 'aucun'}"
                       f" ; remis à 100 % : {', '.join(pleins) or 'aucun'}"
                       f" ; déjà en place : {', '.join(intacts) or 'aucun'}")
    return journal


def activer_son_apercus(vpinfe_ini: Path = VPINFE_INI, marqueur: Path = MARQUEUR_SON_APERCUS) -> str:
    """PINCABOS_VPINFE_SON_APERCUS_V1 : VPinFE joue la bande-son des aperçus de tables
    quand [Settings] muteaudio = false. Le modèle livré le dit déjà ; un cabinet mis à
    jour garde son ancien fichier, où il valait true, et ses aperçus restaient muets.
    On ne le pose qu'une fois (marqueur) : couper le son des aperçus reste un choix
    que l'utilisateur peut faire ensuite, et que PinCabOS ne défait pas."""
    if marqueur.is_file():
        return ""
    if not vpinfe_ini.is_file():
        return ""
    ini = pincabos_ini.Ini(vpinfe_ini.read_text(encoding="utf-8", errors="replace"))
    if (ini.get("Settings", "muteaudio") or "").strip().lower() not in ("true", "1", "yes"):
        _poser_marqueur(marqueur)
        return ""
    ini.poser("Settings", "muteaudio", "false", commentaire())
    try:
        pincabos_ini.ecrire(vpinfe_ini, ini)
    except (OSError, ValueError) as exc:
        return f"VPinFE : son des aperçus non activé ({exc})"
    _poser_marqueur(marqueur)
    return "VPinFE : son des aperçus de tables activé ([Settings] muteaudio = false)"


def _poser_marqueur(marqueur: Path) -> None:
    try:
        marqueur.parent.mkdir(parents=True, exist_ok=True)
        marqueur.write_text(datetime.now().isoformat(timespec="seconds") + chr(10), encoding="utf-8")
    except OSError:
        pass


def appliquer_premier_demarrage(cfg: dict, run=executer, vpx_ini: Path = VPX_INI, vpx_legacy_ini: Path = VPX_LEGACY_INI) -> list:
    """Traduit le choix de l'installeur (ALSA) en réglages de la session : VPX, sortie par défaut, volume."""
    journal = []
    inst = cfg.get("installer") or {}
    rc, out = run(commande_pinball(["/usr/bin/pactl", "list", "sinks"]), timeout=15)
    sinks = sinks_pactl(out) if rc == 0 else []
    if not sinks:
        journal.append("pactl : aucun sink (session PipeWire absente ?), VPX garde ses sorties par défaut")
    pf = sink_pour(cfg.get("playfield_device", ""), sinks)
    bg = sink_pour(cfg.get("backbox_device", ""), sinks) or pf
    # PINCABOS_AUDIO_SSF_GARDE_V1 (Yann : « le SSF ne joue pas les sons ») : un mode a 6 canaux
    # sur une sortie stereo laisse des sons muets ; on retombe en stereo et on le dit.
    voulu = str(inst.get("sound3d", "0"))
    exige = canaux_pour_mode(voulu)
    if pf and exige > 2 and 0 < canaux_du_sink(out, pf["name"]) < exige:
        # PINCABOS_AUDIO_PROFIL_SURROUND_V1 : la carte offre peut-etre un profil multicanal
        bascule = assurer_profil_surround(pf, exige, run)
        if exige == 8 and not any("active pour le SSF" in l for l in bascule):
            # PINCABOS_AUDIO_71_RETASK_V1 : la carte n'expose pas huit canaux telle
            # quelle. Plutot que de rabattre le choix de l'utilisateur, on reaffecte
            # l'entree ligne en sortie laterale (reversible) comme le fait la page Audio.
            bascule += activer_71(run)
        if exige == 8 and not any("active pour le SSF" in l for l in bascule):
            # meme apres la reaffectation : le 5.1 au moins (lateraux muets, on le dira)
            bascule += assurer_profil_surround(pf, 6, run)
        journal += bascule
        if any("active pour le SSF" in l for l in bascule):
            rc, out = run(commande_pinball(["/usr/bin/pactl", "list", "sinks"]), timeout=15)
            sinks = sinks_pactl(out) if rc == 0 else sinks
            pf = sink_pour(cfg.get("playfield_device", ""), sinks) or pf
            bg = sink_pour(cfg.get("backbox_device", ""), sinks) or pf
    if pf and voulu not in ("0", "1"):
        canaux = canaux_du_sink(out, pf["name"])
        if canaux and canaux < 6:
            journal.append(f"Sound3D {voulu} demande mais la sortie {pf['name']} n'a que {canaux} canaux : mode stereo (0) applique")
            inst = dict(inst, sound3d="0", sound3d_voulu=voulu)
        elif canaux and canaux < exige:
            # PINCABOS_AUDIO_71_V1 : 7.1 demande sur une sortie 5.1 : VPX joue lockbar + arriere +
            # basses, les lateraux (fronton) restent muets. Le mode est garde, on le dit.
            journal.append(f"WARN: Sound3D {voulu} (7.1) demande mais la sortie {pf['name']} n'a que {canaux} canaux "
                           "malgre la reaffectation tentee : les canaux lateraux (fond du meuble) seront muets ; il faut "
                           "une carte qui expose huit canaux ou une sortie backbox separee")
    # PINCABOS_AUDIO_PREMIER_DEMARRAGE_V2 : VPX n'a pas encore écrit son ini au
    # premier démarrage d'un cab neuf (vu en VM : « absent, rien écrit ») ; on le
    # crée avec la seule section [Player], VPX complète le reste à son premier
    # lancement. Sans sink connu on n'écrit rien : rien à traduire.
    if pf or bg:
        journal.append("VPX : " + assurer_pref_vpx(vpx_ini, vpx_legacy_ini))
        texte = vpx_ini.read_text(encoding="utf-8", errors="replace") if vpx_ini.is_file() else ""
        nouveau = ecrire_vpx(texte, bg["description"] if bg else "", pf["description"] if pf else "", str(inst.get("sound3d", "0")))
        if nouveau != texte:
            try:
                vpx_ini.parent.mkdir(parents=True, exist_ok=True)
                vpx_ini.write_text(nouveau, encoding="utf-8")
                if not texte:
                    _proprietaire_pinball(vpx_ini)
            except OSError as exc:
                journal.append(f"VPX : {vpx_ini} non écrit ({exc})")
        journal.append(f"VPX : SoundDevice={pf['description'] if pf else '(défaut)'} ; SoundDeviceBG={bg['description'] if bg else '(défaut)'} ; "
                       f"Sound3D={inst.get('sound3d', '0')}{'' if texte else ' (ini créé)'}")
    else:
        journal.append("VPX : aucun sink correspondant, rien écrit")
    if pf:
        # pactl accepte le NOM du sink ; wpctl set-default veut un identifiant numérique
        # (vu en VM : « is not a valid number »).
        rc, out = run(commande_pinball(["/usr/bin/pactl", "set-default-sink", pf["name"]]), timeout=10)
        journal.append(f"sortie par défaut : {pf['name']} ({'ok' if rc == 0 else out.strip()[-80:]})")
        journal += reactiver_sortie(pf, run)
        if bg and bg.get("name") != pf.get("name"):
            journal += reactiver_sortie(bg, run)
        vol = int(inst.get("volume", 70))
        rc, out = run(commande_pinball(["/usr/bin/pactl", "set-sink-volume", pf["name"], f"{vol}%"]), timeout=10)
        journal.append(f"volume : {vol} % ({'ok' if rc == 0 else out.strip()[-80:]})")
    return journal


def _proprietaire_pinball(chemin: Path):
    """Un fichier créé par root dans le dossier de pinball lui appartient (et son dossier)."""
    import pwd
    import shutil
    try:
        u = pwd.getpwnam("pinball")
    except KeyError:
        return
    for p in (chemin, chemin.parent):
        try:
            shutil.chown(p, u.pw_uid, u.pw_gid)
        except OSError:
            pass


def charger(chemin: Path = CONFIG) -> dict:
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
