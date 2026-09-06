"""Étape « Toys / LED » de l'assistant (PINCABOS_INSTALLEUR_TOYS_V1).

Contrôleurs de rubans (Teensy, Wemos) déclarés en matrice ou en rubans,
inventaire de la page DOF, cabinet.xml généré par dof-cabinet (toys multiples).
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE, texte_installateur

R = Path(RACINE)
pd = charger("opt/pincabos/tools/pincabos_dof.py", "pco_dof_toys_mod")
DET = [
    {"dev": "/dev/hidraw5", "vid": "2e8a", "model": "DudesCab", "serial": "DE64", "kind": "DudesCab", "auto_config": True},
    {"dev": "/dev/ttyACM0", "vid": "16c0", "model": "USB_Serial", "serial": "15672630", "kind": "TeensyStripController (strip adressable)", "auto_config": False},
    {"dev": "/dev/ttyUSB0", "vid": "10c4", "model": "CP2104", "serial": "01AA5AA5", "kind": "Wemos D1 / ESP via CP210x (WemosD1MPStripController possible)", "auto_config": False},
]


class Declaration(unittest.TestCase):
    def test_tri_des_cartes(self):
        self.assertEqual([c["type"] for c in pd.controleurs_de_rubans(DET)], ["TeensyStripController", "WemosD1MPStripController"])
        self.assertEqual([c["kind"] for c in pd.cartes_auto(DET)], ["DudesCab"])

    def test_repartition_et_proposition(self):
        self.assertEqual(pd.repartir(144 * 16), [512, 512, 512, 512, 256])     # le backboard de Yann
        self.assertEqual(pd.repartir(0), [])
        p = pd.proposer_toys(DET)["controllers"]
        self.assertEqual((p[0]["mode"], p[0]["width"], p[0]["height"], p[0]["ledwiz_number"]), ("matrice", 144, 16, 30))
        self.assertEqual((p[1]["mode"], p[1]["strips"], p[1]["ledwiz_number"]), ("rubans", [144], 31))

    def test_validation(self):
        p = pd.proposer_toys(DET)
        self.assertEqual(pd.valider_toys(p, DET)[0], [])
        mauvais = json.loads(json.dumps(p)); mauvais["controllers"][0]["strips"] = [512, 512]
        self.assertTrue(any("2304" in e for e in pd.valider_toys(mauvais, DET)[0]))
        mauvais = json.loads(json.dumps(p)); mauvais["controllers"][1]["strips"] = [0, 0]
        self.assertTrue(any("aucun ruban" in e for e in pd.valider_toys(mauvais, DET)[0]))
        mauvais = json.loads(json.dumps(p)); mauvais["controllers"][0]["serial"] = "INCONNU"
        self.assertTrue(any("inconnue" in e for e in pd.valider_toys(mauvais, DET)[0]))
        mauvais = json.loads(json.dumps(p)); mauvais["controllers"][0]["arrangement"] = "Diagonal"
        self.assertTrue(pd.valider_toys(mauvais, DET)[0])
        self.assertTrue(pd.valider_toys("rien", DET)[0])

    def test_inventaire(self):
        _, ok = pd.valider_toys(pd.proposer_toys(DET), DET)
        inv = pd.inventaire_json(ok, DET)
        d0, d1 = inv["devices"]
        self.assertEqual((d0["type"], d0["serial"], d0["leds_per_strip"][:5], d0["toy"]["name"], d0["ledwiz_outputs"]),
                         ("TeensyStripController", "15672630", [512, 512, 512, 512, 256], "Backboard HD", 9))
        self.assertEqual(len(d0["leds_per_strip"]), 10)
        self.assertEqual((d1["type"], d1["toys"][0]["width"], d1["toys"][0]["height"], d1["toys"][0]["first_led"], d1["ledwiz_outputs"]),
                         ("WemosD1MPStripController", 144, 1, 1, 1))
        cfg = pd.config_dof_cabinet(inv)
        self.assertEqual(len(cfg["strips"]), 2)
        self.assertEqual(cfg["strips"][1]["toys"][0]["name"], "Ruban 2.1")

    def test_rubans_plusieurs_sorties(self):
        choix = {"controllers": [{"serial": "01AA5AA5", "mode": "rubans", "strips": [60, 0, 30], "enabled": True}]}
        e, ok = pd.valider_toys(choix, DET)
        self.assertEqual(e, [])
        inv = pd.inventaire_json(ok, DET)
        toys = inv["devices"][0]["toys"]
        self.assertEqual([(t["name"], t["width"], t["first_led"]) for t in toys], [("Ruban 1.1", 60, 1), ("Ruban 1.2", 30, 61)])


class CabinetXml(unittest.TestCase):
    def test_gen_toys_multiples(self):
        mod = pd.outil(R / "opt/pincabos/tools/dof-cabinet/dof-cabinet.py")
        _, ok = pd.valider_toys({"controllers": [
            {"serial": "15672630", "mode": "matrice", "width": 144, "height": 16, "strips": [512, 512, 512, 512, 256], "enabled": True},
            {"serial": "01AA5AA5", "mode": "rubans", "strips": [60, 30], "enabled": True}]}, DET)
        cfg = pd.config_dof_cabinet(pd.inventaire_json(ok, DET))
        cfg["strips"][0]["com_port"] = "/dev/ttyACM0"; cfg["strips"][1]["com_port"] = "/dev/ttyUSB0"
        xml = mod.gen(cfg)
        self.assertEqual(xml.count("<LedStrip>"), 3)
        self.assertEqual(xml.count("<TeensyStripController>"), 1); self.assertEqual(xml.count("<WemosD1MPStripController>"), 1)
        self.assertIn("<Name>Ruban 2.2</Name>", xml); self.assertIn("<FirstLedNumber>61</FirstLedNumber>", xml)
        # matrice : 9 sorties LedWiz vers le meme toy ; rubans : une sortie par ruban
        self.assertEqual(xml.count("<OutputName>Backboard HD</OutputName>"), 9)
        self.assertEqual(xml.count("<OutputName>Ruban 2.1</OutputName>"), 1)
        self.assertIn("<LedWizNumber>31</LedWizNumber>", xml)

    def test_premier_demarrage(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            mod = pd.outil(R / "opt/pincabos/tools/dof-cabinet/dof-cabinet.py")
            _, ok = pd.valider_toys(pd.proposer_toys(DET), DET)
            inv = pd.inventaire_json(ok, DET)
            for dev in inv["devices"]:
                dev["com_port"] = "/dev/ttyACM9"
            dossier = tmp / "directoutputconfig"; dossier.mkdir()
            (dossier / "cabinet.xml").write_text("<Cabinet/>", encoding="utf-8")
            vpx = tmp / ".pincabos/vpx/directoutputconfig"; vpx.mkdir(parents=True)   # le PrefPath de VPX
            j = pd.appliquer_toys_premier_demarrage(inv, inventaire=tmp / "inv.json", dossier=dossier, sauvegardes=tmp / "bak", mod=mod,
                                                    supplementaires=(vpx, tmp / "absent"))
            self.assertTrue((tmp / "inv.json").exists())
            self.assertIn("<TeensyStripController>", (dossier / "cabinet.xml").read_text(encoding="utf-8"))
            self.assertEqual(len(list((tmp / "bak").glob("cabinet.xml.bak-installer-*"))), 1)
            # PINCABOS_DOF_GLOBALCONFIG_V1 : sans GlobalConfig, DOF n'aurait jamais lu ce cabinet.xml
            gc = (dossier / "GlobalConfig_B2SServer.xml").read_text(encoding="utf-8")
            self.assertIn(f"<CabinetConfigFilePattern>{dossier}/cabinet.xml</CabinetConfigFilePattern>", gc)
            self.assertIn(f"<IniFilesPath>{dossier}</IniFilesPath>", gc)
            self.assertNotIn("{GlobalConfigDir}", gc, "libdof ne connait pas cette variable : chemins absolus")
            # le PrefPath de VPX recoit le meme cabinet.xml et son propre GlobalConfig
            self.assertEqual((vpx / "cabinet.xml").read_bytes(), (dossier / "cabinet.xml").read_bytes())
            self.assertIn(f"<CabinetConfigFilePattern>{vpx}/cabinet.xml<", (vpx / "GlobalConfig_B2SServer.xml").read_text(encoding="utf-8"))
            self.assertEqual(len(j), 6, j)
            # sans controleur actif : inventaire seul
            inv2 = json.loads(json.dumps(inv)); [d.__setitem__("enabled", False) for d in inv2["devices"]]
            j = pd.appliquer_toys_premier_demarrage(inv2, inventaire=tmp / "inv2.json", dossier=dossier, sauvegardes=tmp / "bak", mod=mod)
            self.assertTrue(any("inchangé" in l for l in j))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_global_config(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            d = tmp / "directoutputconfig"; d.mkdir(); (d / "cabinet.xml").write_text("<Cabinet/>", encoding="utf-8")
            # un reglage de l'utilisateur qui designe deja un cabinet.xml est garde
            perso = "<GlobalConfig><CabinetConfigFilePattern>/ailleurs/cabinet.xml</CabinetConfigFilePattern></GlobalConfig>"
            (d / "GlobalConfig_B2SServer.xml").write_text(perso, encoding="utf-8")
            self.assertIn("en place", pd.poser_global_config(d, tmp / "bak"))
            self.assertEqual((d / "GlobalConfig_B2SServer.xml").read_text(encoding="utf-8"), perso)
            # un fichier sans cabinet.xml (celui de DOF Windows, par exemple) est sauvegarde puis remplace
            (d / "GlobalConfig_B2SServer.xml").write_text("<GlobalConfig/>", encoding="utf-8")
            self.assertIn("pose", pd.poser_global_config(d, tmp / "bak"))
            self.assertEqual(len(list((tmp / "bak").glob("GlobalConfig_B2SServer.xml.bak-*"))), 1)
            self.assertIn(f"{d}/cabinet.xml", (d / "GlobalConfig_B2SServer.xml").read_text(encoding="utf-8"))
            # la reparation (doctor, CLI) : chaque dossier avec cabinet.xml
            autre = tmp / "vpx/directoutputconfig"; autre.mkdir(parents=True); (autre / "cabinet.xml").write_text("<Cabinet/>", encoding="utf-8")
            j = pd.reparer_global_config(supplementaires=(d, autre), sauvegardes=tmp / "bak")
            self.assertTrue((autre / "GlobalConfig_B2SServer.xml").is_file()); self.assertEqual(len(j), 2, j)
            # le doctor et la CLI existent
            self.assertIn("global-config", (R / "opt/pincabos/tools/pincabos-dof").read_text(encoding="utf-8"))
            doc = R / "usr/local/libexec/pincabos/doctor.d/75-dof.sh"
            self.assertIn("pincabos-dof global-config", doc.read_text(encoding="utf-8"))
            import subprocess
            self.assertEqual(subprocess.run(["bash", "-n", str(doc)]).returncode, 0)
            self.assertIn("propager_cabinet", (R / "opt/pincabos/web/pincabos_dof_hardware.py").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Assistant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import flask  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("flask absent")
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ["PCO_DEMO"] = "1"; os.environ["PCO_RUN_DIR"] = str(cls.tmp)
        import sys
        sys.path.insert(0, str(R / "opt/pincabos/installer-gui"))
        cls.app = charger("opt/pincabos/installer-gui/app.py", "pco_installer_app_toys")
        cls.client = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_api(self):
        d = self.client.get("/api/toys").get_json()
        self.assertTrue(d["disponible"])
        self.assertEqual(d["inputs"][0]["buttons"], 32)
        self.assertEqual([a["kind"] for a in d["auto"]], ["DudesCab"])
        self.assertEqual([s["type"] for s in d["strips"]], ["TeensyStripController", "WemosD1MPStripController"])
        self.assertEqual(len(d["arrangements"]), 16)
        self.assertEqual(d["proposition"]["controllers"][0]["mode"], "matrice")

    def test_installation_ecrit_l_inventaire(self):
        d = self.client.get("/api/toys").get_json()
        r = self.client.post("/api/install", json={"lang": "fr", "mode": "1", "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS",
                                                   "network": False, "toys": d["proposition"]})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn("PCO_ANS_TOYS_FILE=" + str(self.tmp / "gui-toys.json"), (self.tmp / "gui-answers.env").read_text(encoding="utf-8"))
        inv = json.loads((self.tmp / "gui-toys.json").read_text(encoding="utf-8"))
        self.assertEqual(len(inv["devices"]), 2); self.assertEqual(inv["source"], "PinCabOS installer")
        mauvais = d["proposition"]; mauvais["controllers"][0]["strips"] = [1]
        r = self.client.post("/api/install", json={"lang": "fr", "mode": "1", "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS",
                                                   "network": False, "toys": mauvais})
        self.assertEqual(r.status_code, 400); self.assertEqual(r.get_json()["error"], "bad-toys")

    def test_page(self):
        html = self.client.get("/").get_data(as_text=True)
        for m in ('id="st-toys"', 'id="toys-strips"', "loadToys()", "go('st-toys')", "toysProblems"):
            self.assertIn(m, html)


class Integration(unittest.TestCase):
    def test_iso_sh(self):
        s = texte_installateur()
        self.assertIn("apply_target_toys() {", s)
        self.assertIn("  apply_target_dof\n  apply_target_toys\n", s)
        self.assertIn('"$TARGET/opt/pincabos/config/dof/hardware-inventory.json"', s)
        self.assertIn("toys-installer.pending", s)

    def test_premier_demarrage_et_cli(self):
        sc = (R / "usr/local/sbin/pincabos-installer-firstboot").read_text(encoding="utf-8")
        self.assertIn("apply-toys-firstboot", sc)
        self.assertLess(sc.index("toys-installer.pending"), sc.index("audio-installer.pending"))
        self.assertIn("apply-toys-firstboot", (R / "opt/pincabos/tools/pincabos-dof").read_text(encoding="utf-8"))
        self.assertIn('if d.get("toys"):', (R / "opt/pincabos/web/pincabos_dof_hardware.py").read_text(encoding="utf-8"))

    def test_i18n(self):
        d = json.loads((R / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for lang, keys in d.items():
            for k in ("toys_title", "toys_hint", "toys_inputs", "toys_inputs_none", "toys_inputs_note", "toys_auto", "toys_auto_none",
                      "toys_strips_none", "toys_used", "toys_mode", "toys_mode_matrix", "toys_mode_strips", "toys_size", "toys_arrangement",
                      "toys_outputs", "toys_outputs_hint_matrix", "toys_outputs_hint_strips", "toys_total", "toys_color", "toys_brightness",
                      "toys_ledwiz", "toys_err_total", "toys_err_none", "toys_buttons"):
                self.assertIn(k, keys, f"{lang}: {k}")


if __name__ == "__main__":
    unittest.main()
