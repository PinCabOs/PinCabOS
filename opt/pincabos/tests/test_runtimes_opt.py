"""PINCABOS_RUNTIMES_OPT_V1 : VPX et VPinFE vivent sous /opt/pinball.

Jusqu'en 4.40 les runtimes tiers etaient dans le compte du joueur, meles a
ses tables et a ses reglages. Ils vivent sous /opt/pinball ; le compte garde
deux liens de compatibilite (~/vpx, ~/vpinfe). Un cabinet installe avant est
migre par pincabos-runtimes-opt (un rename, aucune copie) au demarrage,
avant VPinFE et la WebApp.
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from _charge import charger, RACINE

R = Path(RACINE)
pp = charger("opt/pincabos/tools/pincabos_paths.py", "pco_paths_runtimes")
MIGRATEUR = R / "usr/local/sbin/pincabos-runtimes-opt"


class Chemins(unittest.TestCase):
    def test_defauts_sous_opt_pinball(self):
        d = pp.defaults("pinball")
        self.assertEqual(d["runtimes"], "/opt/pinball")
        self.assertEqual(d["vpx_link"], "/opt/pinball/vpx")
        self.assertEqual(d["vpx_bin"], "/opt/pinball/vpx/VPinballX_BGFX")
        self.assertEqual(d["vpx_plugins"], "/opt/pinball/vpx/plugins")
        self.assertEqual(d["vpinfe_dir"], "/opt/pinball/vpinfe")
        self.assertEqual(d["vpinfe_bin"], "/opt/pinball/vpinfe/vpinfe")
        self.assertEqual(d["vpinfe_dmdutil"], "/opt/pinball/vpinfe/_internal/third-party/libdmdutil")
        # les liens de compatibilite du compte, pour la migration et le doctor
        self.assertEqual(d["vpx_link_home"], "/home/pinball/vpx")
        self.assertEqual(d["vpinfe_dir_home"], "/home/pinball/vpinfe")
        # le reste du compte du joueur ne bouge pas
        self.assertEqual(d["vpx_pref"], "/home/pinball/.pincabos/vpx")
        self.assertEqual(d["vpinfe_ini"], "/home/pinball/.config/vpinfe/vpinfe.ini")
        self.assertEqual(d["tables"], "/home/pinball/Tables")

    def test_cabinet_pas_encore_migre(self):
        """Mise a jour appliquee, redemarrage pas encore fait : les chemins restent vrais."""
        presents = {"/home/pinball/vpx/VPinballX_BGFX", "/home/pinball/vpinfe/vpinfe"}
        v = pp.compat_home(pp.defaults("pinball"), exists=presents.__contains__)
        self.assertEqual(v["vpx_bin"], "/home/pinball/vpx/VPinballX_BGFX")
        self.assertEqual(v["vpx_plugins"], "/home/pinball/vpx/plugins")
        self.assertEqual(v["vpinfe_dir"], "/home/pinball/vpinfe")
        self.assertEqual(v["vpinfe_bin"], "/home/pinball/vpinfe/vpinfe")
        self.assertEqual(v["vpinfe_dmdutil"], "/home/pinball/vpinfe/_internal/third-party/libdmdutil")
        self.assertEqual(v["runtimes"], "/opt/pinball", "la destination, elle, ne change pas")

    def test_cabinet_migre_ou_neuf(self):
        presents = {"/opt/pinball/vpx/VPinballX_BGFX", "/opt/pinball/vpinfe/vpinfe",
                    "/home/pinball/vpx/VPinballX_BGFX", "/home/pinball/vpinfe/vpinfe"}   # liens de compatibilite
        v = pp.compat_home(pp.defaults("pinball"), exists=presents.__contains__)
        self.assertEqual(v["vpx_bin"], "/opt/pinball/vpx/VPinballX_BGFX")
        self.assertEqual(v["vpinfe_dir"], "/opt/pinball/vpinfe")
        # image nue, rien nulle part : la destination
        v = pp.compat_home(pp.defaults("pinball"), exists=lambda p: False)
        self.assertEqual(v["vpinfe_dir"], "/opt/pinball/vpinfe")

    def test_exports_shell(self):
        out = pp.shell_exports(pp.defaults("pinball"))
        for var in ("PCO_RUNTIMES=/opt/pinball", "PCO_VPX_LINK=/opt/pinball/vpx", "PCO_VPINFE_BIN=/opt/pinball/vpinfe/vpinfe",
                    "PCO_VPX_LINK_HOME=/home/pinball/vpx", "PCO_VPINFE_DIR_HOME=/home/pinball/vpinfe"):
            self.assertIn(f"export {var}\n", out)

    def test_secours_shell_sans_python(self):
        """Le bloc de secours de pincabos-paths.sh dit la meme chose que Python, VPINFE_BIN compris
        (run-vpinfe-systemd.sh n'a que lui)."""
        s = (R / "opt/pincabos/tools/pincabos-paths.sh").read_text(encoding="utf-8")
        for morceau in ("PCO_RUNTIMES=/opt/pinball", "PCO_VPX_BIN=/opt/pinball/vpx/VPinballX_BGFX", "PCO_VPX_PLUGINS=/opt/pinball/vpx/plugins",
                        "PCO_VPINFE_DIR=/opt/pinball/vpinfe", "PCO_VPINFE_BIN=/opt/pinball/vpinfe/vpinfe",
                        'PCO_VPX_LINK="$PCO_VPX_LINK_HOME"', 'PCO_VPINFE_BIN="$PCO_VPINFE_DIR_HOME/vpinfe"'):
            self.assertIn(morceau, s)
        self.assertEqual(subprocess.run(["bash", "-n", str(R / "opt/pincabos/tools/pincabos-paths.sh")]).returncode, 0)


def _peupler_ancien(racine: Path, bundle="VPinballX_BGFX-10.8.1-5436-af26b2d93-linux-x64"):
    h = racine / "home/pinball"
    (h / bundle / "plugins/dof").mkdir(parents=True)
    (h / bundle / "VPinballX_BGFX").write_text("vpx")
    (h / bundle / "plugins/dof/libdof.so").write_text("dof")
    os.symlink(bundle, h / "vpx")
    (h / "vpinfe/_internal").mkdir(parents=True)
    (h / "vpinfe/vpinfe").write_text("fe")
    (h / "Tables").mkdir()
    (h / ".config/vpinfe").mkdir(parents=True)
    (h / ".config/vpinfe/vpinfe.ini").write_text("[Settings]\n")
    return h


def _etat(racine: Path):
    lignes = []
    for p in sorted(racine.rglob("*")):
        rel = p.relative_to(racine)
        lignes.append(f"{rel} -> {os.readlink(p)}" if p.is_symlink() else f"{rel}{'/' if p.is_dir() else ''}")
    return lignes


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uid, self.gid = str(os.getuid()), str(os.getgid())

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def migrer(self, *args):
        return subprocess.run(["bash", str(MIGRATEUR), "--racine", str(self.tmp), "--uid", self.uid, "--gid", self.gid, *args],
                              capture_output=True, text=True)

    def test_syntaxe_et_aide(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(MIGRATEUR)]).returncode, 0)
        self.assertTrue(os.access(MIGRATEUR, os.X_OK))
        r = subprocess.run(["bash", str(MIGRATEUR), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0); self.assertIn("--racine", r.stdout)

    def test_cabinet_installe_avant(self):
        bundle = "VPinballX_BGFX-10.8.1-5436-af26b2d93-linux-x64"
        h = _peupler_ancien(self.tmp, bundle)
        r = self.migrer()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.tmp / "opt/pinball"
        # les runtimes ont bouge, tels quels
        self.assertTrue((d / bundle / "VPinballX_BGFX").is_file())
        self.assertTrue((d / bundle / "plugins/dof/libdof.so").is_file())
        self.assertTrue((d / "vpinfe/vpinfe").is_file()); self.assertTrue((d / "vpinfe/_internal").is_dir())
        self.assertFalse((h / bundle).exists(), "plus de bundle dans le compte")
        # le lien stable vit a cote des bundles, relatif (le lien du compte le disait deja)
        self.assertEqual(os.readlink(d / "vpx"), bundle)
        # le compte garde deux liens de compatibilite, absolus vers /opt/pinball
        self.assertEqual(os.readlink(h / "vpx"), "/opt/pinball/vpx")
        self.assertEqual(os.readlink(h / "vpinfe"), "/opt/pinball/vpinfe")
        for lien in (d / "vpx", h / "vpx", h / "vpinfe"):
            self.assertEqual(os.lstat(lien).st_uid, int(self.uid), f"le lien {lien} appartient au joueur (lchown, pas chown -h)")
        # le reste du compte n'a pas bouge
        self.assertTrue((h / "Tables").is_dir()); self.assertTrue((h / ".config/vpinfe/vpinfe.ini").is_file())
        self.assertIn("VPX " + bundle + " -> /opt/pinball", r.stdout); self.assertIn("VPinFE -> /opt/pinball/vpinfe", r.stdout)
        # idempotent : une seconde passe ne touche a rien
        avant = _etat(self.tmp)
        r2 = self.migrer()
        self.assertEqual(r2.returncode, 0); self.assertIn("rien a faire", r2.stdout); self.assertEqual(_etat(self.tmp), avant)

    def test_a_blanc(self):
        _peupler_ancien(self.tmp)
        avant = _etat(self.tmp)
        r = self.migrer("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("+ mv", r.stdout)
        self.assertEqual(_etat(self.tmp), avant, "a blanc : rien ne bouge")

    def test_installation_neuve(self):
        """Image faite par la recette : deja sous /opt/pinball, liens du compte poses."""
        bundle = "VPinballX_BGFX-1-linux-x64"
        d = self.tmp / "opt/pinball"; h = self.tmp / "home/pinball"
        (d / bundle).mkdir(parents=True); (d / bundle / "VPinballX_BGFX").write_text("vpx")
        os.symlink(bundle, d / "vpx"); (d / "vpinfe").mkdir(); (d / "vpinfe/vpinfe").write_text("fe")
        h.mkdir(parents=True); os.symlink("/opt/pinball/vpx", h / "vpx"); os.symlink("/opt/pinball/vpinfe", h / "vpinfe")
        avant = _etat(self.tmp)
        r = self.migrer()
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("rien a faire", r.stdout); self.assertEqual(_etat(self.tmp), avant)

    def test_liens_du_compte_absents(self):
        """Runtimes sous /opt/pinball mais compte sans liens (payload ancien recette) : les liens sont poses, lien vpx choisi."""
        d = self.tmp / "opt/pinball"; h = self.tmp / "home/pinball"
        for b in ("VPinballX_BGFX-10.8.1-5231-x-linux-x64", "VPinballX_BGFX-10.8.1-5436-y-linux-x64"):
            (d / b).mkdir(parents=True); (d / b / "VPinballX_BGFX").write_text("vpx")
        (d / "vpinfe").mkdir(); (d / "vpinfe/vpinfe").write_text("fe"); h.mkdir(parents=True)
        r = self.migrer()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(d / "vpx"), "VPinballX_BGFX-10.8.1-5436-y-linux-x64", "le plus recent")
        self.assertEqual(os.readlink(h / "vpx"), "/opt/pinball/vpx"); self.assertEqual(os.readlink(h / "vpinfe"), "/opt/pinball/vpinfe")

    def test_doublon_ecarte(self):
        """Le compte a encore une copie alors que /opt/pinball a deja la sienne : on ecarte, on n'ecrase pas."""
        h = _peupler_ancien(self.tmp)
        d = self.tmp / "opt/pinball"; (d / "vpinfe").mkdir(parents=True); (d / "vpinfe/vpinfe").write_text("neuf")
        r = self.migrer()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((d / "vpinfe/vpinfe").read_text(), "neuf")
        self.assertTrue((h / "vpinfe.avant-opt/vpinfe").is_file(), "la copie du compte ecartee, pas detruite")
        self.assertEqual(os.readlink(h / "vpinfe"), "/opt/pinball/vpinfe")

    def test_sans_compte(self):
        r = self.migrer()
        self.assertEqual(r.returncode, 0); self.assertIn("rien a faire", r.stdout)
        self.assertFalse((self.tmp / "opt/pinball").exists())


class Demarrage(unittest.TestCase):
    """L'unite migre avant VPinFE et la WebApp, a chaque demarrage et au redemarrage des services par l'OTA."""

    def test_unite_et_activation(self):
        u = (R / "etc/systemd/system/pincabos-runtimes-opt.service").read_text(encoding="utf-8")
        self.assertIn("Before=pincabos-vpinfe.service pincabos-webapp.service", u)
        self.assertIn("ExecStart=/usr/local/sbin/pincabos-runtimes-opt", u)
        self.assertIn("Type=oneshot", u); self.assertIn("RemainAfterExit=yes", u)
        for w in ("multi-user.target.wants", "pincabos-vpinfe.service.wants", "pincabos-webapp.service.wants"):
            lien = R / "etc/systemd/system" / w / "pincabos-runtimes-opt.service"
            self.assertTrue(lien.is_symlink(), lien); self.assertTrue(lien.resolve().is_file(), lien)

    def test_perimetre_ota(self):
        import sys
        sys.path.insert(0, str(R / "opt/pincabos/update"))
        import pincabos_updates as up
        for rel in ("usr/local/sbin/pincabos-runtimes-opt", "etc/systemd/system/pincabos-runtimes-opt.service",
                    "etc/systemd/system/multi-user.target.wants/pincabos-runtimes-opt.service",
                    "etc/systemd/system/pincabos-vpinfe.service.wants/pincabos-runtimes-opt.service",
                    "etc/systemd/system/pincabos-webapp.service.wants/pincabos-runtimes-opt.service",
                    "opt/pincabos/tools/pincabos_paths.py", "usr/local/libexec/pincabos/doctor.d/70-vpinfe.sh"):
            self.assertTrue(up.allowed(rel), rel)

    def test_doctor(self):
        s = (R / "usr/local/libexec/pincabos/doctor.d/70-vpinfe.sh").read_text(encoding="utf-8")
        self.assertIn('runtime="$PCO_VPINFE_DIR"', s)
        self.assertIn("pco_repairing && ! pco_partie_en_cours", s, "jamais de migration pendant une partie")
        s = (R / "usr/local/libexec/pincabos/doctor.d/80-vpx.sh").read_text(encoding="utf-8")
        self.assertIn('"$PCO_VPX_BIN"', s)


# Ce qui peut encore nommer l'ancien emplacement : la source de verite (et son secours
# shell), la migration, ce qui parle du compte du joueur comme tel.
TOLERES = {
    "opt/pincabos/tools/pincabos_paths.py", "opt/pincabos/tools/pincabos-paths.sh", "usr/local/sbin/pincabos-runtimes-opt",
    "opt/pincabos/config/github-rootfs-exclude.txt", "opt/pincabos/tools/pincabos-gitpush-root.sh",
    "opt/pincabos/install/02-install-engine.sh",   # installateur historique, hors perimetre OTA
    "opt/pincabos/script/installer/pincabos-install-payload",   # payload d'un cabinet pas encore migre
}
MOTIF = re.compile(r"/home/pinball/(vpx|vpinfe|VPinballX)(?![\w.-]*\.(pre|avant))")


class PlusAucunCheminDuCompte(unittest.TestCase):
    """Le code livre ne nomme plus /home/pinball/{vpx,vpinfe,VPinballX_BGFX-*} : il passe par
    pincabos_paths (ou /opt/pinball). Sinon la migration laisserait des orphelins."""

    def test_code_livre(self):
        fautifs = []
        for dossier in ("opt/pincabos", "usr/local", "etc"):
            for racine, dirs, fichiers in os.walk(R / dossier):
                dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".venv", "node_modules", "DEV")]
                for nom in fichiers:
                    p = Path(racine) / nom
                    rel = str(p.relative_to(R))
                    if rel in TOLERES or p.is_symlink() or p.suffix in (".json", ".md", ".txt", ".png", ".jpg", ".log", ".pdf", ".ini"):
                        continue
                    try:
                        data = p.read_bytes()
                    except OSError:
                        continue
                    if b"\0" in data[:4096]:
                        continue
                    for num, ligne in enumerate(data.decode("utf-8", "ignore").splitlines(), 1):
                        if ligne.lstrip().startswith("#"):
                            continue
                        if MOTIF.search(ligne):
                            fautifs.append(f"{rel}:{num}: {ligne.strip()[:100]}")
        self.assertEqual(fautifs, [])


class Recette(unittest.TestCase):
    def test_iso_et_installateur(self):
        s = (R / "opt/pincabos/script/iso/60-validation-payload.sh").read_text(encoding="utf-8")
        self.assertIn("'^\\./(opt|home)/pinball/vpinfe/'", s)
        s = (R / "opt/pincabos/script/iso/40-payload.sh").read_text(encoding="utf-8")
        self.assertIn("--exclude='./home/pinball/*.avant-opt*'", s)
        s = (R / "opt/pincabos/script/installer/pincabos-install-payload").read_text(encoding="utf-8")
        self.assertIn('"$TARGET/opt/pinball/vpinfe" "$TARGET/home/pinball/vpinfe"', s)
        for f in ("opt/pincabos/script/iso/40-payload.sh", "opt/pincabos/script/iso/60-validation-payload.sh",
                  "opt/pincabos/script/installer/pincabos-install-payload", "opt/pincabos/script/installer/pincabos-live-installer",
                  "usr/local/libexec/pincabos/doctor.d/70-vpinfe.sh", "usr/local/libexec/pincabos/doctor.d/80-vpx.sh",
                  "usr/local/sbin/pincabos-sample-tables", "usr/local/sbin/pincabos-b2s-dmd-runtime-repair",
                  "usr/local/sbin/pincabos-firstboot-vpinfe-packaged-runtime-fix", "usr/local/libexec/pincabos/vpinfe-dof-library-bridge.sh",
                  "opt/pincabos/scripts/VPXlauncher.pincabos-original.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", str(R / f)], capture_output=True).returncode, 0, f)

    def test_depot_ignore_les_runtimes(self):
        for f in (".gitignore", "opt/pincabos/config/github-rootfs-exclude.txt"):
            self.assertIn("/opt/pinball/\n", (R / f).read_text(encoding="utf-8"), f)


if __name__ == "__main__":
    unittest.main()
