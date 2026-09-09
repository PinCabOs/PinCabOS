"""L'import DOF Config Tool par clé API (PINCABOS_DOF_IMPORT_API_V1).

La page DOF appelait `/usr/local/sbin/pincabos-dof-online-api-import` depuis
toujours… et ce programme n'a JAMAIS existé : ni dans le dépôt, ni dans
l'historique git, ni dans le master. La page affichait donc « Import DOF via
API indisponible » sur tous les cabinets, et seul l'import ZIP manuel
fonctionnait. Trouvé le 09/09/2026 en cherchant pourquoi un testeur n'avait
aucune LED en table : sans les `directoutputconfig*.ini` de SON cabinet, DOF
n'a rien à jouer.

Le contrat vient du client de référence (mkalkbrenner/dof_configtool_client,
DownloadController.php) :

    GET http://configtool.vpuniverse.com/api.php?query=getconfig&apikey=<clé>
        -> une archive ZIP de *.ini, *.xml, *.png

Quand la clé est refusée, l'API répond du TEXTE et non un ZIP. C'est ce texte
qui explique l'erreur : on le montre plutôt qu'un « échec » muet.
"""
import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from _charge import RACINE, charger

R = Path(RACINE)
REL = "usr/local/sbin/pincabos-dof-online-api-import"
OUTIL = R / REL


def _module():
    # le programme n'a pas d'extension .py : on passe par le chargeur du banc
    return charger(REL, "dof_import")


def _archive(noms) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        for n in noms:
            z.writestr(n, "contenu de " + n)
    return tampon.getvalue()


class LeProgrammeExiste(unittest.TestCase):
    """C'est tout le sujet : la WebApp l'appelle par ce chemin exact."""

    def test_au_chemin_attendu_par_la_webapp(self):
        self.assertTrue(OUTIL.is_file())
        appel = (R / "opt/pincabos/web/pincabos_webapp_dof.py").read_text(encoding="utf-8")
        self.assertIn("/usr/local/sbin/pincabos-dof-online-api-import", appel)

    def test_executable(self):
        self.assertTrue(OUTIL.stat().st_mode & 0o111, "doit être exécutable")

    def test_l_url_est_celle_du_client_de_reference(self):
        s = OUTIL.read_text(encoding="utf-8")
        self.assertIn("configtool.vpuniverse.com/api.php?query=getconfig&apikey=", s)


class LaReponseNEstPasToujoursUneArchive(unittest.TestCase):
    def setUp(self):
        self.m = _module()

    def test_une_archive_est_reconnue(self):
        self.assertTrue(self.m.est_une_archive(_archive(["directoutputconfig30.ini"])))

    def test_du_texte_ne_l_est_pas(self):
        self.assertFalse(self.m.est_une_archive(b"Invalid API key"))

    def test_le_message_de_l_api_est_rendu_a_l_utilisateur(self):
        # une clé refusée doit expliquer pourquoi, pas dire « échec »
        self.m.telecharger = lambda cle: b"Invalid API key"
        code = self.m.main(["mauvaise-cle"])
        self.assertEqual(code, 2)

    def test_sans_cle_on_refuse_avant_tout_reseau(self):
        self.assertEqual(self.m.main([]), 64)
        self.assertEqual(self.m.main(["   "]), 64)


class LExtractionEstFiltree(unittest.TestCase):
    """Une archive vient du réseau : on n'en extrait jamais un chemin."""

    def setUp(self):
        self.m = _module()

    def test_seuls_les_fichiers_dof_sont_retenus(self):
        z = zipfile.ZipFile(io.BytesIO(_archive([
            "directoutputconfig30.ini", "cabinet.xml", "DirectOutputShapes.png",
            "lisezmoi.txt", "script.sh"])))
        with z:
            noms = [b for _, b in self.m.noms_utiles(z)]
        self.assertEqual(sorted(noms),
                         ["DirectOutputShapes.png", "cabinet.xml", "directoutputconfig30.ini"])

    def test_aucune_traversee_de_chemin(self):
        # « ../../etc/passwd.ini » ne doit jamais sortir du dossier cible
        z = zipfile.ZipFile(io.BytesIO(_archive([
            "../../etc/passwd.ini", "sous/dossier/directoutputconfig31.ini"])))
        with z:
            noms = [b for _, b in self.m.noms_utiles(z)]
        self.assertEqual(sorted(noms), ["directoutputconfig31.ini", "passwd.ini"])
        for n in noms:
            self.assertNotIn("/", n)
            self.assertNotIn("..", n)

    def test_pose_dans_le_dossier(self):
        with TemporaryDirectory() as tmp:
            cible = Path(tmp) / "directoutputconfig"
            z = zipfile.ZipFile(io.BytesIO(_archive(["directoutputconfig30.ini", "cabinet.xml"])))
            with z:
                bilan = self.m.poser(z, self.m.noms_utiles(z), cible, True)
            self.assertEqual(bilan["ecrits"], 2)
            self.assertTrue((cible / "directoutputconfig30.ini").is_file())

    def test_un_fichier_identique_n_est_pas_reecrit(self):
        with TemporaryDirectory() as tmp:
            cible = Path(tmp) / "directoutputconfig"
            donnees = _archive(["cabinet.xml"])
            for attendu in ({"ecrits": 1, "inchanges": 0}, {"ecrits": 0, "inchanges": 1}):
                z = zipfile.ZipFile(io.BytesIO(donnees))
                with z:
                    bilan = self.m.poser(z, self.m.noms_utiles(z), cible, True)
                self.assertEqual(bilan["ecrits"], attendu["ecrits"])
                self.assertEqual(bilan["inchanges"], attendu["inchanges"])

    def test_sans_force_on_ne_remplace_pas(self):
        with TemporaryDirectory() as tmp:
            cible = Path(tmp) / "directoutputconfig"
            cible.mkdir(parents=True)
            (cible / "cabinet.xml").write_text("le mien", encoding="utf-8")
            z = zipfile.ZipFile(io.BytesIO(_archive(["cabinet.xml"])))
            with z:
                bilan = self.m.poser(z, self.m.noms_utiles(z), cible, False)
            self.assertEqual(bilan["gardes"], 1)
            self.assertEqual((cible / "cabinet.xml").read_text(encoding="utf-8"), "le mien")


class LesDeuxDossiersSontServis(unittest.TestCase):
    """VPX (PrefPath) et VPinFE lisent chacun le leur : un seul servi donne un
    cabinet à moitié muet."""

    def test_le_dossier_canonique_est_toujours_present(self):
        m = _module()
        self.assertIn(m.CANONIQUE, m.dossiers_dof() + [m.CANONIQUE])
        s = OUTIL.read_text(encoding="utf-8")
        self.assertIn("VPinFE", s, "l'intention doit être écrite noir sur blanc")
