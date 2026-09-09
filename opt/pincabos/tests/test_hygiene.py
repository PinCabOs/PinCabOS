"""Trois cliquets d'hygiène, issus de la revue du 10/09/2026.

Un cliquet ne demande pas de tout réparer aujourd'hui : il fige l'existant et
refuse que ça empire. Chacun des trois vient d'un piège qui a réellement mordu.

  doublons     26 902 lignes strictement identiques, 13 % du code. Le même
               programme en deux ou trois exemplaires : corriger l'un ne corrige
               pas les autres, et rien ne dit lequel s'exécute.
  rm -rf       36 fichiers effacent « $VAR » sans garde. J'ai écrit une de ces
               lignes le 09/09 avec une variable qui n'existait pas ; seul le
               « set -u » du script a évité le dégât.
  [Install]    l'unité de rotation du playfield vivait dans un .target.wants
               sans WantedBy — donc jamais démarrée. Flo a perdu ses écrans
               dans le bon sens pendant toute une soirée.
"""
import hashlib
import re
import subprocess
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
TESTS = R / "opt/pincabos/tests"
DOUBLONS = TESTS / "doublons-connus.txt"
RMRF = TESTS / "rm-rf-connus.txt"
ISO_LIVE = R / "opt/pincabos/script/iso-live.sh"


def _lignes(fichier):
    return [l.strip() for l in fichier.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _fichiers_de_code():
    suivis = subprocess.run(["git", "-C", str(R), "ls-files"],
                            capture_output=True, text=True).stdout.splitlines()
    out = []
    for f in suivis:
        p = R / f
        if not p.is_file():
            continue
        if f.endswith((".py", ".sh")):
            out.append(f)
        else:
            try:
                if p.open("rb").read(2) == b"#!":
                    out.append(f)
            except OSError:
                pass
    return out


class PasDeNouveauDoublon(unittest.TestCase):
    """PINCABOS_PAS_DE_NOUVEAU_DOUBLON_V1 — la liste ne doit que rétrécir."""

    @classmethod
    def setUpClass(cls):
        par_somme = {}
        for f in _fichiers_de_code():
            h = hashlib.sha256((R / f).read_bytes()).hexdigest()[:16]
            par_somme.setdefault(h, []).append(f)
        cls.reels = {" ".join(sorted(v)) for v in par_somme.values() if len(v) > 1}
        cls.connus = set(_lignes(DOUBLONS))

    def test_la_base_existe(self):
        self.assertTrue(DOUBLONS.is_file(), "la base de reference manque")

    def test_aucun_groupe_nouveau(self):
        nouveaux = sorted(self.reels - self.connus)
        self.assertEqual(nouveaux, [],
                         "copie(s) au lieu de lien(s) symbolique(s) :\n  "
                         + "\n  ".join(nouveaux))

    def test_les_groupes_resolus_sortent_de_la_base(self):
        # echec volontairement agreable : quelqu un vient de dedupliquer
        resolus = sorted(self.connus - self.reels)
        self.assertEqual(resolus, [],
                         "ces groupes ne sont plus dupliques — retirez leur ligne "
                         "de doublons-connus.txt :\n  " + "\n  ".join(resolus))


class PasDeNouveauRmRf(unittest.TestCase):
    """PINCABOS_PAS_DE_NOUVEAU_RM_RF_V1 — « rm -rf "$VIDE"/x » efface /x."""

    MOTIF = re.compile(r'rm\s+-rf\s+"?\$(?!\{[A-Za-z_]+:[?-])')

    @classmethod
    def setUpClass(cls):
        cls.reels = {f for f in _fichiers_de_code()
                     if cls.MOTIF.search((R / f).read_text(encoding="utf-8",
                                                           errors="replace"))}
        cls.connus = set(_lignes(RMRF))

    def test_aucun_fichier_nouveau(self):
        nouveaux = sorted(self.reels - self.connus)
        self.assertEqual(nouveaux, [],
                         "utilisez \"${VAR:?}\" — une variable vide efface la racine :\n  "
                         + "\n  ".join(nouveaux))

    def test_les_fichiers_corriges_sortent_de_la_base(self):
        resolus = sorted(self.connus - self.reels)
        self.assertEqual(resolus, [],
                         "corrige(s) — retirez leur ligne de rm-rf-connus.txt :\n  "
                         + "\n  ".join(resolus))


class ToutCeQuiEstActiveEstActivable(unittest.TestCase):
    """Aucune tolérance ici : le contrôle passe déjà strictement.

    Une unité posée dans un `*.target.wants/` sans `WantedBy` correspondant n'est
    pas démarrée par cette cible — c'est le défaut exact de
    pincabos-screen-hotplug, qui laissait le playfield à l'envers."""

    def test_chaque_lien_a_son_WantedBy(self):
        soucis = []
        for lien in sorted((R / "etc/systemd/system").glob("*.target.wants/*")):
            cible_nom = lien.parent.name.replace(".wants", "")
            unite = (lien.parent / lien.readlink()) if lien.is_symlink() else lien
            if not unite.is_file():
                soucis.append("%s/%s : cible absente" % (lien.parent.name, lien.name))
                continue
            texte = unite.read_text(encoding="utf-8", errors="replace")
            if not re.search(r"(?m)^WantedBy=.*\b%s\b" % re.escape(cible_nom), texte):
                soucis.append("%s/%s : pas de WantedBy=%s"
                              % (lien.parent.name, lien.name, cible_nom))
        self.assertEqual(soucis, [], "\n  " + "\n  ".join(soucis))

    def test_reciproque_toute_unite_qui_se_declare_est_liee(self):
        """PINCABOS_UNITE_DECLAREE_SANS_LIEN_V1 — cliquet, pas règle stricte.

        Onze unités déclarent `WantedBy=` sans lien d'activation. Elles ne sont
        donc pas démarrées par la cible qu'elles nomment. Certaines le sont
        autrement — `pincabos-dudescab-hotplug-recovery` par une règle udev,
        `pincabos-splash-sync` par un `.path` du même nom, les trois
        `firstboot-*` par un appel direct de l'installateur. D'autres, non :
        `safe-batch-full`, `scoreview-x11-hq-preview` et `table-test` ne sont
        appelées de nulle part.

        Trancher au cas par cas demande de savoir ce que chaque unité doit
        faire ; ce test se contente d'empêcher la liste de grandir."""
        reels = set()
        for unite in sorted((R / "etc/systemd/system").glob("*.service")):
            m = re.search(r"(?m)^WantedBy=(\S+)", unite.read_text(encoding="utf-8",
                                                                  errors="replace"))
            if not m:
                continue
            for cible in m.group(1).split():
                if not (R / "etc/systemd/system" / (cible + ".wants") / unite.name).exists():
                    reels.add("%s %s" % (unite.name, cible))
        connus = set(_lignes(TESTS / "unites-sans-lien.txt"))
        nouvelles = sorted(reels - connus)
        self.assertEqual(nouvelles, [],
                         "declaree(s) sans lien : elles ne demarreront pas.\n  "
                         + "\n  ".join(nouvelles))
        reglees = sorted(connus - reels)
        self.assertEqual(reglees, [],
                         "reglee(s) — retirez leur ligne de unites-sans-lien.txt :\n  "
                         + "\n  ".join(reglees))


class LImageNEmportePasNosBrouillons(unittest.TestCase):
    """PINCABOS_IMAGE_SANS_BROUILLONS_V1 — 11 039 lignes de scripts de travail et
    les notes de DEV/ partaient sur chaque cabinet."""

    def test_les_exclusions_sont_posees(self):
        s = ISO_LIVE.read_text(encoding="utf-8")
        for motif in ('"root/pincab-*"', '"root/pincabos-*"', '"DEV" "DEV/*"'):
            self.assertIn(motif, s, motif + " n'est pas exclu de l'image")

    def test_ce_qui_appartient_a_root_reste(self):
        # .bashrc, .profile et .ssh sont legitimes : on n'exclut pas root/ en bloc
        s = ISO_LIVE.read_text(encoding="utf-8")
        self.assertNotRegex(s, r'"root"\s+"root/\*"',
                            "exclure root/ en bloc emporterait .ssh et .profile")
