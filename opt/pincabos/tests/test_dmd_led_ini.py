"""DMD LED reel (ZeDMD / PIN2DMD) : ce que l'outil ecrit dans les INI de VPX
et de VPinFE pour chaque mode, et ce qu'il refuse."""
import json
import os
import tempfile
import unittest
from unittest import mock

from _charge import charger

z = charger("opt/pincabos/tools/pincabos-zedmd", "pco_zedmd")

VPX_INI = """[Plugin.B2SLegacy]
Enable = 1

[Plugin.DMDUtil]
; Enable: Enable DMDUtil plugin [Default: 0]
Enable =
ZeDMD =
PIN2DMD =
ZeDMDDevice =
Pixelcade =

[Plugin.FlexDMD]
Enable = 1
"""


def cfg(**k):
    base = {"mode": "off", "device": "", "wifi_addr": "", "brightness": -1, "targets": "game"}
    base.update(k)
    return base


class LectureEcritureIni(unittest.TestCase):
    def test_lecture_section(self):
        s = z.read_section(VPX_INI, "Plugin.DMDUtil")
        self.assertEqual(s["enable"], "")
        self.assertNotIn("Plugin.FlexDMD", s)

    def test_ecriture_conserve_commentaires_et_autres_sections(self):
        out = z.update_section(VPX_INI, "Plugin.DMDUtil", {"Enable": "1", "ZeDMDWiFiAddr": "10.0.0.5"})
        self.assertIn("; Enable: Enable DMDUtil plugin", out)
        self.assertIn("Enable = 1\nZeDMD =", out)
        self.assertIn("ZeDMDWiFiAddr = 10.0.0.5", out)
        self.assertIn("[Plugin.FlexDMD]\nEnable = 1", out)
        self.assertIn("[Plugin.B2SLegacy]\nEnable = 1", out)

    def test_cle_ajoutee_dans_la_bonne_section(self):
        out = z.update_section(VPX_INI, "Plugin.DMDUtil", {"ZeDMDBrightness": "7"})
        avant_flex = out.index("[Plugin.FlexDMD]")
        self.assertLess(out.index("ZeDMDBrightness = 7"), avant_flex)


class ValeursVpx(unittest.TestCase):
    def test_zedmd_usb(self):
        v = z.desired_vpx_values(cfg(mode="usb", device="/dev/ttyUSB0", brightness=8), {})
        self.assertEqual((v["Enable"], v["ZeDMD"], v["PIN2DMD"], v["ZeDMDWiFiEnabled"]), ("1", "1", "0", "0"))
        self.assertEqual(v["ZeDMDDevice"], "/dev/ttyUSB0")
        self.assertEqual(v["ZeDMDBrightness"], "8")

    def test_zedmd_usb_auto_garde_device_vide(self):
        v = z.desired_vpx_values(cfg(mode="usb", device="", targets="both"), {})
        self.assertEqual((v["Enable"], v["ZeDMD"], v["ZeDMDWiFiEnabled"]), ("1", "1", "0"))
        self.assertEqual(v["ZeDMDDevice"], "")

    def test_zedmd_wifi(self):
        v = z.desired_vpx_values(cfg(mode="wifi", wifi_addr="192.168.1.50"), {})
        self.assertEqual((v["ZeDMD"], v["ZeDMDWiFiEnabled"], v["ZeDMDWiFiAddr"]), ("1", "1", "192.168.1.50"))
        self.assertEqual(v["ZeDMDDevice"], "")

    def test_pin2dmd(self):
        v = z.desired_vpx_values(cfg(mode="pin2dmd"), {})
        self.assertEqual((v["Enable"], v["PIN2DMD"], v["ZeDMD"]), ("1", "1", "0"))

    def test_off_garde_le_plugin_si_pixelcade_actif(self):
        self.assertEqual(z.desired_vpx_values(cfg(), {"pixelcade": "1"})["Enable"], "1")
        self.assertEqual(z.desired_vpx_values(cfg(), {"pixelcade": "0"})["Enable"], "0")


class ValeursVpinfe(unittest.TestCase):
    def test_menu_zedmd_usb_et_wifi_avec_cible_both(self):
        wifi = z.desired_vpinfe_values(cfg(mode="wifi", wifi_addr="a", targets="both"))
        self.assertEqual((wifi["enabled"], wifi["zedmdwifiaddr"]), ("true", "a"))

        usb_auto = z.desired_vpinfe_values(cfg(mode="usb", device="", targets="both"))
        self.assertEqual(usb_auto["enabled"], "true")
        self.assertEqual(usb_auto["zedmddevice"], "")

        usb_force = z.desired_vpinfe_values(cfg(mode="usb", device="/dev/x", targets="both"))
        self.assertEqual((usb_force["enabled"], usb_force["zedmddevice"]), ("true", "/dev/x"))

        self.assertEqual(z.desired_vpinfe_values(cfg(mode="usb", device="/dev/x", targets="game"))["enabled"], "false")
        self.assertEqual(z.desired_vpinfe_values(cfg(mode="pin2dmd", targets="both"))["enabled"], "false")


class Validation(unittest.TestCase):
    def test_refus(self):
        self.assertTrue(z.validate(cfg(mode="wifi")))
        self.assertTrue(z.validate(cfg(mode="usb", device="ttyUSB0")))
        self.assertTrue(z.validate(cfg(mode="pin2dmd", targets="both")))

    def test_usb_auto_absent_est_un_avertissement_pas_une_erreur(self):
        with mock.patch.object(z, "detect", return_value=[]):
            erreurs, avertissements = z.problemes(cfg(mode="usb", targets="both"))
        self.assertEqual(erreurs, [])
        self.assertEqual(len(avertissements), 1)
        self.assertIn("auto-detection USB reste active", avertissements[0])

    def test_usb_auto_present_est_valide(self):
        with mock.patch.object(z, "detect", return_value=[{"candidate": True}]):
            self.assertEqual(z.problemes(cfg(mode="usb", targets="both")), ([], []))

    def test_port_force_existant_est_valide(self):
        with mock.patch.object(z.os.path, "exists", return_value=True):
            self.assertEqual(z.problemes(cfg(mode="usb", device="/dev/serial/by-id/zedmd", targets="both")), ([], []))

    def test_port_force_absent_est_avertissement(self):
        with mock.patch.object(z.os.path, "exists", return_value=False):
            erreurs, avertissements = z.problemes(cfg(mode="usb", device="/dev/serial/by-id/zedmd", targets="both"))
        self.assertEqual(erreurs, [])
        self.assertEqual(len(avertissements), 1)


class ApplyCibles(unittest.TestCase):
    """ZeDMD USB auto garde menu + jeu ; PIN2DMD reste jeu seulement."""

    def setUp(self):
        d = tempfile.mkdtemp()
        self.vpx = os.path.join(d, "VPinballX.ini")
        with open(self.vpx, "w") as f:
            f.write(VPX_INI)
        self.fe = os.path.join(d, "vpinfe.ini")
        with open(self.fe, "w") as f:
            f.write("[libdmdutil]\nenabled = false\nzedmddevice =\n")
        self.saved = {}
        self._orig = (z.vpx_ini_path, z.VPINFE_INI, z.save_config, z.ensure_pinball_serial_access)
        z.vpx_ini_path = lambda: self.vpx
        z.VPINFE_INI = self.fe
        z.save_config = lambda c: self.saved.update(c)
        z.ensure_pinball_serial_access = lambda: None

    def tearDown(self):
        z.vpx_ini_path, z.VPINFE_INI, z.save_config, z.ensure_pinball_serial_access = self._orig

    def test_usb_port_auto_avec_menu_reste_both(self):
        with mock.patch.object(z, "detect", return_value=[]):
            self.assertEqual(z.apply(cfg(mode="usb", targets="both")), 0)
        vpx = z.read_section(open(self.vpx).read(), "Plugin.DMDUtil")
        self.assertEqual((vpx["enable"], vpx["zedmd"], vpx["zedmddevice"]), ("1", "1", ""))
        fe = z.read_section(open(self.fe).read(), "libdmdutil")
        self.assertEqual((fe["enabled"], fe["zedmddevice"]), ("true", ""))
        self.assertEqual(self.saved, {})

    def test_pin2dmd_avec_menu_est_degrade_game(self):
        self.assertEqual(z.apply(cfg(mode="pin2dmd", targets="both")), 0)
        vpx = z.read_section(open(self.vpx).read(), "Plugin.DMDUtil")
        self.assertEqual((vpx["enable"], vpx["pin2dmd"]), ("1", "1"))
        fe = z.read_section(open(self.fe).read(), "libdmdutil")
        self.assertEqual(fe["enabled"], "false")
        self.assertEqual(self.saved.get("targets"), "game")

    def test_wifi_sans_adresse_reste_refuse(self):
        self.assertEqual(z.apply(cfg(mode="wifi", targets="both")), 2)
        self.assertEqual(z.read_section(open(self.vpx).read(), "Plugin.DMDUtil")["enable"], "")

    def test_accepte(self):
        with mock.patch.object(z, "detect", return_value=[{"candidate": True}]):
            self.assertEqual(z.validate(cfg(mode="usb")), [])
        self.assertEqual(z.validate(cfg(mode="wifi", wifi_addr="zedmd.local", targets="both")), [])
        self.assertEqual(z.validate(cfg(mode="pin2dmd")), [])


class Normalisation(unittest.TestCase):
    def test_config_invalide_retombe_sur_des_valeurs_sures(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "zedmd.json")
            with open(p, "w") as f:
                json.dump({"mode": "laser", "brightness": 99, "targets": "partout"}, f)
            ancien = z.CONFIG
            z.CONFIG = p
            try:
                c = z.load_config()
            finally:
                z.CONFIG = ancien
        self.assertEqual(c["mode"], "off")
        self.assertEqual(c["brightness"], -1)
        self.assertIn(c["targets"], ("game", "both"))


if __name__ == "__main__":
    unittest.main()
