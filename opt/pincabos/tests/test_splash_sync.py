"""Splash de demarrage par ecran (PINCABOS_SPLASH_FROM_SCREENS_V3).

Portrait sur le playfield, pre-tourne dans le sens de la dalle ; paysage sur
backglass, full DMD et topper ; surfaces ecartees dans l espace virtuel de
Plymouth. Aucune commande executee : un faux executeur enregistre.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE

ss = charger("usr/local/sbin/pincabos-splash-sync", "pco_splash_sync")
R = Path(RACINE)

ECRANS_YANN = {"playfield": (3840, 2160), "backglass": (1920, 1080), "fulldmd": (1920, 1080)}


class SensDuJoueur(unittest.TestCase):
    def test_dalle_paysage_haut_de_table_a_gauche(self):
        # PINCABOS_SPLASH_SENS_JOUEUR_V1 : convention verifiee sur cab reel
        self.assertEqual(ss.rotation_effective(0), 270)
        self.assertEqual(ss.rotation_effective(180), 90)

    def test_dalle_tournee_par_x11(self):
        self.assertEqual(ss.rotation_effective(90), 90)
        self.assertEqual(ss.rotation_effective(270), 270)

    def test_resolution_physique(self):
        self.assertEqual(ss.resolution_physique((2160, 3840), 90), (3840, 2160))
        self.assertEqual(ss.resolution_physique((3840, 2160), 180), (3840, 2160))


class Images(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.theme = self.tmp / "theme"; self.theme.mkdir()
        (self.theme / "pincabos.png").write_bytes(b"HISTORIQUE")
        self.portrait = self.tmp / "portrait.png"; self.portrait.write_bytes(b"PORTRAIT")
        self.paysage = self.tmp / "paysage.png"; self.paysage.write_bytes(b"PAYSAGE")
        self.appels = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_ok(self, args, timeout=120):
        self.appels.append(list(args))
        Path(args[-1]).write_bytes(b"TOURNE")
        return 0, ""

    def test_portrait_pre_tourne_pour_le_playfield(self):
        r = ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok, portrait=self.portrait, paysage=self.paysage, outil="ffmpeg")
        self.assertEqual((r["genre_playfield"], r["genre_autres"], r["rot"], r["pre_tourne"]), ("portrait", "paysage", 270, 1))
        # PINCABOS_SPLASH_PALETTE_V1 : le paysage passe par l outil lui aussi
        # (palette), la ou une source PNG etait recopiee telle quelle.
        self.assertEqual(len(self.appels), 2)
        cmd = self.appels[0]
        self.assertIn(cmd[0], ("ffmpeg", "convert"))
        if cmd[0] == "ffmpeg":
            self.assertIn("transpose=2", " ".join(cmd))      # 270 = anti-horaire
            self.assertIn("paletteuse", " ".join(cmd))
        else:
            self.assertEqual(cmd[cmd.index("-rotate") + 1], "270")
        self.assertEqual((self.theme / ss.IMAGE_PLAYFIELD).read_bytes(), b"TOURNE")
        self.assertEqual((self.theme / ss.IMAGE_AUTRES).read_bytes(), b"TOURNE")

    def test_dalle_a_l_envers(self):
        r = ss.preparer_images(180, theme_dir=self.theme, run=self.run_ok, portrait=self.portrait, paysage=self.paysage, outil="ffmpeg")
        self.assertEqual(r["rot"], 90)
        self.assertTrue("transpose=1" in " ".join(self.appels[0]) or "90" in self.appels[0])

    def test_sans_visuels_karots_comportement_historique(self):
        r = ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok,
                               portrait=self.tmp / "absent.png", paysage=self.tmp / "absent2.png")
        self.assertEqual((r["genre_playfield"], r["genre_autres"], r["rot"]), ("historique", "historique", 0))
        # rotation 0 : plus de rotation, mais la palette passe quand meme
        self.assertTrue(all("paletteuse" in " ".join(a) for a in self.appels), self.appels)
        self.assertTrue(all("transpose" not in " ".join(a) for a in self.appels), self.appels)
        r = ss.preparer_images(180, theme_dir=self.theme, run=self.run_ok,
                               portrait=self.tmp / "absent.png", paysage=self.tmp / "absent2.png")
        self.assertEqual(r["rot"], 180)    # l historique suit X11, jamais plus

    def test_outil_de_rotation_en_panne(self):
        def run_ko(args, timeout=120):
            return 1, "boom"
        r = ss.preparer_images(0, theme_dir=self.theme, run=run_ko, portrait=self.portrait, paysage=self.paysage)
        self.assertEqual(r["pre_tourne"], 0)
        self.assertEqual((self.theme / ss.IMAGE_PLAYFIELD).read_bytes(), b"PORTRAIT")

    def test_galerie_aleatoire(self):
        # portrait0.png + portrait1.jpg + paysage.jpg : tout devient PNG numerote, tire au sort au boot
        (self.tmp / "portrait0.png").write_bytes(b"P0"); (self.tmp / "portrait1.jpg").write_bytes(b"P1")
        (self.tmp / "paysage.jpg").write_bytes(b"L0"); self.portrait.unlink(); self.paysage.unlink()
        r = ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok, portrait=self.tmp / "portrait.png", paysage=self.tmp / "paysage.png", outil="ffmpeg")
        self.assertEqual((r["n_playfield"], r["n_autres"], r["genre_playfield"], r["genre_autres"]), (2, 1, "portrait", "paysage"))
        self.assertEqual(sorted(p.name for p in self.theme.glob("pincabos-*-*.png")),
                         ["pincabos-autres-0.png", "pincabos-playfield-0.png", "pincabos-playfield-1.png"])
        # le jpg est converti (ffmpeg/convert) : trois commandes (2 rotations + 1 conversion)
        self.assertEqual(len(self.appels), 3)
        t = ss.theme(ECRANS_YANN, 0, dict(r, rot=270))
        self.assertIn("k_pf = Math.Int(Math.Random() * 2);", t)
        self.assertIn('if (k_pf == 1) img_pf = Image("pincabos-playfield-1.png");', t)
        self.assertIn("k_autres = Math.Int(Math.Random() * 1);", t)

    def test_voile_genere(self):
        ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok, portrait=self.portrait, paysage=self.paysage)
        v = (self.theme / ss.IMAGE_VOILE).read_bytes()
        self.assertTrue(v.startswith(b"\x89PNG"))
        self.assertEqual(ss.dimensions(self.theme / ss.IMAGE_VOILE), (8, 8))

    def test_purge_des_anciennes_images(self):
        (self.theme / "pincabos-playfield-7.png").write_bytes(b"vieux")
        ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok, portrait=self.portrait, paysage=self.paysage)
        self.assertFalse((self.theme / "pincabos-playfield-7.png").exists())

    def test_arret_galerie_dediee(self):
        # PINCABOS_SPLASH_ARRET_V1 : arret*.png classes a leurs dimensions (entete PNG/JPEG)
        import struct, zlib
        def png(w, h):
            ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
            return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
        (self.tmp / "arret0.png").write_bytes(png(941, 1672))
        (self.tmp / "arret1.png").write_bytes(png(1672, 941))
        self.assertEqual(ss.dimensions(self.tmp / "arret0.png"), (941, 1672))
        r = ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok, portrait=self.portrait, paysage=self.paysage, outil="ffmpeg")
        self.assertEqual((r["n_arret_playfield"], r["n_arret_autres"]), (1, 1))
        self.assertTrue((self.theme / "pincabos-arret-playfield-0.png").exists())
        self.assertTrue((self.theme / "pincabos-arret-autres-0.png").exists())
        t = ss.theme(ECRANS_YANN, 0, dict(r, rot=270))
        self.assertIn('mode = Plymouth.GetMode();', t)
        self.assertIn('if (k_pf == 0) img_pf = Image("pincabos-arret-playfield-0.png");', t)

    def test_arret_sans_visuel_ecran_noir(self):
        r = ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok, portrait=self.portrait, paysage=self.paysage)
        self.assertEqual((r["n_arret_playfield"], r["n_arret_autres"]), (0, 0))
        t = ss.theme(ECRANS_YANN, 0, dict(r, rot=270))
        self.assertIn("montrer_pf = 0;", t)
        self.assertIn("if (0 > 0) {", t)   # aucune galerie d arret : rien n est pose, ecran noir
        self.assertEqual(t.count("{"), t.count("}"))

    def test_dimensions_jpeg(self):
        # SOF0 minimal : FFD8, FFC0 len=11, precision 8, h=941, w=1672
        jpg = b"\xff\xd8" + b"\xff\xc0" + (11).to_bytes(2, "big") + b"\x08" + (941).to_bytes(2, "big") + (1672).to_bytes(2, "big") + b"\x01\x01\x11\x00"
        (self.tmp / "x.jpg").write_bytes(jpg)
        self.assertEqual(ss.dimensions(self.tmp / "x.jpg"), (1672, 941))

    def test_commande_rotation(self):
        self.assertEqual(ss.commande_rotation(Path("a"), Path("b"), 270, outil=""), [])   # sans outil : Plymouth tournera
        self.assertIn("transpose=2", " ".join(ss.commande_rotation(Path("a"), Path("b"), 270, outil="ffmpeg")))
        self.assertEqual(ss.commande_rotation(Path("a"), Path("b"), 90, outil="convert")[2:4], ["-rotate", "90"])
        self.assertIsNone(ss.commande_rotation(Path("a"), Path("b"), 0))
        self.assertIsNone(ss.commande_rotation(Path("a"), Path("b"), 360))


class Palette(unittest.TestCase):
    """PINCABOS_SPLASH_PALETTE_V1 — 40 Mo de PNG dans l initrd, l essentiel de
    l attente entre GRUB et le splash. La palette de 256 couleurs les divise
    par 3,3 sans que l oeil voie la difference (mesure sur le cab de Yann :
    3 565 253 -> 1 069 878 octets)."""

    def test_la_rotation_et_la_palette_dans_la_meme_passe(self):
        """Deux passes ffmpeg couteraient un aller-retour disque par image."""
        f = ss.filtre_ffmpeg(270)
        self.assertTrue(f.startswith("transpose=2,"), f)
        self.assertIn("palettegen=max_colors=256", f)
        self.assertIn("paletteuse=dither=floyd_steinberg", f)

    def test_sans_rotation_la_palette_reste(self):
        f = ss.filtre_ffmpeg()
        self.assertNotIn("transpose", f)
        self.assertIn("palettegen", f)
        self.assertEqual(ss.filtre_ffmpeg(0), f)
        self.assertEqual(ss.filtre_ffmpeg(360), f)

    def test_une_seule_commande_ffmpeg(self):
        cmd = ss.commande_rotation(Path("a"), Path("b"), 270, outil="ffmpeg")
        self.assertEqual(cmd.count("-i"), 1, "une seule entree, donc une seule passe")
        self.assertIn("-filter_complex", cmd)

    def test_imagemagick_sort_du_png8(self):
        """PNG8 = palettise ; sans le prefixe, convert reecrit en couleurs vraies."""
        cmd = ss.commande_conversion(Path("a"), Path("b.png"), outil="convert")
        self.assertTrue(cmd[-1].startswith("PNG8:"), cmd)
        self.assertIn("-colors", cmd)
        cmd = ss.commande_rotation(Path("a"), Path("b.png"), 90, outil="convert")
        self.assertTrue(cmd[-1].startswith("PNG8:"), cmd)

    def test_les_sources_png_passent_aussi_par_la_palette(self):
        """Avant, un PNG etait recopie tel quel : c est lui le plus lourd."""
        self.assertIsNotNone(ss.commande_conversion(Path("a.png"), Path("b.png"), outil="ffmpeg"))

    def test_sans_outil_le_comportement_d_avant(self):
        """Un PNG se recopie (None), un JPEG s abandonne ([]) : rien ne bloque."""
        self.assertIsNone(ss.commande_conversion(Path("a.png"), Path("b.png"), outil=""))
        self.assertEqual(ss.commande_conversion(Path("a.jpg"), Path("b.png"), outil=""), [])


class Theme(unittest.TestCase):
    IMAGES = {"genre_playfield": "portrait", "genre_autres": "paysage", "rot": 270, "pre_tourne": 1}

    def test_contenu(self):
        t = ss.theme(ECRANS_YANN, 0, self.IMAGES)
        self.assertIn("PINCABOS_SPLASH_FROM_SCREENS_V3", t)
        self.assertIn("rot = 270;", t)
        self.assertIn("pf_w = 3840;", t)
        self.assertIn('Image("pincabos-playfield-0.png")', t)
        self.assertIn('Image("pincabos-autres-0.png")', t)
        self.assertIn("Window.SetX(i, cx);", t)          # surfaces ecartees
        self.assertIn("fun placer()", t)
        self.assertIn("placer();\n    if (pf_place != 1) return;", t)   # re-applique a chaque rafraichissement
        self.assertIn("Window.GetWidth(i) * 2 == pf_w", t)   # HiDPI
        self.assertNotIn("Rotate(rot * PI / 180);\n    }\n  }", t)
        self.assertIn(f"bar_width = bw * {ss.BARRE['portrait']['w']};", t)
        self.assertIn(f"bh * {ss.BARRE['portrait']['y']};", t)
        # PINCABOS_SPLASH_BARRE_VOILE_V1 : un voile qui recule, plus de barre rapportee
        self.assertIn('Image("pincabos-voile.png")', t)
        self.assertNotIn("progress_bar.png", t)
        self.assertIn("fun poser_voile(cw)", t)

    def test_playfield_tourne_par_x11(self):
        images = dict(self.IMAGES, rot=90)
        t = ss.theme({"playfield": (2160, 3840), "backglass": (1920, 1080)}, 90, images)
        self.assertIn("pf_w = 3840;", t)   # dalle vue par Plymouth : native
        self.assertIn("pf_h = 2160;", t)
        self.assertIn("rot = 90;", t)

    def test_historique(self):
        images = {"genre_playfield": "historique", "genre_autres": "historique", "rot": 0, "pre_tourne": 1}
        t = ss.theme(ECRANS_YANN, 0, images)
        self.assertIn(f"bar_width = bw * {ss.BARRE['historique']['w']};", t)

    def test_accolades_equilibrees(self):
        t = ss.theme(ECRANS_YANN, 0, self.IMAGES)
        self.assertEqual(t.count("{"), t.count("}"))
        self.assertNotIn("{{", t)

    def test_variables_du_voile_declarees_au_niveau_global(self):
        # PINCABOS_SPLASH_GLOBALES_V1 : une variable assignee d abord dans une fonction est locale
        # (Plymouth script) ; le voile du playfield lisait des NULL et n etait jamais pose.
        t = ss.theme(ECRANS_YANN, 0, self.IMAGES)
        tete = t.split("fun placer()")[0]
        for v in ("pf_sw", "pf_sh", "pf_iw", "pf_ih", "pf_ox", "pf_oy", "bar_width", "bar_lx", "bar_ly", "sw", "sh"):
            self.assertRegex(tete, rf"(^|\n|; ){v} = 0;", v)

    def test_barre_a_vitesse_constante_sans_temporisation(self):
        # PINCABOS_SPLASH_BARRE_TEMPO_V2 : plus de tempo du splash (Yann 06/09) ; barre pleine en 8 s,
        # ou plus vite si Plymouth annonce plus avance ; jamais en arriere.
        self.assertEqual(ss.duree_barre(), 8)
        self.assertFalse(hasattr(ss, "SPLASH_JSON"))
        t = ss.theme(ECRANS_YANN, 0, self.IMAGES)
        self.assertIn("ticks_barre = 400;", t)
        self.assertIn("p = tick / ticks_barre;", t)
        self.assertIn("if (progress_target > p) p = progress_target;", t)
        self.assertIn("if (p > progress_shown) progress_shown = p;", t)
        self.assertNotIn("hold_until_uptime", t)

    def test_barre_repliquee_sur_les_autres_dalles(self):
        # PINCABOS_SPLASH_BARRE_PARTOUT_V1 : masque noir opaque, decouvert au meme rythme partout
        t = ss.theme(ECRANS_YANN, 0, self.IMAGES)
        self.assertIn("fun poser_voiles_autres(frac)", t)
        self.assertIn("poser_voiles_autres(progress_shown);", t)
        self.assertIn(f"bw2 = fw[i] * {ss.BARRE['paysage']['w']};", t)
        self.assertIn(f"fh[i] * {ss.BARRE['paysage']['y']} - bar_height / 2", t)
        self.assertIn("SetOpacity(1.0)", t)
        self.assertNotIn("0.88", t)
        self.assertIn("n_total = n;", t)
        self.assertEqual(t.count("{"), t.count("}"))

    def test_media(self):
        # PINCABOS_SPLASH_MEDIA_V1 : sans screens.json, playfield = la plus grande dalle
        ecrans, rot = ss.parametres_media()
        self.assertEqual((ecrans, rot), ({"playfield": (0, 0)}, 0))
        self.assertEqual(ss.rotation_effective(rot), 270)     # portrait tourne comme un cab a l endroit
        t = ss.theme(ecrans, rot, self.IMAGES)
        self.assertIn("pf_w = 0;", t)
        self.assertIn("if (pf < 0 && pf_w == 0)", t)
        self.assertIn("a = Window.GetWidth(i) * Window.GetHeight(i);", t)
        self.assertIn("la plus grande dalle", t)
        self.assertEqual(t.count("{"), t.count("}"))
        # un cab configure garde la reconnaissance par resolution
        self.assertIn("pf_w = 3840;", ss.theme(ECRANS_YANN, 0, self.IMAGES))


class Perimetre(unittest.TestCase):
    def test_visuels_dans_le_perimetre_de_l_updater(self):
        # 3.69 : prefixe en attente ; a partir de la release suivante : livre (plus en attente)
        up = charger("opt/pincabos/update/pincabos_updates.py", "pco_updates_perimetre")
        rel = "opt/pincabos/media/splash/portrait0.png"
        self.assertTrue(up.allowed(rel))
        self.assertTrue(up.allowed_for_build(rel))
        self.assertNotIn("opt/pincabos/media/splash/", up.PENDING_PREFIXES)

    def test_sources_declarees(self):
        self.assertEqual(str(ss.PORTRAIT), "/opt/pincabos/media/splash/portrait.png")
        self.assertEqual(str(ss.PAYSAGE), "/opt/pincabos/media/splash/paysage.png")


class MediaEnPaysage(unittest.TestCase):
    """PINCABOS_SPLASH_MEDIA_PAYSAGE_V2 — Yann, 08/09/2026.

    Un media d'installation ignore la disposition des ecrans du cabinet :
    screens.json lui est volontairement retire, il est propre a chaque
    machine. Il n'allume donc qu'un ecran, inconnu. Y poser un portrait
    tourne de 270 n'a de sens que sur un playfield reellement monte comme
    tel ; sur un ecran quelconque, seul le paysage se lit.

    Le cabinet installe, lui, ne change pas : il regenere son theme au
    premier demarrage avec sa vraie disposition.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.srcs = self.tmp / "splash"
        self.theme = self.tmp / "theme"
        self.srcs.mkdir(); self.theme.mkdir()
        (self.srcs / "portrait0.png").write_bytes(b"PORTRAIT")
        (self.srcs / "paysage0.png").write_bytes(b"PAYSAGE")
        (self.theme / ss.IMAGE_HISTORIQUE).write_bytes(b"HISTORIQUE")
        self.appels = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_ok(self, args, timeout=120):
        self.appels.append(list(args))
        Path(args[-1]).write_bytes(b"PRODUIT")
        return 0, ""

    def preparer(self, media):
        return ss.preparer_images(0, theme_dir=self.theme, run=self.run_ok,
                                  portrait=self.srcs / "portrait.png",
                                  paysage=self.srcs / "paysage.png",
                                  outil="ffmpeg", media=media)

    def test_le_media_prend_le_paysage_et_ne_tourne_rien(self):
        r = self.preparer(media=True)
        self.assertEqual(r["genre_playfield"], "paysage")
        self.assertEqual(r["rot"], 0)
        tourne = [a for a in self.appels if any("transpose" in x for x in a)]
        self.assertEqual(tourne, [], "aucune rotation sur un media")

    def test_le_cabinet_installe_ne_change_pas(self):
        r = self.preparer(media=False)
        self.assertEqual(r["genre_playfield"], "portrait")
        self.assertEqual(r["rot"], 270)
        tourne = [a for a in self.appels if any("transpose" in x for x in a)]
        self.assertEqual(len(tourne), 1, "le playfield du cabinet reste pre-tourne")

    def test_sans_paysage_le_media_retombe_sur_ce_qu_il_a(self):
        """Une image manquante ne doit pas rendre le media noir."""
        (self.srcs / "paysage0.png").unlink()
        srcs = ss.sources_images(self.theme, self.srcs / "portrait.png",
                                 self.srcs / "paysage.png", media=True)
        self.assertEqual(srcs["playfield"]["genre"], "portrait")

    def test_l_iso_appelle_bien_le_mode_media(self):
        iso = Path(RACINE, "opt/pincabos/script/iso-live.sh").read_text(encoding="utf-8")
        self.assertIn("pincabos-splash-sync --media", iso)


if __name__ == "__main__":
    unittest.main()


class SansTempo(unittest.TestCase):
    """PINCABOS_SPLASH_BARRE_TEMPO_V2 : le splash ne retient plus le gestionnaire d affichage."""

    def test_plus_de_retenue(self):
        self.assertFalse((R / "etc/systemd/system/pincabos-splash-hold.service").exists())
        self.assertFalse((R / "etc/systemd/system/graphical.target.wants/pincabos-splash-hold.service").is_symlink())
        self.assertFalse((R / "usr/local/sbin/pincabos-splash-hold").exists())
        s = (R / "usr/local/sbin/pincabos-splash-sync").read_text(encoding="utf-8")
        self.assertNotIn("hold_until_uptime", s)
        self.assertNotIn("splash.json", s)


class Backboard(unittest.TestCase):
    """PINCABOS_BACKBOARD_BLANK_V1 : C puis O sur le port du TeensyStripController."""

    bb = charger("usr/local/sbin/pincabos-backboard-blank", "pco_backboard_blank")

    def test_port_depuis_cabinet(self):
        xml = "<Cabinet><OutputControllers><TeensyStripController><Name>T</Name><ComPortName>/dev/ttyACM0</ComPortName></TeensyStripController></OutputControllers></Cabinet>"
        self.assertEqual(self.bb.port_backboard(xml, by_id=["/dev/serial/by-id/usb-Teensyduino_USB_Serial_1-if00"]), "/dev/ttyACM0")

    def test_port_depuis_by_id(self):
        self.assertEqual(self.bb.port_backboard("<Cabinet/>", by_id=["/dev/serial/by-id/usb-Teensyduino_USB_Serial_1-if00"]),
                         "/dev/serial/by-id/usb-Teensyduino_USB_Serial_1-if00")
        self.assertEqual(self.bb.port_backboard(None, by_id=[]), "")

    def test_sequence_c_puis_o(self):
        class Faux:
            def __init__(self): self.ecrit = []
            def write(self, b): self.ecrit.append(b)
            def read(self, n): return b"A"
        f = Faux()
        j = self.bb.blanchir(f)
        self.assertEqual(f.ecrit, [b"C", b"O"])
        self.assertEqual(len(j), 2)

    def test_unite(self):
        u = (R / "etc/systemd/system/pincabos-backboard-blank.service").read_text(encoding="utf-8")
        self.assertIn("Before=pincabos-vpinfe.service", u)
        self.assertIn("ExecStop=/usr/local/sbin/pincabos-backboard-blank shutdown", u)
        self.assertTrue((R / "etc/systemd/system/multi-user.target.wants/pincabos-backboard-blank.service").is_symlink())


class ChromeSombre(unittest.TestCase):
    """PINCABOS_VPINFE_CHROME_SOMBRE_V1 : --force-dark-mode dans chromeoptions de vpinfe.ini."""

    cs = charger("usr/local/libexec/pincabos/pincabos-vpinfe-chrome-sombre", "pco_chrome_sombre")

    def test_ajout_idempotent(self):
        ini = "[Chrome]\nchromeoptions = \ndisabledefaultchromeoptions = false\n"
        n, change = self.cs.ajouter(ini)
        self.assertTrue(change)
        self.assertIn("chromeoptions = --force-dark-mode\n", n)
        n2, change2 = self.cs.ajouter(n)
        self.assertFalse(change2); self.assertEqual(n, n2)

    def test_conserve_les_options_existantes(self):
        n, _ = self.cs.ajouter("chromeoptions = --foo --bar\n")
        self.assertEqual(n, "chromeoptions = --foo --bar --force-dark-mode\n")
        self.assertEqual(self.cs.ajouter("rien = ici\n"), ("rien = ici\n", False))

    def test_drop_in(self):
        d = (R / "etc/systemd/system/pincabos-vpinfe.service.d/40-chrome-sombre.conf").read_text(encoding="utf-8")
        self.assertIn("ExecStartPre=-/usr/local/libexec/pincabos/pincabos-vpinfe-chrome-sombre", d)


class VoileEcrans(unittest.TestCase):
    """PINCABOS_VOILE_ECRANS_V1 : voile noir par ecran jusqu au premier rendu du frontend."""

    ve = charger("usr/local/bin/pincabos-voile-ecrans", "pco_voile_ecrans")

    def test_geometries(self):
        s = json.dumps({"playfield": {"geometry": "3840x2160+0+0"}, "backglass": {"geometry": "1920x1080+3840+0"},
                        "fulldmd": {"geometry": "1920x1080+5760+0"}, "topper": None})
        self.assertEqual(self.ve.geometries(s), [('playfield', 0, 0, 3840, 2160), ('backglass', 3840, 0, 1920, 1080), ('fulldmd', 5760, 0, 1920, 1080)])
        self.assertEqual(self.ve.geometries("pas du json"), [])
        self.assertEqual(self.ve.geometries(None), [])

    def test_nouvelle_fenetre_seulement(self):
        # un redemarrage du frontend laisse l ancienne fenetre quelques instants : elle ne compte pas
        self.assertFalse(self.ve.nouvelle_fenetre({"0x1c00003"}, {"0x1c00003"}))
        self.assertTrue(self.ve.nouvelle_fenetre({"0x1c00003"}, {"0x1c00003", "0x2400003"}))
        self.assertFalse(self.ve.nouvelle_fenetre(set(), set()))

    def test_unite(self):
        u = (R / "etc/systemd/system/pincabos-voile-ecrans.service").read_text(encoding="utf-8")
        self.assertIn("User=pinball", u)
        self.assertIn("Before=pincabos-vpinfe.service", u)
        self.assertIn("ExecStart=/usr/local/bin/pincabos-voile-ecrans --delai 3.5", u)
        self.assertTrue((R / "etc/systemd/system/graphical.target.wants/pincabos-voile-ecrans.service").is_symlink())
