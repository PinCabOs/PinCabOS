"""Étape Disque : PinCabOS déjà installé → mise à jour proposée (PINCABOS_INSTALLEUR_DISQUE_V1)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE

R = Path(RACINE)
dk = charger("opt/pincabos/installer-gui/disks.py", "pco_installer_disks")

LSBLK = json.dumps({"blockdevices": [
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": "931,5G", "type": "disk", "model": "Samsung 980 PRO", "children": [
        {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": "550M", "type": "part", "fstype": "vfat"},
        {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "size": "931G", "type": "part", "fstype": "ext4"}]},
    {"name": "sda", "path": "/dev/sda", "size": "223,6G", "type": "disk", "model": "Crucial BX500", "children": [
        {"name": "sda1", "path": "/dev/sda1", "size": "223,6G", "type": "part", "fstype": "ntfs"}]},
    {"name": "loop0", "path": "/dev/loop0", "size": "2,6G", "type": "loop"},
    {"name": "sr0", "path": "/dev/sr0", "size": "2,6G", "type": "rom"}]})


class Disques(unittest.TestCase):
    def test_parse(self):
        d = dk.disques(LSBLK)
        self.assertEqual([x["dev"] for x in d], ["/dev/nvme0n1", "/dev/sda"])
        self.assertEqual([p["fstype"] for p in d[0]["partitions"]], ["vfat", "ext4"])
        self.assertEqual(dk.disques("pas du json"), [])

    def test_version_pincabos(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            self.assertIsNone(dk.version_pincabos(str(tmp)))
            (tmp / "opt/pincabos/config").mkdir(parents=True); (tmp / "home/pinball").mkdir(parents=True)
            self.assertEqual(dk.version_pincabos(str(tmp)), "?")
            (tmp / "opt/pincabos/config/version.json").write_text('{"version": "Alpha 3.66"}', encoding="utf-8")
            self.assertEqual(dk.version_pincabos(str(tmp)), "Alpha 3.66")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recherche_monte_les_racines_seulement(self):
        appels = []
        def run(args, timeout=20):
            appels.append(args); return 0, ""
        d = dk.disques(LSBLK)
        r = dk.chercher_pincabos(d[0], run=run, sonde=lambda p: "Alpha 3.55")
        self.assertEqual(r["version"], "Alpha 3.55"); self.assertEqual(r["partition"], "/dev/nvme0n1p2")
        self.assertEqual([a[0] for a in appels], ["mount", "umount"])       # la vfat n est pas sondee
        self.assertEqual(appels[0][:3], ["mount", "-o", "ro"])
        self.assertIsNone(dk.chercher_pincabos(d[1], run=run, sonde=lambda p: "x"))   # ntfs : rien
        def run_ko(args, timeout=20): return 1, "mount: wrong fs"
        self.assertIsNone(dk.chercher_pincabos(d[0], run=run_ko, sonde=lambda p: "x"))

    def test_detecter_et_modes(self):
        def run(args, timeout=20):
            return (0, LSBLK) if args[0] == "lsblk" else (0, "")
        liste = dk.detecter(run=run, sonde=lambda p: "Alpha 3.60")
        self.assertEqual(liste[0]["pincabos"], {"version": "Alpha 3.60", "partition": "/dev/nvme0n1p2"})
        self.assertIsNone(liste[1]["pincabos"])
        self.assertEqual(dk.modes_possibles(liste[0]), ["1", "2", "3"]); self.assertEqual(dk.modes_possibles(liste[1]), ["1", "2"])
        self.assertEqual((dk.mode_propose(liste[0]), dk.mode_propose(liste[1])), ("3", "1"))


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
        cls.app = charger("opt/pincabos/installer-gui/app.py", "pco_installer_app_disk")
        cls.client = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_api(self):
        d = self.client.get("/api/disks").get_json()
        self.assertIsNone(d[0]["pincabos"]); self.assertEqual(d[1]["pincabos"]["version"], "Alpha 3.55")

    def test_mise_a_jour_acceptee(self):
        r = self.client.post("/api/install", json={"lang": "fr", "mode": "3", "disk": "/dev/sda", "confirm": "INSTALL PINCABOS", "network": False})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn("PCO_ANS_MODE=3", (self.tmp / "gui-answers.env").read_text(encoding="utf-8"))

    def test_page(self):
        html = self.client.get("/").get_data(as_text=True)
        for m in ("diskChosen", 'id="disk-keep"', "disk_found"):
            self.assertIn(m, html)


class I18n(unittest.TestCase):
    def test_cles(self):
        d = json.loads((R / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for lang, keys in d.items():
            for k in ("disk_found", "disk_keep", "mode_up", "mode_up_d"):
                self.assertIn(k, keys, f"{lang}: {k}")


class Confirmation(unittest.TestCase):
    """PINCABOS_INSTALLEUR_CONFIRMATION_V2 — remontee de Patrick (07/09/2026).

    Seul le mode 1 efface le disque. La derniere etape annoncait pourtant
    « TOUTES LES DONNEES SERONT EFFACEES » dans les trois modes : le dualboot
    et la mise a jour, choisis justement pour ne rien perdre, faisaient peur.
    """

    def setUp(self):
        self.html = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.i18n = json.loads((R / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))

    def test_un_message_par_mode(self):
        self.assertIn('S.mode==3?"confirm_warn_up":S.mode==2?"confirm_warn_dual":"confirm_warn"', self.html)
        # le rouge d alerte ne reste que sur l effacement total
        self.assertIn('box.classList.toggle("soft",S.mode!=1)', self.html)
        self.assertIn('t(S.mode==1?"confirm_title":"confirm_title_keep")', self.html)

    def test_traductions_completes(self):
        for lang, cles in self.i18n.items():
            for k in ("confirm_warn", "confirm_warn_up", "confirm_warn_dual",
                      "confirm_title", "confirm_title_keep"):
                self.assertIn(k, cles, f"{lang}: {k}")
            self.assertNotEqual(cles["confirm_warn_dual"], cles["confirm_warn"], lang)
            self.assertNotEqual(cles["confirm_title_keep"], cles["confirm_title"], lang)


if __name__ == "__main__":
    unittest.main()
