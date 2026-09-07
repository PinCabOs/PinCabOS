"""Le manifest apt ne nomme aucun noyau precis (PINCABOS_MASTER_NOYAU_UNIQUE_V1).

Trouve le 08/09/2026 : le master portait CINQ noyaux (7.0.0-22, 27, 28, 29, 31),
soit ~750 Mo dans l'ISO. La cause etait ici — build-master.sh ne lit que la
COLONNE DU NOM du manifest (les versions y sont indicatives), donc chaque ligne
« linux-image-7.0.0-28-generic » ramenait un noyau entier a la reconstruction.

Les metapaquets (linux-image-generic, linux-headers-generic, linux-generic)
suffisent : apt installe le noyau le plus recent, un seul, et la machine reste
a jour sans que le manifest ait a etre retouche.
"""
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
MANIFEST = R / "opt/pincabos/system-manifests/apt-packages.tsv"
SLIM = R / "opt/pincabos/script/slim-master.sh"

# linux-image-7.0.0-28-generic, linux-modules-…, linux-headers-…, linux-tools-…,
# linux-main-modules-zfs-… : tout nom de paquet qui porte une version de noyau.
FIGE = re.compile(r"^linux-[a-z-]*-\d+\.\d+\.\d+-\d+(-generic)?\b")

# Ceux-la doivent rester : ce sont eux qui suivent le noyau courant.
META = {"linux-generic", "linux-image-generic", "linux-headers-generic",
        "linux-libc-dev:amd64", "linux-base"}


def noms() -> list:
    return [l.split("\t")[0] for l in MANIFEST.read_text(encoding="utf-8").splitlines() if l.strip()]


class ManifestSansNoyauFige(unittest.TestCase):
    def test_aucun_paquet_ne_nomme_un_noyau(self):
        figes = [n for n in noms() if FIGE.match(n)]
        self.assertEqual(figes, [], "chacun de ces paquets ramene un noyau entier "
                                    "a la reconstruction du master")

    def test_les_metapaquets_restent(self):
        presents = set(noms())
        for m in META:
            self.assertIn(m, presents, f"{m} : sans lui le master n a plus de noyau du tout")

    def test_le_manifest_reste_lisible(self):
        """build-master.sh fait awk -F'\t' '{print $1}' : une ligne sans nom le casse."""
        for i, n in enumerate(noms(), 1):
            self.assertTrue(n and not n.startswith(("#", " ")), f"ligne {i} : « {n} »")


class SlimMasterProtegeLaRacine(unittest.TestCase):
    """PINCABOS_MASTER_ALLEGE_V1 : ce script purge des noyaux. Le lancer sur un
    cab en fonctionnement le rendrait indemarrable."""

    def setUp(self):
        self.s = SLIM.read_text(encoding="utf-8")

    def test_refus_de_la_racine(self):
        self.assertIn('[ "$M" = "/" ] && { echo "ERREUR: refus de travailler sur /', self.s)

    def test_verifie_que_c_est_un_master_pincabos(self):
        self.assertIn('[ -x "$M/usr/bin/dpkg" ]', self.s)
        self.assertIn('[ -d "$M/opt/pincabos" ]', self.s)

    def test_ne_purge_que_les_paquets_installes(self):
        """dpkg-query liste aussi les paquets connus mais absents : apt echouerait."""
        self.assertIn("db:Status-Abbrev", self.s)
        self.assertIn("$1 ~ /^[ih]i/", self.s)

    def test_garde_les_copyright(self):
        """L image est redistribuee : les licences restent."""
        self.assertIn("! -name copyright -delete", self.s)

    def test_garde_les_langues_de_l_installateur(self):
        for langue in ("fr", "en", "de", "it", "es"):
            self.assertRegex(self.s, rf"LANGUES=.*\b{langue}\b")


if __name__ == "__main__":
    unittest.main()
