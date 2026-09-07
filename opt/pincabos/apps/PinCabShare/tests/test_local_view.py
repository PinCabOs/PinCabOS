import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODULE = ROOT / "pincabshare.py"
spec = importlib.util.spec_from_file_location("pincabshare_local_view_test", MODULE)
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)


class LocalViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_data = p.DATA_PATH
        self.old_view = p.VIEW_PATH
        self.old_runtime = p.RUNTIME_PATH
        self.old_mounts = p.MOUNTS_PATH

        p.DATA_PATH = root / "data"
        p.VIEW_PATH = root / "view"
        p.RUNTIME_PATH = root / "run"
        p.MOUNTS_PATH = p.RUNTIME_PATH / "mounts"
        p.DATA_PATH.mkdir()
        p.VIEW_PATH.mkdir()
        p.MOUNTS_PATH.mkdir(parents=True)

    def tearDown(self):
        p.DATA_PATH = self.old_data
        p.VIEW_PATH = self.old_view
        p.RUNTIME_PATH = self.old_runtime
        p.MOUNTS_PATH = self.old_mounts
        self.tmp.cleanup()

    def test_real_directory_is_never_deleted_on_name_collision(self):
        occupied = p.VIEW_PATH / "Ultimate PinCabOS — CAB1"
        occupied.mkdir()
        result = p._ensure_link("Ultimate PinCabOS — CAB1", p.DATA_PATH)
        self.assertFalse(result)
        self.assertTrue(occupied.is_dir())
        self.assertFalse(occupied.is_symlink())

    def test_managed_local_and_remote_links_are_removed(self):
        local = p.VIEW_PATH / "Ultimate PinCabOS — CAB1"
        remote_target = p.MOUNTS_PATH / "CAB10"
        remote_target.mkdir()
        remote = p.VIEW_PATH / "VMCABOS — CAB10"
        unmanaged_target = Path(self.tmp.name) / "elsewhere"
        unmanaged_target.mkdir()
        unmanaged = p.VIEW_PATH / "Keep Me"

        local.symlink_to(p.DATA_PATH, target_is_directory=True)
        remote.symlink_to(remote_target, target_is_directory=True)
        unmanaged.symlink_to(unmanaged_target, target_is_directory=True)

        p._remove_managed_links()

        self.assertFalse(local.exists())
        self.assertFalse(remote.exists())
        self.assertTrue(unmanaged.is_symlink())

    def test_label_is_sanitized(self):
        self.assertEqual(
            p._safe_label("VMCABOS / Test\n— CAB10"),
            "VMCABOS _ Test_— CAB10",
        )


if __name__ == "__main__":
    unittest.main()
