"""Étape Boutons de l'assistant d'installation (PINCABOS_INSTALLEUR_BOUTONS_V1).

Remonté par Patrick le 09/09/2026 : arrivé sur le frontend après installation,
aucun bouton ne répondait et rien ne disait quoi faire. Le mappage n'existait
qu'après coup, dans Map Commander — qu'il fallait deviner.

Le cabinet est branché pendant l'installation : c'est le bon moment pour
appuyer sur ses boutons. On réutilise le moteur de Map Commander tel quel
(`pincabos_vpx_input`) : mêmes actions, mêmes jetons de liaison, même écriture.
L'assistant ne fait que CAPTURER ; l'écriture dans le VPinballX.ini et le
vpinfe.ini de la cible est rejouée au premier démarrage, là où les
périphériques et les chemins sont ceux du cabinet installé — la leçon du ZeDMD
appliqué dans le chroot (PINCABOS_ZEDMD_AU_PREMIER_DEMARRAGE_V1).
"""
from __future__ import annotations

import datetime

try:
    import pincabos_vpx_input as vi
except Exception:                                   # pragma: no cover - hors cab
    vi = None

# Ce qu'un cabinet a forcément, et qu'il faut pour jouer dès le premier
# démarrage. Le reste des actions de Map Commander reste accessible, replié.
ESSENTIELLES = ("LeftFlipper", "RightFlipper", "Start", "Credit1",
                "LaunchBall", "Lockbar", "ExitGame")

DELAI_MAX = 30.0


def disponible() -> bool:
    return vi is not None


def actions() -> list:
    """Les actions mappables, l'essentiel d'abord."""
    if vi is None:
        return []
    rang = {a: i for i, a in enumerate(ESSENTIELLES)}
    tout = [{"id": a, "label": label, "defaut": defaut,
             "essentielle": a in rang}
            for a, label, defaut in vi.ACTIONS]
    tout.sort(key=lambda d: (0, rang[d["id"]]) if d["essentielle"] else (1, 0))
    return tout


def peripheriques() -> list:
    """Cartes de boutons vues par le noyau, pour dire à l'utilisateur ce qu'on voit."""
    if vi is None:
        return []
    try:
        devs = vi.list_devices()
    except Exception:
        return []
    ids = vi.joystick_setting_ids(devs)
    return [{"name": d.name, "id": ids.get(d.path, ("", ""))[0],
             "boutons": len(d.button_order()), "axes": len(d.axis_order())}
            for d in devs]


def capturer(delai: float = 8.0) -> dict:
    """Attend un appui et renvoie la liaison, ou dit pourquoi elle n'est pas venue."""
    if vi is None:
        return {"error": "moteur d'entrées indisponible"}
    try:
        delai = max(1.0, min(float(delai), DELAI_MAX))
    except (TypeError, ValueError):
        delai = 8.0
    try:
        r = vi.detect_once(delai)
    except Exception as exc:
        return {"error": str(exc)}
    if r is None:
        return {"timeout": True}
    return r


def valider(choix) -> tuple[list, dict]:
    """Un mappage vide est valide : cette étape n'est pas obligatoire."""
    if vi is None:
        return [], {"mappings": {}}
    if not isinstance(choix, dict):
        return ["choix boutons invalide"], {}
    brut = choix.get("mappings")
    if brut is None:
        brut = {}
    if not isinstance(brut, dict):
        return ["mappings invalide"], {}
    erreurs, ok = [], {}
    for action, texte in brut.items():
        if action not in vi.ACTION_LABELS:
            erreurs.append("action inconnue : %s" % action)
            continue
        texte = str(texte or "").strip()
        if not texte:
            continue
        try:
            normalise = vi.normalize_mapping(texte)
        except Exception:
            erreurs.append("liaison illisible pour %s" % action)
            continue
        if not normalise:
            continue
        ok[action] = normalise
    return erreurs, {"mappings": ok}


def config_json(ok: dict) -> dict:
    """Ce que l'installateur pose sur la cible, rejoué au premier démarrage."""
    return {
        "version": 1,
        "source": "PinCabOS installer",
        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mappings": dict(ok.get("mappings") or {}),
    }
