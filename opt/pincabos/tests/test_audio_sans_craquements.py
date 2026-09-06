"""PINCABOS_AUDIO_SANS_CRAQUEMENT_V1 : rien n'est rejoue quand tout est deja en place.

Cab de Yann, 06/09/2026 : a chaque demarrage (et a chaque « initialisation du
son ») les amplis des vibrants claquaient. Deux causes : le profil surround
repose alors qu'il etait actif (PipeWire ferme et rouvre la carte), et la mise
en veille de la sortie apres quelques secondes de silence (reveil du codec au
son suivant).
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE

R = Path(RACINE)
su = charger("usr/local/sbin/pincabos-audio-surround", "pco_audio_surround")

CARTES = """Card #49
\tName: alsa_card.pci-0000_00_1f.3
\tDriver: alsa
\tActive Profile: output:analog-surround-71+input:analog-stereo
Card #48
\tName: alsa_card.pci-0000_01_00.1
\tActive Profile: output:hdmi-stereo
"""
SINKS = """Sink #57
\tName: alsa_output.pci-0000_01_00.1.hdmi-stereo
\tMute: yes
Sink #60
\tName: alsa_output.pci-0000_00_1f.3.analog-surround-71
\tMute: no
"""


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=out, stderr=err)


class Profil(unittest.TestCase):
    def setUp(self):
        self.appels = []
        self._pactl = su.pactl

    def tearDown(self):
        su.pactl = self._pactl

    def faux_pactl(self, *args):
        self.appels.append(args)
        if args[:2] == ("list", "cards"):
            return _cp(0, CARTES)
        if args[:2] == ("list", "sinks"):
            return _cp(0, SINKS)
        return _cp(0)

    def test_profil_actif_de_cette_carte(self):
        self.assertEqual(su.profil_actif("alsa_card.pci-0000_00_1f.3", CARTES), "output:analog-surround-71+input:analog-stereo")
        self.assertEqual(su.profil_actif("alsa_card.pci-0000_01_00.1", CARTES), "output:hdmi-stereo")
        self.assertEqual(su.profil_actif("alsa_card.inconnue", CARTES), "")

    def test_profil_deja_actif_non_rejoue(self):
        su.pactl = self.faux_pactl
        ok, msg = su.rejouer_profil("alsa_card.pci-0000_00_1f.3", "output:analog-surround-71+input:analog-stereo")
        self.assertTrue(ok); self.assertIn("deja actif", msg)
        self.assertFalse([a for a in self.appels if a[0] == "set-card-profile"], "la carte n est pas rouverte")

    def test_profil_different_rejoue(self):
        su.pactl = self.faux_pactl
        ok, msg = su.rejouer_profil("alsa_card.pci-0000_00_1f.3", "output:analog-surround-51+input:analog-stereo")
        self.assertTrue(ok); self.assertIn("rejoue", msg)
        self.assertIn(("set-card-profile", "alsa_card.pci-0000_00_1f.3", "output:analog-surround-51+input:analog-stereo"), self.appels)

    def test_mute_leve_seulement_si_pose(self):
        su.pactl = self.faux_pactl
        lignes = su.reactiver_sinks_de_la_carte("alsa_card.pci-0000_00_1f.3")
        self.assertFalse([a for a in self.appels if a[0] == "set-sink-mute"], "sink ouvert : rien")
        self.assertTrue(any("sortie ouverte" in l for l in lignes), lignes)
        self.appels.clear()
        su.reactiver_sinks_de_la_carte("alsa_card.pci-0000_01_00.1")
        self.assertIn(("set-sink-mute", "alsa_output.pci-0000_01_00.1.hdmi-stereo", "0"), self.appels)

    def test_sinks_muets(self):
        self.assertEqual(su.sinks_muets(SINKS), {"alsa_output.pci-0000_01_00.1.hdmi-stereo": True,
                                                 "alsa_output.pci-0000_00_1f.3.analog-surround-71": False})


class SansVeille(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.modele = R / "opt/pincabos/templates/home/.config/wireplumber/wireplumber.conf.d/51-pincabos-sortie-sans-veille.conf"
        self.cible = self.tmp / "home/.config/wireplumber/wireplumber.conf.d/51-pincabos-sortie-sans-veille.conf"
        self.redemarrages = 0

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def redemarrer(self):
        self.redemarrages += 1
        return _cp(0)

    def test_modele_livre(self):
        s = self.modele.read_text(encoding="utf-8")
        self.assertIn("session.suspend-timeout-seconds = 0", s)
        self.assertIn('node.name = "~alsa_output.*"', s)
        import sys
        sys.path.insert(0, str(R / "opt/pincabos/update"))
        import pincabos_updates as up
        self.assertTrue(up.allowed("opt/pincabos/templates/home/.config/wireplumber/wireplumber.conf.d/51-pincabos-sortie-sans-veille.conf"))

    def test_pose_une_fois_puis_plus_rien(self):
        uid, gid = os.getuid(), os.getgid()
        msg = su.sans_veille(self.modele, self.cible, self.redemarrer, uid, gid)
        self.assertIn("GO", msg); self.assertEqual(self.redemarrages, 1)
        self.assertEqual(self.cible.read_text(encoding="utf-8"), self.modele.read_text(encoding="utf-8"))
        msg = su.sans_veille(self.modele, self.cible, self.redemarrer, uid, gid)
        self.assertEqual(msg, ""); self.assertEqual(self.redemarrages, 1, "cabinet a jour : WirePlumber n est pas relance")

    def test_modele_absent(self):
        msg = su.sans_veille(self.tmp / "nulle-part.conf", self.cible, self.redemarrer)
        self.assertIn("WARN", msg); self.assertFalse(self.cible.exists()); self.assertEqual(self.redemarrages, 0)


if __name__ == "__main__":
    unittest.main()
