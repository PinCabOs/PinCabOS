"""Le doctor dit si l'installation a vraiment atteint le cabinet.

PINCABOS_DOCTOR_PREMIER_DEMARRAGE_V1 — le 09/09/2026, deux testeurs ont perdu
leur soirée sur des échecs qui étaient déjà journalisés :

  Flo     « No displays found by libdmdutil », toutes les 10 s depuis le premier
          démarrage. Il a soupçonné son routeur, sa passerelle, son câblage.
  Patrick des rubans qui répondaient au menu et restaient noirs en table, faute
          de directoutputconfig<N>.ini pour le numéro LedWiz de son contrôleur.
  Flo     la rotation du playfield choisie à l'installation, jamais appliquée.

Aucun de ces trois échecs n'était silencieux : ils étaient invisibles, ce qui
n'est pas pareil. Le doctor les remonte maintenant.
"""
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
DOCTOR = R / "usr/local/libexec/pincabos/doctor.d"
CHECK = DOCTOR / "85-installation.sh"


class LeControleExiste(unittest.TestCase):
    def test_au_bon_endroit_et_dans_le_bon_ordre(self):
        self.assertTrue(CHECK.is_file())
        # après VPX (80), avant le verdict final (99)
        noms = sorted(p.name for p in DOCTOR.glob("*.sh"))
        self.assertIn("85-installation.sh", noms)
        self.assertLess(noms.index("80-vpx.sh"), noms.index("85-installation.sh"))
        self.assertLess(noms.index("85-installation.sh"), noms.index("99-ready.sh"))

    def test_droits_alignes_sur_les_autres_modules(self):
        # les modules du doctor sont SOURCÉS, pas exécutés
        autres = [p.stat().st_mode & 0o777 for p in DOCTOR.glob("*.sh")
                  if p.name != "85-installation.sh"]
        self.assertIn(CHECK.stat().st_mode & 0o777, set(autres),
                      "droits differents des autres modules du doctor")

    def test_ouvre_sa_section(self):
        self.assertRegex(CHECK.read_text(encoding="utf-8"), r'^pco_section "INSTALLATION"')


class LesQuatreControles(unittest.TestCase):
    def setUp(self):
        self.s = CHECK.read_text(encoding="utf-8")

    def test_les_rejeux_en_attente(self):
        # un drapeau qui traîne après plusieurs démarrages = le rejeu ne passe pas
        for drapeau in ("inputs-installer.pending", "dmd-installer.pending"):
            self.assertIn(drapeau, self.s)
        self.assertIn("--list-boots", self.s,
                      "il faut distinguer « pas encore rejoué » de « ne passe jamais »")

    def test_le_dmd_materiel_vu_par_vpinfe(self):
        self.assertIn("No displays found by libdmdutil", self.s,
                      "c'est la phrase exacte que VPinFE journalise")
        self.assertIn("zedmd.json", self.s)

    def test_la_rotation_reellement_appliquee(self):
        self.assertIn("playfield_rotation", self.s)
        self.assertIn("xrandr", self.s)
        # la correspondance degrés -> mot-clé xrandr doit être complète
        for degre, mot in (("90", "right"), ("180", "inverted"), ("270", "left")):
            self.assertRegex(self.s, r"%s\)\s*attendu=%s" % (degre, mot))

    def test_les_definitions_d_effets_dof(self):
        self.assertIn("directoutputconfig", self.s)
        self.assertIn("ledwiz_number", self.s)
        self.assertIn("hardware-inventory.json", self.s)


class LeControleNAvalePasSesErreurs(unittest.TestCase):
    """C'est le constat 01 de la revue : 2 187 « || true » dans le projet. Un
    contrôle dont le rôle est de rendre les échecs visibles ne peut pas en
    ajouter."""

    def test_pas_de_ou_true_hors_du_chargement_des_chemins(self):
        lignes = [l for l in CHECK.read_text(encoding="utf-8").splitlines()
                  if "|| true" in l and not l.strip().startswith("#")]
        # seule tolérance : le sourcing de pincabos-paths.sh, absent en test
        self.assertEqual(len(lignes), 1, "un « || true » de trop : " + repr(lignes))
        self.assertIn("pincabos-paths.sh", lignes[0])

    def test_chaque_controle_a_ses_trois_issues(self):
        # un contrôle qui ne peut que réussir ne sert à rien
        s = CHECK.read_text(encoding="utf-8")
        self.assertGreaterEqual(len(re.findall(r"\bpco_fail\b", s)), 4)
        self.assertGreaterEqual(len(re.findall(r"\bpco_go\b", s)), 5)
        self.assertGreaterEqual(len(re.findall(r"\bpco_warn\b", s)), 2)

    def test_les_messages_disent_quoi_faire(self):
        s = CHECK.read_text(encoding="utf-8")
        for indice in ("Map Commander", "la page DMD", "page DOF"):
            self.assertIn(indice, s, "aucun message ne renvoie vers " + indice)
