"""Le cabinet installe porte son propre nom (PINCABOS_NOM_MACHINE_V1).

Cab de Yann, 08/09/2026, apres une installation complete depuis l'ISO :

    static  : pincabos-live
    courant : pincabos-live

Le systeme installe EST le rootfs live, il heritait donc de son nom. Tous les
cabinets sortis de l'ISO portaient le meme, sur le reseau, dans les journaux,
dans SSH et dans la WebApp. L'installateur ne le corrigeait jamais : « grep
hostname » sur son moteur ne renvoyait rien.

Le nom vient de la carte reseau, seul identifiant stable qu'une machine ait a
l'installation : pincabos-<6 derniers caracteres de la MAC>.
"""
import tempfile
import unittest
from pathlib import Path

from _charge import charger

pi = charger("opt/pincabos/tools/pincabos_identity.py", "pco_identity_nom")


class NomDepuisLaMac(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.net = self.tmp / "net"
        self.net.mkdir()

    def carte(self, nom, mac, physique=True):
        d = self.net / nom
        d.mkdir()
        (d / "address").write_text(mac + "\n", encoding="utf-8")
        if physique:
            (d / "device").mkdir()
        return d

    def test_les_six_derniers_caracteres(self):
        self.carte("enp0s31f6", "04:d4:c4:a8:65:ed")
        self.assertEqual(pi.mac_de_la_machine(self.net), "a865ed")
        self.assertEqual(pi.nom_machine("a865ed"), "pincabos-a865ed")

    def test_le_filaire_passe_avant_le_sans_fil(self):
        """Une carte Wi-Fi peut manquer d'un cabinet a l'autre : le nom bougerait."""
        self.carte("wlp3s0", "aa:bb:cc:dd:ee:ff")
        self.carte("enp0s31f6", "04:d4:c4:a8:65:ed")
        self.assertEqual(pi.mac_de_la_machine(self.net), "a865ed")

    def test_les_cartes_virtuelles_sont_ecartees(self):
        """docker0, veth, bridges, ZeroTier : le nom changerait au gre des conteneurs."""
        self.carte("docker0", "02:42:11:22:33:44", physique=False)
        self.carte("ztabcdef01", "02:aa:bb:cc:dd:ee", physique=False)
        self.carte("enp0s31f6", "04:d4:c4:a8:65:ed")
        self.assertEqual(pi.mac_de_la_machine(self.net), "a865ed")

    def test_lo_est_ignoree(self):
        self.carte("lo", "00:00:00:00:00:00")
        self.assertEqual(pi.mac_de_la_machine(self.net), "")

    def test_une_mac_toute_a_zero_ne_nomme_rien(self):
        """Mieux vaut garder l'ancien nom qu'appeler tous les cabs pincabos-000000."""
        self.carte("enp0s31f6", "00:00:00:00:00:00")
        self.assertEqual(pi.mac_de_la_machine(self.net), "")
        self.assertEqual(pi.nom_machine(""), "")

    def test_aucune_carte(self):
        self.assertEqual(pi.mac_de_la_machine(self.net), "")


class FichiersDuNom(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "etc").mkdir()

    def test_hosts_suit_le_nom(self):
        avant = "127.0.0.1\tlocalhost\n127.0.1.1\tpincabos-live\n::1\tip6-localhost\n"
        apres = pi.hosts_avec_nom(avant, "pincabos-a865ed")
        self.assertIn("127.0.1.1\tpincabos-a865ed", apres)
        self.assertNotIn("pincabos-live", apres)
        self.assertIn("127.0.0.1\tlocalhost", apres, "le reste du fichier ne bouge pas")
        self.assertIn("::1\tip6-localhost", apres)

    def test_hosts_sans_ligne_127_0_1_1(self):
        apres = pi.hosts_avec_nom("127.0.0.1\tlocalhost\n", "pincabos-a865ed")
        self.assertIn("127.0.1.1\tpincabos-a865ed", apres)

    def test_une_seule_ligne_127_0_1_1(self):
        """Deux lignes 127.0.1.1 rendraient la resolution ambigue."""
        avant = "127.0.1.1\tvieux\n127.0.0.1\tlocalhost\n127.0.1.1\tencore-vieux\n"
        apres = pi.hosts_avec_nom(avant, "pincabos-a865ed")
        self.assertEqual(apres.count("127.0.1.1"), 1, apres)

    def test_un_nom_choisi_ailleurs_est_conserve(self):
        """On ne renomme jamais un cabinet que quelqu un a deja baptise."""
        (self.tmp / "etc/hostname").write_text("le-cab-de-yann\n", encoding="utf-8")
        journal = []
        change = pi.appliquer_nom(self.tmp, journal)
        self.assertFalse(change)
        self.assertEqual((self.tmp / "etc/hostname").read_text(encoding="utf-8").strip(),
                         "le-cab-de-yann")
        self.assertTrue(any("conservé" in l for l in journal), journal)

    def test_les_noms_du_live_sont_remplaces(self):
        for nom in ("pincabos-live", "localhost", "ubuntu", ""):
            with self.subTest(nom=nom):
                self.assertIn(nom, pi.NOMS_A_REMPLACER)


if __name__ == "__main__":
    unittest.main()
