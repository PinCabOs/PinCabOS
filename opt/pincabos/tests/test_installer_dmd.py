"""Étape Écrans : DMD matériel sans full DMD (PINCABOS_INSTALLEUR_DMD_V1).

Détection rejouée sur les sorties réelles de pincabos-zedmd (detect / status),
aucune commande exécutée.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE, texte_installateur

R = Path(RACINE)
dm = charger("opt/pincabos/installer-gui/dmd.py", "pco_installer_dmd")

SERIE = [
    {"device": "/dev/ttyACM0", "vendor_id": "303a", "product_id": "1001", "model": "USB_JTAG_serial_debug_unit", "serial": "A0B1C2",
     "family": "esp32", "label": "ESP32 natif (Espressif) — ZeDMD probable", "candidate": True,
     "by_id": "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_A0B1C2-if00"},
    {"device": "/dev/ttyACM1", "vendor_id": "16c0", "product_id": "0483", "model": "USB_Serial", "serial": "1234",
     "family": "teensy", "label": "Teensy — controleur LED / DOF, pas un ZeDMD — declare dans cabinet.xml (DOF)", "candidate": False, "by_id": ""},
]
STATUS_SANS = {"config": {"mode": "off"}, "pin2dmd": {"devices": [], "udev_rule": True}}
STATUS_P2 = {"config": {"mode": "off"}, "pin2dmd": {"devices": [{"product": "PIN2DMD", "serial": "P2-1", "node": "/dev/bus/usb/001/004", "writable": True}], "udev_rule": True}}


def faux(serie, status):
    def run(args, timeout=30):
        if args[0] == "detect":
            return 0, json.dumps(serie)
        if args[0] == "status":
            return 0, json.dumps(status)
        return 0, "ok " + " ".join(args)
    return run


class Detection(unittest.TestCase):
    def test_zedmd_usb_propose(self):
        d = dm.detecter(run=faux(SERIE, STATUS_SANS))
        self.assertEqual([p["device"] for p in d["candidats"]], ["/dev/ttyACM0"])
        self.assertEqual(d["proposition"], {"type": "zedmd_usb", "device": SERIE[0]["by_id"], "wifi_addr": ""})

    def test_pin2dmd_prioritaire(self):
        d = dm.detecter(run=faux(SERIE, STATUS_P2))
        self.assertEqual(d["proposition"]["type"], "pin2dmd")
        self.assertEqual(d["pin2dmd"][0]["serial"], "P2-1")

    def test_rien(self):
        d = dm.detecter(run=faux([], STATUS_SANS))
        self.assertEqual(d["proposition"], {"type": "none", "device": "", "wifi_addr": ""})

    def test_outil_absent(self):
        d = dm.detecter(run=lambda args, timeout=30: (99, "ERREUR: absent"))
        self.assertFalse(d["disponible"])
        self.assertEqual(d["proposition"]["type"], "none")


class Validation(unittest.TestCase):
    def test_types(self):
        self.assertEqual([t["id"] for t in dm.TYPES], ["zedmd_usb", "zedmd_wifi", "pin2dmd", "none"])
        self.assertEqual(dm.valider({"type": "pixelcade"})[0], ["type de DMD inconnu : 'pixelcade'"])

    def test_usb(self):
        det = dm.detecter(run=faux(SERIE, STATUS_SANS))
        self.assertEqual(dm.valider({"type": "zedmd_usb", "device": SERIE[0]["by_id"], "wifi_addr": "x"}, det),
                         ([], {"type": "zedmd_usb", "device": SERIE[0]["by_id"], "wifi_addr": ""}))
        self.assertEqual(dm.valider({"type": "zedmd_usb", "device": ""}, det)[0], [])
        self.assertTrue(any("absent de la machine" in e for e in dm.valider({"type": "zedmd_usb", "device": "/dev/ttyUSB7"}, det)[0]))
        self.assertTrue(any("invalide" in e for e in dm.valider({"type": "zedmd_usb", "device": "/etc/passwd"})[0]))

    def test_wifi(self):
        self.assertEqual(dm.valider({"type": "zedmd_wifi", "wifi_addr": "192.168.1.50"})[0], [])
        self.assertEqual(dm.valider({"type": "zedmd_wifi", "wifi_addr": "zedmd.local"})[0], [])
        self.assertTrue(dm.valider({"type": "zedmd_wifi", "wifi_addr": ""})[0])
        self.assertTrue(dm.valider({"type": "zedmd_wifi", "wifi_addr": "192.168.1.50; rm -rf /"})[0])

    def test_config_json(self):
        self.assertEqual(dm.config_json({"type": "none"}), {"mode": "off", "device": "", "wifi_addr": "", "brightness": -1, "targets": ""})
        c = dm.config_json({"type": "zedmd_wifi", "wifi_addr": "192.168.1.50"})
        self.assertEqual((c["mode"], c["wifi_addr"], c["targets"]), ("wifi", "192.168.1.50", "both"))
        c = dm.config_json({"type": "pin2dmd", "device": "/dev/ttyACM0"})
        self.assertEqual((c["mode"], c["device"], c["targets"]), ("pin2dmd", "", "game"))

    def test_mire(self):
        appels = []

        def run(args, timeout=30):
            appels.append(list(args))
            return 0, "mire"
        r = dm.tester({"type": "zedmd_usb", "device": ""}, run=run, secondes=2)
        self.assertTrue(r["ok"])
        self.assertEqual(appels[0][0], "set")
        self.assertEqual(json.loads(appels[0][1])["mode"], "usb")
        # PINCABOS_INSTALLEUR_DECOR_ROLES_V1 : le visuel DMD de l assistant remplace la mire
        self.assertEqual(appels[1][0], "image"); self.assertTrue(appels[1][1].endswith("/static/decor/dmd.jpg")); self.assertEqual(appels[1][2], "2")
        self.assertFalse(dm.tester({"type": "pin2dmd"}, run=run)["ok"])


class Assistant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import flask  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("flask absent")
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ["PCO_DEMO"] = "1"
        os.environ["PCO_RUN_DIR"] = str(cls.tmp)
        import sys
        sys.path.insert(0, str(R / "opt/pincabos/installer-gui"))
        cls.app = charger("opt/pincabos/installer-gui/app.py", "pco_installer_app_dmd")
        cls.client = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _install(self, usage, dmd):
        d = self.client.get("/api/screens").get_json()
        roles = dict(d["roles"])
        if not usage["fulldmd"]:
            roles["fulldmd"] = ""
        return self.client.post("/api/install", json={
            "lang": "fr", "locale": "fr_FR.UTF-8", "xkb": "fr", "tz": "Europe/Paris", "mode": "1",
            "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS", "network": False,
            "screens": {"roles": roles, "rotation": 0, "usage": usage}, "dmd": dmd})

    def test_api(self):
        d = self.client.get("/api/dmd").get_json()
        self.assertEqual(d["proposition"]["type"], "zedmd_usb")
        self.assertEqual(d["types"], ["zedmd_usb", "zedmd_wifi", "pin2dmd", "none"])
        self.assertTrue(self.client.post("/api/dmd/test", json={"type": "zedmd_usb", "device": ""}).get_json()["ok"])
        self.assertFalse(self.client.post("/api/dmd/test", json={"type": "zedmd_wifi", "wifi_addr": ""}).get_json()["ok"])

    def test_installation_sans_full_dmd_ecrit_zedmd_json(self):
        r = self._install({"backglass": True, "fulldmd": False, "topper": False}, {"type": "zedmd_wifi", "wifi_addr": "192.168.1.50"})
        self.assertEqual(r.status_code, 200, r.get_json())
        env = (self.tmp / "gui-answers.env").read_text(encoding="utf-8")
        self.assertIn("PCO_ANS_DMD_FILE=" + str(self.tmp / "gui-zedmd.json"), env)
        cfg = json.loads((self.tmp / "gui-zedmd.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["mode"], cfg["wifi_addr"], cfg["targets"]), ("wifi", "192.168.1.50", "both"))

    def test_installation_avec_full_dmd_n_ecrit_rien(self):
        (self.tmp / "gui-zedmd.json").unlink(missing_ok=True)
        r = self._install({"backglass": True, "fulldmd": True, "topper": False}, {"type": "pin2dmd"})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertNotIn("PCO_ANS_DMD_FILE", (self.tmp / "gui-answers.env").read_text(encoding="utf-8"))
        self.assertFalse((self.tmp / "gui-zedmd.json").exists())

    def test_choix_invalide_refuse(self):
        r = self._install({"backglass": True, "fulldmd": False, "topper": False}, {"type": "zedmd_wifi", "wifi_addr": "pas une adresse!"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "bad-dmd")

    def test_page(self):
        html = self.client.get("/").get_data(as_text=True)
        for m in ('id="dmd-card"', 'data-dmd="pin2dmd"', "testDmd", "loadDmd"):
            self.assertIn(m, html)


class Integration(unittest.TestCase):
    def test_iso_sh(self):
        s = texte_installateur()
        self.assertIn("apply_target_dmd() {", s)
        self.assertIn("  apply_target_network\n  apply_target_dmd\n", s)
        self.assertIn('"$TARGET/opt/pincabos/config/zedmd.json"', s)
        self.assertIn("dmd-installer.pending", s)
        # PINCABOS_ZEDMD_AU_PREMIER_DEMARRAGE_V1 : l installateur n applique plus
        # rien depuis le chroot. Un ZeDMD en Wi-Fi n y est pas joignable — pas de
        # reseau final, pas de peripherique — et le « || true » avalait l echec
        # (remonte par Flo le 09/09/2026 : IP renseignee, ZeDMD inactif ensuite).
        # Le drapeau suffit : pincabos-dmd-installer.service rejoue au premier
        # demarrage et CONSERVE le drapeau tant que l application echoue.
        self.assertNotIn("pincabos-zedmd apply", s,
                         "plus d application ZeDMD depuis le chroot du media")

    def test_premier_demarrage(self):
        u = (R / "etc/systemd/system/pincabos-dmd-installer.service").read_text(encoding="utf-8")
        self.assertIn("ConditionPathExists=/opt/pincabos/flags/dmd-installer.pending", u)
        self.assertTrue((R / "etc/systemd/system/multi-user.target.wants/pincabos-dmd-installer.service").is_symlink())
        sc = (R / "usr/local/sbin/pincabos-dmd-installer-apply").read_text(encoding="utf-8")
        self.assertIn("pincabos-zedmd", sc)
        self.assertIn('rm -f "$DRAPEAU"', sc)

    def test_i18n(self):
        d = json.loads((R / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for lang, keys in d.items():
            for k in ("dmd_title", "dmd_hint", "dmd_zedmd_usb", "dmd_zedmd_wifi", "dmd_pin2dmd", "dmd_none", "dmd_port",
                      "dmd_port_auto", "dmd_addr", "dmd_detected", "dmd_none_detected", "dmd_test", "dmd_testing",
                      "dmd_test_ok", "dmd_test_failed", "dmd_addr_invalid"):
                self.assertIn(k, keys, f"{lang}: {k}")


if __name__ == "__main__":
    unittest.main()
