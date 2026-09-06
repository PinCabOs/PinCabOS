"""Recette d'image : composants tiers depuis les releases amont (PINCABOS_IMAGE_RECETTE_V1)."""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from _charge import RACINE

R = Path(RACINE)
sys.path.insert(0, str(R / "image"))
import fetch_components as fc  # noqa: E402


class Composants(unittest.TestCase):
    def test_fichier_epingle(self):
        d = fc.charger()
        self.assertEqual(set(d["components"]), {"vpx", "vpinfe", "libdof"})
        for nom in ("vpx", "vpinfe"):
            c = d["components"][nom]
            self.assertEqual(c["kind"], "bundle")
            self.assertRegex(c["url"], r"^https://github\.com/[\w.-]+/[\w.-]+/releases/download/[^/]+/[^/]+$")
            self.assertRegex(c["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(c["archive"], c["url"].rsplit("/", 1)[1])
            self.assertTrue(c["install"].startswith("opt/pinball/"), "PINCABOS_RUNTIMES_OPT_V1")
        vpx = d["components"]["vpx"]
        self.assertIn("5436", vpx["url"]); self.assertIn("5436", vpx["install"])
        # variante slim : l archive complete embarque un Chromium de 633 Mo inutile (ISO +160 Mo, rootfs +660 Mo)
        self.assertTrue(d["components"]["vpinfe"]["archive"].endswith("-linux-x64-slim.zip"))
        self.assertEqual(vpx["links"]["opt/pinball/vpx"], Path(vpx["install"]).name, "/opt/pinball/vpx pointe sur le bundle epingle")
        self.assertEqual(vpx["links"]["home/pinball/vpx"], "/opt/pinball/vpx", "lien de compatibilite du compte")
        self.assertEqual(d["components"]["vpinfe"]["links"]["home/pinball/vpinfe"], "/opt/pinball/vpinfe")
        self.assertEqual(d.get("runtimes_dir"), "opt/pinball")

    def test_libdof_canonique_du_depot(self):
        c = fc.charger()["components"]["libdof"]
        src = R / c["source"]
        self.assertTrue(src.is_file(), src)
        self.assertEqual(hashlib.md5(src.read_bytes()).hexdigest(), c["md5"], "le libdof canonique a change : mettre components.json a jour")
        vpx = fc.charger()["components"]["vpx"]["install"]
        for cible in c["copies"]:
            self.assertTrue(cible.startswith(vpx + "/plugins/dof/"), cible)
        for lien in c["links"]:
            self.assertTrue(lien.startswith("opt/pinball/vpinfe/_internal/libdof"), lien)

    def test_hors_perimetre_ota(self):
        sys.path.insert(0, str(R / "opt/pincabos/update"))
        import pincabos_updates as up
        self.assertFalse(up.allowed("image/fetch_components.py"))
        self.assertFalse(up.allowed("image/components.json"))


def _tar_vpx(chemin: Path):
    with tarfile.open(chemin, "w:gz") as t:
        for nom, data, mode in (("./VPinballX_BGFX", b"#!/bin/sh\necho vpx\n", 0o755), ("./plugins/dof/libdof.so.0.4.7", b"vendored", 0o644),
                                ("./plugins/dof/libdof.so", b"vendored", 0o644), ("./libSDL3.so", b"x", 0o644)):
            info = tarfile.TarInfo(nom); info.size = len(data); info.mode = mode
            t.addfile(info, io.BytesIO(data))


def _zip_vpinfe(chemin: Path):
    with zipfile.ZipFile(chemin, "w") as z:
        for nom, data, mode in (("vpinfe/vpinfe", b"#!/bin/sh\necho fe\n", 0o755), ("vpinfe/_internal/libdof.so.0.4.7", b"vendored", 0o644),
                                ("vpinfe/_internal/base_library.zip", b"z", 0o644)):
            info = zipfile.ZipInfo(nom); info.external_attr = (mode | 0o100000) << 16
            z.writestr(info, data)


class Pose(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cache = self.tmp / "cache"; self.cache.mkdir()
        self.rootfs = self.tmp / "rootfs"; (self.rootfs / "home/pinball").mkdir(parents=True)
        self.depot = self.tmp / "depot"
        (self.depot / "opt/pincabos/overlays/libdof-canonical").mkdir(parents=True)
        (self.depot / "opt/pincabos/overlays/libdof-canonical/libdof.so.0.4.7").write_bytes(b"patche")
        vpx_tar = self.tmp / "vpx.tar.gz"; _tar_vpx(vpx_tar)
        fe_zip = self.tmp / "fe.zip"; _zip_vpinfe(fe_zip)
        self.archives = {"https://x/vpx.tar.gz": vpx_tar, "https://x/fe.zip": fe_zip}
        self.comp = {"schema": "pincabos.image-components/v1", "components": {
            "vpx": {"kind": "bundle", "name": "vpx", "url": "https://x/vpx.tar.gz", "archive": "vpx.tar.gz", "sha256": fc.sha256_de(vpx_tar),
                    "install": "opt/pinball/VPinballX_BGFX-1-linux-x64", "check": "VPinballX_BGFX", "links": {"opt/pinball/vpx": "VPinballX_BGFX-1-linux-x64", "home/pinball/vpx": "/opt/pinball/vpx"}},
            "vpinfe": {"kind": "bundle", "name": "fe", "url": "https://x/fe.zip", "archive": "fe.zip", "sha256": fc.sha256_de(fe_zip),
                       "install": "opt/pinball/vpinfe", "check": "vpinfe", "links": {"home/pinball/vpinfe": "/opt/pinball/vpinfe"}},
            "libdof": {"kind": "repo-file", "name": "libdof", "source": "opt/pincabos/overlays/libdof-canonical/libdof.so.0.4.7",
                       "md5": hashlib.md5(b"patche").hexdigest(),
                       "copies": ["opt/pinball/VPinballX_BGFX-1-linux-x64/plugins/dof/libdof.so.0.4.7", "opt/pinball/VPinballX_BGFX-1-linux-x64/plugins/dof/libdof.so"],
                       "links": {"opt/pinball/vpinfe/_internal/libdof.so.0.4.7": "/opt/pincabos/overlays/vpinfe-dof-ledwiz-hidraw-stable/libdof.so.0.4.7"}}}}
        self.appels = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fetch(self, url, dest):
        self.appels.append(url); shutil.copy(self.archives[url], dest)

    def test_pose_complete(self):
        j = fc.appliquer(self.rootfs, self.cache, composants=self.comp, depot=self.depot, fetch=self.fetch)
        self.assertFalse(any(l.startswith("NOGO") for l in j), j)
        h = self.rootfs / "opt/pinball"
        self.assertTrue((h / "VPinballX_BGFX-1-linux-x64/VPinballX_BGFX").is_file(), "archive VPX aplatie (racine ./)")
        self.assertEqual(os.readlink(self.rootfs / "home/pinball/vpx"), "/opt/pinball/vpx", "compatibilite du compte")
        self.assertEqual(os.readlink(self.rootfs / "home/pinball/vpinfe"), "/opt/pinball/vpinfe")
        self.assertTrue(os.access(h / "VPinballX_BGFX-1-linux-x64/VPinballX_BGFX", os.X_OK))
        self.assertEqual(os.readlink(h / "vpx"), "VPinballX_BGFX-1-linux-x64")
        self.assertTrue((h / "vpinfe/vpinfe").is_file(), "dossier racine unique du zip aplati")
        self.assertTrue(os.access(h / "vpinfe/vpinfe", os.X_OK), "bit executable restaure depuis le zip")
        self.assertEqual((h / "VPinballX_BGFX-1-linux-x64/plugins/dof/libdof.so.0.4.7").read_bytes(), b"patche", "libdof vendored remplace")
        self.assertEqual((h / "VPinballX_BGFX-1-linux-x64/plugins/dof/libdof.so").read_bytes(), b"patche")
        self.assertEqual(os.readlink(h / "vpinfe/_internal/libdof.so.0.4.7"), "/opt/pincabos/overlays/vpinfe-dof-ledwiz-hidraw-stable/libdof.so.0.4.7")
        self.assertEqual(len(self.appels), 2)
        # seconde passe : cache verifie, rien retelecharge
        j2 = fc.appliquer(self.rootfs, self.cache, composants=self.comp, depot=self.depot, fetch=self.fetch)
        self.assertEqual(len(self.appels), 2, "archives en cache, somme verifiee")
        self.assertTrue(any("en cache" in l for l in j2), j2)

    def test_somme_inattendue_bloque_le_composant(self):
        self.comp["components"]["vpx"]["sha256"] = "0" * 64
        j = fc.appliquer(self.rootfs, self.cache, composants=self.comp, depot=self.depot, fetch=self.fetch)
        self.assertTrue(any(l.startswith("NOGO: vpx") and "somme inattendue" in l for l in j), j)
        self.assertFalse((self.cache / "vpx.tar.gz").exists(), "archive refusee non gardee")
        self.assertTrue((self.rootfs / "opt/pinball/vpinfe/vpinfe").is_file(), "les autres composants passent quand meme")

    def test_libdof_change_dans_le_depot(self):
        (self.depot / "opt/pincabos/overlays/libdof-canonical/libdof.so.0.4.7").write_bytes(b"autre")
        j = fc.appliquer(self.rootfs, self.cache, only=["libdof"], composants=self.comp, depot=self.depot, fetch=self.fetch)
        self.assertTrue(any("NOGO" in l and "md5" in l for l in j), j)

    def test_a_blanc(self):
        j = fc.appliquer(self.rootfs, self.cache, dry_run=True, composants=self.comp, depot=self.depot, fetch=self.fetch)
        self.assertEqual(self.appels, [])
        self.assertFalse((self.rootfs / "opt/pinball/vpinfe").exists())
        self.assertTrue(all(not l.startswith("NOGO") for l in j), j)


if __name__ == "__main__":
    unittest.main()
