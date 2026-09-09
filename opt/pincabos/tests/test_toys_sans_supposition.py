"""L'assistant ne decrit pas le cabinet a votre place (PINCABOS_TOYS_SANS_SUPPOSITION_V1).

Remonte par Patrick le 09/09/2026 : sa backboard n allumait que 512 LED sur
1368. L etape Toys proposait d office, pour le premier controleur detecte :

    mode = matrice, width = 144, height = 16, strips = repartir(2304)
                                                     -> [512, 512, 512, 512, 256]

Les deux valeurs etant coherentes ENTRE ELLES, le controle « le total doit
faire largeur x hauteur » passait sans rien dire. On validait, sans le voir, la
description du cabinet de quelqu un d autre — et la premiere sortie n eclairait
que ses 512 premieres LED.

512 n est pas arbitraire : c est le maximum qu une sortie de Teensy pilote. Une
matrice plus grande DOIT etre repartie sur plusieurs sorties, et cablee ainsi.
"""
import importlib.util
import json
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
OUTIL = R / "opt/pincabos/tools/pincabos_dof.py"
I18N = R / "opt/pincabos/installer-gui/i18n.json"
LANGUES = ("fr", "en", "de", "it", "es")


def _module():
    spec = importlib.util.spec_from_file_location("pincabos_dof", OUTIL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# une Teensy et une Wemos, comme chez Patrick
DETECTES = [
    {"dev": "/dev/ttyACM1", "serial": "TEENSY123", "auto_config": False,
     "kind": "TeensyStripController (strip adressable)"},
    {"dev": "/dev/ttyUSB0", "serial": "", "auto_config": False,
     "kind": "Wemos D1 / ESP via CH340 (WemosD1MPStripController possible)"},
]


class RienNEstInvente(unittest.TestCase):
    def setUp(self):
        self.m = _module()
        self.ctrls = self.m.proposer_toys(DETECTES)["controllers"]

    def test_les_controleurs_sont_bien_listes(self):
        self.assertEqual(len(self.ctrls), 2, "les cartes detectees doivent apparaitre")

    def test_aucun_n_arrive_allume(self):
        # un controleur allume mais mal decrit part sur le disque en silence
        for c in self.ctrls:
            self.assertFalse(c["enabled"], "%s ne doit pas etre allume d office" % c.get("type"))

    def test_aucune_dimension_inventee(self):
        for c in self.ctrls:
            self.assertEqual(c["width"], 0)
            self.assertEqual(c["height"], 0)
            self.assertEqual(c["strips"], [], "aucune LED ne doit etre supposee")

    def test_plus_de_matrice_144x16_par_defaut(self):
        texte = OUTIL.read_text(encoding="utf-8")
        corps = texte.split("def proposer_toys", 1)[1].split("\ndef ", 1)[0]
        for invente in ('"width": 144', '"height": 16', "repartir(144"):
            self.assertNotIn(invente, corps, "l assistant suppose encore " + invente)


class LaDecoupeEnSortiesResteJuste(unittest.TestCase):
    """`repartir` sert toujours, quand l utilisateur decrit VRAIMENT sa matrice."""

    def test_512_par_sortie(self):
        m = _module()
        self.assertEqual(m.repartir(2304), [512, 512, 512, 512, 256])
        self.assertEqual(m.repartir(1368), [512, 512, 344], "cas de Patrick : 19 x 72")
        self.assertEqual(m.repartir(0), [])


class LesLibellesDisentCeQuOnDemande(unittest.TestCase):
    def setUp(self):
        self.d = json.loads(I18N.read_text(encoding="utf-8"))

    def test_toutes_les_langues_suivent(self):
        tailles = {k: len(v) for k, v in self.d.items()}
        self.assertEqual(len(set(tailles.values())), 1, "les langues ont divergé : %s" % tailles)

    def test_l_audio_parle_de_cablage_pas_de_place(self):
        # Patrick : « Exciters à l'arrière du meuble ou à l'avant du meuble ? »
        # Les deux libelles disaient « (lockbar) » — or la lockbar est un seul
        # endroit, a l avant. La vraie question est : sur quels canaux de la
        # carte son les exciters sont-ils cables ?
        for lang in LANGUES:
            for cle in ("sound3d_2", "sound3d_3"):
                v = self.d[lang][cle]
                self.assertNotIn("lockbar", v.lower(),
                                 "%s/%s decrit encore une place dans le meuble" % (lang, cle))
        self.assertIn("ARRIÈRE", self.d["fr"]["sound3d_2"])
        self.assertIn("AVANT", self.d["fr"]["sound3d_3"])
        self.assertIn("REAR", self.d["en"]["sound3d_2"])
        self.assertIn("FRONT", self.d["en"]["sound3d_3"])

    def test_les_aides_audio_renvoient_au_test_des_haut_parleurs(self):
        for lang in LANGUES:
            for cle in ("sound3d_hint_2", "sound3d_hint_3"):
                self.assertGreater(len(self.d[lang][cle]), 120,
                                   "%s/%s reste trop court pour lever le doute" % (lang, cle))

    def test_l_aide_matrice_annonce_la_limite_de_512(self):
        # personne ne devine qu une sortie de Teensy s arrete a 512 LED
        for lang in LANGUES:
            self.assertIn("512", self.d[lang]["toys_outputs_hint_matrix"],
                          "%s : la limite par sortie n est pas dite" % lang)

    def test_la_page_toys_previent_que_rien_n_est_prerempli(self):
        for lang, mot in (("fr", "prérempli"), ("en", "pre-filled"), ("de", "vorausgefüllt"),
                          ("it", "precompilato"), ("es", "rellenado")):
            self.assertIn(mot, self.d[lang]["toys_hint"],
                          "%s : l utilisateur n est pas prevenu" % lang)
