"""Chaque controleur de rubans a SON port (PINCABOS_DOF_PORT_PAR_FAMILLE_V1).

Remonte par Patrick le 09/09/2026 : sa Wemos n allumait aucune LED alors que la
carte repondait bien a son propre bouton de test. Son cabinet porte deux
controleurs de rubans — une Teensy et une Wemos.

La resolution du port « auto » etait la meme pour les deux familles :

    port = _tty_by_serial(serial) or _teensy_port() or "/dev/ttyACM0"

Or l inventaire n attribuait un numero de serie qu aux Teensy (la page Materiel
affichait « renseigner le n° de serie » pour la Wemos). Sans serie, la Wemos
tombait sur `_teensy_port()` — le port de la TEENSY. Les deux controleurs
sortaient dans cabinet.xml sur le meme /dev/ttyACM1 : la Wemos ne recevait
rien, et la Teensy recevait le trafic des deux.

Une Wemos se presente en CH340 (1a86) ou CP210x (10c4) sur /dev/ttyUSB*, jamais
sur /dev/ttyACM* que balaie `_teensy_port()` : les deux familles ne peuvent pas
partager la meme recherche.
"""
import importlib.util
import types
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
OUTIL = R / "opt/pincabos/tools/dof-cabinet/dof-cabinet.py"
PAGE = R / "opt/pincabos/web/pincabos_dof_hardware.py"


def _module():
    spec = importlib.util.spec_from_file_location("dof_cabinet", OUTIL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# un cabinet a deux controleurs, comme celui de Patrick
FAUX_BUS = {
    "/dev/ttyACM1": {"ID_VENDOR_ID": "16c0", "ID_SERIAL": "Teensyduino_USB_Serial",
                     "ID_MODEL": "USB_Serial", "ID_SERIAL_SHORT": "TEENSY123"},
    "/dev/ttyUSB0": {"ID_VENDOR_ID": "1a86", "ID_SERIAL": "1a86_USB_Serial",
                     "ID_MODEL": "USB_Serial", "ID_SERIAL_SHORT": ""},
}


def _poser_bus(m, bus):
    """Fait croire au module qu il voit ce bus USB.

    On remplace l ATTRIBUT `glob` du module par un objet a nous. Surtout pas
    `m.glob.glob = ...` : `m.glob` est le module glob lui-meme, partage par tout
    le processus — le remplacer casse silencieusement tous les tests suivants qui
    listent des fichiers (deux echecs a retardement, 09/09/2026).
    """
    m._udev = lambda dev: bus.get(dev, {})
    m.glob = types.SimpleNamespace(
        glob=lambda motif: sorted(d for d in bus if d.startswith(motif.rstrip("*"))))


class PortsDistincts(unittest.TestCase):
    def setUp(self):
        self.m = _module()
        _poser_bus(self.m, FAUX_BUS)

    def test_la_wemos_ne_prend_pas_le_port_de_la_teensy(self):
        strips = [{"controller": "TeensyStripController", "name": "Teensy 1"},
                  {"controller": "WemosD1MPStripController", "name": "Wemos 2"}]
        resolus = self.m._resoudre_ports(strips)
        ports = [r["com_port"] for r in resolus]
        self.assertEqual(ports[0], "/dev/ttyACM1", "la Teensy garde son port")
        self.assertEqual(ports[1], "/dev/ttyUSB0", "la Wemos doit prendre le port CH340")
        self.assertNotEqual(ports[0], ports[1], "deux controleurs sur le meme port")

    def test_l_ordre_de_declaration_ne_change_rien(self):
        strips = [{"controller": "WemosD1MPStripController", "name": "Wemos 1"},
                  {"controller": "TeensyStripController", "name": "Teensy 2"}]
        ports = [r["com_port"] for r in self.m._resoudre_ports(strips)]
        self.assertEqual(ports, ["/dev/ttyUSB0", "/dev/ttyACM1"])

    def test_sans_materiel_le_repli_reste_dans_la_bonne_famille(self):
        _poser_bus(self.m, {})
        strips = [{"controller": "WemosD1MPStripController", "name": "Wemos 1"},
                  {"controller": "TeensyStripController", "name": "Teensy 2"}]
        ports = [r["com_port"] for r in self.m._resoudre_ports(strips)]
        # une Wemos ne sort jamais sur ttyACM par defaut
        self.assertEqual(ports[0], "/dev/ttyUSB0")
        self.assertEqual(ports[1], "/dev/ttyACM0")

    def test_le_numero_de_serie_reste_prioritaire(self):
        strips = [{"controller": "TeensyStripController", "serial": "TEENSY123"}]
        self.assertEqual(self.m._resoudre_ports(strips)[0]["com_port"], "/dev/ttyACM1")

    def test_deux_cartes_de_la_meme_famille_ne_se_marchent_pas_dessus(self):
        bus = dict(FAUX_BUS)
        bus["/dev/ttyUSB1"] = {"ID_VENDOR_ID": "10c4", "ID_SERIAL": "cp210x",
                               "ID_MODEL": "CP2102", "ID_SERIAL_SHORT": ""}
        _poser_bus(self.m, bus)
        strips = [{"controller": "WemosD1MPStripController", "name": "W1"},
                  {"controller": "WemosD1MPStripController", "name": "W2"}]
        ports = [r["com_port"] for r in self.m._resoudre_ports(strips)]
        self.assertEqual(len(set(ports)), 2, "deux Wemos doivent avoir deux ports")


class LeGenerateurPasseParLaResolution(unittest.TestCase):
    def test_gen_resout_les_ports(self):
        texte = OUTIL.read_text(encoding="utf-8")
        self.assertIn("strips = _resoudre_ports(config.get(\"strips\", []))", texte,
                      "gen() doit resoudre les ports avant d ecrire cabinet.xml")

    def test_le_repli_direct_connait_la_famille(self):
        # _strip_controller peut etre appele seul : son repli doit rester fidele
        # a la famille, sinon le defaut revient par la petite porte.
        corps = OUTIL.read_text(encoding="utf-8").split("def _strip_controller", 1)[1][:1400]
        self.assertIn("_esp_port()", corps)
        self.assertIn("/dev/ttyUSB0", corps)


class InventaireParFamille(unittest.TestCase):
    """La page Materiel n attribuait un numero de serie qu aux Teensy."""

    def test_la_wemos_recoit_aussi_un_numero_de_serie(self):
        t = PAGE.read_text(encoding="utf-8")
        self.assertIn("series_par_type", t)
        self.assertIn("WemosD1MPStripController", t)
        self.assertNotIn("teensy_serials", t,
                         "la file reservee aux Teensy ne doit plus exister")
