"""Une seule branche NVIDIA, et c'est la 580 (PINCABOS_NVIDIA_BRANCHE_UNIQUE_V1).

Trouve le 09/09/2026, apres la remontee de testeurs bloques sur GTX 1080 Ti :
le master embarquait `nvidia-driver-595-open`. Or NVIDIA a sorti Maxwell,
Pascal et Volta de la branche 590 ET DES SUIVANTES, dans les deux variantes.
Compare sur les Modaliases du depot Ubuntu 26.04 :

    595-open et 595 proprietaire  293 cartes (listes IDENTIQUES)
    610 / 610-open / 580-open     295 a 298 cartes
    580 proprietaire              449 cartes

Les 156 cartes d ecart sont TOUTE la generation GTX 9xx et GTX 10xx, c est-a-dire
le parc reel des pincabs. Aucune ligne de commande noyau ne rattrape ca : le
pilote ne connait pas l identifiant PCI de la carte, il ne s y attachera jamais.
La 580 est devenue la branche de support long de Maxwell/Pascal, comme la 470
l est pour Kepler. Elle couvre de la GTX 750 Ti a la RTX 5090 (5060, 5070, 5080
et 5090 verifiees une a une) ; les 4 references qu elle perd sont des RTX PRO
et du datacenter, aucune GeForce.

Deux branches ne peuvent pas cohabiter : elles declarent `Conflicts:` sur les
memes paquets virtuels et posent les memes chemins (nvidia-smi, nvidia_drv.so,
libGL). `apt-get install -s nvidia-driver-580 nvidia-driver-595-open` repond
« E: two conflicting assignments ». D ou : une seule branche dans le manifest.
"""
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
MANIFEST = R / "opt/pincabos/system-manifests/apt-packages.tsv"

BRANCHE = "580"

# nvidia-driver-580, nvidia-dkms-580, libnvidia-gl-580, xserver-xorg-video-nvidia-580,
# nvidia-firmware-580-580.178.04 : tout paquet qui porte un numero de branche.
NUMEROTE = re.compile(r"^(?:lib)?nvidia[a-z-]*-(\d{3})\b|^xserver-xorg-video-nvidia-(\d{3})\b")


def noms() -> list:
    """Noms de paquets, sans le suffixe d architecture : le manifest melange les
    deux formes (mesa-vulkan-drivers:amd64 mais xserver-xorg-video-amdgpu)."""
    lignes = MANIFEST.read_text(encoding="utf-8").splitlines()
    return [l.split("\t")[0].removesuffix(":amd64") for l in lignes if l.strip()]


def branches() -> set:
    trouvees = set()
    for n in noms():
        m = NUMEROTE.match(n)
        if m:
            trouvees.add(m.group(1) or m.group(2))
    return trouvees


class BrancheUnique(unittest.TestCase):
    def test_une_seule_branche(self):
        b = branches()
        self.assertEqual(len(b), 1, "les branches NVIDIA se declarent Conflicts entre "
                                    "elles : apt refuse le manifest. Trouve : " + repr(sorted(b)))

    def test_c_est_la_580(self):
        self.assertEqual(branches(), {BRANCHE},
                         "seule la 580 connait Maxwell et Pascal (449 cartes contre 293)")


class PasDeVarianteOpen(unittest.TestCase):
    def test_aucun_paquet_open(self):
        # les modules « open » exigent le firmware GSP : Turing et plus recent
        # uniquement. Sur une GTX 1080 Ti ils ne s attachent pas.
        ouverts = [n for n in noms() if n.startswith("nvidia") and n.endswith("-open")]
        self.assertEqual(ouverts, [], "la variante open ne couvre ni Pascal ni Maxwell")


class PileComplete(unittest.TestCase):
    """Le pilote noyau seul ne suffit pas : sans le pilote Xorg, pas d affichage."""

    def test_paquets_indispensables(self):
        presents = set(noms())
        for attendu in ("nvidia-driver-" + BRANCHE,
                        "nvidia-dkms-" + BRANCHE,
                        "nvidia-kernel-common-" + BRANCHE,
                        "xserver-xorg-video-nvidia-" + BRANCHE,
                        "libnvidia-gl-" + BRANCHE,
                        "nvidia-utils-" + BRANCHE):
            self.assertIn(attendu, presents, attendu + " manque au manifest")

    def test_firmware_nvidia_present(self):
        # linux-firmware a ete decoupe par fabricant en 26.04 : sans ce paquet,
        # les cartes recentes n ont pas leur micrologiciel GSP.
        self.assertIn("linux-firmware-nvidia-graphics", set(noms()))


class AmdEtIntelIntacts(unittest.TestCase):
    """AMD et Intel n ont jamais demande d arbitrage : amdgpu/i915/xe sont dans le
    noyau, Mesa fournit RADV et ANV. Rien a choisir, mais tout doit etre la."""

    def test_pile_mesa_et_firmware(self):
        presents = set(noms())
        for attendu in ("mesa-vulkan-drivers", "libgl1-mesa-dri",
                        "xserver-xorg-video-amdgpu",
                        "linux-firmware-amd-graphics",
                        "linux-firmware-intel-graphics"):
            self.assertIn(attendu, presents, attendu + " manque : "
                          "une Radeon ou une Intel resterait sans affichage accelere")
