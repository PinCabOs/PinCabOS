"""iso.sh : le helper d'installation genere doit rester executable de bout en bout.

Regression Alpha 3.12-3.46 (commit adf4c1e) : une continuation de ligne
doublee (`\\\\`) dans le bloc `systemd-analyze verify` du helper coupait la
commande ; avec `set -euo pipefail` le helper s'arretait et l'installateur
rendait « Payload extraction/install failed (code 1) ». Karots ne pouvait
plus installer une ISO ; les ISO construites depuis le 01/09 etaient
inutilisables.
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from _charge import RACINE, texte_installateur, texte_fichier_livre

ISO = os.path.join(RACINE, "opt/pincabos/script/iso.sh")


def _texte():
    return texte_installateur()  # iso.sh + fichiers livres de l installateur


def _bloc_verify():
    s = _texte()
    a = s.index("systemd-analyze --root=")
    b = s.index("|| true", a) + len("|| true")
    return s[a:b]


class Continuations(unittest.TestCase):
    def test_aucune_ligne_ne_finit_par_un_double_backslash(self):
        fautives = [f"{i}: {l}" for i, l in enumerate(_texte().splitlines(), 1) if l.endswith("\\\\")]
        self.assertEqual(fautives, [])

    def test_le_bloc_verify_est_une_seule_commande(self):
        """Simule le helper : systemd-analyze remplace par un stub qui echoue sur un
        argument « \\ » (le vrai rend « Failed to prepare filename \\: Invalid argument' »). Avec set -e,
        le bloc doit rendre 0 grace au `|| true` rattache a la vraie commande."""
        bloc = _bloc_verify()
        script = (
            "set -euo pipefail\nTARGET=/nonexistent\nSYSTEMD_VERIFY_LOG=$(mktemp)\n"
            "systemd-analyze() { for a in \"$@\"; do [ \"$a\" = '\\' ] && { echo 'Failed to prepare filename \\: Invalid argument' >&2; return 1; }; done; return 3; }\n"
            + bloc + "\necho FIN\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
            f.write(script)
        r = subprocess.run(["bash", f.name], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("FIN", r.stdout)

    def test_les_unites_verifiees_existent(self):
        unites = re.findall(r"(pincabos-[a-z0-9-]+\.service)", _bloc_verify())
        self.assertTrue(unites)
        absentes = [u for u in unites if not os.path.exists(os.path.join(RACINE, "etc/systemd/system", u))]
        self.assertEqual(absentes, [])

    def test_garde_de_construction_presente(self):
        self.assertIn("PINCABOS_ISO_HELPER_CONTINUATION_GUARD_V1", _texte())


class DropIns(unittest.TestCase):
    def test_les_drop_ins_ne_sont_pas_executables(self):
        d = os.path.join(RACINE, "etc/systemd/system/pincabos-vpinfe.service.d")
        out = subprocess.run(["git", "-C", RACINE, "ls-files", "-s", d], capture_output=True, text=True).stdout
        exec_ = [l.split()[3] for l in out.splitlines() if l.startswith("100755")]
        self.assertEqual(exec_, [])


class PreferencesVpx(unittest.TestCase):
    """PINCABOS_VPX_PREF_PATH_V1 : les preferences VPX vivent sous ~/.pincabos/vpx
    (-PrefPath). iso.sh doit traiter ce chemin partout ou il traitait les anciens :
    sans cela le VPinballX.ini du master (noms de cartes audio) partait dans la
    photo et la garde audio de Karots refusait l'ISO (04/09/2026)."""

    NOUVEAU = "home/pinball/.pincabos/vpx"

    def test_exclu_du_tar_neutralise_et_conserve(self):
        s = _texte()
        self.assertIn("--exclude='./home/pinball/.pincabos/vpx/VPinballX.ini'", s)
        self.assertGreaterEqual(s.count('source_root / "home/pinball/.pincabos/vpx"'), 1)
        self.assertEqual(s.count('target / "home/pinball/.pincabos/vpx"'), 2)
        self.assertIn('"home/pinball/.pincabos/vpx/VPinballX.ini"', s)

    def test_partout_ou_l_ancien_chemin_est_traite(self):
        """Chaque bloc qui cite ~/.vpinball/VPinballX.ini cite aussi le nouveau chemin."""
        lignes = _texte().splitlines()
        for i, l in enumerate(lignes):
            if ".vpinball" in l and "VPinballX" in l or 'target / "home/pinball/.vpinball"' in l or 'Path("/home/pinball/.vpinball")' in l:
                voisinage = "\n".join(lignes[max(0, i - 8): i + 4])
                self.assertIn(".pincabos/vpx", voisinage, f"ligne {i + 1}: {l.strip()}")

    def test_regex_archive_prefpath_est_exacte(self):
        """La regex doit matcher './home/...' et ne jamais chercher un backslash litteral."""
        s = _texte()
        bonne = r"^\./home/pinball/\.pincabos/vpx/VPinballX\.ini$"
        mauvaise = r"^\\\./home/pinball/\\\.pincabos/vpx/VPinballX\\\.ini$"
        self.assertIn(bonne, s)
        self.assertNotIn(mauvaise, s)


if __name__ == "__main__":
    unittest.main()


class ModeleLive(unittest.TestCase):
    """PINCABOS_ISO_MODELE_LIVE_V1 : iso.sh --live confie l ISO a iso-live.sh."""

    def setUp(self):
        self.s = texte_installateur()

    def test_le_modele_live_est_le_seul(self):
        # PINCABOS_ISO_MODELE_LIVE_V2 : le classique (base Ubuntu + payload en morceaux) est retire
        self.assertIn('PCO_ISO_MODEL="live"', self.s)
        self.assertIn("--classic) echo \"ERROR: le modele classique a ete retire", self.s)
        self.assertNotIn('PCO_ISO_MODEL" = "live"', self.s)
        for reste in ('echo "=== 9) Download', 'echo "=== 15) Repack', 'echo "=== 19) Build final bootable ISO',
                      "split -b 1900M", "PAYLOAD_ISO_READY", "BASE_ISO_URL", "PINCABOS_GRUB_TTY_POLICY", "mksquashfs"):
            self.assertNotIn(reste, self.s, reste)

    def test_helper_une_seule_forme_de_payload(self):
        bloc = texte_fichier_livre("pincabos-install-payload")  # PINCABOS_INSTALLEUR_FICHIERS_V1
        self.assertIn("PINCABOS_LIVE_SQUASHFS_V1", bloc)  # contrat lu par le banc (681) et iso-live.sh
        self.assertIn('[ -f "$LIVE_SQUASHFS" ] || { echo "ERROR: live squashfs missing', bloc)
        self.assertIn('unsquashfs -f -d "$TARGET" "$LIVE_SQUASHFS"', bloc)
        self.assertNotIn("tar.zst.part-", bloc)
        self.assertNotIn("sha256sum -c pincabos-rootfs-cab-v8.1g.parts.sha256", bloc)

    def test_live_utilise_le_payload_et_iso_live(self):
        self.assertIn('tar --zstd -xpf "$ARCHIVE" -C "$LIVE_ROOTFS" --numeric-owner', self.s)
        self.assertIn('ROOTFS_DIR="$LIVE_ROOTFS"', self.s)
        self.assertIn('bash "$LIVE_SH" --rootfs "$ROOTFS_DIR" --payload "$PAYLOAD_FULL" --out "$OUT_ISO"', self.s)
        # les montages du chroot (section 12) sont defaits avant iso-live.sh, qui monte les siens
        bloc = self.s[self.s.index('echo "=== 14L)'):self.s.index('bash "$LIVE_SH"')]
        self.assertIn("cleanup_mounts", bloc)

    def test_syntaxe_bash(self):
        import subprocess
        for f in ("opt/pincabos/script/iso.sh", "opt/pincabos/script/iso-live.sh"):
            r = subprocess.run(["bash", "-n", str(Path(RACINE) / f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f + " : " + r.stderr)

    def test_iso_live_installe_les_outils_manquants(self):
        l = (Path(RACINE) / "opt/pincabos/script/iso-live.sh").read_text(encoding="utf-8")
        for outil in ("grub-efi-amd64-bin", "grub-pc-bin", "xorriso", "mtools", "casper"):
            self.assertIn(outil, l)


class FichiersVivants(unittest.TestCase):
    """PINCABOS_KEEP_PATHS_V2 : ce qui est propre au cab survit a la mise a jour."""

    def test_liste_de_conservation(self):
        s = texte_installateur()
        bloc = s.split("PCO_KEEP_PATHS=(")[1].split("\n)\n")[0]   # une parenthese dans un commentaire ne ferme pas le tableau
        for p in ("opt/pincabos/config/screens", "home/pinball/.config/vpinfe/vpinfe.ini",
                  "home/pinball/.local/share/VPinballX/10.8/directoutputconfig", "home/pinball/.config/pincabos",
                  "opt/pincabos/config/dof", "opt/pincabos/config/zedmd.json", "opt/pincabos/config/splash.json",
                  "opt/pincabos/flags", "etc/netplan", "etc/ssh", "etc/machine-id", "var/lib/NetworkManager"):
            self.assertIn(f'"{p}"', bloc, p)
        self.assertNotIn('"opt/pincabos/config/version.json"', bloc)   # la version, elle, doit changer


class LienVpx(unittest.TestCase):
    """PINCABOS_VPX_LINK_V1 : le lien vpx existe sur la cible et a l execution
    (sous /opt/pinball depuis PINCABOS_RUNTIMES_OPT_V1)."""

    def test_cible_et_filet(self):
        s = texte_installateur()
        self.assertIn("ensure_target_vpx_link() {", s)
        self.assertLess(s.index("  ensure_target_vpx_link\n"), s.index("  apply_target_identity\n"))
        self.assertIn('local h="$TARGET/opt/pinball"', s)
        self.assertIn('ln -sfn "$(basename "$plus_recent")" "$h/vpx"', s)
        self.assertIn('bash "$migrateur" --racine "$TARGET" --uid 1000 --gid 1000', s)
        self.assertIn('test -x "$TARGET/opt/pinball/vpinfe/vpinfe"', s)
        p = Path(RACINE, "opt/pincabos/tools/pincabos-paths.sh").read_text(encoding="utf-8")
        self.assertIn("PINCABOS_VPX_LINK_V1", p)
        self.assertIn('ln -sfn "$(basename "$_pco_vpx_dir")" "$PCO_VPX_LINK"', p)



class RepertoireTemporaire(unittest.TestCase):
    """PR #156 (Karots) : un vieux worktree de PR sous /opt/pincabos/tmp contenait
    un VPinballX.ini avec des noms de cartes audio ; la garde audio refusait
    l'ISO. Le repertoire est exclu du payload ET refuse par la validation des
    fichiers transitoires, directement dans iso.sh (plus besoin du helper)."""

    def test_tmp_exclu_du_payload_et_garde(self):
        s = _texte()
        self.assertIn("--exclude='./opt/pincabos/tmp' \\", s)
        self.assertIn("--exclude='./opt/pincabos/tmp/*' \\", s)
        self.assertIn("tmp(/|$)", s)
        self.assertIn('echo "OK: /opt/pincabos/tmp excluded"', s)

    def test_la_regex_transitoire_refuse_tmp(self):
        m = re.search(r"grep -E -q \\\n'(\^\\\./opt/pincabos/[^']+)'", _texte())
        self.assertIsNotNone(m, "regex de validation transitoire introuvable")
        motif = re.compile(m.group(1))
        self.assertTrue(motif.search("./opt/pincabos/tmp/pr43/worktree/home/pinball/.local/share/VPinballX/10.8/VPinballX.ini"))
        self.assertTrue(motif.search("./opt/pincabos/tmp"))
        self.assertFalse(motif.search("./opt/pincabos/tools/pincabos-vps"))


class FichiersLivres(unittest.TestCase):
    """PINCABOS_INSTALLEUR_FICHIERS_V1 : moteur, helper, attente et unite tty sont des fichiers, installes par iso.sh."""

    def test_iso_installe_les_fichiers_et_ne_les_ecrit_plus(self):
        # PINCABOS_ISO_ETAPES_V1 : iso.sh orchestre, les sections sont des etapes (texte_installateur les lit)
        s = texte_installateur()
        for delim in ("PINCBOS_PAYLOAD_HELPER", "PINCBOS_LIVE_INSTALLER", "PINCABOS_LIVE_WAIT", "PINCBOS_SERVICE"):
            self.assertNotIn(delim, s, delim)
        self.assertIn('INSTALLER_SRC="${PCO_ISO_SCRIPT_DIR:-$(dirname "$(readlink -f "$0")")}/installer"', s)
        for f, dest in (("pincabos-install-payload", '"$PAYLOAD_FULL/pincabos-v8.1g-install-cab-payload-to-target.sh"'),
                        ("pincabos-live-installer", '"$ROOTFS_DIR/usr/local/sbin/pincabos-live-installer"'),
                        ("pincabos-live-installer-wait", '"$ROOTFS_DIR/usr/local/sbin/pincabos-live-installer-wait"'),
                        ("pincabos-live-installer-tty.service", '"$ROOTFS_DIR/etc/systemd/system/pincabos-live-installer-tty.service"')):
            self.assertIn(f'"$INSTALLER_SRC/{f}" {dest}', s, f)
            self.assertTrue(os.path.exists(os.path.join(RACINE, "opt/pincabos/script/installer", f)), f)

    def test_fichiers_livres_executables_et_syntaxe(self):
        import subprocess
        for f in ("pincabos-install-payload", "pincabos-live-installer", "pincabos-live-installer-wait"):
            chemin = os.path.join(RACINE, "opt/pincabos/script/installer", f)
            self.assertTrue(os.access(chemin, os.X_OK), f)
            self.assertEqual(subprocess.run(["bash", "-n", chemin], capture_output=True, text=True).returncode, 0, f)
        moteur = texte_fichier_livre("pincabos-live-installer")
        self.assertIn("upgrade_install()", moteur)  # contrats lus par le banc (683)
        self.assertIn("PCO_KEEP_PATHS", moteur)
        helper = texte_fichier_livre("pincabos-install-payload")
        self.assertIn("PINCABOS_LIVE_SQUASHFS_V1", helper)
        self.assertNotIn("-no-progress", helper)
        self.assertIn("ExecStart=/usr/local/sbin/pincabos-installer-dispatch", texte_fichier_livre("pincabos-live-installer-tty.service"))


class OutilsCible(unittest.TestCase):
    """PINCABOS_OUTILS_CIBLE_V1 : les blocs Python que le helper appliquait a la cible sont des outils livres."""
    OUTILS = ("pincabos-cible-audio-privacy.py", "pincabos-cible-screen-privacy.py", "pincabos-cible-vpinfe-ini-purge.py",
              "pincabos-cible-dashboard-helper-patch.py", "pincabos-cible-systemd-units.py")

    def test_outils_presents_et_valides(self):
        import py_compile
        for nom in self.OUTILS:
            chemin = os.path.join(RACINE, "opt/pincabos/tools/cible", nom)
            self.assertTrue(os.path.exists(chemin), nom)
            py_compile.compile(chemin, doraise=True)

    def test_le_helper_les_appelle_depuis_la_cible(self):
        helper = texte_fichier_livre("pincabos-install-payload")
        self.assertIn("pco_outil_cible() {", helper)
        self.assertIn('for d in "$TARGET/opt/pincabos/tools/cible" /opt/pincabos/tools/cible; do', helper)
        for nom in self.OUTILS:
            self.assertEqual(helper.count(f'python3 "$(pco_outil_cible {nom})"'), 1, nom)
        for delim in ("PINCABOS_TARGET_AUDIO_PRIVACY_PY", "PINCABOS_SCREEN_PRIVACY_PY", "PINCABOS_VPINFE_INI_PURGE",
                      "PINCABOS_DASHBOARD_HELPER_PATCH", "PINCABOS_REWRITE_SYSTEMD_UNITS"):
            self.assertNotIn(delim, helper, delim)
        # plus aucun bloc Python dans le helper (le script sanitize vient du depot, PINCABOS_CIBLE_FICHIERS_DU_DEPOT_V1)
        self.assertEqual(helper.count("python3 - "), 0)

    def test_les_outils_gardent_leurs_arguments(self):
        helper = texte_fichier_livre("pincabos-install-payload")
        self.assertIn('python3 "$(pco_outil_cible pincabos-cible-systemd-units.py)" "$TARGET"', helper)
        self.assertIn('python3 "$(pco_outil_cible pincabos-cible-vpinfe-ini-purge.py)" "$TARGET/home/pinball/.config/vpinfe/vpinfe.ini"', helper)
        self.assertIn('python3 "$(pco_outil_cible pincabos-cible-dashboard-helper-patch.py)" "$TARGET/usr/local/sbin/pincabos-dashboard-admin"', helper)


class FichiersDuDepotSurLaCible(unittest.TestCase):
    """PINCABOS_CIBLE_FICHIERS_DU_DEPOT_V1 : le helper ne reecrit plus ce que le squashfs porte deja."""

    def test_un_seul_fichier_encore_ecrit_par_le_helper(self):
        helper = texte_fichier_livre("pincabos-install-payload")
        ecrits = re.findall(r'cat\s*>\s*"\$TARGET/([^"]+)"', helper)
        self.assertEqual(ecrits, ["etc/ssh/sshd_config.d/00-pincabos-security.conf"])

    def test_la_garde_verifie_les_fichiers_du_depot(self):
        from _charge import FICHIERS_CIBLE
        helper = texte_fichier_livre("pincabos-install-payload")
        self.assertIn("PINCABOS_CIBLE_FICHIERS_DU_DEPOT_V1", helper)
        for rel in FICHIERS_CIBLE:
            self.assertIn(f'  "{rel}"', helper, rel)
            self.assertTrue(os.path.exists(os.path.join(RACINE, rel)), rel)
        self.assertIn('echo "ERROR: fichier attendu absent de la cible extraite: $pco_attendu"', helper)
        self.assertIn("exit 78", helper)

    def test_le_depot_porte_les_versions_les_plus_recentes(self):
        lire = lambda rel: open(os.path.join(RACINE, rel), encoding="utf-8").read()
        reseau = lire("usr/local/sbin/pincabos-firstboot-network-webapp-fix")
        self.assertIn("PINCABOS_INSTALLEUR_RESEAU_V1", reseau)   # venait du heredoc (fix(network) 17/08)
        self.assertIn("PINCABOS_NETPLAN_SANITIZE_V1", reseau)
        self.assertIn("PINCABOS_PROFILE_GC_ASYNC_V1", lire("usr/local/libexec/pincabos/pincabos-vpinfe-prestart-guard"))  # perf(demarrage) 05/09
        dropin = lire("etc/systemd/system/pincabos-vpinfe.service.d/90-pincabos-iso-start.conf")
        self.assertIn("display-manager.service network.target pincabos-screen-topology-boot.service", dropin)
        self.assertIn("PermitRootLogin no", lire("etc/ssh/sshd_config.d/00-pincabos-security.conf"))

    def test_le_drop_in_iso_start_survit_au_retrait_des_drop_ins_herites(self):
        # le helper retire les anciens drop-ins VPinFE (screen|display|topology|xrandr|iso-start) ; le courant est garde
        helper = texte_fichier_livre("pincabos-install-payload")
        i = helper.index('if [ "$dropin_name" = "90-pincabos-iso-start.conf" ]; then')
        self.assertLess(i, helper.index('=~ (screen|display|topology|xrandr|iso-start)'))
        self.assertIn("continue", helper[i:i + 120])
