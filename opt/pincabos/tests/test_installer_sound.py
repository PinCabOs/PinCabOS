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

from _charge import charger, RACINE, texte_installateur

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

    def test_migration_du_dossier_vpx_avant_ecriture(self):
        # PINCABOS_VPX_PREF_MIGRATION_V1 : l ini complet du cab (legacy) devient celui de ~/.pincabos/vpx
        sinks = "Sink #1\n\tName: alsa_output.pci-0000_00_05.0.analog-stereo\n\tDescription: HDA Intel Analog\n\tSample Specification: s16le 2ch 48000Hz\n\tProperties:\n\t\talsa.card = \"0\"\n\t\talsa.device = \"0\"\n"
        with tempfile.TemporaryDirectory() as d:
            legacy = Path(d, "legacy", "10.8"); legacy.mkdir(parents=True)
            (legacy / "VPinballX.ini").write_text("[Player]\nPlayfieldFullScreen = 1\nBGSet = 1\n", encoding="utf-8")
            (legacy / "directoutputconfig").mkdir()
            pref_ini = Path(d, "pref", "vpx", "VPinballX.ini")
            j = pa.appliquer_premier_demarrage({"playfield_device": "hw:0,0", "backbox_device": "", "installer": {"sound3d": "0", "volume": 70}},
                                               run=lambda a, timeout=20: (0, sinks if "list" in a else ""), vpx_ini=pref_ini, vpx_legacy_ini=legacy / "VPinballX.ini")
            self.assertTrue(any("migre" in l for l in j), j)
            texte = pref_ini.read_text(encoding="utf-8")
            self.assertIn("BGSet = 1", texte)                       # l ini complet a suivi
            self.assertIn("SoundDevice = HDA Intel Analog", texte)   # nos cles par-dessus
            self.assertTrue((pref_ini.parent / "directoutputconfig").is_dir())
            self.assertTrue(legacy.is_symlink())                     # l ancien chemin pointe sur le nouveau
            self.assertFalse(any("ini créé" in l for l in j))

    def test_reparation_d_un_squelette_ecrit_par_vpx(self):
        """PINCABOS_VPX_PREF_REPARATION_V2 : VPX a reecrit l ini minimal en squelette ([Version] present,
        cles vides) ; le dossier complet doit quand meme etre repris (retex cab de Yann, 3.88)."""
        squelette = "[Player]\nPlayfieldFullScreen = \nBGSet = \nSoundDevice = X\n[Version]\nVPinball = 10.8.1\n"
        complet = "[Version]\nVPinball = 10.8.1\n[Player]\nPlayfieldFullScreen = 1\nBGSet = 1\n"
        self.assertTrue(pa.ini_squelette(squelette)); self.assertTrue(pa.ini_squelette("[Player]\nSound3D = 0\n"))
        self.assertFalse(pa.ini_squelette(complet)); self.assertTrue(pa.ini_complet(complet)); self.assertFalse(pa.ini_complet(squelette))
        with tempfile.TemporaryDirectory() as d:
            pref = Path(d, "pref"); pref.mkdir(); (pref / "VPinballX.ini").write_text(squelette, encoding="utf-8")
            legacy = Path(d, "legacy"); legacy.mkdir(); (legacy / "VPinballX.ini").write_text(complet, encoding="utf-8")
            (legacy / "directoutputconfig").mkdir(); (legacy / "directoutputconfig" / "directoutputconfig30.ini").write_text("x")
            etat = pa.assurer_pref_vpx(pref / "VPinballX.ini", legacy / "VPinballX.ini")
            self.assertIn("repare", etat)
            self.assertEqual((pref / "VPinballX.ini").read_text(encoding="utf-8"), complet)
            self.assertTrue((pref / "VPinballX.ini.minimal").is_file())
            self.assertTrue((pref / "directoutputconfig" / "directoutputconfig30.ini").is_file())
            self.assertTrue(legacy.is_symlink())

    def test_reparation_d_un_ini_minimal(self):
        # PINCABOS_VPX_PREF_REPARATION_V1 : mise a jour d un cab installe avec la V2 (ini minimal)
        sinks = "Sink #1\n\tName: alsa_output.pci-0000_00_05.0.analog-stereo\n\tDescription: HDA Intel Analog\n\tSample Specification: s16le 2ch 48000Hz\n\tProperties:\n\t\talsa.card = \"0\"\n\t\talsa.device = \"0\"\n"
        with tempfile.TemporaryDirectory() as d:
            legacy = Path(d, "legacy", "10.8"); legacy.mkdir(parents=True)
            (legacy / "VPinballX.ini").write_text("[Version]\nVPinball = 10.8.1\n[Player]\nPlayfieldFullScreen = 1\nBGSet = 1\n", encoding="utf-8")
            (legacy / "directoutputconfig").mkdir()
            pref_ini = Path(d, "pref", "vpx", "VPinballX.ini"); pref_ini.parent.mkdir(parents=True)
            pref_ini.write_text("[Player]\nSoundDevice = X\n", encoding="utf-8")          # l ini minimal de la V2
            j = pa.appliquer_premier_demarrage({"playfield_device": "hw:0,0", "backbox_device": "", "installer": {"sound3d": "0", "volume": 70}},
                                               run=lambda a, timeout=20: (0, sinks if "list" in a else ""), vpx_ini=pref_ini, vpx_legacy_ini=legacy / "VPinballX.ini")
            self.assertTrue(any("repare" in l for l in j), j)
            texte = pref_ini.read_text(encoding="utf-8")
            self.assertIn("BGSet = 1", texte); self.assertIn("SoundDevice = HDA Intel Analog", texte)
            self.assertTrue((pref_ini.parent / "directoutputconfig").is_dir())
            self.assertTrue(Path(str(pref_ini) + ".minimal").is_file())
            self.assertTrue(legacy.is_symlink())

    def test_haut_parleurs_un_par_un(self):
        # PINCABOS_AUDIO_HP_UN_PAR_UN_V1 (Yann : « pouvoir tester les haut-parleurs un par un »)
        appels = []

        def run(args, timeout=20):
            appels.append(args)
            return (0, "")
        r = pa.tester_canal("hw:1,3", 6, 2, run)
        self.assertTrue(r["ok"]); self.assertEqual(r["canal"], "RL")
        # PINCABOS_AUDIO_HP_CHMAP_V1 : ordre standard impose (HDMI brut = FL FR LFE FC RL RR)
        self.assertEqual(appels[-1], ["speaker-test", "-D", "hw:1,3", "-c", "6", "-t", "wav", "-s", "3", "-l", "1", "-m", "FL,FR,RL,RR,FC,LFE"])
        self.assertFalse(pa.tester_canal("hw:1,3", 6, 6, run)["ok"])

        def refuse_chmap(args, timeout=20):
            appels.append(args)
            return (1, "Unable to set channel map") if "-m" in args else (0, "")
        r = pa.tester_canal("hw:1,3", 6, 4, refuse_chmap)
        self.assertTrue(r["ok"]); self.assertEqual(r["canal"], "C")
        self.assertNotIn("-m", appels[-1], "pilote sans chmap : rejoue sans")
        self.assertFalse(pa.tester_canal("hw:1,3", 3, 0, run)["ok"])
        r = pa.tester_canal("hw:0,0", 6, 0, lambda a, timeout=20: (1, "Channels count (6) not available for playbacks: Invalid argument"))
        self.assertFalse(r["ok"]); self.assertIn("n'offre pas 6 canaux", r["sortie"])
        self.assertEqual(pa.canaux_pour_mode("0"), 2); self.assertEqual(pa.canaux_pour_mode("3"), 6)
        # PINCABOS_AUDIO_71_V1 : les modes 4 et 5 sont du 7.1 (lateraux = fronton)
        self.assertEqual(pa.canaux_pour_mode("4"), 8); self.assertEqual(pa.canaux_pour_mode("5"), 8)
        self.assertEqual(pa.tester_canal("hw:1,3", 8, 6, run)["canal"], "SL")
        a = Path(RACINE, "opt/pincabos/installer-gui/app.py").read_text(encoding="utf-8")
        self.assertIn('@app.route("/api/sound/test-channel", methods=["POST"])', a)
        w = Path(RACINE, "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.assertIn('id="snd-speakers"', w); self.assertIn("function testSpeaker(", w)
        self.assertIn('8:["FL","FR","RL","RR","C","LFE","SL","SR"]', w)   # PINCABOS_AUDIO_71_V1
        self.assertIn('SL:"hp_sl"', w); self.assertIn('(s==="4"||s==="5")?8:6', w)
        i18n = json.loads(Path(RACINE, "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))
        for l in ("fr", "en", "de", "it", "es"):
            for k in ("hp_fl", "hp_lfe", "hp_sl", "snd_speakers_hint6", "snd_speakers_hint8", "snd_speaker_ok"):
                self.assertIn(k, i18n[l], (l, k))

    CARDS = ("Card #54\n\tName: alsa_card.pci-0000_00_05.0\n\tDriver: alsa\n\tProperties:\n\t\talsa.card = \"0\"\n\tProfiles:\n"
             "\t\toutput:analog-stereo: Analog Stereo Output (sinks: 1, sources: 0, priority: 6500, available: yes)\n"
             "\t\toutput:analog-surround-51: Analog Surround 5.1 Output (sinks: 1, sources: 0, priority: 800, available: yes)\n"
             "\t\toff: Off (sinks: 0, sources: 0, priority: 0, available: yes)\n\tActive Profile: output:analog-stereo\n")
    SINKS_51 = ("Sink #3\n\tName: alsa_output.pci-0000_00_05.0.analog-surround-51\n\tDescription: Built-in Audio Analog Surround 5.1\n"
                "\tSample Specification: s32le 6ch 48000Hz\n\tProperties:\n\t\talsa.card = \"0\"\n\t\talsa.device = \"0\"\n")

    def test_profil_surround_active_avant_la_garde(self):
        """PINCABOS_AUDIO_PROFIL_SURROUND_V1 (retex cab de Yann : ALC1220 ouvert en stereo par PipeWire,
        SSF demande -> garde -> stereo alors que la carte a un profil 5.1)."""
        c = pa.cartes_pactl(self.CARDS)
        self.assertEqual(c[0]["card"], "0"); self.assertEqual(c[0]["active"], "output:analog-stereo")
        self.assertEqual(pa.profil_multicanal(c[0], 6), "output:analog-surround-51")
        self.assertEqual(pa.profil_multicanal(c[0], 8), "")
        stereo = ("Sink #1\n\tName: alsa_output.pci-0000_00_05.0.analog-stereo\n\tDescription: Built-in Audio Analog Stereo\n"
                  "\tSample Specification: s16le 2ch 48000Hz\n\tProperties:\n\t\talsa.card = \"0\"\n\t\talsa.device = \"0\"\n")
        etat = {"profil": "stereo"}
        appels = []

        def run(args, timeout=20):
            appels.append(list(args))
            c = " ".join(args)
            if "list cards" in c:
                return (0, self.CARDS)
            if "list sinks" in c:
                return (0, self.SINKS_51 if etat["profil"] == "51" else stereo)
            if "set-card-profile" in c:
                etat["profil"] = "51"
            return (0, "")
        with tempfile.TemporaryDirectory() as d:
            ini = Path(d, "VPinballX.ini")
            j = pa.appliquer_premier_demarrage({"playfield_device": "hw:0,0", "backbox_device": "", "installer": {"sound3d": "3", "volume": 70}}, run=run, vpx_ini=ini)
            t = ini.read_text(encoding="utf-8")
            self.assertIn("Sound3D = 3", t); self.assertIn("SoundDevice = Built-in Audio Analog Surround 5.1", t)
            self.assertTrue(any(a[-3:] == ["set-card-profile", "alsa_card.pci-0000_00_05.0", "output:analog-surround-51"] for a in appels), appels)
            self.assertTrue(any("profil output:analog-surround-51 active" in l for l in j), j)
            self.assertFalse(any("stereo (0) applique" in l for l in j), j)

    def test_71_sur_carte_51_garde_le_mode_et_previent(self):
        """PINCABOS_AUDIO_71_V1 (cab de Yann : ALC1220 = 5.1 maxi, mode 4 demande) : profil 5.1 active,
        mode garde, avertissement sur les lateraux."""
        etat = {"profil": "stereo"}
        stereo = ("Sink #1\n\tName: alsa_output.pci-0000_00_05.0.analog-stereo\n\tDescription: Built-in Audio Analog Stereo\n"
                  "\tSample Specification: s16le 2ch 48000Hz\n\tProperties:\n\t\talsa.card = \"0\"\n\t\talsa.device = \"0\"\n")
        appels = []

        def run(args, timeout=20):
            appels.append(list(args)); c = " ".join(args)
            if "list cards" in c:
                return (0, self.CARDS)
            if "list sinks" in c:
                return (0, self.SINKS_51 if etat["profil"] == "51" else stereo)
            if "set-card-profile" in c:
                etat["profil"] = "51"
            return (0, "")
        with tempfile.TemporaryDirectory() as d:
            ini = Path(d, "VPinballX.ini")
            j = pa.appliquer_premier_demarrage({"playfield_device": "hw:0,0", "backbox_device": "", "installer": {"sound3d": "4", "volume": 70}}, run=run, vpx_ini=ini)
            self.assertIn("Sound3D = 4", ini.read_text(encoding="utf-8"))
            self.assertTrue(any("lateraux (fronton) seront muets" in l for l in j), j)
            self.assertTrue(any(a[-1] == "output:analog-surround-51" for a in appels if "set-card-profile" in a), appels)

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

    def test_reactiver_sortie(self):
        # PINCABOS_AUDIO_UNMUTE_V1 (cab de Yann 06/09 : sink « Mute: yes », Front/Surround/Center/LFE off)
        appels = []
        etat_sinks = "Sink #1\n\tName: alsa_output.pci-0000_00_1f.3.analog-surround-51\n\tMute: yes\n"
        def run(args, timeout=20, **kw):
            appels.append(list(args))
            if args[-2:] == ["list", "sinks"]:
                return (0, etat_sinks)
            if args[:1] == ["amixer"] and "sget" in args:
                ctrl = args[-1]
                if ctrl == "Side":
                    return (1, "amixer: Unable to find simple control 'Side',0")
                if ctrl in ("Master", "PCM"):
                    return (0, "  Front Left: Playback 87 [100%] [on]\n  Front Right: Playback 87 [100%] [on]\n")
                return (0, "  Front Left: Playback 0 [0%] [off]\n  Front Right: Playback 0 [0%] [off]\n")
            return (0, "")
        j = pa.reactiver_sortie({"name": "alsa_output.pci-0000_00_1f.3.analog-surround-51", "card": "0"}, run=run)
        self.assertIn(["amixer", "-q", "-c", "0", "sset", "Front", "unmute"], appels)
        self.assertIn(["amixer", "-q", "-c", "0", "sset", "Front", "100%"], appels)
        self.assertNotIn(["amixer", "-q", "-c", "0", "sset", "Master", "100%"], appels)   # Master : volume du widget
        self.assertNotIn(["amixer", "-q", "-c", "0", "sset", "Master", "unmute"], appels)  # deja ouvert : on n y touche pas
        self.assertNotIn(["amixer", "-q", "-c", "0", "sset", "Side", "100%"], appels)     # commutateur absent : pas de volume
        self.assertTrue(any("Front, Surround, Center, LFE" in l for l in j), j)
        self.assertTrue(any("set-sink-mute" in " ".join(a) for a in appels), "sink coupe : mute leve")
        # PINCABOS_AUDIO_SANS_CRAQUEMENT_V1 : tout deja en place -> aucune commande qui modifie
        appels.clear(); etat_sinks = etat_sinks.replace("Mute: yes", "Mute: no")
        def run2(args, timeout=20, **kw):
            appels.append(list(args))
            if args[-2:] == ["list", "sinks"]:
                return (0, etat_sinks)
            if "sget" in args:
                return (0, "  Front Left: Playback 87 [100%] [on]\n")
            return (0, "")
        j = pa.reactiver_sortie({"name": "alsa_output.pci-0000_00_1f.3.analog-surround-51", "card": "0"}, run=run2)
        self.assertFalse([a for a in appels if "sset" in a or "set-sink-mute" in a], appels)
        self.assertTrue(any("ouverte" in l for l in j), j)

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
            self.assertTrue(all(a[:3] == ["runuser", "-u", "pinball"] for a in appels if a[0] != "amixer"))
            # PINCABOS_AUDIO_UNMUTE_V1 : le mute est leve (PipeWire + ALSA) pour la sortie playfield et la backbox
            self.assertTrue(any("set-sink-mute" in a and "0" == a[-1] for a in appels), appels)
            self.assertTrue(any(a[:2] == ["amixer", "-q"] and "unmute" in a for a in appels), appels)
            self.assertTrue(any("mute PipeWire leve" in l for l in j), j)
            self.assertEqual(len(j), 8)   # migration + VPX + defaut + 2 x (mute, ALSA) + volume
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
        self.assertEqual(pd.poser_cle_ini("[X]\na = 1\n", "DOF", "enabledof", "false"), "[X]\na = 1\n\n[DOF]\nenabledof = false\n")   # INI_UNIQUE_V1 : fin de ligne conservee

    def test_reactiver_sortie(self):
        # PINCABOS_AUDIO_UNMUTE_V1 (cab de Yann 06/09 : sink « Mute: yes », Front/Surround/Center/LFE off)
        appels = []
        etat_sinks = "Sink #1\n\tName: alsa_output.pci-0000_00_1f.3.analog-surround-51\n\tMute: yes\n"
        def run(args, timeout=20, **kw):
            appels.append(list(args))
            if args[-2:] == ["list", "sinks"]:
                return (0, etat_sinks)
            if args[:1] == ["amixer"] and "sget" in args:
                ctrl = args[-1]
                if ctrl == "Side":
                    return (1, "amixer: Unable to find simple control 'Side',0")
                if ctrl in ("Master", "PCM"):
                    return (0, "  Front Left: Playback 87 [100%] [on]\n  Front Right: Playback 87 [100%] [on]\n")
                return (0, "  Front Left: Playback 0 [0%] [off]\n  Front Right: Playback 0 [0%] [off]\n")
            return (0, "")
        j = pa.reactiver_sortie({"name": "alsa_output.pci-0000_00_1f.3.analog-surround-51", "card": "0"}, run=run)
        self.assertIn(["amixer", "-q", "-c", "0", "sset", "Front", "unmute"], appels)
        self.assertIn(["amixer", "-q", "-c", "0", "sset", "Front", "100%"], appels)
        self.assertNotIn(["amixer", "-q", "-c", "0", "sset", "Master", "100%"], appels)   # Master : volume du widget
        self.assertNotIn(["amixer", "-q", "-c", "0", "sset", "Master", "unmute"], appels)  # deja ouvert : on n y touche pas
        self.assertNotIn(["amixer", "-q", "-c", "0", "sset", "Side", "100%"], appels)     # commutateur absent : pas de volume
        self.assertTrue(any("Front, Surround, Center, LFE" in l for l in j), j)
        self.assertTrue(any("set-sink-mute" in " ".join(a) for a in appels), "sink coupe : mute leve")
        # PINCABOS_AUDIO_SANS_CRAQUEMENT_V1 : tout deja en place -> aucune commande qui modifie
        appels.clear(); etat_sinks = etat_sinks.replace("Mute: yes", "Mute: no")
        def run2(args, timeout=20, **kw):
            appels.append(list(args))
            if args[-2:] == ["list", "sinks"]:
                return (0, etat_sinks)
            if "sget" in args:
                return (0, "  Front Left: Playback 87 [100%] [on]\n")
            return (0, "")
        j = pa.reactiver_sortie({"name": "alsa_output.pci-0000_00_1f.3.analog-surround-51", "card": "0"}, run=run2)
        self.assertFalse([a for a in appels if "sset" in a or "set-sink-mute" in a], appels)
        self.assertTrue(any("ouverte" in l for l in j), j)

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
        s = texte_installateur()
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


class PlanDeCablage(unittest.TestCase):
    """PINCABOS_AUDIO_CABLAGE_V1 — l'assistant doit dire ou brancher chaque ampli, et le dire juste.

    Cab de Yann, 07/09/2026 : l'aide du mode 7.1 annoncait « lateraux = lockbar,
    arriere = fond du cab » dans les cinq langues. C'est l'inverse de ce que fait
    VPX (sa propre documentation : « 6ch Side & Rear at lockbar », l'avant portant
    le haut de table donc le fronton) et l'ecoute l'a confirme : les flips
    sortaient au fond du meuble. Les vibrants de la lockbar vont sur l'ARRIERE.
    """

    LANGUES = ("fr", "en", "de", "it", "es")
    CANAUX = ("FL", "FR", "RL", "RR", "SL", "SR", "C", "LFE")

    def setUp(self):
        self.i18n = json.loads((R / "opt/pincabos/installer-gui/i18n.json").read_text(encoding="utf-8"))

    def test_position_de_chaque_haut_parleur_dans_les_cinq_langues(self):
        for langue in self.LANGUES:
            for canal in self.CANAUX:
                cle = f"hp_pos_{canal}"
                self.assertIn(cle, self.i18n[langue], f"{langue}/{cle}")
                self.assertTrue(self.i18n[langue][cle].strip(), f"{langue}/{cle} vide")

    def test_la_lockbar_est_a_l_arriere_pas_sur_les_lateraux(self):
        mots = {"fr": "lockbar", "en": "lockbar", "de": "Lockbar", "it": "lockbar", "es": "lockbar"}
        for langue in self.LANGUES:
            lockbar = mots[langue].lower()
            self.assertIn(lockbar, self.i18n[langue]["hp_pos_RL"].lower(), f"{langue} : arriere = lockbar")
            self.assertIn(lockbar, self.i18n[langue]["hp_pos_RR"].lower(), langue)
            self.assertNotIn(lockbar, self.i18n[langue]["hp_pos_SL"].lower(), f"{langue} : lateral != lockbar")
            self.assertNotIn(lockbar, self.i18n[langue]["hp_pos_SR"].lower(), langue)

    def test_l_aide_du_mode_7_1_ne_dit_plus_l_inverse(self):
        for langue in self.LANGUES:
            texte = self.i18n[langue]["snd_speakers_hint8"]
            self.assertGreater(len(texte), 120, langue)
            for fautif in ("side = lockbar", "latéraux = lockbar", "seitlich = Lockbar",
                           "laterali = lockbar", "laterales = lockbar"):
                self.assertNotIn(fautif, texte, f"{langue} : {fautif}")

    def test_le_wizard_affiche_la_position_sous_le_bouton(self):
        w = (R / "opt/pincabos/installer-gui/templates/wizard.html").read_text(encoding="utf-8")
        self.assertIn("PINCABOS_AUDIO_CABLAGE_V1", w)
        self.assertIn('const HP_POS={FL:"hp_pos_FL"', w)
        # la legende n'apparait qu'au-dela de la stereo, ou la question ne se pose pas
        self.assertIn("if(n>2){const p=t(HP_POS[hp]);", w)
        self.assertLess(w.index("const HP_POS="), w.index("function renderSpeakers"))

    def test_les_modes_disent_ou_part_le_bas_de_table(self):
        for langue in ("fr", "en"):
            for cle in ("sound3d_hint_4", "sound3d_hint_5"):
                texte = self.i18n[langue][cle].lower()
                self.assertIn("lockbar", texte, f"{langue}/{cle}")
                self.assertTrue("arrière" in texte or "rear" in texte, f"{langue}/{cle}")


if __name__ == "__main__":
    unittest.main()
