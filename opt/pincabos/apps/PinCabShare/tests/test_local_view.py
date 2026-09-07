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
        p.DATA_PATH = root / "data"
        p.VIEW_PATH = root / "view"
        p.DATA_PATH.mkdir()
        p.VIEW_PATH.mkdir()

    def tearDown(self):
        p.DATA_PATH = self.old_data
        p.VIEW_PATH = self.old_view
        self.tmp.cleanup()

    def gate(self, label):
        return p.Gate(
            session_id="mp-1",
            room_code="ABC123",
            nonce="a" * 64,
            local_cabinet_id=1,
            local_label=label,
            members=(),
            expires_at=9999999999,
        )

    def test_rename_replaces_old_local_symlink(self):
        p.ensure_local_view(self.gate("Old Name — CAB1"))
        old_link = p.VIEW_PATH / "Old Name — CAB1"
        self.assertTrue(old_link.is_symlink())

        p.ensure_local_view(self.gate("Ultimate PinCabOS — CAB1"))
        new_link = p.VIEW_PATH / "Ultimate PinCabOS — CAB1"

        self.assertFalse(old_link.exists())
        self.assertTrue(new_link.is_symlink())
        self.assertEqual(new_link.resolve(), p.DATA_PATH.resolve())

    def test_real_directory_is_never_deleted_on_name_collision(self):
        occupied = p.VIEW_PATH / "Ultimate PinCabOS — CAB1"
        occupied.mkdir()

        result = p._ensure_link("Ultimate PinCabOS — CAB1", p.DATA_PATH)

        self.assertFalse(result)
        self.assertTrue(occupied.is_dir())
        self.assertFalse(occupied.is_symlink())


if __name__ == "__main__":
    unittest.main()
