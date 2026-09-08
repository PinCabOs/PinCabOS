"""Les sommes de la charge utile nomment les fichiers en RELATIF.

PINCABOS_PAYLOAD_SOMMES_RELATIVES_V1 — cab de Yann, ISO 4.63, 08/09/2026.

L'assistant graphique demarrait enfin, l'installation partait, puis :

    sha256sum: /opt/pincabos/build/live-v8.1g-english/payload-full/
               pincabos-plymouth-theme-overlay-v8.1g.tar.zst: No such file or directory
    FAILED open or read
    sha256sum: WARNING: 1 listed file could not be read

sha256sum ecrit le nom qu'on lui donne. L'etape 70 lui passait un chemin
ABSOLU de la machine de construction : le fichier de sommes grave sur le media
nommait un chemin qui n'existe evidemment pas sur le cabinet. L'installateur
fait « cd "$PAYLOAD_DIR" && sha256sum -c », donc il cherchait la-bas.

Le fichier voisin parts.sha256 nommait deja « ../casper/filesystem.squashfs »
en relatif, et lui fonctionnait : c'est le modele.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
ETAPE = R / "opt/pincabos/script/iso/70-helper.sh"
INSTALLATEUR = R / "opt/pincabos/script/installer/pincabos-live-installer"


class SommesRelatives(unittest.TestCase):
    def setUp(self):
        self.s = ETAPE.read_text(encoding="utf-8")

    def test_aucune_somme_ecrite_depuis_un_chemin_absolu(self):
        """« sha256sum "$ARCHIVE" » grave le chemin du constructeur."""
        for n, ligne in enumerate(self.s.splitlines(), 1):
            if ligne.lstrip().startswith("#"):
                continue
            m = re.search(r'sha256sum\s+"\$(ARCHIVE|OVERLAY)"', ligne)
            if m:
                self.fail(f'ligne {n} : sha256sum "${m.group(1)}" grave un chemin absolu ; '
                          "il faut se placer dans le dossier et nommer le fichier seul")

    def test_les_deux_sommes_passent_par_le_dossier(self):
        for nom in ("ARCHIVE", "OVERLAY"):
            self.assertIn(f'( cd "$PAYLOAD_FULL" && sha256sum "$(basename "${nom}")" )', self.s,
                          f"la somme de ${nom} doit etre prise depuis $PAYLOAD_FULL")

    def test_l_installateur_verifie_bien_depuis_le_dossier(self):
        """Si l'installateur changeait de methode, le relatif n'irait plus."""
        i = INSTALLATEUR.read_text(encoding="utf-8")
        self.assertIn('cd "$PAYLOAD_DIR" && sha256sum -c pincabos-plymouth-theme-overlay-v8.1g.sha256', i)


class MecanismeReel(unittest.TestCase):
    """On rejoue la manoeuvre : ecrire ici, verifier ailleurs."""

    def test_verification_apres_deplacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            build = tmp / "payload-full"
            build.mkdir()
            fichier = build / "pincabos-plymouth-theme-overlay-v8.1g.tar.zst"
            fichier.write_text("charge utile", encoding="utf-8")
            somme = build / "pincabos-plymouth-theme-overlay-v8.1g.sha256"
            with somme.open("w") as f:
                subprocess.run(["sha256sum", fichier.name], cwd=build, stdout=f, check=True)

            self.assertNotIn(str(build), somme.read_text(encoding="utf-8"),
                             "le chemin de construction ne doit pas figurer dans la somme")

            media = tmp / "cdrom" / "pincabos-payload"
            media.mkdir(parents=True)
            for p in build.iterdir():
                (media / p.name).write_bytes(p.read_bytes())
            for p in list(build.iterdir()):
                p.unlink()
            build.rmdir()          # le dossier de construction n existe plus

            r = subprocess.run(["sha256sum", "-c", somme.name], cwd=media,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(": OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
