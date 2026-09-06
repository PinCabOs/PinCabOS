"""PINCABOS_INI_APLATI_V1 : un INI ne doit jamais etre colle sur une seule ligne.

Cab de Yann, 06/09/2026, « no tables found » : la page Audio lisait vpinfe.ini avec
splitlines() (lignes sans fin de ligne) puis les recollait avec "" — tout le fichier
sur une ligne, plus aucune section lisible. VPinFE le reecrivait alors avec ses
valeurs par defaut : tablerootdir vide, bibliotheque vide.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE

R = Path(RACINE)
pi = charger("opt/pincabos/tools/pincabos_ini.py", "pco_ini_aplati")
OUTIL = R / "usr/local/sbin/pincabos-reparer-ini-aplati"

INI = """[Displays]
tablescreenid = 0
cabmode = true

[Settings]
vpxbinpath = /opt/pincabos/launchers/pincabos-launch-hybrid.sh
tablerootdir = /home/pinball/Tables
theme = PinCabOS
chromeoptions = --force-dark-mode
disabledefaultchromeoptions = false
muteaudio = true

[DOF]
enabledof = true
"""


class LaCause(unittest.TestCase):
    """La page Audio : lignes sans fin de ligne des deux cotes."""

    def test_ecriture_de_la_page_audio(self):
        s = (R / "opt/pincabos/web/pincabos_webapp_audio.py").read_text(encoding="utf-8")
        self.assertIn('ini = pincabos_ini.Ini("\\n".join(lines))', s)
        self.assertNotIn('pincabos_ini.Ini("".join(lines))', s, "les lignes n'ont pas de fin de ligne")
        self.assertIn("return list(ini.lignes)", s)

    def test_aller_retour_page_audio(self):
        """Le trajet exact de la page : read_text().splitlines() -> pose -> "\n".join."""
        lignes = INI.splitlines()
        ini = pi.Ini("\n".join(lignes))
        ini.poser("Settings", "muteaudio", "false")
        sortie = "\n".join(list(ini.lignes)).rstrip() + "\n"
        self.assertFalse(pi.est_aplati(sortie), sortie[:200])
        self.assertEqual(len(sortie.splitlines()), len(INI.splitlines()))
        self.assertIn("tablerootdir = /home/pinball/Tables", sortie)
        self.assertIn("muteaudio = false", sortie)


class LeGardeFou(unittest.TestCase):
    def test_detection(self):
        self.assertFalse(pi.est_aplati(INI))
        self.assertFalse(pi.est_aplati(""))
        self.assertTrue(pi.est_aplati(INI.replace("\n", "")))
        # une valeur qui contient des crochets n'est pas un fichier aplati
        self.assertFalse(pi.est_aplati("[Settings]\nmask = [a][b]\n"))

    def test_ecriture_refusee(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "vpinfe.ini")
            p.write_text(INI, encoding="utf-8")
            with self.assertRaises(ValueError):
                pi.ecrire_texte(p, INI.replace("\n", ""))
            self.assertEqual(p.read_text(encoding="utf-8"), INI, "le fichier reste intact")
            self.assertTrue(pi.ecrire_texte(p, INI.replace("theme = PinCabOS", "theme = Revolution")))


class LaReparation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ini = self.tmp / "vpinfe.ini"
        # l'etat reel du cab : la ligne collee, puis ce que VPinFE a reecrit par defaut
        self.ini.write_text(INI.replace("\n", "") + "\n\n[Settings]\nmuteaudio = false\ntablerootdir = \n"
                            "theme = Revolution\nnouveaute = 1\n", encoding="utf-8")

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def lancer(self, *args):
        return subprocess.run([sys.executable, str(OUTIL), str(self.ini), *args], capture_output=True, text=True)

    def test_essai_a_blanc_puis_ecriture(self):
        self.assertTrue(os.access(OUTIL, os.X_OK))
        avant = self.ini.read_text(encoding="utf-8")
        r = self.lancer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tablerootdir = /home/pinball/Tables", r.stdout)
        self.assertEqual(self.ini.read_text(encoding="utf-8"), avant, "a blanc : rien n'est ecrit")

        r = self.lancer("--ecrire")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        texte = self.ini.read_text(encoding="utf-8")
        self.assertFalse(pi.est_aplati(texte))
        ini = pi.Ini(texte)
        self.assertEqual(ini.get("Settings", "tablerootdir"), "/home/pinball/Tables")
        self.assertEqual(ini.get("Settings", "theme"), "PinCabOS", "la valeur de l'utilisateur, pas le defaut")
        self.assertEqual(ini.get("Settings", "chromeoptions"), "--force-dark-mode",
                         "une valeur qui ressemble a une cle ne doit pas etre coupee")
        self.assertEqual(ini.get("Settings", "disabledefaultchromeoptions"), "false")
        self.assertEqual(ini.get("Settings", "muteaudio"), "true",
                         "la valeur de l'ancien fichier fait foi ; la reecriture n'apporte que les cles absentes")
        self.assertEqual(ini.get("Settings", "nouveaute"), "1", "cle absente de l'ancien fichier : gardee")
        self.assertEqual(ini.get("DOF", "enabledof"), "true")
        self.assertTrue((self.tmp / "vpinfe.ini.aplati").is_file(), "ancien fichier conserve")

    def test_section_repetee_derniere_valeur(self):
        """Le fichier du cab avait trois [Settings] a la suite des ecritures : c'est la
        derniere valeur que lit un parseur d'INI, donc celle qu'on garde."""
        self.ini.write_text((INI + "\n[Settings]\nmuteaudio = false\n").replace("\n", ""), encoding="utf-8")
        r = self.lancer("--ecrire")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ini = pi.Ini(self.ini.read_text(encoding="utf-8"))
        self.assertEqual(ini.get("Settings", "muteaudio"), "false")
        self.assertEqual(ini.get("Settings", "tablerootdir"), "/home/pinball/Tables")
        self.assertEqual(len([l for l in self.ini.read_text(encoding="utf-8").splitlines()
                              if l.strip() == "[Settings]"]), 1, "sections fusionnees")

    def test_texte_inconnu_rien_ecrit(self):
        self.ini.write_text("[Settings]cleinconnuedumodele = 1inventee = 2", encoding="utf-8")
        r = self.lancer("--ecrire")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOGO", r.stdout)
        self.assertFalse((self.tmp / "vpinfe.ini.aplati").exists())

    def test_fichier_sain_intact(self):
        self.ini.write_text(INI, encoding="utf-8")
        r = self.lancer("--ecrire")
        self.assertEqual(r.returncode, 1)
        self.assertIn("aucune ligne aplatie", r.stdout)
        self.assertEqual(self.ini.read_text(encoding="utf-8"), INI)


class LeDoctor(unittest.TestCase):
    def test_detection_et_reparation(self):
        s = (R / "usr/local/libexec/pincabos/doctor.d/70-vpinfe.sh").read_text(encoding="utf-8")
        self.assertIn("pincabos-reparer-ini-aplati", s)
        self.assertIn("pco_repairing", s)
        self.assertEqual(subprocess.run(["bash", "-n", str(R / "usr/local/libexec/pincabos/doctor.d/70-vpinfe.sh")]).returncode, 0)

    def test_perimetre_ota(self):
        sys.path.insert(0, str(R / "opt/pincabos/update"))
        import pincabos_updates as up
        self.assertTrue(up.allowed("usr/local/sbin/pincabos-reparer-ini-aplati"))
        self.assertTrue(up.allowed("opt/pincabos/tools/pincabos_ini.py"))


if __name__ == "__main__":
    unittest.main()
