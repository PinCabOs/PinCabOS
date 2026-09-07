"""VPX et VPinFE tournent sur la MEME libdof (PINCABOS_LIBDOF_UNIQUE_V1).

Trouve sur le cab de Yann le 08/09/2026 : VPX chargeait le build du 31 aout
(11 625 296 o) et VPinFE celui du 28 juin (11 846 032 o). Trois mois d'ecart,
sur le meme cabinet, avec la meme configuration DOF — selon qu'on etait en jeu
ou dans le menu.

La cause : la recette COPIAIT le binaire canonique vers VPX mais faisait
pointer VPinFE, par lien, vers un SECOND overlay. Et opt/pincabos/overlays/
etant hors du perimetre des mises a jour, l'ecart etait a la fois invisible et
non rattrapable — le cab a garde son binaire de juin pendant trois mois.

Le test ne verifie pas seulement la valeur du jour : il exige que TOUT ce qui
nomme un overlay libdof nomme le meme que components.json.
"""
import json
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
COMPOSANTS = R / "image/components.json"

# Les fichiers qui designent la libdof a charger. En ajouter un sans le mettre
# ici ne casse rien : le balayage ci-dessous les trouve tout seul.
CONSOMMATEURS = (
    "opt/pincabos/tools/run-vpinfe-systemd.sh",
    "usr/local/libexec/pincabos/vpinfe-dof-library-bridge.sh",
)

OVERLAY = re.compile(r"/opt/pincabos/overlays/([A-Za-z0-9._-]+)")


def source_canonique() -> str:
    """Le dossier d'overlay dont la recette tire le binaire."""
    d = json.loads(COMPOSANTS.read_text(encoding="utf-8"))
    return Path(d["components"]["libdof"]["source"]).parent.name


class UneSeuleLibdof(unittest.TestCase):
    def setUp(self):
        self.d = json.loads(COMPOSANTS.read_text(encoding="utf-8"))
        self.libdof = self.d["components"]["libdof"]
        self.canonique = source_canonique()

    def test_vpx_recoit_le_binaire_canonique(self):
        self.assertTrue(self.libdof["copies"], "VPX doit recevoir une copie")
        for c in self.libdof["copies"]:
            self.assertTrue(c.startswith("opt/pinball/vpx/plugins/dof/"), c)

    def test_vpinfe_pointe_sur_le_meme_overlay_que_la_source(self):
        liens = self.libdof["links"]
        self.assertTrue(liens, "VPinFE doit avoir ses liens")
        for cible, source in liens.items():
            self.assertTrue(cible.startswith("opt/pinball/vpinfe/_internal/"), cible)
            trouve = OVERLAY.findall(source)
            self.assertEqual(trouve, [self.canonique],
                             f"{cible} pointe sur {trouve}, la source est {self.canonique}")

    def test_les_consommateurs_nomment_le_meme_overlay(self):
        """Le lanceur et le pont : un seul nom, celui de la source."""
        for rel in CONSOMMATEURS:
            texte = (R / rel).read_text(encoding="utf-8")
            noms = set(OVERLAY.findall(texte))
            self.assertTrue(noms, f"{rel} : aucun overlay nomme")
            self.assertEqual(noms, {self.canonique},
                             f"{rel} nomme {sorted(noms)}, la source est {self.canonique}")

    def test_aucun_autre_overlay_libdof_nomme_ailleurs(self):
        """Balayage : tout fichier livre qui nomme un overlay libdof doit nommer
        celui-la. C'est ce garde-fou qui manquait, pas la valeur du jour."""
        ecarts = []
        for rel in ("opt/pincabos/tools", "usr/local/libexec/pincabos", "usr/local/sbin",
                    "usr/local/bin", "etc/systemd/system"):
            base = R / rel
            if not base.is_dir():
                continue
            for f in base.rglob("*"):
                if not f.is_file() or f.suffix in (".png", ".jpg", ".gif", ".so"):
                    continue
                try:
                    texte = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for nom in OVERLAY.findall(texte):
                    if nom.startswith("libdof") or "dof" in nom:
                        if nom != self.canonique:
                            ecarts.append(f"{f.relative_to(R)} : {nom}")
        self.assertEqual(ecarts, [], "ces fichiers nomment un autre overlay libdof")


if __name__ == "__main__":
    unittest.main()
