"""Unites systemd : pas de cycle d'ordonnancement, pas de casper sur la cible.

Vu sur le cab de Yann le 07/09/2026, deux defauts de demarrage sans rapport
avec Secure Boot, mais reveles en cherchant pourquoi le boot figeait.
"""
import re
import unittest
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
UNITES = R / "etc/systemd/system"

# graphical.target est tire APRES multi-user.target. Une unite activee par l un
# ne peut pas declarer « After » l autre sans fermer une boucle : systemd la
# casse en supprimant un job, silencieusement, et l unite ne demarre jamais.
APRES_INTERDIT = {
    "multi-user.target": ("graphical.target",),
    "graphical.target": (),
}


def champs(unite: Path) -> dict:
    """Valeurs des directives, une liste par cle (les repetitions s'ajoutent)."""
    valeurs: dict[str, list[str]] = {}
    for ligne in unite.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith(("#", ";", "[")):
            continue
        cle, _, reste = ligne.partition("=")
        valeurs.setdefault(cle.strip(), []).extend(reste.split())
    return valeurs


class CyclesDOrdonnancement(unittest.TestCase):
    def test_aucune_unite_ne_ferme_de_cycle(self):
        """PINCABOS_UNITES_SANS_CYCLE_V1"""
        for unite in sorted(UNITES.glob("pincabos-*.service")):
            v = champs(unite)
            apres = set(v.get("After", []))
            for cible in set(v.get("WantedBy", [])) | set(v.get("RequiredBy", [])):
                for interdit in APRES_INTERDIT.get(cible, ()):
                    self.assertNotIn(
                        interdit, apres,
                        f"{unite.name} : WantedBy={cible} + After={interdit} "
                        "ferme un cycle, systemd supprimera son job")

    def test_le_lien_dactivation_suit_la_directive(self):
        """Un lien pose dans le mauvais .wants rejoue le cycle malgre l unite corrigee."""
        for lien in sorted(UNITES.glob("*.target.wants/pincabos-*.service")):
            unite = UNITES / lien.name
            if not unite.is_file():
                continue
            cible = lien.parent.name[: -len(".wants")]
            self.assertIn(cible, champs(unite).get("WantedBy", []),
                          f"{lien.parent.name}/{lien.name} : l unite dit "
                          f"WantedBy={champs(unite).get('WantedBy')}")


class CasperHorsDeLaCible(unittest.TestCase):
    """PINCABOS_CIBLE_SANS_CASPER_V1

    Le systeme installe est une copie du rootfs live : sans purge, il garde
    casper-md5check, qui cherche les sommes d un ISO absent et echoue a chaque
    demarrage.
    """

    def setUp(self):
        self.s = (R / "opt/pincabos/script/installer/pincabos-live-installer").read_text(encoding="utf-8")

    def test_la_purge_existe_et_est_appelee(self):
        self.assertIn("purge_live_only_from_target() {", self.s)
        self.assertIn("PINCABOS_CIBLE_SANS_CASPER_V1", self.s)
        self.assertRegex(self.s, r"\n  purge_live_only_from_target\n")

    def test_avant_la_regeneration_de_l_initrd(self):
        """Purger casper regenere l initrd : le faire apres serait un tour de trop."""
        purge = self.s.index("\n  purge_live_only_from_target\n")
        initrd = self.s.index("\n  refresh_target_initrd_for_orientation\n")
        self.assertLess(purge, initrd)

    def test_masque_si_la_purge_echoue(self):
        corps = self.s[self.s.index("purge_live_only_from_target() {"):]
        corps = corps[: corps.index("\nensure_target_vpx_link()")]
        self.assertIn("ln -sfn /dev/null", corps, "pas de masquage de secours")
        self.assertIn("dpkg --purge", corps)


if __name__ == "__main__":
    unittest.main()
