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

from _charge import RACINE

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
    """{consigne en degres: filtre ffmpeg}."""
    texte = SPLASH.read_text(encoding="utf-8")
    ligne = re.search(r"vf = \{(.+?)\}\[degres % 360\]", texte, re.S)
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


if __name__ == "__main__":
    unittest.main()
