"""Le live laisse Xorg choisir son pilote (PINCABOS_LIVE_XORG_AUTO_V1).

Cab de Yann, 08/09/2026, RTX 3070 Ti : l'assistant graphique de l'ISO ne
demarrait pas, alors que le systeme installe demarre parfaitement.

    (EE) Fatal server error:
    (EE) failed to create screen resources
    pincabos-gui-kiosk.service: Scheduled restart job, restart counter is at 3
    Failed to start pincabos-gui-kiosk.service

La cause : le live ecrivait

    Section "Device"
      Identifier "PinCabOS Kiosk"
      Driver "modesetting"
    EndSection

Sur un noeud DRM nvidia, modesetting ne sait pas creer de ressources d'ecran.
Et une section Device explicite ECRASE l'OutputClass que le pilote installe
(/usr/share/X11/xorg.conf.d/10-nvidia.conf : MatchDriver nvidia-drm, Driver
nvidia). Aucun cab NVIDIA ne pouvait donc lancer l'installateur.

Sans section Device, Xorg choisit seul : l'OutputClass NVIDIA s'applique la ou
il faut, et modesetting reste le choix automatique ailleurs (Intel, AMD, VM).
"""
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
ETAPE = R / "opt/pincabos/script/iso/80-live-rootfs.sh"


class LiveSansPiloteImpose(unittest.TestCase):
    def setUp(self):
        self.s = ETAPE.read_text(encoding="utf-8")

    def test_aucun_driver_impose_dans_le_live(self):
        """Un « Driver ... » ECRIT par la recette rendrait l ISO aveugle sur
        toute carte que ce pilote ne gere pas. Les commentaires ont le droit
        d en parler : on ne lit que les lignes de code."""
        for n, ligne in enumerate(self.s.splitlines(), 1):
            if ligne.lstrip().startswith("#"):
                continue
            m = re.search(r'Driver\s+"([a-z]+)"', ligne)
            if m:
                self.fail(f'ligne {n} : la recette impose Driver "{m.group(1)}" au live, '
                          "Xorg doit choisir seul (PINCABOS_LIVE_XORG_AUTO_V1)")

    def test_le_fichier_est_retire_des_images_deja_construites(self):
        """Une reconstruction sur un rootfs qui l a deja doit l effacer."""
        self.assertIn('rm -f "$ROOTFS_DIR/etc/X11/xorg.conf.d/10-pincabos-kiosk.conf"', self.s)

    def test_la_disposition_clavier_reste(self):
        """On ne jette que le pilote impose, pas tout le repertoire."""
        self.assertIn('mkdir -p "$ROOTFS_DIR/etc/X11/xorg.conf.d"', self.s)
        self.assertNotIn('rm -rf "$ROOTFS_DIR/etc/X11/xorg.conf.d"', self.s)

    def test_le_marqueur_explique_pourquoi(self):
        self.assertIn("PINCABOS_LIVE_XORG_AUTO_V1", self.s)


if __name__ == "__main__":
    unittest.main()
