"""Le cabinet installe appartient au joueur (PINCABOS_CIBLE_DROITS_V1).

Remonte par Patrick le 09/09/2026 sur une installation neuve :

    Erreur : [Errno 13] Permission denied : '/opt/pincabos/config/input-commander.json'
    Erreur : [Errno 13] ... '/opt/pincabos/config/webapp-screen-autostart.conf'

La WebApp tourne en `User=pinball`. Les fichiers de `/opt/pincabos/config`
heritent des uid du depot, recopies tels quels par `rsync -a` : ceux que le
mainteneur avait touches sortent en uid 1000 (= pinball sur le cabinet) et
marchent, ceux restes root:root bloquent. La propriete d un fichier livre
dependait donc du hasard d un checkout git.

Le seul `chown -R pinball:pinball /opt/pincabos` du projet vit dans
`02-install-engine.sh`, l ancien moteur texte — que l assistant graphique
n appelle plus depuis la 3.66, quand il est devenu le seul chemin
d installation. Il ne tournait donc plus sur aucune installation neuve.

Consequence en chaine : le mappage des boutons ne pouvait pas etre enregistre,
donc aucun bouton ne repondait, donc aucune table ne demarrait.
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
INSTALLEUR = R / "opt/pincabos/script/installer/pincabos-live-installer"
MODELE_INI = R / "opt/pincabos/templates/home/.config/vpinfe/vpinfe.ini"
COMMANDER = R / "opt/pincabos/config/inputs-commander.json"
SLIM = R / "opt/pincabos/script/slim-master.sh"

# les dossiers que la WebApp ecrit : 235 references a config, 196 a logs...
ECRITS = ("config", "logs", "backups", "state", "download", "tmp", "uploads", "cache")


class DroitsPosesParLInstallateur(unittest.TestCase):
    def setUp(self):
        self.texte = INSTALLEUR.read_text(encoding="utf-8")

    def test_la_fonction_existe(self):
        self.assertIn("apply_target_ownership() {", self.texte)

    def test_elle_est_appelee_dans_le_chemin_commun(self):
        # install_payload() sert les trois modes : disque entier, mise a jour,
        # double amorcage. L appel doit y etre, pas dans un seul mode.
        corps = self.texte.split("install_payload() {", 1)[1].split("\nfinal_boot_refresh", 1)[0]
        self.assertIn("apply_target_ownership", corps,
                      "sans appel, la fonction ne sert a rien")

    def test_tous_les_dossiers_ecrits_sont_donnes_au_joueur(self):
        corps = self.texte.split("apply_target_ownership() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("chown -R pinball:pinball", corps)
        for d in ECRITS:
            self.assertIn("/opt/pincabos/" + d, corps, d + " reste hors du chown")

    def test_les_dossiers_manquants_sont_crees(self):
        # backups n existe pas dans l image : sans mkdir, le chown le rate.
        corps = self.texte.split("apply_target_ownership() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("mkdir -p", corps)


class MappageUtilisableSansRienConfigurer(unittest.TestCase):
    """Un cabinet neuf doit pouvoir lancer une table."""

    def test_le_bouton_start_valide(self):
        # Un bouton Start de cabinet envoie « 1 » (convention Visual Pinball).
        # Avec « keyselect = Enter » seul, les flips naviguaient (ShiftLeft et
        # ShiftRight sont bien lies) mais rien ne lancait la table.
        ligne = [l for l in MODELE_INI.read_text(encoding="utf-8").splitlines()
                 if l.startswith("keyselect")]
        self.assertEqual(len(ligne), 1)
        valeurs = [v.strip() for v in ligne[0].split("=", 1)[1].split(",")]
        self.assertIn("1", valeurs, "aucune touche de Start : rien ne lance de table")
        self.assertIn("Enter", valeurs)

    def test_les_flips_naviguent(self):
        texte = MODELE_INI.read_text(encoding="utf-8")
        self.assertRegex(texte, r"keyleft\s*=.*ShiftLeft")
        self.assertRegex(texte, r"keyright\s*=.*ShiftRight")


class RienDeLaMachineDuMainteneur(unittest.TestCase):
    """Ce qui est livre ne doit designer aucun materiel particulier."""

    def test_aucun_peripherique_en_dur_dans_le_mappage(self):
        # nudge_axis_x valait « /dev/input/event8|ABS_X » : le numero du cabinet
        # du mainteneur, qui designe autre chose sur toute autre machine.
        brut = COMMANDER.read_text(encoding="utf-8")
        self.assertNotIn("/dev/input/", brut,
                         "un chemin de peripherique fige part sur tous les cabinets")
        json.loads(brut)  # et le fichier reste lisible

    def test_les_fichiers_lus_restent(self):
        # Piege : ces trois-la RESSEMBLENT a des residus de fabrication, mais ils
        # sont lus — gitpush-release-sequence.json par l installateur lui-meme.
        # Les supprimer casse l installation.
        for nom in ("github-rootfs-exclude.txt", "gitpush-release-sequence.json",
                    "pincabos-publish-policy.conf"):
            self.assertTrue((R / "opt/pincabos/config" / nom).is_file(),
                            nom + " est lu par le projet : il doit rester")


class LeMasterNAccumulePas(unittest.TestCase):
    """`build-master.sh` recopie le depot avec « rsync -a » SANS --delete : tout
    ce qui a ete livre un jour reste dans le master pour toujours. On y a trouve
    les journaux et les sauvegardes du cabinet du mainteneur, vpinball.log seul
    pesant 3,1 Mo, expedies dans chaque ISO."""

    def test_le_degraissage_purge_les_journaux_du_cabinet_d_origine(self):
        s = SLIM.read_text(encoding="utf-8")
        self.assertIn("PINCABOS_MASTER_SANS_RESIDUS_V1", s)
        for motif in ("vpinball.log", "vpinfe-start-", "vpinfe.ini.backup-screens-"):
            self.assertIn(motif, s, motif + " n est pas purge du master")

    def test_il_ne_purge_pas_les_fichiers_lus(self):
        bloc = SLIM.read_text(encoding="utf-8").split("PINCABOS_MASTER_SANS_RESIDUS_V1", 1)[1][:1200]
        for nom in ("github-rootfs-exclude.txt", "gitpush-release-sequence.json",
                    "pincabos-publish-policy.conf", "apt-installed-full-"):
            self.assertNotIn(nom, bloc, nom + " est lu : le degraissage ne doit pas y toucher")

    def test_la_purge_vise_le_master_et_pas_l_hote(self):
        # Une variable non definie ici effacerait des chemins de la machine de
        # fabrication : slim-master.sh a « set -u », mais la cible doit etre
        # explicite. La racine du master s appelle $M dans ce script.
        s = SLIM.read_text(encoding="utf-8")
        bloc = s.split("PINCABOS_MASTER_SANS_RESIDUS_V1", 1)[1][:1200]
        for chemin in re.findall(r'rm -f[^\n]*(?:\\\n[^\n]*)*', bloc):
            self.assertNotRegex(chemin, r'rm -f\s+/',
                                "chemin absolu : viserait la machine de fabrication")
            self.assertIn('"$M"', chemin, "la purge doit etre ancree sur $M")
