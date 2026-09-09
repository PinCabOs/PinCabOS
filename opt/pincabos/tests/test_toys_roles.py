"""Chaque sortie adressable a un rôle (PINCABOS_TOYS_ROLES_V1).

Le nom du toy dans cabinet.xml était générique : « Backboard HD » pour la
première matrice, « Matrice 2 », « Ruban 1.2 »… Exact, mais illisible le jour
où l'on relit sa configuration — et c'est ce nom que DOF cherche ensuite.

Le rôle (backboard, sous le meuble, côtés, fronton, flippers, intérieur) donne
son nom à la sortie. Il reste FACULTATIF : sans lui, le nom générique demeure,
donc rien ne change pour un cabinet déjà configuré.

« backboard » garde volontairement « Backboard HD » : c'est le nom qu'ont les
cabinets en service, et le changer casserait leur configuration DOF.
"""
import importlib.util
import json
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
OUTIL = R / "opt/pincabos/tools/pincabos_dof.py"
GUI = R / "opt/pincabos/installer-gui"
WIZARD = GUI / "templates/wizard.html"
I18N = GUI / "i18n.json"
LANGUES = ("fr", "en", "de", "it", "es")

DETECTES = [{"dev": "/dev/ttyACM1", "serial": "TEENSY123", "auto_config": False,
             "kind": "TeensyStripController (strip adressable)"}]


def _module():
    spec = importlib.util.spec_from_file_location("pincabos_dof", OUTIL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class LeCatalogue(unittest.TestCase):
    def setUp(self):
        self.m = _module()

    def test_les_roles_attendus(self):
        for r in ("backboard", "sous-caisse", "cote-gauche", "cote-droit",
                  "fronton", "flippers", "interieur", "libre"):
            self.assertIn(r, self.m.ROLE_IDS)

    def test_backboard_garde_son_nom_historique(self):
        # les cabinets en service ont « Backboard HD » dans leur cabinet.xml
        self.assertEqual(self.m.nom_toy("backboard", "peu importe"), "Backboard HD")

    def test_sans_role_le_nom_generique_demeure(self):
        self.assertEqual(self.m.nom_toy("", "Ruban 1.2"), "Ruban 1.2")
        self.assertEqual(self.m.nom_toy("libre", "Ruban 1.2"), "Ruban 1.2")


class LaValidation(unittest.TestCase):
    def setUp(self):
        self.m = _module()

    def _ctrl(self, **kw):
        c = {"serial": "TEENSY123", "enabled": True, "mode": "rubans",
             "strips": [144, 144], "arrangement": "LeftRightTopDown",
             "color_order": "GRB", "brightness": 25, "ledwiz_number": 30}
        c.update(kw)
        return {"controllers": [c]}

    def test_un_role_connu_passe(self):
        erreurs, ok = self.m.valider_toys(self._ctrl(roles=["sous-caisse", "fronton"]), DETECTES)
        self.assertEqual(erreurs, [])
        self.assertEqual(ok["controllers"][0]["roles"], ["sous-caisse", "fronton"])

    def test_un_role_inconnu_est_refuse(self):
        erreurs, _ = self.m.valider_toys(self._ctrl(roles=["gyrophare"]), DETECTES)
        self.assertTrue(any("rôle inconnu" in e for e in erreurs))

    def test_le_role_reste_facultatif(self):
        erreurs, ok = self.m.valider_toys(self._ctrl(), DETECTES)
        self.assertEqual(erreurs, [])
        self.assertEqual(ok["controllers"][0]["roles"], [])
        self.assertEqual(ok["controllers"][0]["role"], "")

    def test_la_proposition_n_avance_aucun_role(self):
        # cohérent avec PINCABOS_TOYS_SANS_SUPPOSITION_V1
        for c in self.m.proposer_toys(DETECTES)["controllers"]:
            self.assertEqual(c["role"], "")
            self.assertEqual(c["roles"], [])


class LesToysPortentLeNomDuRole(unittest.TestCase):
    def setUp(self):
        self.m = _module()

    def test_en_rubans_chaque_sortie_est_nommee(self):
        choix = {"controllers": [{"serial": "TEENSY123", "enabled": True, "mode": "rubans",
                                  "strips": [144, 0, 72], "roles": ["sous-caisse", "", "fronton"],
                                  "arrangement": "LeftRightTopDown", "color_order": "GRB",
                                  "brightness": 25, "ledwiz_number": 30}]}
        _, ok = self.m.valider_toys(choix, DETECTES)
        inv = self.m.inventaire_json(ok, DETECTES)
        noms = [t["name"] for t in inv["devices"][0]["toys"]]
        self.assertEqual(noms, ["Undercab", "Backbox"],
                         "la sortie vide ne produit pas de toy, les autres portent leur rôle")

    def test_une_sortie_sans_role_garde_le_nom_generique(self):
        choix = {"controllers": [{"serial": "TEENSY123", "enabled": True, "mode": "rubans",
                                  "strips": [144, 144], "roles": ["sous-caisse"],
                                  "arrangement": "LeftRightTopDown", "color_order": "GRB",
                                  "brightness": 25, "ledwiz_number": 30}]}
        _, ok = self.m.valider_toys(choix, DETECTES)
        noms = [t["name"] for t in self.m.inventaire_json(ok, DETECTES)["devices"][0]["toys"]]
        self.assertEqual(noms, ["Undercab", "Ruban 1.2"])

    def test_en_matrice_le_role_nomme_le_controleur(self):
        choix = {"controllers": [{"serial": "TEENSY123", "enabled": True, "mode": "matrice",
                                  "width": 144, "height": 16, "role": "fronton",
                                  "strips": [512, 512, 512, 512, 256],
                                  "arrangement": "TopDownAlternateLeftRight", "color_order": "GRB",
                                  "brightness": 25, "ledwiz_number": 30}]}
        _, ok = self.m.valider_toys(choix, DETECTES)
        self.assertEqual(self.m.inventaire_json(ok, DETECTES)["devices"][0]["toy"]["name"], "Backbox")


class LAssistantLeDemande(unittest.TestCase):
    def test_le_choix_est_dans_la_page(self):
        h = WIZARD.read_text(encoding="utf-8")
        self.assertIn("selRole", h)
        self.assertIn('t("toys_role_"+r)', h)
        self.assertIn("c.roles=c.roles||[]", h, "le tableau des rôles doit être alimenté")

    def test_l_api_expose_les_roles(self):
        s = (GUI / "app.py").read_text(encoding="utf-8")
        self.assertIn('"roles": list(pco_dof.ROLE_IDS)', s)

    def test_un_libelle_par_role_dans_les_cinq_langues(self):
        d = json.loads(I18N.read_text(encoding="utf-8"))
        m = _module()
        tailles = {k: len(v) for k, v in d.items()}
        self.assertEqual(len(set(tailles.values())), 1, "langues divergentes : %s" % tailles)
        for lang in LANGUES:
            for r in m.ROLE_IDS:
                self.assertIn("toys_role_" + r, d[lang], "%s manque en %s" % (r, lang))
