"""opt/pincabos/overlays/ dans le perimetre des mises a jour, en deux temps.

PINCABOS_OVERLAYS_LIVRES_V1 — cab de Yann, 08/09/2026.

Les bibliotheques posees a cote des runtimes (libdof pour VPX et VPinFE,
surcouches DudesCab) etaient HORS du perimetre : un cabinet gardait celle de
son ISO pour toujours. VPX et VPinFE ont ainsi tourne trois mois sur deux
libdof differentes sans qu aucune mise a jour puisse les rattraper.

Livraison en DEUX releases (PINCABOS_UPDATE_SCOPE_PREFIX_TRAP) :
  celle-ci  : le prefixe est ACCEPTE par le client (allowed) mais le
              constructeur ne l embarque pas (allowed_for_build) ;
  la suivante : le prefixe sort de PENDING_PREFIXES et les fichiers partent,
              le parc entier connaissant deja le perimetre.

Ajouter le prefixe ET les fichiers dans la meme release ferait refuser TOUTE
la mise a jour par les cabinets qui ne connaissent pas encore le perimetre.
"""
import unittest

from _charge import charger

up = charger("opt/pincabos/update/pincabos_updates.py", "pco_updates_overlays")

OVERLAY = "opt/pincabos/overlays/libdof-canonical/libdof.so.0.4.7"


class OverlaysDansLePerimetre(unittest.TestCase):
    def test_le_client_accepte_desormais_le_prefixe(self):
        self.assertTrue(up.allowed(OVERLAY),
                        "sans cela un cab refuse le fichier, et avec lui toute la mise a jour")

    def test_le_constructeur_ne_l_embarque_pas_encore(self):
        self.assertFalse(up.allowed_for_build(OVERLAY),
                         "cette release doit apprendre le prefixe, pas livrer les fichiers")

    def test_le_prefixe_est_bien_en_attente(self):
        self.assertIn("opt/pincabos/overlays/", up.PENDING_PREFIXES)

    def test_rien_dautre_ne_sest_ouvert(self):
        """Le perimetre ne doit pas s elargir par megarde."""
        for hors in ("opt/pincabos/nimportequoi/x", "home/pinball/Tables/x.vpx",
                     "etc/passwd", "opt/pinball/vpx/VPinballX_BGFX"):
            self.assertFalse(up.allowed(hors), hors)

    def test_les_prefixes_livres_restent_livres(self):
        for dedans in ("opt/pincabos/tools/x.sh", "opt/pincabos/web/x.py",
                       "usr/local/sbin/pincabos-x", "opt/pincabos/media/splash/portrait0.png"):
            self.assertTrue(up.allowed(dedans), dedans)
            self.assertTrue(up.allowed_for_build(dedans), dedans)


if __name__ == "__main__":
    unittest.main()
