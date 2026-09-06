"""pincabos_paths : la source de verite des chemins et de l'identite machine."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from _charge import charger, RACINE

pp = charger("opt/pincabos/tools/pincabos_paths.py", "pco_paths")


class Defauts(unittest.TestCase):
    def test_la_realite_d_un_cabinet(self):
        d = pp.defaults("pinball")
        self.assertEqual(d["tables"], "/home/pinball/Tables")
        self.assertEqual(d["vpx_bin"], "/opt/pinball/vpx/VPinballX_BGFX")
        self.assertEqual(d["vpx_ini"], "/home/pinball/.pincabos/vpx/VPinballX.ini")
        self.assertEqual(d["vpx_legacy_pref"], "/home/pinball/.local/share/VPinballX/10.8")
        self.assertEqual(d["vpinfe_ini"], "/home/pinball/.config/vpinfe/vpinfe.ini")
        self.assertEqual(d["aliases_env"], "/opt/pincabos/config/display-aliases.env")
        self.assertEqual(d["cabinet_xml"], "/home/pinball/.pincabos/vpx/directoutputconfig/cabinet.xml")

    def test_identite_derivee_de_l_utilisateur(self):
        d = pp.defaults("pinball")
        self.assertEqual(d["runtime_dir"], f"/run/user/{d['uid']}")
        self.assertEqual(d["dbus_address"], f"unix:path=/run/user/{d['uid']}/bus")
        self.assertEqual(d["xauthority"], d["home"] + "/.Xauthority")

    def test_utilisateur_inconnu_retombe_sur_1000(self):
        d = pp.defaults("pinball-inexistant-xyz")
        self.assertEqual((d["uid"], d["gid"], d["home"]), ("1000", "1000", "/home/pinball-inexistant-xyz"))


class Chargement(unittest.TestCase):
    def ecrire(self, data):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "pincabos-paths.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return p

    def test_fichier_absent_ou_invalide(self):
        self.assertEqual(pp.load("/nulle/part.json")["tables"], "/home/pinball/Tables")
        p = self.ecrire(None)
        open(p, "w").write("{pas du json")
        self.assertEqual(pp.load(p)["tables"], "/home/pinball/Tables")

    def test_ancien_schema_ne_garde_que_les_cles_vraies(self):
        p = self.ecrire({
            "created_by": "Karots Sugarpie",
            "paths": {"vpx_dir": "/opt/pincabos/apps/vpinball", "vpx_ini": "/home/pinball/.vpinball/VPinballX.ini",
                      "tables": "/home/pinball/Tables", "logs": "/opt/pincabos/logs"},
        })
        v = pp.load(p)
        self.assertEqual(v["vpx_ini"], "/home/pinball/.pincabos/vpx/VPinballX.ini")
        self.assertNotIn("vpx_dir", v)
        self.assertEqual(v["logs"], "/opt/pincabos/logs")

    def test_schema_2_surcharge_cle_par_cle(self):
        p = self.ecrire({"schema": "pincabos.paths/2", "paths": {"tables": "/mnt/pincabos/tables", "display": ":1"}})
        v = pp.load(p)
        self.assertEqual(v["tables"], "/mnt/pincabos/tables")
        self.assertEqual(v["display"], ":1")
        self.assertEqual(v["vpx_bin"], "/opt/pinball/vpx/VPinballX_BGFX")

    def test_valeur_vide_ignoree(self):
        p = self.ecrire({"schema": "pincabos.paths/2", "paths": {"tables": ""}})
        self.assertEqual(pp.load(p)["tables"], "/home/pinball/Tables")


class Exports(unittest.TestCase):
    def test_format_shell(self):
        out = pp.shell_exports({"tables": "/home/pinball/Tables", "bizarre": "un chemin 'avec' espace"})
        self.assertIn("export PCO_TABLES=/home/pinball/Tables\n", out)
        self.assertIn("export PCO_BIZARRE='un chemin '\"'\"'avec'\"'\"' espace'\n", out)
        self.assertTrue(out.endswith("export PCO_PATHS_LOADED=1\n"))

    def test_cli(self):
        script = os.path.join(RACINE, "opt/pincabos/tools/pincabos_paths.py")
        out = subprocess.run([sys.executable, script, "get", "vpx_pref"], capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "/home/pinball/.pincabos/vpx")
        bad = subprocess.run([sys.executable, script, "get", "inconnue"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        sh = subprocess.run([sys.executable, script, "--shell"], capture_output=True, text=True)
        self.assertIn("export PCO_VPX_BIN=", sh.stdout)

    def test_objet_en_lecture_seule(self):
        with self.assertRaises(AttributeError):
            pp.PATHS.tables = "/ailleurs"
        self.assertEqual(pp.PATHS.get("cle-inconnue", "x"), "x")


if __name__ == "__main__":
    unittest.main()


class Consommateurs(unittest.TestCase):
    """Regression 3.25 : `. /opt/pincabos/tools/pincabos-paths.shset -Eeuo pipefail`
    (retour a la ligne perdu au portage). Le source echouait en silence, les
    PCO_* restaient vides : pont backglass en boucle sur `find ''`, hotplug HS."""

    def test_chaque_source_est_seul_sur_sa_ligne(self):
        import re
        motif = re.compile(r"pincabos-paths\.sh[^\s\"'\)\]]")
        fautifs = []
        for dossier in ("opt", "usr", "etc"):
            for racine, _, fichiers in os.walk(os.path.join(RACINE, dossier)):
                if racine.startswith(os.path.join(RACINE, "opt", "pincabos", "tests")):
                    continue
                for nom in fichiers:
                    chemin = os.path.join(racine, nom)
                    try:
                        with open(chemin, "rb") as f:
                            if b"\0" in f.read(4096):
                                continue  # binaire
                        with open(chemin, encoding="utf-8", errors="ignore") as f:
                            for num, ligne in enumerate(f, 1):
                                if "pincabos-paths.sh" in ligne and motif.search(ligne):
                                    fautifs.append(f"{os.path.relpath(chemin, RACINE)}:{num}: {ligne.strip()}")
                    except OSError:
                        continue
        self.assertEqual(fautifs, [])
