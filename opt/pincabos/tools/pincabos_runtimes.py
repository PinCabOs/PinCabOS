#!/usr/bin/env python3
"""PinCabOS — dossiers de production des logiciels tiers.

PINCABOS_RUNTIME_ROTATION_V1

Un dossier de production porte son nom, jamais sa version : /opt/pinball/vpx et
/opt/pinball/vpinfe. Deux raisons : un chemin stable se lit dans un journal, une
configuration ou un script sans indirection, et la version d un logiciel n a pas
a decider du nom de son dossier.

La version se lit alors dans .pincabos-version, ecrit par celui qui installe
(recette d image ou updater), et non plus dans le nom du dossier.

Une mise a jour se fait par rotation de noms, sur le meme systeme de fichiers,
donc en quelques millisecondes :

    vpx.bak2  <- vpx.bak  <- vpx  <- vpx.new

Le retour arriere refait le chemin inverse. Deux versions precedentes sont
conservees : de quoi revenir deux fois sans retelecharger.

  from pincabos_runtimes import poser, revenir, lire_version, ecrire_version
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

FICHIER_VERSION = ".pincabos-version"
SCHEMA = "pincabos.runtime-version/1"
GARDER = 2


class RotationError(RuntimeError):
    pass


# ------------------------------------------------------------------ version
def fichier_version(dossier) -> Path:
    return Path(dossier) / FICHIER_VERSION


def lire_version(dossier) -> dict:
    """Le contenu de .pincabos-version, {} si absent ou illisible."""
    try:
        valeur = json.loads(fichier_version(dossier).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return valeur if isinstance(valeur, dict) else {}


def version_de(dossier) -> str:
    """La version installee, chaine vide si inconnue."""
    return str(lire_version(dossier).get("version") or "")


def ecrire_version(dossier, version: str, *, composant: str = "", source: str = "",
                   sha256: str = "", pose_par: str = "", proprietaire=(None, None)) -> Path:
    """Depose .pincabos-version dans le dossier ; ecriture atomique."""
    dossier = Path(dossier)
    valeur = {
        "schema": SCHEMA,
        "composant": composant or dossier.name,
        "version": str(version),
        "source": source,
        "sha256": sha256,
        "pose_par": pose_par,
        "pose_le": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    cible = fichier_version(dossier)
    temp = cible.with_name(cible.name + ".tmp")
    temp.write_text(json.dumps(valeur, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    uid, gid = proprietaire
    if uid is None:
        try:
            st = dossier.stat()
            uid, gid = st.st_uid, st.st_gid
        except OSError:
            uid = gid = None
    if uid is not None and os.geteuid() == 0:
        try:
            os.chown(temp, uid, gid)
        except OSError:
            pass
    os.replace(temp, cible)
    return cible


# ------------------------------------------------------------------ rotation
def nom_sauvegarde(cible, rang: int) -> Path:
    """vpx.bak pour le rang 1, vpx.bak2 pour le rang 2, et ainsi de suite."""
    cible = Path(cible)
    return cible.with_name(cible.name + (".bak" if rang == 1 else f".bak{rang}"))


def sauvegardes(cible, garder: int = GARDER) -> list:
    """Les sauvegardes presentes, de la plus recente a la plus ancienne."""
    return [p for p in (nom_sauvegarde(cible, r) for r in range(1, garder + 1)) if p.is_dir()]


def _jeter(chemin: Path) -> None:
    """Ecarte puis supprime : le nom est libere tout de suite, meme sur un gros dossier."""
    if not chemin.exists():
        return
    poubelle = chemin.with_name("." + chemin.name + ".jeter")
    shutil.rmtree(poubelle, ignore_errors=True)
    os.replace(chemin, poubelle)
    shutil.rmtree(poubelle, ignore_errors=True)


def poser(cible, nouveau, garder: int = GARDER) -> list:
    """Met `nouveau` a la place de `cible` en faisant tourner les sauvegardes.

    Le nouveau dossier doit deja etre pose a cote, sur le meme systeme de fichiers :
    la bascule n est alors qu une suite de renommages, sans copie.
    """
    cible, nouveau = Path(cible), Path(nouveau)
    if not nouveau.is_dir():
        raise RotationError(f"dossier a poser absent : {nouveau}")
    if nouveau.resolve() == cible.resolve():
        raise RotationError("le dossier a poser est deja la cible")
    if cible.exists() and cible.parent.stat().st_dev != nouveau.stat().st_dev:
        raise RotationError("le dossier a poser n est pas sur le meme systeme de fichiers")

    journal = []
    _jeter(nom_sauvegarde(cible, garder))
    for rang in range(garder - 1, 0, -1):
        source = nom_sauvegarde(cible, rang)
        if source.is_dir():
            os.replace(source, nom_sauvegarde(cible, rang + 1))
            journal.append(f"{source.name} -> {nom_sauvegarde(cible, rang + 1).name}")
    if cible.is_symlink():
        # heritage de l epoque du lien : il ne doit plus rien en rester
        cible.unlink()
        journal.append(f"ancien lien {cible.name} retire")
    elif cible.is_dir():
        os.replace(cible, nom_sauvegarde(cible, 1))
        journal.append(f"{cible.name} -> {nom_sauvegarde(cible, 1).name}")
    os.replace(nouveau, cible)
    journal.append(f"{nouveau.name} -> {cible.name}")
    return journal


def revenir(cible, garder: int = GARDER) -> list:
    """Revient a la sauvegarde la plus recente ; la version en place est jetee."""
    cible = Path(cible)
    precedente = nom_sauvegarde(cible, 1)
    if not precedente.is_dir():
        raise RotationError("aucune version precedente conservee")

    journal = []
    _jeter(cible)
    journal.append(f"{cible.name} jete")
    os.replace(precedente, cible)
    journal.append(f"{precedente.name} -> {cible.name}")
    for rang in range(2, garder + 1):
        source = nom_sauvegarde(cible, rang)
        if source.is_dir():
            os.replace(source, nom_sauvegarde(cible, rang - 1))
            journal.append(f"{source.name} -> {nom_sauvegarde(cible, rang - 1).name}")
    return journal


def etat(cible, garder: int = GARDER) -> dict:
    """Ce qui est en place et ce qui reste en reserve, pour les pages et le journal."""
    cible = Path(cible)
    return {
        "chemin": str(cible),
        "version": version_de(cible),
        "presente": cible.is_dir(),
        "sauvegardes": [
            {"chemin": str(p), "version": version_de(p)}
            for p in sauvegardes(cible, garder)
        ],
    }
