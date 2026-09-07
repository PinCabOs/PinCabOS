"""Dossiers de production : un nom stable, la version dans un fichier (PINCABOS_RUNTIME_ROTATION_V1).

Decision de Yann (07/09/2026) : /opt/pinball/vpx et /opt/pinball/vpinfe portent
leur nom, jamais leur version. La reversibilite vient d une rotation de noms
(vpx, vpx.bak, vpx.bak2) et non plus d un lien symbolique vers un dossier
versionne.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _charge import charger

RACINE = Path(__file__).resolve().parents[3]

r = charger("opt/pincabos/tools/pincabos_runtimes.py", "pco_runtimes")


def poser_dossier(chemin: Path, marque: str) -> Path:
    chemin.mkdir(parents=True)
    (chemin / "binaire").write_text(marque, encoding="utf-8")
    return chemin


class Version(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ecrit_et_relit(self):
        d = poser_dossier(self.tmp / "vpx", "v1")
        r.ecrire_version(d, "10.8.1-5436-af26b2d93", source="https://x/a.tar.gz",
                         sha256="ab" * 32, pose_par="pincabos-vpx-update")
        self.assertEqual(r.version_de(d), "10.8.1-5436-af26b2d93")
        valeur = r.lire_version(d)
        self.assertEqual(valeur["schema"], "pincabos.runtime-version/1")
        self.assertEqual(valeur["composant"], "vpx")
        self.assertEqual(valeur["pose_par"], "pincabos-vpx-update")
        self.assertTrue(valeur["pose_le"].endswith("Z"))
        self.assertEqual((self.tmp / "vpx" / ".pincabos-version").exists(), True)

    def test_version_inconnue_ne_leve_pas(self):
        d = poser_dossier(self.tmp / "vpinfe", "x")
        self.assertEqual(r.version_de(d), "")
        self.assertEqual(r.lire_version(d), {})
        self.assertEqual(r.version_de(self.tmp / "absent"), "")

    def test_fichier_illisible_ne_leve_pas(self):
        d = poser_dossier(self.tmp / "vpx", "x")
        (d / ".pincabos-version").write_text("{pas du json", encoding="utf-8")
        self.assertEqual(r.version_de(d), "")


class Rotation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cible = self.tmp / "vpx"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def contenu(self, chemin):
        p = Path(chemin) / "binaire"
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def test_trois_mises_a_jour_gardent_deux_precedentes(self):
        poser_dossier(self.cible, "v1")
        for version in ("v2", "v3", "v4"):
            nouveau = poser_dossier(self.tmp / "vpx.new", version)
            r.poser(self.cible, nouveau)
            self.assertFalse(nouveau.exists(), "le dossier pose est consomme")
        self.assertEqual(self.contenu(self.cible), "v4")
        self.assertEqual(self.contenu(self.tmp / "vpx.bak"), "v3")
        self.assertEqual(self.contenu(self.tmp / "vpx.bak2"), "v2")
        # la plus ancienne est bien partie, et rien ne traine
        self.assertFalse((self.tmp / "vpx.bak3").exists())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["vpx", "vpx.bak", "vpx.bak2"])

    def test_premiere_pose_sans_cible_existante(self):
        nouveau = poser_dossier(self.tmp / "vpx.new", "v1")
        r.poser(self.cible, nouveau)
        self.assertEqual(self.contenu(self.cible), "v1")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["vpx"])

    def test_retour_arriere(self):
        poser_dossier(self.cible, "v1")
        for version in ("v2", "v3"):
            r.poser(self.cible, poser_dossier(self.tmp / "vpx.new", version))
        r.revenir(self.cible)
        self.assertEqual(self.contenu(self.cible), "v2", "on revient a la precedente")
        self.assertEqual(self.contenu(self.tmp / "vpx.bak"), "v1")
        self.assertFalse((self.tmp / "vpx.bak2").exists())
        # deux retours de suite : on remonte jusqu au plus ancien conserve
        r.revenir(self.cible)
        self.assertEqual(self.contenu(self.cible), "v1")
        with self.assertRaises(r.RotationError):
            r.revenir(self.cible)

    def test_ancien_lien_symbolique_remplace(self):
        """Migration : la cible etait un lien vers un dossier versionne."""
        bundle = poser_dossier(self.tmp / "VPinballX_BGFX-10.8.1-linux-x64", "ancien")
        self.cible.symlink_to(bundle.name)
        r.poser(self.cible, poser_dossier(self.tmp / "vpx.new", "neuf"))
        self.assertFalse(self.cible.is_symlink())
        self.assertEqual(self.contenu(self.cible), "neuf")
        self.assertFalse((self.tmp / "vpx.bak").exists(), "un lien ne devient pas une sauvegarde")
        self.assertTrue(bundle.is_dir(), "le bundle d origine n est pas detruit")

    def test_refus_si_dossier_absent(self):
        with self.assertRaises(r.RotationError):
            r.poser(self.cible, self.tmp / "nulle-part")

    def test_refus_si_on_pose_la_cible_sur_elle_meme(self):
        poser_dossier(self.cible, "v1")
        with self.assertRaises(r.RotationError):
            r.poser(self.cible, self.cible)

    def test_etat_lisible(self):
        poser_dossier(self.cible, "v1")
        r.ecrire_version(self.cible, "1.0")
        r.poser(self.cible, poser_dossier(self.tmp / "vpx.new", "v2"))
        r.ecrire_version(self.cible, "2.0")
        etat = r.etat(self.cible)
        self.assertEqual(etat["version"], "2.0")
        self.assertTrue(etat["presente"])
        self.assertEqual([s["version"] for s in etat["sauvegardes"]], ["1.0"])


class LecteursDeVersion(unittest.TestCase):
    """Les consommateurs lisent .pincabos-version, plus le nom du dossier.

    La page VPX et PinCabOS Link portent chacun leur copie de _version_posee
    (aucun des deux ne peut importer les outils du cab depuis le banc) : on
    execute la copie reelle de chaque fichier, pas une reecriture du test.
    """

    FICHIERS = (
        "opt/pincabos/web/pincabos_pinball_engine_vpx_version.py",
        "opt/pincabos/bin/pincabos-link",
    )

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def lecteur(self, fichier):
        texte = Path(RACINE, fichier).read_text(encoding="utf-8")
        debut = texte.index("def _version_posee(")
        fin = texte.index("\ndef ", debut + 1)
        espace = {"Path": Path}
        exec(compile(texte[debut:fin], fichier, "exec"), espace)
        return espace["_version_posee"]

    def test_lit_le_fichier_de_version(self):
        dossier = poser_dossier(self.tmp / "vpx", "bin")
        r.ecrire_version(dossier, "10.8.1-5436-af26b2d93", composant="vpx")
        for fichier in self.FICHIERS:
            with self.subTest(fichier=fichier):
                self.assertEqual(self.lecteur(fichier)(dossier), "10.8.1-5436-af26b2d93")

    def test_silencieux_sans_fichier_ni_dossier(self):
        nu = poser_dossier(self.tmp / "nu", "bin")
        (self.tmp / "casse").mkdir()
        (self.tmp / "casse/.pincabos-version").write_text("{pas du json", encoding="utf-8")
        for fichier in self.FICHIERS:
            with self.subTest(fichier=fichier):
                lire = self.lecteur(fichier)
                self.assertEqual(lire(nu), "", "dossier sans etiquette")
                self.assertEqual(lire(self.tmp / "absent"), "", "dossier absent")
                self.assertEqual(lire(self.tmp / "casse"), "", "etiquette illisible")


if __name__ == "__main__":
    unittest.main()
