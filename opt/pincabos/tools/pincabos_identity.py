#!/usr/bin/env python3
"""pincabos_identity : le système s'appelle PinCabOS partout où un humain le lit
(PINCABOS_IDENTITE_V1).

PinCabOS est bâti sur Ubuntu et le reste sous le capot : `ID=ubuntu`,
`VERSION_CODENAME`, `DISTRIB_ID`, dépôts apt, ubuntu-drivers, tout ce que
des outils testent continue de voir Ubuntu. Ce qui change, c'est ce qui
s'affiche :

  - /etc/os-release : NAME et PRETTY_NAME (« PinCabOS Alpha 3.60 (Ubuntu
    26.04.1 LTS) »), URLs du projet, plus PINCABOS_VERSION / _CODENAME /
    _BASE. Le fichier devient un vrai fichier (plus un lien vers
    /usr/lib/os-release, qu'une mise à jour de base-files réécrit) et il
    est régénéré depuis /usr/lib/os-release à chaque application.
  - /etc/lsb-release : DISTRIB_DESCRIPTION seulement.
  - /etc/issue, /etc/issue.net : bannière console.
  - /etc/default/grub : GRUB_DISTRIBUTOR="PinCabOS" (menu GRUB), puis
    update-grub si la ligne a changé.
  - entrée de démarrage UEFI : l'entrée qui pointe sur \\EFI\\PINCABOS\\ et
    s'appelle encore « Ubuntu » est recréée sous le nom PinCabOS (même
    disque, même partition, même chargeur), l'ancienne retirée ensuite.

Idempotent : n'écrit que ce qui diffère, dit ce qu'il a fait. `--root DIR`
applique sur une arborescence (installation, tests) sans update-grub ni UEFI.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

NOM = "PinCabOS"
HOME_URL = "https://pincabos.cc/"
BUG_URL = "https://github.com/PinCabOs/PinCabOS/issues"
VERSION_FILES = ("opt/pincabos/config/version.json", "opt/pincabos/version.json")
EFI_DIR_MARQUEUR = "\\EFI\\PINCABOS\\"
CLES_CONSERVEES_TELLES_QUELLES = ("ID", "ID_LIKE", "VERSION_ID", "VERSION", "VERSION_CODENAME", "UBUNTU_CODENAME", "LOGO")


# ---------------------------------------------------------------- version
def version_info(root: Path = Path("/")) -> dict:
    for rel in VERSION_FILES:
        p = root / rel
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("version"):
            return {"version": str(d["version"]).strip(), "codename": str(d.get("codename") or "").strip()}
    return {"version": "", "codename": ""}


def libelle(version: dict, base_pretty: str) -> str:
    v = (NOM + " " + version["version"]).strip() if version.get("version") else NOM
    return f"{v} ({base_pretty})" if base_pretty else v


# ---------------------------------------------------------------- os-release
def parse_kv(text: str) -> list:
    """[(clé, valeur brute avec ses guillemets)] dans l'ordre, commentaires ignorés."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out.append((k.strip(), v.strip()))
    return out


def sans_guillemets(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def os_release_pincabos(base_text: str, version: dict) -> str:
    """Contenu de /etc/os-release à partir de /usr/lib/os-release (Ubuntu)."""
    base = dict(parse_kv(base_text))
    base_pretty = sans_guillemets(base.get("PRETTY_NAME", "")) or "Ubuntu"
    if base_pretty.startswith(NOM):  # déjà réécrit : on repart de PINCABOS_BASE
        base_pretty = sans_guillemets(base.get("PINCABOS_BASE", "")) or "Ubuntu"
    lignes = [
        f'PRETTY_NAME="{libelle(version, base_pretty)}"',
        f'NAME="{NOM}"',
    ]
    for k in ("VERSION_ID", "VERSION", "VERSION_CODENAME", "ID", "ID_LIKE"):
        if k in base:
            lignes.append(f"{k}={base[k]}")
    lignes += [
        f'HOME_URL="{HOME_URL}"',
        f'SUPPORT_URL="{HOME_URL}"',
        f'BUG_REPORT_URL="{BUG_URL}"',
    ]
    for k in ("UBUNTU_CODENAME", "LOGO"):
        if k in base:
            lignes.append(f"{k}={base[k]}")
    lignes += [
        f'PINCABOS_VERSION="{version.get("version", "")}"',
        f'PINCABOS_CODENAME="{version.get("codename", "")}"',
        f'PINCABOS_BASE="{base_pretty}"',
    ]
    return "\n".join(lignes) + "\n"


def lsb_release_pincabos(text: str, version: dict, base_pretty: str) -> str:
    desc = f'DISTRIB_DESCRIPTION="{libelle(version, base_pretty)}"'
    lignes, vu = [], False
    for line in text.splitlines():
        if line.startswith("DISTRIB_DESCRIPTION="):
            lignes.append(desc)
            vu = True
        else:
            lignes.append(line)
    if not vu:
        lignes.append(desc)
    return "\n".join(lignes) + "\n"


def issue_pincabos(version: dict) -> str:
    v = (NOM + " " + version["version"]).strip() if version.get("version") else NOM
    return f"{v} \\n \\l\n\n"


def issue_net_pincabos(version: dict) -> str:
    return ((NOM + " " + version["version"]).strip() if version.get("version") else NOM) + "\n"


def grub_default_pincabos(text: str) -> str:
    ligne = f'GRUB_DISTRIBUTOR="{NOM}"'
    lignes, vu = [], False
    for line in text.splitlines():
        if re.match(r"^\s*GRUB_DISTRIBUTOR=", line):
            if not vu:
                lignes.append(ligne)
                vu = True
            continue
        lignes.append(line)
    if not vu:
        lignes.append(ligne)
    return "\n".join(lignes) + "\n"


# ---------------------------------------------------------------- UEFI
EFI_LIGNE = re.compile(r"^Boot([0-9A-Fa-f]{4})(\*?)\s+(.*?)\t(HD\((\d+),GPT,([0-9a-fA-F-]+),[^)]*\))/(.+)$")


def entrees_efi(texte: str) -> list:
    """Entrées lues dans `efibootmgr -v` : numéro, libellé, partition, PARTUUID, chargeur."""
    out = []
    for line in texte.splitlines():
        m = EFI_LIGNE.match(line.rstrip())
        if not m:
            continue
        out.append({
            "entree": m.group(1).upper(), "active": m.group(2) == "*", "libelle": m.group(3).strip(),
            "partition": int(m.group(5)), "partuuid": m.group(6).lower(), "chargeur": m.group(7).strip(),
        })
    return out


def a_renommer(entrees: list) -> list:
    return [e for e in entrees if EFI_DIR_MARQUEUR in e["chargeur"].upper() and e["libelle"] != NOM]


def deja_nommees(entrees: list) -> list:
    return [e for e in entrees if EFI_DIR_MARQUEUR in e["chargeur"].upper() and e["libelle"] == NOM]


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def renommer_entree_efi(e: dict, executer=_run) -> str:
    """Recrée l'entrée sous le nom PinCabOS (même disque/partition/chargeur), puis retire l'ancienne."""
    dev = executer(["blkid", "-t", f"PARTUUID={e['partuuid']}", "-o", "device"]).stdout.strip()
    if not dev:
        return f"NOGO: partition PARTUUID={e['partuuid']} introuvable, entrée {e['entree']} laissée telle quelle"
    disque = executer(["lsblk", "-no", "PKNAME", dev]).stdout.strip().splitlines()
    partn = executer(["lsblk", "-no", "PARTN", dev]).stdout.strip().splitlines()
    if not disque or not partn:
        return f"NOGO: disque/partition de {dev} non résolus, entrée {e['entree']} laissée telle quelle"
    r = executer(["efibootmgr", "-c", "-d", "/dev/" + disque[0].strip(), "-p", partn[0].strip(), "-L", NOM, "-l", e["chargeur"]])
    if r.returncode != 0:
        return f"NOGO: efibootmgr -c a échoué ({r.stderr.strip() or r.stdout.strip()}), entrée {e['entree']} conservée"
    apres = entrees_efi(executer(["efibootmgr", "-v"]).stdout)
    if not [x for x in deja_nommees(apres) if x["chargeur"].upper() == e["chargeur"].upper()]:
        return f"NOGO: la nouvelle entrée {NOM} n'apparaît pas, entrée {e['entree']} conservée"
    r = executer(["efibootmgr", "-B", "-b", e["entree"]])
    if r.returncode != 0:
        return f"WARN: entrée {NOM} créée, mais l'ancienne {e['entree']} « {e['libelle']} » n'a pas pu être retirée"
    return f"GO: entrée UEFI « {e['libelle']} » ({e['entree']}) recréée sous le nom {NOM}, chargeur {e['chargeur']}"


def appliquer_efi(executer=_run) -> list:
    if not shutil.which("efibootmgr") or not Path("/sys/firmware/efi").exists():
        return ["INFO: pas de firmware UEFI accessible (BIOS hérité ou conteneur) : entrée UEFI ignorée"]
    r = executer(["efibootmgr", "-v"])
    if r.returncode != 0:
        return [f"WARN: efibootmgr -v indisponible ({r.stderr.strip()}), entrée UEFI ignorée"]
    entrees = entrees_efi(r.stdout)
    cibles = a_renommer(entrees)
    if not cibles:
        nb = len(deja_nommees(entrees))
        return [f"OK: entrée UEFI déjà nommée {NOM}" if nb else "INFO: aucune entrée UEFI PinCabOS trouvée, rien à renommer"]
    if len(cibles) > 1:
        return ["WARN: plusieurs entrées UEFI pointent sur PINCABOS, renommage laissé à la main : "
                + ", ".join(f"{c['entree']} « {c['libelle']} »" for c in cibles)]
    return [renommer_entree_efi(cibles[0], executer)]


# ---------------------------------------------------------------- application
def _ecrire_si_different(path: Path, contenu: str, journal: list, libelle_fichier: str) -> bool:
    actuel = None
    if path.is_symlink():
        try:
            actuel = path.read_text(encoding="utf-8")
        except OSError:
            actuel = None
        path.unlink()
        journal.append(f"GO: {libelle_fichier} : lien symbolique remplacé par un fichier")
    elif path.exists():
        actuel = path.read_text(encoding="utf-8", errors="replace")
    if actuel == contenu:
        journal.append(f"OK: {libelle_fichier} déjà à jour")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenu, encoding="utf-8")
    journal.append(f"GO: {libelle_fichier} écrit")
    return True


# PINCABOS_NOM_MACHINE_V1
# Le systeme installe EST le rootfs live : il heritait donc de son nom,
# « pincabos-live ». Tous les cabinets sortis de l ISO portaient le meme, sur
# le reseau, dans les journaux, dans SSH et dans la WebApp (constate sur le cab
# de Yann le 08/09/2026 apres une installation complete). L installateur ne le
# corrigeait jamais : « grep hostname » sur son moteur ne renvoyait rien.
#
# Le nom vient de la carte reseau, seul identifiant stable qu une machine ait
# a l installation : pincabos-<6 derniers caracteres de la MAC>. Deux cabinets
# sur le meme reseau ne se marchent plus dessus.
NOMS_A_REMPLACER = {"", "pincabos-live", "localhost", "ubuntu", "ubuntu-server", "(none)"}


def mac_de_la_machine(base=Path("/sys/class/net")) -> str:
    """Les 6 derniers caracteres de la MAC de la premiere carte physique.

    Toujours lue sur la machine COURANTE, jamais sous --root : a l installation
    le script tourne depuis le live, la cible n a pas encore de /sys. C est le
    meme materiel, donc la meme carte.

    Les cartes virtuelles (docker, veth, bridges, ZeroTier) n ont pas de dossier
    « device » : elles sont ecartees, sinon le nom changerait au gre des
    conteneurs. Les filaires passent avant le sans-fil : une carte Wi-Fi peut
    etre absente d un cabinet a l autre.
    """
    try:
        cartes = sorted(p for p in base.iterdir() if p.name != "lo")
    except OSError:
        return ""
    def rang(p: Path) -> tuple:
        return (0 if p.name.startswith(("en", "eth")) else 1, p.name)
    for carte in sorted(cartes, key=rang):
        if not (carte / "device").exists():
            continue
        try:
            mac = (carte / "address").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        hexa = mac.replace(":", "").replace("-", "").lower()
        if len(hexa) >= 6 and hexa.strip("0"):
            return hexa[-6:]
    return ""


def nom_machine(mac=None) -> str:
    """pincabos-a865ed, ou chaine vide si aucune carte physique."""
    mac = mac_de_la_machine() if mac is None else mac
    return f"pincabos-{mac}" if mac else ""


def hosts_avec_nom(texte: str, nom: str) -> str:
    """La ligne 127.0.1.1 suit le nom ; le reste du fichier ne bouge pas."""
    lignes, vu = [], False
    for l in texte.splitlines():
        if l.split("#", 1)[0].strip().startswith("127.0.1.1"):
            if vu:
                continue
            lignes.append(f"127.0.1.1\t{nom}")
            vu = True
        else:
            lignes.append(l)
    if not vu:
        lignes.append(f"127.0.1.1\t{nom}")
    return "\n".join(lignes).rstrip("\n") + "\n"


def appliquer_nom(root: Path, journal: list) -> bool:
    """Nomme la machine, sauf si quelqu un lui a deja donne un vrai nom."""
    fichier = root / "etc/hostname"
    actuel = ""
    if fichier.exists():
        actuel = fichier.read_text(encoding="utf-8", errors="replace").strip()
    if actuel not in NOMS_A_REMPLACER:
        journal.append(f"INFO: nom de machine « {actuel} » conservé (choisi ailleurs)")
        return False
    nom = nom_machine()
    if not nom:
        journal.append("WARN: aucune carte réseau physique trouvée, nom de machine inchangé")
        return False
    change = _ecrire_si_different(fichier, nom + "\n", journal, "/etc/hostname")
    hosts = root / "etc/hosts"
    if hosts.exists():
        change |= _ecrire_si_different(
            hosts, hosts_avec_nom(hosts.read_text(encoding="utf-8", errors="replace"), nom),
            journal, "/etc/hosts (127.0.1.1)")
    if change:
        journal.append(f"GO: la machine s appelle « {nom} »")
    return change


def appliquer(root: Path = Path("/"), grub: bool = True, efi: bool = False, executer=_run) -> dict:
    journal, change = [], False
    version = version_info(root)
    if not version["version"]:
        journal.append("WARN: version PinCabOS inconnue (version.json absent) : libellé sans numéro")

    base_file = root / "usr/lib/os-release"
    etc_osr = root / "etc/os-release"
    base_text = ""
    if base_file.exists():
        base_text = base_file.read_text(encoding="utf-8", errors="replace")
    elif etc_osr.exists():
        base_text = etc_osr.read_text(encoding="utf-8", errors="replace")
    if not base_text:
        journal.append("NOGO: aucun os-release lisible, identité non appliquée")
        return {"journal": journal, "change": False}
    contenu = os_release_pincabos(base_text, version)
    base_pretty = sans_guillemets(dict(parse_kv(contenu)).get("PINCABOS_BASE", ""))
    change |= _ecrire_si_different(etc_osr, contenu, journal, "/etc/os-release")

    lsb = root / "etc/lsb-release"
    if lsb.exists():
        change |= _ecrire_si_different(lsb, lsb_release_pincabos(lsb.read_text(encoding="utf-8", errors="replace"), version, base_pretty), journal, "/etc/lsb-release")
    change |= _ecrire_si_different(root / "etc/issue", issue_pincabos(version), journal, "/etc/issue")
    change |= _ecrire_si_different(root / "etc/issue.net", issue_net_pincabos(version), journal, "/etc/issue.net")

    grub_file = root / "etc/default/grub"
    if grub_file.exists():
        avant = grub_file.read_text(encoding="utf-8", errors="replace")
        apres = grub_default_pincabos(avant)
        if _ecrire_si_different(grub_file, apres, journal, "/etc/default/grub (GRUB_DISTRIBUTOR)"):
            change = True
            if grub and root == Path("/"):
                r = executer(["update-grub"])
                journal.append("GO: update-grub exécuté, le menu GRUB dit PinCabOS" if r.returncode == 0
                               else f"WARN: update-grub a échoué ({r.stderr.strip()[-200:]})")
            elif grub:
                journal.append("INFO: update-grub laissé à l'installateur (racine différente de /)")
    else:
        journal.append("INFO: /etc/default/grub absent, menu GRUB non touché")

    change |= appliquer_nom(root, journal)

    if efi and root == Path("/"):
        journal.extend(appliquer_efi(executer))
    return {"journal": journal, "change": change, "libelle": libelle(version, base_pretty)}


def statut(root: Path = Path("/"), executer=_run) -> list:
    out = []
    version = version_info(root)
    out.append(f"version PinCabOS : {version['version'] or 'inconnue'}" + (f" ({version['codename']})" if version['codename'] else ""))
    osr = root / "etc/os-release"
    if osr.exists():
        d = dict(parse_kv(osr.read_text(encoding="utf-8", errors="replace")))
        out.append(f"os-release : NAME={sans_guillemets(d.get('NAME', ''))} PRETTY_NAME={sans_guillemets(d.get('PRETTY_NAME', ''))} ID={d.get('ID', '')}"
                   + (" (lien symbolique)" if osr.is_symlink() else ""))
    for f in ("etc/issue", "etc/issue.net"):
        p = root / f
        if p.exists():
            out.append(f"{f} : {p.read_text(encoding='utf-8', errors='replace').splitlines()[0] if p.read_text(encoding='utf-8', errors='replace').strip() else '(vide)'}")
    g = root / "etc/default/grub"
    if g.exists():
        m = re.search(r"^\s*GRUB_DISTRIBUTOR=(.*)$", g.read_text(encoding="utf-8", errors="replace"), re.M)
        out.append(f"GRUB_DISTRIBUTOR : {m.group(1) if m else '(absent)'}")
    if root == Path("/") and shutil.which("efibootmgr") and Path("/sys/firmware/efi").exists():
        r = executer(["efibootmgr", "-v"])
        for e in entrees_efi(r.stdout if r.returncode == 0 else ""):
            if EFI_DIR_MARQUEUR in e["chargeur"].upper():
                out.append(f"UEFI Boot{e['entree']} : « {e['libelle']} » -> {e['chargeur']}" + ("" if e["libelle"] == NOM else "   [à renommer]"))
    return out


USAGE = """usage : pincabos-identity status | apply [--efi] [--no-grub] [--root DIR]
  status     ce que le système affiche aujourd'hui (os-release, bannière, GRUB, entrée UEFI)
  apply      écrit os-release, lsb-release, issue, GRUB_DISTRIBUTOR (+ update-grub si changé)
  --efi      renomme aussi l'entrée de démarrage UEFI qui pointe sur \\EFI\\PINCABOS\\
  --no-grub  n'exécute pas update-grub
  --root DIR applique sur une arborescence (installation) : ni update-grub, ni UEFI
"""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    cmd, args = argv[0], argv[1:]
    root = Path("/")
    if "--root" in args:
        root = Path(args[args.index("--root") + 1])
    if cmd == "status":
        print("\n".join(statut(root)))
        return 0
    if cmd == "apply":
        res = appliquer(root, grub="--no-grub" not in args, efi="--efi" in args)
        print("\n".join(res["journal"]))
        if res.get("libelle"):
            print(f"identité : {res['libelle']}")
        return 0 if not any(l.startswith("NOGO") for l in res["journal"]) else 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
