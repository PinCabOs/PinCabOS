"""Étape « Écrans » de l'assistant d'installation (PINCABOS_INSTALLEUR_ECRANS_V1).

Sorties xrandr réelles du cab de Yann (NVIDIA, trois écrans) ; aucune commande
exécutée : un faux exécuteur enregistre ce qui serait lancé.
"""
import json
import re
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE

sc = charger("opt/pincabos/installer-gui/screens.py", "pco_installer_screens")

QUERY = """Screen 0: minimum 8 x 8, current 7680 x 2160, maximum 32767 x 32767
HDMI-0 connected primary 3840x2160+0+0 (normal left inverted right x axis y axis) 1600mm x 900mm
   3840x2160     143.99*+  60.00    59.94    50.00    30.00
   1920x1080     60.00    59.94    50.00
DP-0 connected 1920x1080+5760+0 (normal left inverted right x axis y axis) 597mm x 336mm
   1920x1080     60.00*+  50.00
DP-1 disconnected (normal left inverted right x axis y axis)
DP-2 connected 1920x1080+3840+0 (normal left inverted right x axis y axis) 598mm x 336mm
   1920x1080     60.00*+
DP-3 disconnected (normal left inverted right x axis y axis)
"""
QUERY_INVERTED = QUERY.replace("HDMI-0 connected primary 3840x2160+0+0 (normal", "HDMI-0 connected primary 3840x2160+0+0 inverted (normal")
PROPS = """HDMI-0 connected primary 3840x2160+0+0 (0x1c6) normal (normal left inverted right x axis y axis) 1600mm x 900mm
	EDID:
		00ffffffffffff001e6dcd8201010101
		0122010380a05a780aee91a3544c9926
		0f5054a1080031404540614071408180
		d1c00101010108e80030f2705a80b058
		8a0040846300001e6fc200a0a0a05550
		3020350040846300001e000000fd0018
		901eff86000a202020202020000000fc
		004c472054562053534352320a200372
DP-0 connected 1920x1080+5760+0 (0x1d3) normal (normal left inverted right x axis y axis) 597mm x 336mm
	EDID:
		00ffffffffffff004a8b3b2a01010101
		17150103803c2278ea1ec5ae4f34b126
		0e5054a54b008180a940d1c0714f0101
		010101010101023a801871382d40582c
		450055502100001e000000ff004a3235
		374d3936423030464c0a000000fc0052
		544b204648440a2020202020000000fd
		00384c1e5111000a20202020202001bb
DP-2 connected 1920x1080+3840+0 (0x1d3) normal (normal left inverted right x axis y axis) 598mm x 336mm
	Brightness: 1.0
"""


class Faux:
    def __init__(self, query=QUERY, props=PROPS, rc=0):
        self.query, self.props, self.rc = query, props, rc
        self.commandes = []

    def __call__(self, args, timeout=20):
        self.commandes.append(list(args))
        if args[:2] == ["xrandr", "--query"]:
            return 0, self.query, ""
        if args[:2] == ["xrandr", "--prop"]:
            return 0, self.props, ""
        return self.rc, "", "" if self.rc == 0 else "xrandr: erreur simulee"


class Decouverte(unittest.TestCase):
    def test_parse_query(self):
        s = sc.parse_query(QUERY)
        self.assertEqual([x["name"] for x in s], ["HDMI-0", "DP-0", "DP-1", "DP-2", "DP-3"])
        pf = s[0]
        self.assertTrue(pf["connected"] and pf["primary"])
        self.assertEqual((pf["width"], pf["height"], pf["x"], pf["y"]), (3840, 2160, 0, 0))
        self.assertEqual(pf["preferred"], "3840x2160")
        self.assertEqual(pf["modes"], ["3840x2160", "1920x1080"])
        self.assertEqual(pf["mm"], (1600, 900))
        self.assertFalse(s[2]["connected"])
        self.assertEqual(sc.parse_query(QUERY_INVERTED)[0]["rotation"], 180)

    def test_edid(self):
        e = sc.parse_edids(PROPS)
        self.assertEqual(set(e), {"HDMI-0", "DP-0"})
        self.assertEqual(len(e["HDMI-0"]), 64)
        self.assertNotEqual(e["HDMI-0"], e["DP-0"])

    def test_moniteurs(self):
        mons = sc.moniteurs(QUERY, PROPS)
        self.assertEqual([m["name"] for m in mons], ["HDMI-0", "DP-0", "DP-2"], "ordre de declaration X = identifiant VPinFE")
        self.assertEqual([m["app_index"] for m in mons], [0, 1, 2])
        self.assertTrue(mons[2]["edid_sha256"].startswith("connector:DP-2"), "sans EDID : repli sur le nom de sortie")
        self.assertEqual(mons[0]["area"], 3840 * 2160)

    def test_decouvrir(self):
        f = Faux()
        mons = sc.decouvrir(f)
        self.assertEqual(len(mons), 3)
        self.assertEqual(f.commandes[0], ["xrandr", "--query"])
        with self.assertRaises(RuntimeError):
            sc.decouvrir(lambda a, timeout=20: (1, "", "Can't open display"))


class Roles(unittest.TestCase):
    def test_proposition_cab_de_yann(self):
        mons = sc.moniteurs(QUERY, PROPS)
        r = sc.proposer_roles(mons)
        self.assertEqual(r["playfield"], "HDMI-0")
        self.assertEqual({r["backglass"], r["fulldmd"]}, {"DP-0", "DP-2"})
        self.assertEqual(r["topper"], "")

    def test_dmd_reconnu_par_son_format(self):
        q = QUERY.replace("DP-0 connected 1920x1080+5760+0", "DP-0 connected 1920x480+5760+0").replace("   1920x1080     60.00*+  50.00", "   1920x480      60.00*+")
        mons = sc.moniteurs(q, PROPS)
        r = sc.proposer_roles(mons)
        self.assertEqual(r, {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""})

    def test_quatre_ecrans(self):
        q = QUERY.replace("DP-3 disconnected (normal left inverted right x axis y axis)", "DP-3 connected 1280x720+7680+0 (normal left inverted right x axis y axis) 300mm x 170mm\n   1280x720      60.00*+")
        r = sc.proposer_roles(sc.moniteurs(q, PROPS))
        self.assertEqual(r["topper"], "DP-3")

    def test_un_seul_ecran(self):
        q = "\n".join(l for l in QUERY.splitlines() if not l.startswith(("DP-0", "DP-2", "   1920x1080     60.00*+"))) + "\n"
        r = sc.proposer_roles(sc.moniteurs(q, PROPS))
        self.assertEqual(r, {"playfield": "HDMI-0", "backglass": "", "fulldmd": "", "topper": ""})

    def test_usage_propose_et_valide(self):
        # PINCABOS_INSTALLEUR_CAB_USAGE_V1 : le cab de Yann = backglass + full DMD, pas de topper
        mons = sc.moniteurs(QUERY, PROPS)
        roles = sc.proposer_roles(mons)
        self.assertEqual(sc.usage_propose(roles), {"backglass": True, "fulldmd": True, "topper": False})
        self.assertEqual(sc.valider_usage(sc.usage_propose(roles), roles), [])
        # declare un topper sans ecran, nie le backglass qui a un ecran
        erreurs = sc.valider_usage({"backglass": False, "fulldmd": True, "topper": True}, roles)
        # PINCABOS_INSTALLEUR_MINIMUM_V1 : nier le backglass est en plus une faute en soi
        self.assertEqual(len(erreurs), 3)
        self.assertTrue(any(e.startswith("topper") and "aucun écran" in e for e in erreurs))
        self.assertTrue(any(e.startswith("backglass") and "absent" in e for e in erreurs))
        self.assertTrue(any(e.startswith("backglass") and "obligatoire" in e for e in erreurs))
        self.assertIsNone(sc.usage_depuis({}))
        self.assertEqual(sc.usage_depuis({"usage": {"topper": 1}}), {"backglass": False, "fulldmd": False, "topper": True})

    def test_validation(self):
        mons = sc.moniteurs(QUERY, PROPS)
        self.assertEqual(sc.valider_roles({"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""}, mons), [])
        self.assertIn("le playfield est obligatoire", sc.valider_roles({"playfield": "", "backglass": "DP-2"}, mons))
        self.assertTrue(any("inconnue" in e for e in sc.valider_roles({"playfield": "HDMI-9"}, mons)))
        self.assertTrue(any("à la fois" in e for e in sc.valider_roles({"playfield": "HDMI-0", "backglass": "HDMI-0"}, mons)))


class Disposition(unittest.TestCase):
    ROLES = {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""}

    def test_canonique(self):
        mons = sc.moniteurs(QUERY, PROPS)
        d = sc.disposition(mons, self.ROLES, 0)
        self.assertEqual((d["HDMI-0"]["x"], d["DP-2"]["x"], d["DP-0"]["x"]), (0, 3840, 5760))
        self.assertTrue(d["HDMI-0"]["primary"] and not d["DP-2"]["primary"])
        cmd = sc.commande_xrandr(d, ["DP-1"])
        self.assertEqual(cmd[:8], ["xrandr", "--output", "HDMI-0", "--mode", "3840x2160", "--pos", "0x0", "--rotate"])
        self.assertIn("--primary", cmd)
        self.assertEqual(cmd[-3:], ["--output", "DP-1", "--off"])

    def test_playfield_tourne_de_90(self):
        mons = sc.moniteurs(QUERY, PROPS)
        d = sc.disposition(mons, self.ROLES, 90)
        self.assertEqual((d["HDMI-0"]["width"], d["HDMI-0"]["height"]), (2160, 3840), "largeur vue par X apres rotation")
        self.assertEqual(d["DP-2"]["x"], 2160, "le fronton se pose apres la hauteur de la dalle")
        self.assertEqual(d["HDMI-0"]["mode"], "3840x2160", "le mode reste celui de la dalle")
        self.assertIn("right", sc.commande_xrandr(d))

    def test_appliquer(self):
        f = Faux()
        mons = sc.decouvrir(f)
        res = sc.appliquer(mons, self.ROLES, 180, f)
        self.assertTrue(res["ok"], res)
        self.assertIn("inverted", res["commande"])
        self.assertEqual(sc.appliquer(mons, {"playfield": ""}, 0, f)["ok"], False)
        self.assertEqual(sc.appliquer(mons, self.ROLES, 45, f)["ok"], False)
        f2 = Faux(rc=1)
        mons = sc.decouvrir(f2)
        res = sc.appliquer(mons, self.ROLES, 0, f2)
        self.assertFalse(res["ok"])
        self.assertIn("xrandr", res["erreurs"][0])


class Fichier(unittest.TestCase):
    ROLES = {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""}

    def test_screens_json(self):
        mons = sc.moniteurs(QUERY, PROPS)
        d = sc.screens_json(mons, self.ROLES, 180)
        self.assertEqual(d["playfield_rotation"], "180")
        self.assertEqual(d["mode"], "installer")
        self.assertEqual(d["roles"]["playfield"], {"output": "HDMI-0", "mode": "3840x2160", "rate": "143.99"})   # PINCABOS_INSTALLEUR_CADENCE_V1
        pf = d["playfield"]
        for k in ("name", "x", "y", "width", "height", "area", "is_primary", "raw", "edid_sha256", "geometry", "id", "screen_id", "available"):
            self.assertIn(k, pf, k)
        self.assertEqual(pf["geometry"], "3840x2160+0+0")
        self.assertEqual(d["backglass"]["geometry"], "1920x1080+3840+0")
        self.assertEqual(d["fulldmd"]["screen_id"], 1, "identifiant VPinFE = rang de la sortie, pas rang du role")
        self.assertNotIn("topper", d)
        b = sc.bindings_json(d)
        self.assertEqual(set(b["roles"]), {"playfield", "backglass", "fulldmd"})
        self.assertEqual(b["disabled_roles"], ["topper"])
        self.assertEqual(b["roles"]["playfield"], pf["edid_sha256"])
        json.dumps(d)

    def test_code_orient_du_moteur(self):
        self.assertEqual([sc.code_orient(r) for r in (0, 90, 180, 270)], ["1", "2", "4", "3"])

    def test_identification(self):
        appels = []

        def run(args, timeout=20):
            appels.append(list(args))
            return 0, "", ""
        mons = sc.moniteurs(QUERY, PROPS)
        res = sc.identifier(mons, self.ROLES, 5, run=run)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["labels"]["HDMI-0"], {"number": 1, "role": "Playfield"})
        self.assertEqual(res["labels"]["DP-2"]["number"], 3)
        self.assertEqual(appels[0][:3], ["python3", str(sc.IDENTIFY), "--seconds"])


class Assistant(unittest.TestCase):
    """L'appli Flask en mode démo : trois écrans factices, aucune commande."""

    @classmethod
    def setUpClass(cls):
        try:
            import flask  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("flask absent")
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ["PCO_DEMO"] = "1"
        os.environ["PCO_RUN_DIR"] = str(cls.tmp)
        import sys
        sys.path.insert(0, str(Path(RACINE) / "opt/pincabos/installer-gui"))
        cls.app = charger("opt/pincabos/installer-gui/app.py", "pco_installer_app")
        cls.client = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ecrans_demo(self):
        d = self.client.get("/api/screens").get_json()
        self.assertEqual([m["name"] for m in d["monitors"]], ["HDMI-0", "DP-0", "DP-2"])
        self.assertEqual(d["roles"], {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""})
        r = self.client.post("/api/screens/apply", json={"roles": d["roles"], "rotation": 180}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["disposition"]["DP-2"]["x"], 3840)
        r = self.client.post("/api/screens/apply", json={"roles": {"playfield": ""}, "rotation": 0}).get_json()
        self.assertFalse(r["ok"])
        self.assertTrue(self.client.post("/api/screens/identify", json={"roles": d["roles"]}).get_json()["ok"])

    def test_installation_ecrit_screens_et_orient(self):
        d = self.client.get("/api/screens").get_json()
        r = self.client.post("/api/install", json={"lang": "fr", "locale": "fr_FR.UTF-8", "xkb": "fr", "tz": "Europe/Paris", "mode": "1",
                                                   "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS",
                                                   "screens": {"roles": d["roles"], "rotation": 180}})
        self.assertEqual(r.status_code, 200, r.get_json())
        env = (self.tmp / "gui-answers.env").read_text(encoding="utf-8")
        self.assertIn("PCO_ANS_SCREENS_FILE=" + str(self.tmp / "gui-screens.json"), env.replace("'", ""))
        self.assertIn("PCO_ANS_BINDINGS_FILE=", env)
        self.assertIn("PCO_ANS_ORIENT=4", env)
        data = json.loads((self.tmp / "gui-screens.json").read_text(encoding="utf-8"))
        self.assertEqual(data["playfield_rotation"], "180")
        self.assertEqual(data["playfield"]["name"], "HDMI-0")
        liaisons = json.loads((self.tmp / "gui-screens-bindings.json").read_text(encoding="utf-8"))
        self.assertEqual(liaisons["roles"]["playfield"], "demo-pf")
        r = self.client.post("/api/install", json={"lang": "fr", "mode": "1", "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS",
                                                   "screens": {"roles": {"playfield": "HDMI-9"}, "rotation": 0}})
        self.assertEqual(r.status_code, 400)

    def test_installation_avec_l_etat_entier_de_l_assistant(self):
        # PINCABOS_INSTALLEUR_REPONSE_NULLE_V1 : l'assistant envoie tout son état,
        # orient:null compris (calculé ici depuis Écrans). Vu en VM : refus « bad-orient ».
        d = self.client.get("/api/screens").get_json()
        etat = {"lang": "fr", "locale": "fr_FR.UTF-8", "xkb": "fr", "xkb_variant": "", "tz": "Europe/Paris",
                "orient": None, "mode": "1", "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS",
                "screens": {"roles": d["roles"], "rotation": 0, "usage": d["usage"]},
                "dmd": {"type": "none", "device": "", "wifi_addr": ""}, "network": {"applied": []}}
        r = self.client.post("/api/install", json=etat)
        self.assertEqual(r.status_code, 200, r.get_json())
        env = (self.tmp / "gui-answers.env").read_text(encoding="utf-8")
        self.assertIn("PCO_ANS_ORIENT=1", env)
        self.assertNotIn("PCO_ANS_ORIENT=None", env)
        # une vraie valeur hors moule reste refusee
        r = self.client.post("/api/install", json=dict(etat, orient="9"))
        self.assertEqual(r.get_json()["error"], "bad-orient")

    def test_minimum_playfield_et_backglass(self):
        # PINCABOS_INSTALLEUR_MINIMUM_V1 : sans backglass, ni test de disposition ni installation
        d = self.client.get("/api/screens").get_json()
        self.assertTrue(d["usage"]["backglass"])
        sans = dict(d["roles"], backglass="")
        rep = self.client.post("/api/screens/apply", json={"roles": sans, "rotation": 0,
                               "usage": dict(d["usage"], backglass=False)}).get_json()
        self.assertFalse(rep["ok"])
        self.assertTrue(any("backglass" in e for e in rep["erreurs"]))
        r = self.client.post("/api/install", json={"lang": "fr", "mode": "1", "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS",
                                                   "screens": {"roles": sans, "rotation": 0, "usage": dict(d["usage"], backglass=False)}})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], "bad-screens")
        self.assertEqual(sc.usage_propose({"playfield": "HDMI-0"}), {"backglass": True, "fulldmd": False, "topper": False})
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.assertIn('class="segb sel" disabled data-use="backglass"', w)
        self.assertIn('if(role==="backglass")return;', w)

    def test_pointeurs_absolus_cadres_sur_le_playfield(self):
        # PINCABOS_INSTALLEUR_POINTEUR_ABSOLU_V1 (VM : plus de clic apres l application)
        liste = (
            "⎡ Virtual core pointer                    \tid=2\t[master pointer  (3)]\n"
            "⎜   ↳ Virtual core XTEST pointer              \tid=4\t[slave  pointer  (2)]\n"
            "⎜   ↳ QEMU Virtio Tablet                      \tid=6\t[slave  pointer  (2)]\n"
            "⎜   ↳ VirtualPS/2 VMware VMMouse              \tid=10\t[slave  pointer  (2)]\n"
            "⎜   ↳ ILITEK Multi-Touch-V5000               \tid=12\t[slave  pointer  (2)]\n"
            "⎣ Virtual core keyboard                   \tid=3\t[master keyboard (2)]\n"
            "    ↳ QEMU Virtio Keyboard                    \tid=7\t[slave  keyboard (3)]\n")
        self.assertEqual(sc.pointeurs_absolus(liste), [6, 12])
        appels = []

        def f(args, timeout=20):
            appels.append(args)
            return (0, liste if args[:2] == ["xinput", "list"] else "", "")
        self.assertEqual(sc.cadrer_pointeurs_absolus("HDMI-0", f), [6, 12])
        self.assertIn(["xinput", "map-to-output", "6", "HDMI-0"], appels)
        # xinput absent : rien a cadrer, pas d erreur
        self.assertEqual(sc.cadrer_pointeurs_absolus("HDMI-0", lambda a, timeout=20: (127, "", "absent")), [])
        mons = sc.moniteurs(QUERY, PROPS)
        res = sc.appliquer(mons, {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""}, 0, f)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["pointeurs"], [6, 12])

    def test_mode_applique_est_le_mode_natif(self):
        # PINCABOS_INSTALLEUR_MODE_NATIF_V1 : cab 4K dont la session tourne en 1080p -> 4K ecrit
        cab = {"name": "HDMI-0", "width": 1920, "height": 1080, "preferred": "3840x2160", "modes": ["3840x2160", "1920x1080"]}
        self.assertEqual(sc.mode_de(cab), (3840, 2160))
        sans_pref = {"name": "V", "width": 1440, "height": 1920, "preferred": "", "modes": ["1920x1440", "1280x800"]}
        self.assertEqual(sc.mode_de(sans_pref), (1920, 1440))     # deja tournee : cotes remis
        d = sc.disposition([cab, dict(cab, name="DP-2", preferred="1920x1080")], {"playfield": "HDMI-0", "backglass": "DP-2"}, 0)
        self.assertEqual(d["HDMI-0"]["mode"], "3840x2160")
        self.assertEqual(d["DP-2"]["x"], 3840)

    def test_cadence_preferee_et_calibrations(self):
        # PINCABOS_INSTALLEUR_CADENCE_V1 / CALIBRATIONS_V1 (retex cab de Yann : 23,98 Hz, full DMD du cab source)
        mons = sc.moniteurs(QUERY, PROPS)
        par_nom = {m["name"]: m for m in mons}
        self.assertEqual(par_nom["HDMI-0"]["preferred_rate"], "143.99")
        self.assertEqual(par_nom["DP-0"]["preferred_rate"], "60.00")
        roles = {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""}
        data = sc.screens_json(mons, roles, 0)
        self.assertEqual(data["roles"]["backglass"]["rate"], "60.00")
        self.assertEqual(data["roles"]["playfield"]["rate"], "143.99")
        cal = sc.calibrations_json(data)
        fd = data["fulldmd"]
        self.assertEqual(cal["fulldmd"]["geometry_x11"], f"{fd['width']}x{fd['height']}+{fd['x']}+{fd['y']}")
        self.assertEqual(cal["fulldmd"]["screen_id"], str(fd["id"]))
        self.assertEqual(cal["dmd"]["width"], (fd["width"] * 2) // 3)
        self.assertEqual(cal["dmd"]["height"], cal["dmd"]["width"] // 4)
        self.assertGreaterEqual(cal["dmd"]["x"], fd["x"])
        # sans full DMD : DMD en haut du backglass
        sans = sc.screens_json(mons, {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "", "topper": ""}, 0)
        cal2 = sc.calibrations_json(sans)
        self.assertIsNone(cal2["fulldmd"])
        self.assertEqual(cal2["dmd"]["screen_id"], str(sans["backglass"]["id"]))
        self.assertEqual(cal2["dmd"]["width"], sans["backglass"]["width"] // 2)
        s = Path(RACINE, "opt/pincabos/script/iso.sh").read_text(encoding="utf-8")
        self.assertIn('PCO_ANS_CALIBRATIONS_FILE', s)
        self.assertIn('rm -f "$TARGET/opt/pincabos/config/fulldmd-calibration.json"', s)

    def test_decor_des_dalles_secondaires(self):
        # PINCABOS_INSTALLEUR_DECOR_V1 (Yann) : backglass / full DMD / topper habilles pendant l installation
        import random
        with tempfile.TemporaryDirectory() as d:
            g = Path(d)
            for n in ("paysage0.png", "paysage1.jpg", "portrait0.png", "grub0.jpg"):
                (g / n).write_bytes(b"x")
            mons = sc.moniteurs(QUERY, PROPS)
            imgs = sc.images_decor(mons, {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0"}, g, random.Random(1))
            self.assertEqual(sorted(imgs), ["DP-0", "DP-2"])                       # jamais le playfield
            self.assertTrue(all(Path(v).name.startswith("paysage") for v in imgs.values()))
            self.assertEqual(sc.images_decor(mons, {"playfield": "HDMI-0"}, Path(d, "vide"), random.Random(1)), {})
        src = Path(RACINE, "opt/pincabos/installer-gui/decor.py").read_text(encoding="utf-8")
        self.assertIn('TITRE = "pincabos-decor-{n}"', src)
        self.assertIn("Gtk.ContentFit.COVER", src)
        rc = Path(RACINE, "opt/pincabos/installer-gui/kiosk-rc.xml").read_text(encoding="utf-8")
        self.assertIn('<application title="pincabos-decor-1">', rc)
        self.assertEqual(rc.count("<layer>below</layer>"), 8)
        import xml.dom.minidom
        xml.dom.minidom.parseString(rc)
        a = Path(RACINE, "opt/pincabos/installer-gui/app.py").read_text(encoding="utf-8")
        self.assertIn('res["decor"] = pco_screens.lancer_decor(mons, roles)', a)

    def test_egerie_sur_chaque_page(self):
        # PINCABOS_INSTALLEUR_EGERIE_V3 (Yann : repartie de facon homogene sur les pages)
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        ids = re.findall(r'<section class="step(?: active)?" id="(st-[a-z]+)"', w)
        pages = dict(re.findall(r'"(st-[a-z]+)":"(pose-[a-z0-9-]+)"', w.split("const EGERIE_PAGES=")[1].split(";")[0]))
        self.assertEqual(sorted(ids), sorted(pages))                      # une pose par page, toutes les pages
        self.assertEqual(len(set(pages.values())), len(pages))            # toutes differentes
        for p in pages.values():
            self.assertTrue(Path(RACINE, "opt/pincabos/installer-gui/static/egerie", p + ".webp").is_file(), p)
        self.assertIn('class="egerie egerie-page" id="egerie"', w)
        self.assertIn("main{position:relative;z-index:1}", w)
        self.assertIn("go=function(id){_goSansEgerie(id);egeriePour(id)}", w)

    def test_rotation_de_lecture_jamais_ecrite(self):
        # PINCABOS_INSTALLEUR_LECTURE_V1 (Yann) : l assistant tourne, la config reste standard
        mons = sc.moniteurs(QUERY, PROPS)
        roles = {"playfield": "HDMI-0", "backglass": "DP-2", "fulldmd": "DP-0", "topper": ""}
        appels = []

        def f(args, timeout=20):
            appels.append(args)
            return (0, "", "")
        res = sc.appliquer(mons, roles, 0, f, lecture=90)
        self.assertTrue(res["ok"], res)
        cmd = [a for a in appels if a and a[0] == "xrandr"][0]
        self.assertIn("right", cmd)                                  # la session est tournee...
        data = sc.screens_json(mons, roles, 0)                       # ...la config, non
        self.assertEqual(data["playfield_rotation"], "0")
        self.assertEqual(data["playfield"]["geometry"], "3840x2160+0+0")
        self.assertFalse(sc.appliquer(mons, roles, 0, f, lecture=45)["ok"])
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.assertNotIn('data-rot="90"', w)
        self.assertIn('data-lecture="270"', w)
        self.assertIn("S.screens.lecture=+b.dataset.lecture", w)
        i18n = json.loads(Path(RACINE, "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for l in ("fr", "en", "de", "it", "es"):
            self.assertIn("lecture_q", i18n[l]); self.assertNotIn("o_90", i18n[l])
        k = Path(RACINE, "usr/local/bin/pincabos-kiosk.py").read_text(encoding="utf-8")
        self.assertIn("set_zoom_level(2.0 if max(g.width, g.height) >= 3000 else 1.0)", k)

    def test_kiosque_un_bureau_sans_liaisons_et_suit_la_geometrie(self):
        # PINCABOS_KIOSK_OPENBOX_V1 / PINCABOS_KIOSK_SUIT_LA_GEOMETRIE_V1 (Yann : molette = changement de bureau, coince)
        rc = Path(RACINE, "opt/pincabos/installer-gui/kiosk-rc.xml").read_text(encoding="utf-8")
        self.assertIn("<number>1</number>", rc)
        self.assertNotIn("GoToDesktop", rc)
        self.assertNotIn("mousebind", rc)
        sess = Path(RACINE, "usr/local/bin/pincabos-kiosk-session").read_text(encoding="utf-8")
        self.assertIn("openbox --config-file /opt/pincabos/installer-gui/kiosk-rc.xml", sess)
        k = Path(RACINE, "usr/local/bin/pincabos-kiosk.py").read_text(encoding="utf-8")
        self.assertIn('geometrie(mon) != cible["geometrie"]', k)
        self.assertIn("view.grab_focus()", k)

    def test_identification_en_overlay(self):
        # PINCABOS_INSTALLEUR_IDENTIFY_OVERLAY_V1 (Yann) : badge dans un coin, par-dessus, sans focus
        src = Path(RACINE, "opt/pincabos/installer-gui/identify.py").read_text(encoding="utf-8")
        self.assertNotIn("fullscreen_on_monitor", src)
        self.assertIn('TITRE = "pincabos-identify-{n}"', src)
        self.assertIn("win.set_title(TITRE.format(n=i + 1))", src)
        rc = Path(RACINE, "opt/pincabos/installer-gui/kiosk-rc.xml").read_text(encoding="utf-8")
        for n in (1, 2, 8):
            self.assertIn(f'<application title="pincabos-identify-{n}">', rc)
            self.assertIn(f"<monitor>{n}</monitor>", rc)
        self.assertIn("<layer>above</layer>", rc)
        self.assertEqual(rc.count("<focus>no</focus>"), 16)   # 8 badges d identification + 8 decors (PINCABOS_INSTALLEUR_DECOR_V1)
        import xml.dom.minidom
        xml.dom.minidom.parseString(rc)

    def test_ergonomie_de_l_etape(self):
        # PINCABOS_INSTALLEUR_ECRANS_UX_V1 (Yann : « pas très clair ») : trois gestes numerotes,
        # un bouton d application primaire dans sa carte, un etat qui dit quoi faire, numeros automatiques
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.assertEqual(w.count('<span class="stepno">'), 3)
        self.assertIn('class="primary" id="btn-apply"', w)
        self.assertIn('id="screens-status" data-state="todo"', w)
        self.assertIn('id="screens-next-hint"', w)
        self.assertIn("setTimeout(identifyScreens,500)", w)          # numeros a l arrivee
        self.assertIn('resumeDisposition());identifyScreens()', w)   # roles sur les dalles apres application
        self.assertIn('setScreensStatus("screens_changed",false)', w)
        i18n = json.loads(Path(RACINE, "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for l in ("fr", "en", "de", "it", "es"):
            for k in ("screens_roles_title", "screens_changed", "screens_next_hint", "screens_dalle", "apply_layout"):
                self.assertIn(k, i18n[l], (l, k))

    def test_egerie_et_credits(self):
        # PINCABOS_INSTALLEUR_EGERIE_V1 / CREDITS_V1 : emplacements Miss Tilt (Langue, Progression, Terminé), auteurs
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        for f in Path(RACINE, "opt/pincabos/installer-gui/static/egerie").glob("*.webp"):
            self.assertLess(f.stat().st_size, 400_000, f.name)
        self.assertEqual(len(list(Path(RACINE, "opt/pincabos/installer-gui/static/egerie").glob("*.webp"))), 15)
        self.assertIn('<footer class="credits">', w)
        self.assertIn("Karots SugarPie &amp; YaNFoX", w)
        i18n = json.loads(Path(RACINE, "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for l in ("fr", "en", "de", "it", "es"):
            self.assertIn("progress_start", i18n[l])
            self.assertIn("backglass", i18n[l]["cab_usage_hint"].lower())

    def test_le_wizard_affiche_un_refus(self):
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.assertIn('id="confirm-status"', w)
        self.assertIn("launchRefused(d,r.status)", w)
        self.assertNotIn("if(!r.ok)throw 0", w)
        i18n = json.loads(Path(RACINE, "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for l in ("fr", "en", "de", "it", "es"):
            self.assertIn("install_refused", i18n[l])

    def test_usage_dans_l_api(self):
        d = self.client.get("/api/screens").get_json()
        self.assertIn("usage", d)
        self.assertEqual(set(d["usage"]), {"backglass", "fulldmd", "topper"})
        # un topper declare sans ecran : l'application est refusee
        rep = self.client.post("/api/screens/apply", json={"roles": d["roles"], "rotation": 0,
                               "usage": dict(d["usage"], topper=True)}).get_json()
        self.assertFalse(rep["ok"])
        self.assertTrue(any("topper" in e for e in rep["erreurs"]))
        rep = self.client.post("/api/screens/apply", json={"roles": d["roles"], "rotation": 0, "usage": d["usage"]}).get_json()
        self.assertTrue(rep["ok"])

    def test_page(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="st-screens"', html)
        self.assertIn('id="cab-usage"', html)
        self.assertIn("toggleUsage", html)
        self.assertNotIn('id="st-orient"', html)
        self.assertIn("applyScreens", html)
        self.assertIn("screens-next", html)


class Integration(unittest.TestCase):
    def test_iso_sh_pose_screens_sur_la_cible(self):
        s = (Path(RACINE) / "opt/pincabos/script/iso.sh").read_text(encoding="utf-8")
        self.assertIn("apply_target_screens() {", s)
        self.assertIn('install -o 1000 -g 1000 -m 0664 "$src" "$TARGET/opt/pincabos/config/screens/screens.json"', s)
        a, b, c = s.index("  apply_target_identity\n"), s.index("  apply_target_screens\n"), s.index("  refresh_target_initrd_for_orientation\n")
        self.assertLess(a, b, "apres l'identite")
        self.assertLess(b, c, "avant la regeneration de l'initrd")

    def test_i18n_complet(self):
        d = json.loads((Path(RACINE) / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for lang, keys in d.items():
            for k in ("screens", "identify", "apply_layout", "orient_q", "o_up", "o_down", "role_playfield", "screens_applied", "screens_none",
                      "cab_usage", "cab_usage_hint", "screens_missing"):
                self.assertIn(k, keys, f"{lang}: {k}")

    def test_kiosque_theme_sombre(self):
        # PINCABOS_KIOSK_THEME_SOMBRE_V1 : les <select> natifs suivent le theme
        src = (Path(RACINE) / "usr/local/bin/pincabos-kiosk.py").read_text(encoding="utf-8")
        self.assertIn("gtk-application-prefer-dark-theme", src)

    def test_kiosque_suit_le_playfield(self):
        s = (Path(RACINE) / "usr/local/bin/pincabos-kiosk.py").read_text(encoding="utf-8")
        self.assertIn("kiosk-target", s)
        self.assertIn("fullscreen_on_monitor", s)
        # PINCABOS_INSTALLEUR_IDENTIFY_OVERLAY_V1 : l identification est un badge de coin, plus une fenetre plein ecran
        s = (Path(RACINE) / "opt/pincabos/installer-gui/identify.py").read_text(encoding="utf-8")
        self.assertIn("pincabos-identify-", s)


if __name__ == "__main__":
    unittest.main()
