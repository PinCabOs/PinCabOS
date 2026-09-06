#!/usr/bin/env python3
"""Recette d'image PinCabOS : composants tiers depuis les releases amont (PINCABOS_IMAGE_RECETTE_V1).

Le rootfs de l'ISO ne porte plus les bundles VPX et VPinFE copiés d'un cab :
ils sont téléchargés depuis les releases officielles, version épinglée et
somme SHA-256 vérifiée (image/components.json), puis posés sous /opt/pinball
dans le rootfs (PINCABOS_RUNTIMES_OPT_V1 ; le compte du joueur garde les liens
de compatibilité ~/vpx et ~/vpinfe). libdof patché (backboard, Dude's Cab) vient du dépôt
(overlays/libdof-canonical) et remplace la copie vendored des deux bundles,
comme sur les cabs. Les modèles du compte (vpinfe.ini, DOF, tableau de bord)
suivent via pincabos_home_templates.py.

  python3 image/fetch_components.py apply --rootfs /root/pco-master [--cache DIR] [--only vpx,vpinfe,libdof] [--dry-run]
  python3 image/fetch_components.py verify --cache DIR      # sommes des archives en cache
  python3 image/fetch_components.py list
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
COMPONENTS = ICI / "components.json"
CACHE = Path(os.environ.get("PCO_IMAGE_CACHE", "/root/image-cache"))
UID, GID = 1000, 1000


def charger(chemin: Path = COMPONENTS) -> dict:
    d = json.loads(chemin.read_text(encoding="utf-8"))
    if d.get("schema") != "pincabos.image-components/v1":
        raise ValueError(f"schema inattendu : {d.get('schema')}")
    return d


def sha256_de(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def telecharger(url: str, dest: Path, sha256: str, fetch=None) -> str:
    """Archive en cache, vérifiée. `fetch(url, dest)` injectable (tests)."""
    if dest.is_file() and sha256_de(dest) == sha256:
        return f"GO: {dest.name} en cache, somme vérifiée"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if fetch is None:
        def fetch(u, d):
            with urllib.request.urlopen(u, timeout=120) as r, open(d, "wb") as f:
                shutil.copyfileobj(r, f)
    fetch(url, tmp)
    somme = sha256_de(tmp)
    if somme != sha256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"NOGO: somme inattendue pour {dest.name} : {somme} (attendu {sha256}) — version amont changée ?")
    tmp.replace(dest)
    return f"GO: {dest.name} téléchargé, somme vérifiée"


def _membres_racine(noms: list) -> set:
    return {n.split("/", 1)[0] for n in noms if n and n != "."}


def extraire(archive: Path, dest: Path) -> Path:
    """Extrait dans `dest` (vidé d'abord). Un dossier racine unique est aplati."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.mkdir()
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        tmp = Path(tmp)
        if archive.name.endswith((".tar.gz", ".tgz", ".tar.xz", ".tar")):
            with tarfile.open(archive) as t:
                noms = t.getnames()
                t.extractall(tmp, filter="tar")
        elif archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                noms = z.namelist()
                z.extractall(tmp)
                # zip ne garde pas le bit exécutable : on le remet depuis les attributs externes
                for info in z.infolist():
                    mode = (info.external_attr >> 16) & 0o777
                    p = tmp / info.filename
                    if mode and p.is_file():
                        p.chmod(mode)
        else:
            raise ValueError(f"format d'archive inconnu : {archive.name}")
        racines = _membres_racine(noms)
        source = tmp / next(iter(racines)) if len(racines) == 1 and (tmp / next(iter(racines))).is_dir() else tmp
        for element in source.iterdir():
            shutil.move(str(element), str(dest / element.name))
    return dest


def proprietaire(chemin: Path, uid: int = UID, gid: int = GID):
    if os.geteuid() != 0:
        return
    for racine, dossiers, fichiers in os.walk(chemin):
        for n in dossiers + fichiers:
            try:
                os.chown(os.path.join(racine, n), uid, gid, follow_symlinks=False)
            except OSError:
                pass
    try:
        os.chown(chemin, uid, gid, follow_symlinks=False)
    except OSError:
        pass


def poser_bundle(rootfs: Path, comp: dict, cache: Path, dry_run=False, fetch=None) -> list:
    journal = []
    archive = cache / comp["archive"]
    journal.append(telecharger(comp["url"], archive, comp["sha256"], fetch) if not dry_run else f"GO: (à blanc) {comp['archive']}")
    dest = rootfs / comp["install"]
    if dry_run:
        journal.append(f"GO: (à blanc) extraction vers {dest}")
    else:
        extraire(archive, dest)
        proprietaire(dest)
        journal.append(f"GO: {comp['name']} posé dans {comp['install']}")
        if comp.get("check") and not (dest / comp["check"]).exists():
            journal.append(f"NOGO: {comp['check']} absent après extraction de {comp['name']}")
    for lien, cible in (comp.get("links") or {}).items():
        p = rootfs / lien
        if dry_run:
            journal.append(f"GO: (à blanc) lien {lien} -> {cible}")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink() or p.exists():
            p.unlink() if not p.is_dir() or p.is_symlink() else shutil.rmtree(p)
        os.symlink(cible, p)
        if os.geteuid() == 0:
            os.lchown(p, UID, GID)
        journal.append(f"GO: lien {lien} -> {cible}")
    return journal


def poser_libdof(rootfs: Path, comp: dict, depot: Path, dry_run=False) -> list:
    """libdof patché du dépôt (overlays/libdof-canonical) à la place des copies vendored."""
    journal = []
    source = depot / comp["source"]
    if not source.is_file():
        return [f"NOGO: libdof canonique absent du dépôt : {source}"]
    if comp.get("md5") and hashlib.md5(source.read_bytes()).hexdigest() != comp["md5"]:
        return [f"NOGO: libdof canonique ≠ md5 attendu {comp['md5']} (le dépôt a changé de libdof : mettre components.json à jour)"]
    for cible in comp.get("copies", []):
        p = rootfs / cible
        if dry_run:
            journal.append(f"GO: (à blanc) copie libdof -> {cible}")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink():
            p.unlink()
        shutil.copy2(source, p)
        if os.geteuid() == 0:
            os.chown(p, UID, GID)
        journal.append(f"GO: libdof patché -> {cible}")
    for lien, cible in (comp.get("links") or {}).items():
        p = rootfs / lien
        if dry_run:
            journal.append(f"GO: (à blanc) lien {lien} -> {cible}")
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_symlink() or p.exists():
            p.unlink()
        os.symlink(cible, p)
        if os.geteuid() == 0:
            os.lchown(p, UID, GID)
        journal.append(f"GO: lien {lien} -> {cible}")
    return journal


def appliquer(rootfs: Path, cache: Path = CACHE, only=None, dry_run=False, composants: dict | None = None,
              depot: Path | None = None, fetch=None) -> list:
    d = composants or charger()
    depot = depot or ICI.parent
    journal = []
    # PINCABOS_RUNTIMES_OPT_V1 : /opt/pinball appartient au joueur (les updaters
    # VPX et VPinFE y ecrivent en son nom), comme sur un cabinet migre.
    runtimes = rootfs / d.get("runtimes_dir", "opt/pinball")
    if not dry_run:
        runtimes.mkdir(parents=True, exist_ok=True)
        if os.geteuid() == 0:
            os.chown(runtimes, UID, GID)
    journal.append(f"GO: runtimes sous {d.get('runtimes_dir', 'opt/pinball')}")
    for nom, comp in d["components"].items():
        if only and nom not in only:
            continue
        journal.append(f"--- {nom} : {comp.get('name', nom)}")
        try:
            if comp["kind"] == "bundle":
                journal += poser_bundle(rootfs, comp, cache, dry_run, fetch)
            elif comp["kind"] == "repo-file":
                journal += poser_libdof(rootfs, comp, depot, dry_run)
            else:
                journal.append(f"NOGO: kind inconnu {comp['kind']}")
        except Exception as exc:   # une archive absente ou corrompue ne doit pas cacher les autres composants
            journal.append(f"NOGO: {nom} : {exc}")
    outil = rootfs / "opt/pincabos/tools/pincabos_home_templates.py"
    if outil.is_file() and not dry_run and (only is None or "templates" in only):
        import subprocess
        r = subprocess.run([sys.executable, str(outil), "apply", "--root", str(rootfs)], capture_output=True, text=True)
        journal.append(("GO: " if r.returncode == 0 else "WARN: ") + "modèles du joueur : " + (r.stdout.strip().splitlines() or ["?"])[-1])
    return journal


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Composants tiers de l'image PinCabOS")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("apply")
    a.add_argument("--rootfs", required=True)
    a.add_argument("--cache", default=str(CACHE))
    a.add_argument("--only", default="", help="vpx,vpinfe,libdof,templates")
    a.add_argument("--dry-run", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--cache", default=str(CACHE))
    sub.add_parser("list")
    args = ap.parse_args(argv)
    d = charger()
    if args.cmd == "list":
        for nom, c in d["components"].items():
            print(f"{nom:8s} {c.get('name', '')}  {c.get('url', c.get('source', ''))}")
        return 0
    if args.cmd == "verify":
        rc = 0
        for nom, c in d["components"].items():
            if c["kind"] != "bundle":
                continue
            p = Path(args.cache) / c["archive"]
            ok = p.is_file() and sha256_de(p) == c["sha256"]
            print(f"{'GO ' if ok else 'NOGO'} {c['archive']}")
            rc |= 0 if ok else 1
        return rc
    if args.cmd != "apply":
        ap.print_help()
        return 2
    only = [x for x in args.only.split(",") if x] or None
    journal = appliquer(Path(args.rootfs), Path(args.cache), only, args.dry_run)
    print("\n".join(journal))
    return 1 if any(l.startswith("NOGO") for l in journal) else 0


if __name__ == "__main__":
    sys.exit(main())
