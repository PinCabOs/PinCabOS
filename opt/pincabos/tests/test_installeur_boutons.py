"""L'assistant capture les boutons du cabinet (PINCABOS_INSTALLEUR_BOUTONS_V1).

Remonté par Patrick le 09/09/2026 : arrivé sur le frontend après installation,
aucun bouton ne répondait et rien ne disait quoi faire. Le mappage n'existait
qu'après coup, dans Map Commander — qu'il fallait deviner. Son tire-bille, lui,
répondait très bien dès qu'il a trouvé la page : le matériel allait, il ne
manquait que le moment de le déclarer.

Le cabinet est branché PENDANT l'installation. On réutilise le moteur de Map
Commander tel quel (pincabos_vpx_input) : mêmes actions, mêmes jetons. On ne
fait que capturer ; l'écriture dans le VPinballX.ini et le vpinfe.ini de la
cible est rejouée au premier démarrage, là où les périphériques et les chemins
sont ceux du cabinet installé (leçon du ZeDMD appliqué dans le chroot).
"""
import json
import sys
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
GUI = R / "opt/pincabos/installer-gui"
MODULE = GUI / "inputs.py"
APP = GUI / "app.py"
WIZARD = GUI / "templates/wizard.html"
I18N = GUI / "i18n.json"
INSTALLEUR = R / "opt/pincabos/script/installer/pincabos-live-installer"
UNITE = R / "etc/systemd/system/pincabos-inputs-installer.service"
LIEN = R / "etc/systemd/system/multi-user.target.wants/pincabos-inputs-installer.service"
REJEU = R / "usr/local/sbin/pincabos-inputs-installer-apply"
LANGUES = ("fr", "en", "de", "it", "es")


def _mod():
    sys.path.insert(0, str(R / "opt/pincabos/tools"))
    sys.path.insert(0, str(GUI))
    import importlib
    import inputs as m
    importlib.reload(m)
    return m


class LeModuleReutiliseMapCommander(unittest.TestCase):
    def setUp(self):
        self.m = _mod()

    def test_les_actions_viennent_du_moteur(self):
        # surtout pas une seconde liste d actions qui divergerait
        self.assertIn("import pincabos_vpx_input", MODULE.read_text(encoding="utf-8"))
        ids = [a["id"] for a in self.m.actions()]
        for attendu in ("LeftFlipper", "RightFlipper", "Start", "LaunchBall", "ExitGame"):
            self.assertIn(attendu, ids)

    def test_l_essentiel_vient_en_premier(self):
        acts = self.m.actions()
        essentielles = [a for a in acts if a["essentielle"]]
        self.assertEqual([a["id"] for a in acts[:len(essentielles)]],
                         [a["id"] for a in essentielles],
                         "l essentiel doit ouvrir la liste")
        self.assertIn("LeftFlipper", [a["id"] for a in essentielles])

    def test_un_mappage_vide_reste_valide(self):
        # l etape est facultative : la passer ne doit rien casser
        self.assertEqual(self.m.valider({"mappings": {}}), ([], {"mappings": {}}))
        self.assertEqual(self.m.valider({})[0], [])

    def test_une_action_inconnue_est_refusee(self):
        erreurs, _ = self.m.valider({"mappings": {"PasUneAction": "Key;225"}})
        self.assertTrue(any("inconnue" in e for e in erreurs))

    def test_les_liaisons_sont_normalisees(self):
        _, ok = self.m.valider({"mappings": {"LeftFlipper": "Key;225"}})
        self.assertEqual(ok["mappings"]["LeftFlipper"], "Key;225")

    def test_le_delai_de_capture_est_borne(self):
        # une capture sans borne fige l assistant
        self.assertIn("DELAI_MAX", MODULE.read_text(encoding="utf-8"))

    def test_le_fichier_de_reponses_porte_sa_provenance(self):
        c = self.m.config_json({"mappings": {"Start": "Key;30"}})
        self.assertEqual(c["source"], "PinCabOS installer")
        self.assertEqual(c["mappings"], {"Start": "Key;30"})


class LAssistantExposeLEtape(unittest.TestCase):
    def test_les_routes_existent(self):
        s = APP.read_text(encoding="utf-8")
        self.assertIn('@app.route("/api/inputs")', s)
        self.assertIn('@app.route("/api/inputs/capture", methods=["POST"])', s)

    def test_le_choix_part_dans_les_reponses(self):
        s = APP.read_text(encoding="utf-8")
        self.assertIn("def boutons_vers_fichiers", s)
        self.assertIn('"inputs_file"', s)   # -> PCO_ANS_INPUTS_FILE
        self.assertIn('if isinstance(a.get("inputs"), dict):', s)

    def test_la_page_a_l_etape(self):
        h = WIZARD.read_text(encoding="utf-8")
        for m in ('id="st-inputs"', "loadInputs()", "captureAction(", "S.inputs"):
            self.assertIn(m, h)

    def test_l_etape_s_insere_entre_toys_et_reseau(self):
        h = WIZARD.read_text(encoding="utf-8")
        self.assertIn("loadInputs();go('st-inputs')", h, "l etape Toys doit y mener")
        bloc = h.split('id="st-inputs"', 1)[1].split("</section>", 1)[0]
        self.assertIn("go('st-toys')", bloc, "le retour va vers Toys")
        self.assertIn("go('st-network')", bloc, "la suite va vers Reseau")


class LeMappageEstRejoueAuPremierDemarrage(unittest.TestCase):
    """Jamais d'écriture depuis le chroot : ni les périphériques ni les chemins
    n'y sont ceux du cabinet installé."""

    def test_l_installateur_pose_le_fichier_et_le_drapeau(self):
        corps = INSTALLEUR.read_text(encoding="utf-8") \
            .split("apply_target_inputs() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("inputs-installer.json", corps)
        self.assertIn("flags/inputs-installer.pending", corps)

    def test_rien_n_est_ecrit_depuis_le_chroot(self):
        corps = INSTALLEUR.read_text(encoding="utf-8") \
            .split("apply_target_inputs() {", 1)[1].split("\n}", 1)[0]
        # On ne regarde que le CODE : le commentaire, lui, doit justement parler
        # du chroot pour expliquer pourquoi on n'y écrit pas. Piège déjà pris en
        # 4.63, où un test échouait sur son propre commentaire d'explication.
        code = "\n".join(l for l in corps.splitlines() if not l.strip().startswith("#"))
        self.assertNotIn("chroot", code,
                         "le mappage ne doit pas etre applique depuis le media")

    def test_l_etape_est_appelee(self):
        corps = INSTALLEUR.read_text(encoding="utf-8") \
            .split("install_payload() {", 1)[1].split("\nfinal_boot_refresh", 1)[0]
        self.assertIn("apply_target_inputs", corps)

    def test_l_unite_de_rejeu_est_activee(self):
        self.assertTrue(UNITE.is_file())
        u = UNITE.read_text(encoding="utf-8")
        self.assertIn("ConditionPathExists=/opt/pincabos/flags/inputs-installer.pending", u)
        self.assertIn("Before=pincabos-vpinfe.service", u)
        self.assertRegex(u, r"(?m)^WantedBy=multi-user\.target$")
        self.assertTrue(LIEN.is_symlink(), "le lien d activation manque")

    def test_le_drapeau_survit_a_un_echec(self):
        # comme pour le ZeDMD : on retente au demarrage suivant plutot que de
        # perdre ce que l utilisateur a saisi
        s = REJEU.read_text(encoding="utf-8")
        self.assertIn("drapeau conservé", s)
        self.assertIn("write_mappings", s)
        self.assertIn("write_vpinfe", s)


class LesLibellesSuivent(unittest.TestCase):
    def test_les_cinq_langues(self):
        d = json.loads(I18N.read_text(encoding="utf-8"))
        tailles = {k: len(v) for k, v in d.items()}
        self.assertEqual(len(set(tailles.values())), 1, "langues divergentes : %s" % tailles)
        for lang in LANGUES:
            for cle in ("inputs_title", "inputs_hint", "inputs_press", "inputs_timeout",
                        "inputs_more", "inputs_count", "inputs_skip_ok"):
                self.assertIn(cle, d[lang], "%s manque en %s" % (cle, lang))

    def test_l_aide_dit_que_l_etape_est_facultative(self):
        d = json.loads(I18N.read_text(encoding="utf-8"))
        for lang, mot in (("fr", "facultative"), ("en", "Optional"), ("de", "Optionaler"),
                          ("it", "facoltativo"), ("es", "opcional")):
            self.assertIn(mot, d[lang]["inputs_hint"],
                          "%s : rien ne dit que l etape peut etre passee" % lang)
