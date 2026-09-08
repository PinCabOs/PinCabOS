"""Le voile prolonge le splash : il doit tourner dans le meme sens que lui.

PINCABOS_VOILE_SENS_V2 — cab de Yann, 07/09/2026. Le splash etait a l endroit,
le visuel du voile arrivait tete en bas juste derriere. Les deux annoncaient
pourtant « 270 ».

Le piege : la valeur de l'enumeration GdkPixbuf EST l'angle ANTI-horaire
(COUNTERCLOCKWISE=90, CLOCKWISE=270), alors que le splash passe par ffmpeg,
ou transpose=1 est 90 HORAIRE et transpose=2 est 90 anti-horaire. Consigne
« 270 » : le splash tourne de 90 anti-horaire, le voile tournait de 90 horaire.
"""
import re
import unittest
from pathlib import Path

from _charge import RACINE, charger

R = Path(RACINE)
VOILE = R / "usr/local/bin/pincabos-voile-ecrans"
SPLASH = R / "usr/local/sbin/pincabos-splash-sync"


def rotations_du_voile() -> dict:
    """{consigne en degres: nom de la constante GdkPixbuf employee}."""
    texte = VOILE.read_text(encoding="utf-8")
    corps = texte[texte.index("def composer("):]
    corps = corps[: corps.index("\ndef ", 1)]
    trouve = {}
    for degres, nom in re.findall(
            r"rotation == (\d+):\s*\n\s*pb = pb\.rotate_simple\("
            r"GdkPixbuf\.PixbufRotation\.([A-Z]+)\)", corps):
        trouve[int(degres)] = nom
    return trouve


def rotations_du_splash() -> dict:
    """{consigne en degres: filtre ffmpeg}, lue dans ROTATION_FFMPEG."""
    texte = SPLASH.read_text(encoding="utf-8")
    ligne = re.search(r"ROTATION_FFMPEG = \{(.+?)\}", texte, re.S)
    assert ligne, "table de rotation ffmpeg introuvable"
    return dict((int(d), f) for d, f in re.findall(r"(\d+): \"([^\"]+)\"", ligne.group(1)))


# ffmpeg transpose=1 = 90 horaire ; transpose=2 = 90 anti-horaire.
# GdkPixbuf : la valeur de l enumeration est l angle anti-horaire.
FFMPEG_ANTIHORAIRE = {"transpose=1": 270, "transpose=2": 90,
                      "transpose=1,transpose=1": 180}
GDK_ANTIHORAIRE = {"NONE": 0, "COUNTERCLOCKWISE": 90, "UPSIDEDOWN": 180, "CLOCKWISE": 270}


class MemeSens(unittest.TestCase):
    def test_les_deux_chemins_tournent_pareil(self):
        voile, splash = rotations_du_voile(), rotations_du_splash()
        self.assertTrue(voile, "aucune rotation lue dans composer()")
        for degres, nom in voile.items():
            self.assertIn(degres, splash, f"le splash ne connait pas la consigne {degres}")
            self.assertEqual(
                GDK_ANTIHORAIRE[nom], FFMPEG_ANTIHORAIRE[splash[degres]],
                f"consigne {degres} : le voile fait {GDK_ANTIHORAIRE[nom]} anti-horaire "
                f"({nom}), le splash {FFMPEG_ANTIHORAIRE[splash[degres]]} "
                f"({splash[degres]}) — le visuel arrivera de travers derriere le splash")

    def test_la_consigne_du_playfield_paysage_reste_270(self):
        """Les deux fichiers doivent partir de la meme consigne, sinon comparer n a pas de sens."""
        voile = VOILE.read_text(encoding="utf-8")
        self.assertIn('return ("portrait", 270) if w >= h else ("portrait", 0)', voile)
        splash = SPLASH.read_text(encoding="utf-8")
        self.assertIn("return (270 + rotation_x11) % 360", splash)


class VisuelsParDefaut(unittest.TestCase):
    """PINCABOS_VOILE_VISUELS_V4 — Yann, 08/09/2026, apres une installation complete.

    Le voile etait passe au noir la veille (V3) parce que les visuels
    « clignotaient ». Mais ce clignotement venait du sens de rotation inverse
    (PINCABOS_VOILE_SENS_V2, corrige depuis) : le voile rejouait l image du
    splash tete en bas. Les deux chemins alignes, le voile affiche EXACTEMENT
    ce que Plymouth affichait et le raccord ne se voit plus.

    Le noir, lui, se voyait — mesure sur le cab : 8,5 s d ecran noir entre la
    fin du splash et le premier rendu du frontend.
    """

    def setUp(self):
        self.s = VOILE.read_text(encoding="utf-8")

    def test_les_visuels_sont_le_defaut(self):
        self.assertIn("if not a.noir:", self.s)
        self.assertNotIn("if a.visuels:", self.s)

    def test_le_noir_reste_possible(self):
        """Un cabinet peut vouloir le noir : l option doit rester vraie."""
        self.assertIn('p.add_argument("--noir", action="store_true", help="voile noir, sans visuel")', self.s)

    def test_visuels_reste_accepte_sans_rien_faire(self):
        """Une unite du parc peut encore le passer : elle ne doit pas planter."""
        self.assertIn('p.add_argument("--visuels", action="store_true", help=argparse.SUPPRESS)', self.s)

    def test_l_unite_ne_force_aucun_des_deux(self):
        """Le defaut doit venir du programme, pas d un drapeau cache dans l unite."""
        unite = Path(RACINE, "etc/systemd/system/pincabos-voile-ecrans.service").read_text(encoding="utf-8")
        for ligne in unite.splitlines():
            if ligne.startswith("ExecStart="):
                self.assertNotIn("--noir", ligne, ligne)
                self.assertNotIn("--visuels", ligne, ligne)


class FonduVersLeFrontend(unittest.TestCase):
    """Sans compositeur, l opacite d une fenetre X n existe pas : on passe par la
    rampe de gamma, qui s applique aussi a ce qui est SOUS le voile."""

    def setUp(self):
        self.s = VOILE.read_text(encoding="utf-8")
        self.mod = charger("usr/local/bin/pincabos-voile-ecrans", "pco_voile")

    def test_rampe_zero_est_noire(self):
        self.assertEqual(set(self.mod.rampe(2048, 0.0)), {0})

    def test_rampe_un_va_jusqu_au_maximum(self):
        r = self.mod.rampe(2048, 1.0)
        self.assertEqual(r[0], 0)
        self.assertEqual(r[-1], 65535)
        self.assertEqual(r, sorted(r), "une rampe ne redescend pas")

    def test_rampe_moitie(self):
        self.assertEqual(self.mod.rampe(2048, 0.5)[-1], 32767)

    def test_facteur_borne(self):
        """Un facteur hors bornes assombrirait ou saturerait l ecran sans retour."""
        self.assertEqual(self.mod.rampe(256, -3.0)[-1], 0)
        self.assertEqual(self.mod.rampe(256, 12.0)[-1], 65535)

    def test_taille_degeneree(self):
        self.assertEqual(self.mod.rampe(1, 1.0), [])
        self.assertEqual(self.mod.rampe(0, 1.0), [])

    def test_l_ecran_est_toujours_rendu(self):
        """Un ecran laisse a zero serait une panne noire : trois filets."""
        self.assertIn("finally:", self.s)
        self.assertIn("fondu.restaurer()", self.s)
        self.assertIn("signal.SIGTERM", self.s)
        self.assertIn("def restaurer(self)", self.s)

    def test_le_voile_est_retire_pendant_le_noir(self):
        """Descendre a zero APRES avoir retire le voile montrerait le frontend d un coup."""
        corps = self.s[self.s.index("    etapes = max(1,"):]
        zero = corps.index("fondu.poser(0.0)")
        retrait = corps.index("lib.XUnmapWindow(dpy, win)")
        remontee = corps.index("fondu.poser(i / etapes)")
        self.assertLess(zero, retrait, "l ecran doit etre noir avant le retrait")
        self.assertLess(retrait, remontee, "on remonte apres avoir retire le voile")

    def test_fondu_desactivable(self):
        self.assertIn('p.add_argument("--fondu", type=float, default=0.45', self.s)
        self.assertIn("if a.fondu > 0 and fondu.disponible() else 0", self.s)


if __name__ == "__main__":
    unittest.main()
