"""Les tables de demonstration partent en mode automatique.

PINCABOS_SAMPLE_TABLES_DEFAUT_AUTO_V1 — Yann, 08/09/2026, apres une
installation complete depuis l'ISO : « l'option pour faire disparaitre les
tables de demo devrait etre positionnee sur automatique par defaut, pas sur
toujours affichees ».

Le script et l'interface etaient d'accord — « auto » est le repli du script et
la premiere option de la page, libellee « Automatique (recommande) ». Mais le
depot livrait un sample-tables.json a « always », qui gagne sur les deux :
chaque cabinet neuf gardait donc les tables d'exemple meme apres avoir importe
les siennes.
"""
import json
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
CONFIG = R / "opt/pincabos/config/sample-tables.json"
SCRIPT = R / "usr/local/sbin/pincabos-sample-tables"
UI = R / "opt/pincabos/web/tools.py"

MODES = ("auto", "always", "never")


class ModeParDefaut(unittest.TestCase):
    def test_le_fichier_livre_dit_auto(self):
        d = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(d.get("mode"), "auto",
                         "un cabinet neuf garderait les tables d'exemple pour toujours")

    def test_le_fichier_ne_contient_que_le_mode(self):
        """Une cle en trop ici serait un reglage fantome, jamais relu."""
        d = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(set(d), {"mode"}, d)

    def test_le_script_replie_sur_auto(self):
        """Fichier absent ou illisible : le comportement reste le bon."""
        s = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("auto|always|never)", s)
        # le cas par defaut du case, juste apres : *) printf 'auto...'
        defaut = re.search(r"auto\|always\|never\).*?\*\)\s*printf\s+'([a-z]+)", s, re.S)
        self.assertIsNotNone(defaut, "cas par defaut du case introuvable")
        self.assertEqual(defaut.group(1), "auto", "le repli du script doit etre auto")

    def test_l_interface_propose_auto_en_premier(self):
        """L'ordre de la liste est ce que l'oeil lit comme le defaut."""
        ui = UI.read_text(encoding="utf-8")
        bloc = ui[ui.index("_SAMPLE_TABLES_MODES = ("):]
        bloc = bloc[: bloc.index(chr(10) + ")")]
        ordre = re.findall(r'\("(auto|always|never)"', bloc)
        self.assertEqual(ordre[0], "auto", f"ordre affiche : {ordre}")
        self.assertEqual(set(ordre), set(MODES), ordre)

    def test_les_trois_modes_restent_offerts(self):
        """Corriger le defaut ne doit pas retirer un choix a l'utilisateur."""
        s = SCRIPT.read_text(encoding="utf-8")
        for m in MODES:
            self.assertIn(m, s)


if __name__ == "__main__":
    unittest.main()
