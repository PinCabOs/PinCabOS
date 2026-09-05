"""Étape « Son et DOF » de l'assistant (PINCABOS_INSTALLEUR_SON_DOF_V1).

Modules du cab pincabos_audio et pincabos_dof : détection rejouée sur les
sorties réelles du cab de Yann, INI sur fichiers temporaires, aucune commande.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE

R = Path(RACINE)
pa = charger("opt/pincabos/tools/pincabos_audio.py", "pco_audio_mod")
pd = charger("opt/pincabos/tools/pincabos_dof.py", "pco_dof_mod")

APLAY = """**** List of PLAYBACK Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC1220 Analog [ALC1220 Analog]
card 0: PCH [HDA Intel PCH], device 1: ALC1220 Digital [ALC1220 Digital]
card 1: NVidia [HDA NVidia], device 3: HDMI 0 [RTK FHD]
card 1: NVidia [HDA NVidia], device 7: HDMI 1 [LG TV SSCR2]
"""
APLAY_FR = "carte 1 : NVidia [HDA NVidia], périphérique 7 : HDMI 1 [LG TV SSCR2]\n"
PACTL = """Sink #45
\tName: alsa_output.pci-0000_00_1f.3.analog-stereo
\tDescription: Built-in Audio Analog Stereo
\tProperties:
\t\talsa.card = "0"
\t\talsa.device = "0"
Sink #52
\tName: alsa_output.pci-0000_01_00.1.hdmi-stereo-extra1
\tDescription: HDA NVidia HDMI 1
\tProperties:
\t\talsa.card = "1"
\t\talsa.device = "7"
"""


class Audio(unittest.TestCase):
    def test_parse_aplay(self):
        d = pa.peripheriques_alsa(APLAY)
        self.assertEqual([x["id"] for x in d], ["hw:0,0", "hw:0,1", "hw:1,3", "hw:1,7"])
        self.assertEqual(d[3]["label"], "HDA NVidia · LG TV SSCR2")
        self.assertTrue(d[3]["hdmi"]); self.assertTrue(d[1]["digital"]); self.assertFalse(d[0]["hdmi"])
        self.assertEqual(pa.peripheriques_alsa(APLAY_FR)[0]["id"], "hw:1,7")

    def test_chargement_des_pilotes(self):
        # le media d installation met snd_hda_intel sur liste noire : charge a la demande
        appels = []
        def run(args, timeout=20, **kw):
            appels.append(args); return (0 if args[1] == "snd_hda_intel" else 1), ""
        import unittest.mock as um
        with um.patch("time.sleep"):
            self.assertEqual(pa.charger_pilotes(run=run), ["snd_hda_intel"])
        self.assertEqual([a[1] for a in appels], ["snd_hda_intel", "snd_usb_audio"])

    def test_proposition_analogique_d_abord(self):
        d = pa.peripheriques_alsa(APLAY)
        self.assertEqual(pa.proposer(d), {"playfield": "hw:0,0", "backbox": "hw:0,0", "sound3d": "0", "volume": 70})
        self.assertEqual(pa.proposer(d[2:])["playfield"], "hw:1,3")
        self.assertEqual(pa.proposer([])["playfield"], "")

    def test_validation(self):
        d = pa.peripheriques_alsa(APLAY)
        self.assertEqual(pa.valider({"playfield": "hw:1,7", "backbox": "", "sound3d": "3", "volume": "55"}, d),
                         ([], {"playfield": "hw:1,7", "backbox": "", "sound3d": "3", "volume": 55}))
        e, _ = pa.valider({"playfield": "hw:9,9", "sound3d": "7", "volume": 200}, d)
        self.assertEqual(len(e), 3)
        self.assertTrue(pa.valider({"playfield": "/etc/passwd"})[0])

    def test_config_json(self):
        d = pa.peripheriques_alsa(APLAY)
        c = pa.config_json({"playfield": "hw:1,7", "backbox": "", "sound3d": "0", "volume": 70}, d)
        self.assertEqual((c["playfield_device"], c["backbox_device"], c["audio_mode"]), ("hw:1,7", "hw:1,7", "single"))
        self.assertEqual(c["installer"]["playfield"]["label"], "HDA NVidia · LG TV SSCR2")
        c = pa.config_json({"playfield": "hw:0,0", "backbox": "hw:1,7", "sound3d": "2", "volume": 80}, d)
        self.assertEqual(c["audio_mode"], "dual"); self.assertEqual(c["ssf_mode"], "7.1")

    def test_sinks_et_correspondance(self):
        s = pa.sinks_pactl(PACTL)
        self.assertEqual([x["description"] for x in s], ["Built-in Audio Analog Stereo", "HDA NVidia HDMI 1"])
        self.assertEqual(pa.sink_pour("hw:1,7", s)["name"], "alsa_output.pci-0000_01_00.1.hdmi-stereo-extra1")
        self.assertEqual(pa.sink_pour("hw:1,3", s)["card"], "1")        # meme carte, autre device : la carte
        self.assertIsNone(pa.sink_pour("hw:5,0", s)); self.assertIsNone(pa.sink_pour("x", s))

    def test_ecriture_vpx(self):
        ini = "[Player]\nSoundVolume = 100\nSound3D = 0\nSoundDeviceBG = \nSoundDevice = \n\n[Plugin.DOF]\nEnable = 1\n"
        n = pa.ecrire_vpx(ini, "Built-in Audio Analog Stereo", "HDA NVidia HDMI 1", "2")
        self.assertIn("SoundDevice = HDA NVidia HDMI 1", n)
        self.assertIn("SoundDeviceBG = Built-in Audio Analog Stereo", n)
        self.assertIn("Sound3D = 2", n)
        self.assertIn("par PinCabOS fonction(Audio SSF VPX Routing V2)", n)
        self.assertEqual(n.count("[Player]"), 1)
        n2 = pa.ecrire_vpx(n, "Built-in Audio Analog Stereo", "HDA NVidia HDMI 1", "2")
        self.assertEqual(n2.count("par PinCabOS fonction("), 3)      # un commentaire par cle, jamais empile

    def test_haut_parleurs_un_par_un(self):
        # PINCABOS_AUDIO_HP_UN_PAR_UN_V1 (Yann : « pouvoir tester les haut-parleurs un par un »)
        appels = []

        def run(args, timeout=20):
            appels.append(args)
            return (0, "")
        r = pa.tester_canal("hw:1,3", 6, 2, run)
        self.assertTrue(r["ok"]); self.assertEqual(r["canal"], "RL")
        self.assertEqual(appels[-1], ["speaker-test", "-D", "hw:1,3", "-c", "6", "-t", "wav", "-s", "3", "-l", "1"])
        self.assertFalse(pa.tester_canal("hw:1,3", 6, 6, run)["ok"])
        self.assertFalse(pa.tester_canal("hw:1,3", 3, 0, run)["ok"])
        r = pa.tester_canal("hw:0,0", 6, 0, lambda a, timeout=20: (1, "Channels count (6) not available for playbacks: Invalid argument"))
        self.assertFalse(r["ok"]); self.assertIn("n'offre pas 6 canaux", r["sortie"])
        self.assertEqual(pa.canaux_pour_mode("0"), 2); self.assertEqual(pa.canaux_pour_mode("5"), 6)
        a = Path(RACINE, "opt/pincabos/installer-gui/app.py").read_text(encoding="utf-8")
        self.assertIn('@app.route("/api/sound/test-channel", methods=["POST"])', a)
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.assertIn('id="snd-speakers"', w); self.assertIn("function testSpeaker(", w)
        i18n = json.loads(Path(RACINE, "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for l in ("fr", "en", "de", "it", "es"):
            for k in ("hp_fl", "hp_lfe", "snd_speakers_hint6", "snd_speaker_ok"):
                self.assertIn(k, i18n[l], (l, k))

    def test_ssf_sur_sortie_stereo_retombe_en_stereo(self):
        # PINCABOS_AUDIO_SSF_GARDE_V1 (Yann : « le SSF ne joue pas les sons »)
        sinks = ("Sink #1\n\tName: alsa_output.pci-0000_00_05.0.analog-stereo\n\tDescription: Built-in Audio Analog Stereo\n"
                 "\tSample Specification: s16le 2ch 48000Hz\n\tProperties:\n\t\talsa.card = \"0\"\n\t\talsa.device = \"0\"\n"
                 "Sink #2\n\tName: alsa_output.usb-7.1\n\tDescription: USB 7.1\n\tSample Specification: s16le 8ch 48000Hz\n\tProperties:\n\t\talsa.card = \"1\"\n\t\talsa.device = \"0\"\n")
        self.assertEqual(pa.canaux_du_sink(sinks, "alsa_output.pci-0000_00_05.0.analog-stereo"), 2)
        self.assertEqual(pa.canaux_du_sink(sinks, "alsa_output.usb-7.1"), 8)
        self.assertEqual(pa.canaux_du_sink(sinks, "inconnu"), 0)
        with tempfile.TemporaryDirectory() as d:
            ini = Path(d, "VPinballX.ini")

            def run(args, timeout=20):
                return (0, sinks if "list" in args else "")
            j = pa.appliquer_premier_demarrage({"playfield_device": "hw:0,0", "backbox_device": "", "installer": {"sound3d": "5", "volume": 70}}, run=run, vpx_ini=ini)
            self.assertIn("Sound3D = 0", ini.read_text(encoding="utf-8"))
            self.assertTrue(any("2 canaux" in l and "stereo" in l for l in j), j)
            j = pa.appliquer_premier_demarrage({"playfield_device": "hw:1,0", "backbox_device": "", "installer": {"sound3d": "5", "volume": 70}}, run=run, vpx_ini=ini)
            self.assertIn("Sound3D = 5", ini.read_text(encoding="utf-8"))
        i18n = json.loads(Path(RACINE, "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for l in ("fr", "en", "de", "it", "es"):
            for k in range(6):
                self.assertIn(f"sound3d_hint_{k}", i18n[l], (l, k))
            self.assertIn("SSF", i18n[l]["sound3d_5"])

    def test_premier_demarrage_cree_l_ini_vpx_absent(self):
        # PINCABOS_AUDIO_PREMIER_DEMARRAGE_V2 : cab neuf, VPX n a pas encore ecrit son ini (vu en VM)
        with tempfile.TemporaryDirectory() as d:
            ini = Path(d, "vpx", "VPinballX.ini")
            sinks = "Sink #1\n\tName: alsa_output.pci-0000_00_05.0.analog-stereo\n\tDescription: HDA Intel Analog\n\tProperties:\n\t\talsa.card = \"0\"\n\t\talsa.device = \"0\"\n"
            appels = []

            def run(args, timeout=20):
                appels.append(args)
                return (0, sinks if "list" in args else "")
            cfg = {"playfield_device": "hw:0,0", "backbox_device": "", "installer": {"sound3d": "0", "volume": 70}}
            j = pa.appliquer_premier_demarrage(cfg, run=run, vpx_ini=ini)
            self.assertTrue(ini.is_file(), j)
            texte = ini.read_text(encoding="utf-8")
            self.assertIn("[Player]", texte)
            self.assertIn("SoundDevice = HDA Intel Analog", texte)
            self.assertTrue(any("ini créé" in l for l in j), j)

    def test_premier_demarrage(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            ini = tmp / "VPinballX.ini"; ini.write_text("[Player]\nSound3D = 0\n", encoding="utf-8")
            appels = []
            def run(args, timeout=20, **kw):
                appels.append(list(args))
                return (0, PACTL) if "pactl" in " ".join(args) else (0, "")
            cfg = pa.config_json({"playfield": "hw:1,7", "backbox": "hw:0,0", "sound3d": "3", "volume": 65}, pa.peripheriques_alsa(APLAY))
            j = pa.appliquer_premier_demarrage(cfg, run=run, vpx_ini=ini)
            t = ini.read_text(encoding="utf-8")
            self.assertIn("SoundDevice = HDA NVidia HDMI 1", t); self.assertIn("SoundDeviceBG = Built-in Audio Analog Stereo", t); self.assertIn("Sound3D = 3", t)
            self.assertTrue(any("/usr/bin/pactl" in a and "set-default-sink" in a for a in appels))
            self.assertTrue(any("set-sink-volume" in a and "65%" in a for a in appels))
            self.assertFalse(any("wpctl" in " ".join(a) for a in appels))   # wpctl set-default veut un id numerique
            self.assertTrue(all(a[:3] == ["runuser", "-u", "pinball"] for a in appels))
            self.assertEqual(len(j), 3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Dof(unittest.TestCase):
    DET = [{"dev": "/dev/hidraw5", "vid": "2e8a", "model": "DudesCab", "serial": "DE64", "kind": "DudesCab", "auto_config": True},
           {"dev": "/dev/ttyACM0", "vid": "16c0", "model": "USB_Serial", "serial": "1567", "kind": "TeensyStripController (strip adressable)", "auto_config": False}]

    def test_resume_et_proposition(self):
        r = pd.resume(self.DET)
        self.assertEqual([x["strip"] for x in r], [False, True])
        self.assertEqual(pd.proposer(self.DET), {"enabled": True}); self.assertEqual(pd.proposer([]), {"enabled": False})
        self.assertEqual(pd.valider({"enabled": "1"}), ([], {"enabled": True}))
        c = pd.config_json({"enabled": False}, self.DET)
        self.assertFalse(c["enabled"]); self.assertEqual(len(c["detected"]), 2)

    def test_poser_cle_ini(self):
        t = "[Plugin.DOF]\nEnable = 1\n\n[Plugin.vpx]\nEnable = \n"
        self.assertIn("[Plugin.DOF]\nEnable = 0\n\n[Plugin.vpx]", pd.poser_cle_ini(t, "Plugin.DOF", "Enable", "0"))
        self.assertEqual(pd.poser_cle_ini("[DOF]\nautre = 1\n", "DOF", "enabledof", "true"), "[DOF]\nautre = 1\nenabledof = true\n")
        self.assertEqual(pd.poser_cle_ini("[X]\na = 1\n", "DOF", "enabledof", "false"), "[X]\na = 1\n\n[DOF]\nenabledof = false")

    def test_premier_demarrage(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            vpx = tmp / "VPinballX.ini"; vpx.write_text("[Plugin.DOF]\nEnable = 1\n", encoding="utf-8")
            fe = tmp / "vpinfe.ini"; fe.write_text("[DOF]\nenabledof = true\n", encoding="utf-8")
            j = pd.appliquer_premier_demarrage({"enabled": False}, vpx_ini=vpx, vpinfe_ini=fe)
            self.assertIn("Enable = 0", vpx.read_text()); self.assertIn("enabledof = false", fe.read_text())
            self.assertEqual(len(j), 2)
            pd.appliquer_premier_demarrage({"enabled": True}, vpx_ini=vpx, vpinfe_ini=fe)
            self.assertIn("Enable = 1", vpx.read_text())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_detection_via_dof_cabinet(self):
        mod = pd.outil(R / "opt/pincabos/tools/dof-cabinet/dof-cabinet.py")
        self.assertIsNotNone(mod)
        self.assertTrue(hasattr(mod, "detect"))
        self.assertEqual(pd.detecter(mod=type("M", (), {"detect": staticmethod(lambda: self.DET)})()), self.DET)


class Assistant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import flask  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("flask absent")
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ["PCO_DEMO"] = "1"; os.environ["PCO_RUN_DIR"] = str(cls.tmp)
        import sys
        sys.path.insert(0, str(R / "opt/pincabos/installer-gui"))
        cls.app = charger("opt/pincabos/installer-gui/app.py", "pco_installer_app_son")
        cls.client = cls.app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_api(self):
        d = self.client.get("/api/sound").get_json()
        self.assertTrue(d["disponible"])
        self.assertEqual(len(d["audio"]["devices"]), 4)
        self.assertEqual(d["audio"]["proposition"]["playfield"], "hw:0,0")
        self.assertEqual(len(d["audio"]["modes"]), 6)
        self.assertTrue(d["dof"]["proposition"]["enabled"]); self.assertEqual(len(d["dof"]["detected"]), 2)
        self.assertTrue(self.client.post("/api/sound/test", json={"device": "hw:1,7"}).get_json()["ok"])
        self.assertFalse(self.client.post("/api/sound/test", json={"device": "; rm"}).get_json()["ok"])
        self.assertTrue(self.client.post("/api/sound/volume", json={"device": "hw:1,7", "volume": 40}).get_json()["ok"])

    def test_installation_ecrit_son_et_dof(self):
        d = self.client.get("/api/screens").get_json()
        r = self.client.post("/api/install", json={
            "lang": "fr", "locale": "fr_FR.UTF-8", "xkb": "fr", "tz": "Europe/Paris", "mode": "1", "disk": "/dev/nvme0n1",
            "confirm": "INSTALL PINCABOS", "network": False, "screens": {"roles": d["roles"], "rotation": 0},
            "sound": {"playfield": "hw:1,7", "backbox": "", "sound3d": "3", "volume": 60}, "dof": {"enabled": False}})
        self.assertEqual(r.status_code, 200, r.get_json())
        env = (self.tmp / "gui-answers.env").read_text(encoding="utf-8")
        self.assertIn("PCO_ANS_AUDIO_FILE=" + str(self.tmp / "gui-audio.json"), env)
        self.assertIn("PCO_ANS_DOF_FILE=" + str(self.tmp / "gui-dof.json"), env)
        a = json.loads((self.tmp / "gui-audio.json").read_text(encoding="utf-8"))
        self.assertEqual((a["playfield_device"], a["installer"]["sound3d"], a["installer"]["volume"]), ("hw:1,7", "3", 60))
        self.assertFalse(json.loads((self.tmp / "gui-dof.json").read_text(encoding="utf-8"))["enabled"])
        r = self.client.post("/api/install", json={"lang": "fr", "mode": "1", "disk": "/dev/nvme0n1", "confirm": "INSTALL PINCABOS",
                                                   "network": False, "sound": {"playfield": "hw:7,7"}})
        self.assertEqual(r.status_code, 400); self.assertEqual(r.get_json()["error"], "bad-sound")

    def test_page(self):
        html = self.client.get("/").get_data(as_text=True)
        for m in ('id="st-sound"', 'id="snd-out"', 'id="dof-enable"', "loadSound()", "go('st-sound')"):
            self.assertIn(m, html)


class Integration(unittest.TestCase):
    def test_iso_sh(self):
        s = (R / "opt/pincabos/script/iso.sh").read_text(encoding="utf-8")
        self.assertIn("apply_target_audio() {", s); self.assertIn("apply_target_dof() {", s)
        self.assertIn("  apply_target_dmd\n  apply_target_audio\n  apply_target_dof\n  apply_target_toys\n", s)
        self.assertIn('"$TARGET/opt/pincabos/config/audio-router.json"', s)
        self.assertIn("audio-installer.pending", s); self.assertIn("dof-installer.pending", s)
        # le nettoyeur audio de la cible (installation NEUVE) precede la pose du choix de l installeur
        self.assertLess(s.index("PINCABOS_ISO_AUDIO_TARGET_SANITIZER_V1"), s.index("apply_target_audio() {"))

    def test_premier_demarrage(self):
        u = (R / "etc/systemd/system/pincabos-installer-firstboot.service").read_text(encoding="utf-8")
        self.assertIn("ConditionPathExistsGlob=/opt/pincabos/flags/*-installer.pending", u)
        self.assertIn("Before=pincabos-vpinfe.service", u)
        self.assertTrue((R / "etc/systemd/system/multi-user.target.wants/pincabos-installer-firstboot.service").is_symlink())
        sc = (R / "usr/local/sbin/pincabos-installer-firstboot").read_text(encoding="utf-8")
        self.assertIn("pincabos-dof", sc); self.assertIn("pipewire-0", sc); self.assertIn("pincabos-audio", sc)
        import subprocess
        self.assertEqual(subprocess.run(["bash", "-n", str(R / "usr/local/sbin/pincabos-installer-firstboot")]).returncode, 0)

    def test_i18n(self):
        d = json.loads((R / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for lang, keys in d.items():
            for k in ("sound_title", "sound_hint", "snd_output", "snd_backbox", "snd_same", "snd_mode", "snd_volume", "snd_test",
                      "snd_testing", "snd_test_ok", "snd_test_failed", "snd_none", "dof_title", "dof_enable", "dof_hint",
                      "dof_detected", "dof_none", "dof_strip_note", "sound3d_0", "sound3d_5"):
                self.assertIn(k, keys, f"{lang}: {k}")


if __name__ == "__main__":
    unittest.main()
