"""Étape « Réseau » de l'assistant d'installation (PINCABOS_INSTALLEUR_RESEAU_V1).

DHCP par défaut, IP fixe proposée depuis le bail, Wi-Fi si matériel ; ce que la
session a configuré (profils NetworkManager) part sur la cible.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _charge import RACINE, charger, texte_installateur

R = Path(RACINE)


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
        sys.path.insert(0, str(R / "opt/pincabos/installer-gui"))
        cls.app = charger("opt/pincabos/installer-gui/app.py", "pco_installer_app_net")
        cls.client = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_etat_demo(self):
        d = self.client.get("/api/network").get_json()
        self.assertTrue(d["disponible"])
        self.assertEqual([i["device"] for i in d["interfaces"]], ["eno1", "wlp3s0"])
        eno = d["interfaces"][0]
        self.assertEqual(eno["proposition"]["source"], "dhcp")
        self.assertEqual(eno["proposition"]["address"], "172.18.40.80/24")
        self.assertEqual(d["interfaces"][1]["proposition"]["dns"], ["9.9.9.9", "1.1.1.1"], "sans DHCP : DNS de repli")
        self.assertTrue(d["wifi"]["present"])

    def test_balayage_demo(self):
        s = self.client.get("/api/network/wifi-scan").get_json()
        self.assertTrue(s["present"])
        neuf = next(r for r in s["reseaux"] if r["ssid"] == "Neuf")
        self.assertFalse(neuf["compatible"])
        self.assertIn("5 GHz", neuf["raison"])

    def test_application(self):
        r = self.client.post("/api/network/apply", json={"iface": "eno1", "mode": "static", "address": "192.168.1.0/24", "gateway": "", "dns": ""}).get_json()
        self.assertFalse(r["ok"])
        self.assertTrue(all(l.startswith("NOGO") for l in r["journal"]))
        r = self.client.post("/api/network/apply", json={"iface": "eno1", "mode": "static", "address": "192.168.1.50/24", "gateway": "192.168.1.1", "dns": "9.9.9.9, 1.1.1.1"}).get_json()
        self.assertTrue(r["ok"], r)
        r = self.client.post("/api/network/apply", json={"iface": "eno1", "mode": "dhcp"}).get_json()
        self.assertTrue(r["ok"])

    def test_wifi(self):
        self.assertFalse(self.client.post("/api/network/wifi-join", json={"ssid": "Neuf", "password": "motdepasse"}).get_json()["ok"])
        self.assertFalse(self.client.post("/api/network/wifi-join", json={"ssid": "", "password": ""}).get_json()["ok"])
        self.assertTrue(self.client.post("/api/network/wifi-join", json={"ssid": "Maison", "password": "motdepasse"}).get_json()["ok"])

    def test_installation_photographie_le_reseau(self):
        r = self.client.post("/api/install", json={"lang": "fr", "locale": "fr_FR.UTF-8", "xkb": "fr", "tz": "Europe/Paris", "mode": "1",
                                                   "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS"})
        self.assertEqual(r.status_code, 200, r.get_json())
        env = (self.tmp / "gui-answers.env").read_text(encoding="utf-8").replace("'", "")
        self.assertIn("PCO_ANS_NETWORK_FILE=" + str(self.tmp / "gui-network.json"), env)
        self.assertIn("PCO_ANS_NETPLAN_DIR=" + str(self.tmp / "gui-netplan"), env)
        data = json.loads((self.tmp / "gui-network.json").read_text(encoding="utf-8"))
        self.assertEqual([i["device"] for i in data["interfaces"]], ["eno1", "wlp3s0"])
        self.assertTrue((self.tmp / "gui-netplan").is_dir())

    def test_page(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="st-network"', html)
        self.assertIn("loadNetwork(false);go('st-network')", html)
        disque = html.split('id="st-disk"')[1].split('<section', 1)[0]
        self.assertIn("go('st-network')", disque, "retour du disque vers le reseau")


class PriseEnMainHorsLigne(unittest.TestCase):
    """netplan-takeover --root DIR : ce que l'installateur exécute sur la cible."""

    def test_cli_root(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "etc/netplan").mkdir(parents=True)
            (tmp / "etc/netplan/01-pincabos-dhcp.yaml").write_text("network:\n  version: 2\n  renderer: NetworkManager\n  ethernets:\n    eno1:\n      dhcp4: true\n", encoding="utf-8")
            (tmp / "etc/netplan/90-NM-abc.yaml").write_text("network:\n  version: 2\n  ethernets:\n    eno1:\n      renderer: NetworkManager\n      addresses:\n      - \"192.168.1.50/24\"\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(R / "opt/pincabos/tools/pincabos_network.py"), "netplan-takeover", "eno1", "--root", str(tmp)],
                               capture_output=True, text=True, env=dict(os.environ, PINCABOS_GC_SYNC="1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("GO:", r.stdout)
            self.assertFalse((tmp / "etc/netplan/01-pincabos-dhcp.yaml").exists())
            self.assertTrue((tmp / "etc/netplan/90-NM-abc.yaml").exists())
            self.assertNotIn("netplan generate", r.stdout, "hors ligne : rien n'est regenere")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Integration(unittest.TestCase):
    def test_iso_sh(self):
        s = texte_installateur()
        self.assertIn("apply_target_network() {", s)
        self.assertIn("  apply_target_screens\n  apply_target_network\n  apply_target_dmd\n  apply_target_audio\n  apply_target_dof\n  apply_target_toys\n  apply_target_inputs\n  apply_target_ownership\n  purge_live_only_from_target\n  refresh_target_initrd_for_orientation\n", s)
        self.assertIn('netplan-takeover "$iface" --root "$TARGET"', s)
        self.assertIn("network-installer.done", s)
        # PINCABOS_INSTALLEUR_RESEAU_V2 : a la mise a jour, le choix reseau est rejoue apres la restauration
        self.assertRegex(s, r"  restore_user_settings\n(?:  #.*\n)*  apply_target_network\n")
        # PINCABOS_KEEP_MERGE_V1 : un dossier conserve est fusionne, pas remplace
        self.assertIn('cp -a "$PCO_KEEP_DIR/$p/." "$TARGET/$p/"', s)
        self.assertLess(s.index("Network configured by the installer / NetworkManager: generic DHCP netplan skipped."),
                        s.index('echo "=== Write generic DHCP netplan ==="'), "la garde precede l'ecriture du fichier generique au premier boot")

    def test_i18n(self):
        d = json.loads((R / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for lang, keys in d.items():
            for k in ("network", "network_hint", "net_dhcp", "net_static", "net_no_dhcp", "net_join", "net_hidden"):
                self.assertIn(k, keys, f"{lang}: {k}")


def _fonction_iso(nom):
    s = texte_installateur()
    a = s.index(f"\n{nom}() {{\n") + 1
    b = s.index("\n}\n", a) + 3
    return s[a:b]


class CibleReseau(unittest.TestCase):
    """apply_target_network (PINCABOS_INSTALLEUR_RESEAU_V2) : ce que la session a
    persiste part sur la cible ; sinon la cible ne doit surtout pas recevoir le
    drapeau qui fait sauter le DHCP generique du premier demarrage (Alpha 3.77 :
    installation neuve en DHCP = cab sans reseau)."""

    ETH = {"interfaces": [{"device": "enp0s2", "type": "ethernet", "method": "auto", "address": ""}]}
    NM_NEW = 'network:\n  version: 2\n  ethernets:\n    NM-1111:\n      renderer: NetworkManager\n      match:\n        name: "enp0s2"\n      dhcp4: true\n'
    NM_OLD = 'network:\n  version: 2\n  ethernets:\n    enp0s2:\n      renderer: NetworkManager\n      match: {}\n      addresses:\n      - "192.168.1.50/24"\n'
    NM_WIFI = 'network:\n  version: 2\n  wifis:\n    NM-2222:\n      renderer: NetworkManager\n      match:\n        name: "wlp3s0"\n      dhcp4: true\n'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cible = self.tmp / "cible"
        (self.cible / "etc/netplan").mkdir(parents=True)
        self.dossier = self.tmp / "gui-netplan"
        self.dossier.mkdir()
        self.fichier = self.tmp / "gui-network.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, gui=None, session=None, cible=None, drapeau=False):
        self.fichier.write_text(json.dumps(gui or self.ETH), encoding="utf-8")
        for nom, txt in (session or {}).items():
            (self.dossier / nom).write_text(txt, encoding="utf-8")
        for nom, txt in (cible or {}).items():
            (self.cible / "etc/netplan" / nom).write_text(txt, encoding="utf-8")
        if drapeau:
            (self.cible / "opt/pincabos/flags").mkdir(parents=True)
            (self.cible / "opt/pincabos/flags/network-installer.done").write_text("x")
        script = ("set -u\npco_step(){ :; }\npco_go(){ echo \"GO: $*\"; }\npco_warn(){ echo \"WARN: $*\"; }\n"
                  + _fonction_iso("apply_target_network") + "\napply_target_network\n")
        env = dict(os.environ, TARGET=str(self.cible), PCO_ANS_NETWORK_FILE=str(self.fichier), PCO_ANS_NETPLAN_DIR=str(self.dossier))
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def _netplan(self):
        return sorted(p.name for p in (self.cible / "etc/netplan").iterdir())

    def _drapeau(self):
        return (self.cible / "opt/pincabos/flags/network-installer.done").exists()

    def test_dhcp_laisse_tel_quel_installation_neuve(self):
        out = self._run()
        self.assertEqual(self._netplan(), ["01-pincabos-dhcp.yaml"])
        y = (self.cible / "etc/netplan/01-pincabos-dhcp.yaml").read_text(encoding="utf-8")
        self.assertIn("renderer: NetworkManager", y)
        self.assertIn("    enp0s2:\n      dhcp4: true", y)
        self.assertFalse(self._drapeau(), "sans profil persiste, le premier demarrage garde son DHCP generique")
        self.assertIn("DHCP netplan written for enp0s2", out)

    def test_dhcp_laisse_tel_quel_retire_un_ancien_drapeau(self):
        self._run(drapeau=True)
        self.assertFalse(self._drapeau())

    def test_dhcp_laisse_tel_quel_cab_deja_configure(self):
        out = self._run(cible={"90-NM-old.yaml": self.NM_OLD})
        self.assertEqual(self._netplan(), ["90-NM-old.yaml"], "le reseau du cab n'est pas touche")
        self.assertFalse(self._drapeau())
        self.assertIn("keeps its own network", out)

    def test_wifi_seul_sans_profil_n_ecrit_rien(self):
        gui = {"interfaces": [{"device": "wlp3s0", "type": "wifi", "method": "auto", "address": ""}]}
        self._run(gui=gui)
        self.assertEqual(self._netplan(), [])
        self.assertFalse(self._drapeau())

    def test_profil_de_la_session_remplace_celui_du_cab_sur_la_meme_interface(self):
        out = self._run(session={"90-NM-new.yaml": self.NM_NEW}, cible={"90-NM-old.yaml": self.NM_OLD, "90-NM-wifi.yaml": self.NM_WIFI})
        self.assertEqual(self._netplan(), ["90-NM-new.yaml", "90-NM-wifi.yaml"])
        self.assertTrue(self._drapeau())
        self.assertIn("older NetworkManager profile of enp0s2 removed", out)
        self.assertIn("network profiles installed (1 netplan file(s))", out)


if __name__ == "__main__":
    unittest.main()


class CibleInstalleur(unittest.TestCase):
    def test_networkmanager_demarre_sur_le_media(self):
        # PINCABOS_INSTALLEUR_RESEAU_LIVE_V1 : vu en VM, « aucune interface reseau detectee »
        u = (R / "etc/systemd/system/pincabos-gui-install.target").read_text(encoding="utf-8")
        self.assertIn("NetworkManager.service", u.split("Wants=")[1].splitlines()[0])

