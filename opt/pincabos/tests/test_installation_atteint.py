"""Ce que l'installateur pose doit atteindre le systeme qui tourne.

Trois remontees du 09/09/2026, meme famille :

  Flo     « Reglage ecran ok pendant l'installation mais apres reboot sur le dd
            ca n'a pas suivi » — playfield tete en bas, refait a la main depuis
            la WebApp.
  Flo     « J'ai fait la config IP de mon zedmd pendant l'installation mais il
            n'est pas actif sous vpinfe. »
  Patrick « Ca semble vouloir se lancer, l'affichage s'estompe, une animation de
            chargement, et ca revient sur l'interface. »

Trois causes distinctes, toutes du meme genre : le choix est bien enregistre,
mais personne ne le rejoue la ou il compte.
"""
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
HOTPLUG = R / "etc/systemd/system/pincabos-screen-hotplug.service"
LIEN = R / "etc/systemd/system/graphical.target.wants/pincabos-screen-hotplug.service"
INSTALLEUR = R / "opt/pincabos/script/installer/pincabos-live-installer"
LANCEUR = R / "opt/pincabos/scripts/VPXlauncher.pincabos-original.sh"
REEL = R / "opt/pincabos/scripts/VPXlauncher.real.sh"


class RotationAppliqueeAuDemarrage(unittest.TestCase):
    """La rotation du playfield vient de screens.json et n est posee que par
    xrandr, dans pincabos-screen-hotplug. Cette unite n etait demarree que par
    une regle udev « change » sur drm — qui ne survient pas quand les ecrans
    sont deja branches au demarrage."""

    def test_l_unite_est_demarree_au_boot(self):
        s = HOTPLUG.read_text(encoding="utf-8")
        self.assertIn("[Install]", s, "sans [Install], aucune cible ne la demarre")
        self.assertRegex(s, r"(?m)^WantedBy=graphical\.target$")

    def test_le_lien_d_activation_existe(self):
        self.assertTrue(LIEN.is_symlink(), "le lien graphical.target.wants manque")

    def test_l_ordre_du_boot_est_conserve(self):
        # PINCABOS_TOPOLOGIE_VERROU_BOOT_V1 : la topologie de demarrage passe
        # d abord, sinon le verrou bloquait le frontend (regression de la 4.32).
        s = HOTPLUG.read_text(encoding="utf-8")
        self.assertRegex(s, r"(?m)^After=.*pincabos-screen-topology-boot\.service")

    def test_c_est_toujours_le_hotplug_qui_tourne_les_ecrans(self):
        # si un jour la rotation demenage, ce test doit etre revu sciemment
        code = (R / "usr/local/libexec/pincabos/pincabos-screen-hotplug").read_text(encoding="utf-8")
        self.assertIn("--rotate", code)
        self.assertIn("screens.json", code)


class ZedmdRejoueLaOuIlEstJoignable(unittest.TestCase):
    """Un ZeDMD en Wi-Fi n est pas joignable depuis le chroot du media : pas de
    reseau final, pas de peripherique. L application appartient au premier
    demarrage du cabinet."""

    def test_plus_d_application_dans_le_chroot(self):
        s = INSTALLEUR.read_text(encoding="utf-8")
        self.assertNotIn("pincabos-zedmd apply", s,
                         "l installateur ne doit plus appliquer le ZeDMD depuis le chroot")

    def test_le_drapeau_de_rejeu_reste_pose(self):
        # c est lui qui declenche pincabos-dmd-installer.service au boot, et ce
        # service CONSERVE le drapeau tant que l application echoue : il retente.
        s = INSTALLEUR.read_text(encoding="utf-8")
        self.assertIn("flags/dmd-installer.pending", s)

    def test_le_service_de_rejeu_est_active(self):
        self.assertTrue((R / "etc/systemd/system/multi-user.target.wants"
                           / "pincabos-dmd-installer.service").exists())


class LeCompteDuJoueurLuiAppartient(unittest.TestCase):
    """PINCABOS_CIBLE_DROITS_V2 — le chown s arretait a /opt."""

    def test_home_pinball_est_dans_le_chown(self):
        corps = INSTALLEUR.read_text(encoding="utf-8") \
            .split("apply_target_ownership() {", 1)[1].split("\n}", 1)[0]
        self.assertRegex(corps, r"chown -R pinball:pinball /home/pinball\b",
                         "sans lui, VPX ne peut pas migrer son dossier de preferences")


class LaMigrationDesPrefsNeTuePasLeLanceur(unittest.TestCase):
    """Chez Patrick :

        mv: cannot move '/home/pinball/.local/share/VPinballX/10.8'
            to '/home/pinball/.pincabos/vpx': Permission denied

    Renommer un dossier demande le droit d ecriture sur le PARENT. Le mv
    echouait, `set -Eeuo pipefail` tuait le lanceur, VPX ne demarrait pas — et
    VPinFE se contentait de reafficher son menu."""

    def test_le_mv_est_garde(self):
        s = LANCEUR.read_text(encoding="utf-8")
        bloc = s.split("PINCABOS_VPX_PREFPATH_V2", 1)[1][:1500]
        self.assertRegex(bloc, r'if ! mv "\$\{VPX_LEGACY_PREF\}" "\$\{VPX_PREF_DIR\}"',
                         "le mv doit etre teste, pas laisse tuer le script")

    def test_le_repli_garde_l_ancien_dossier(self):
        bloc = LANCEUR.read_text(encoding="utf-8").split("PINCABOS_VPX_PREFPATH_V2", 1)[1][:1500]
        self.assertIn('VPX_PREF_DIR="${VPX_LEGACY_PREF}"', bloc,
                      "quand la migration echoue, on doit continuer avec l ancien dossier")

    def test_le_set_e_est_toujours_la(self):
        # on ne corrige pas en desarmant le garde-fou du script entier
        self.assertRegex(LANCEUR.read_text(encoding="utf-8"), r"(?m)^set -Eeuo pipefail$")


class LeLanceurDitPourquoiVpxEstParti(unittest.TestCase):
    """Seul le code 139 (SIGSEGV) etait traite. Un retour immediat et non nul
    repartait en silence : le journal ne montrait que « Lancement Original
    direct » puis « frontend reactive », a la meme seconde."""

    def test_une_sortie_rapide_et_non_nulle_est_journalisee(self):
        s = REEL.read_text(encoding="utf-8")
        self.assertIn("PINCABOS_LANCEUR_SORTIE_PARLANTE_V1", s)
        self.assertRegex(s, r'\$rc" -ne 0')
        self.assertIn("SECONDS - DEBUT", s)

    def test_le_repli_opengl_sur_139_est_conserve(self):
        s = REEL.read_text(encoding="utf-8")
        self.assertIn('"$rc" -eq 139', s, "le repli OpenGL ne doit pas disparaitre")
