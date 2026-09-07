from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from webapp_patch import MARKER, patch_text  # noqa: E402


FIXTURE = '''from pathlib import Path\n\ndef pcx_roots():\n    return {\n        "Tables": Path("/tables"),\n        "Exports": Path("/home/pinball/Exports"),\n        "Imports": Path("/home/pinball/Downloads"),\n        "Home Pinball": Path("/home/pinball"),\n        "Logs": Path("/opt/pincabos/logs"),\n        "Backups": Path("/opt/pincabos/backups"),\n        "Medias": Path("/opt/pincabos/media"),\n        "PinCabShare": Path("/home/pinball/Share"),\n        "Stockage USB": Path("/mnt/pincab-usb"),\n        "Lecteurs SMB": Path("/home/pinball/NetworkDrives"),\n    }\n\ndef pcx_resolve(root_name, rel_path=""):\n    return root_name\n\ndef page():\n    roots = pcx_roots()\n    root_name = "Tables"\n    sidebar = ""\n    for name in roots:\n        cls = "pcx-root active" if name == root_name else "pcx-root"\n        icon = "📁"\n        if name == "Tables":\n            icon = "🎮"\n        elif name == "PinCabShare":\n            icon = "📌"\n        elif "USB" in name or "Clés" in name:\n            icon = "🔌"\n        elif "SMB" in name:\n            icon = "🌐"\n        sidebar += name + icon\n'''


class WebAppPatchTests(unittest.TestCase):
    def test_patch_keeps_pincabshare_on_smb(self):
        patched, changed = patch_text(FIXTURE)
        self.assertTrue(changed)
        self.assertIn(
            '"PinCabShare": Path("/home/pinball/Share")',
            patched,
        )
        self.assertNotIn(
            '"PinCabShare": Path("/home/pinball/PinCabShare")',
            patched,
        )

    def test_patch_adds_dynamic_pincab_links_menu(self):
        patched, _changed = patch_text(FIXTURE)
        self.assertIn(MARKER, patched)
        self.assertIn("def pcx_pincab_links():", patched)
        self.assertIn("🔗 PinCab Links", patched)
        self.assertIn('elif name in pincab_link_names:', patched)

    def test_patch_is_idempotent(self):
        once, changed_once = patch_text(FIXTURE)
        twice, changed_twice = patch_text(once)
        self.assertTrue(changed_once)
        self.assertFalse(changed_twice)
        self.assertEqual(once, twice)

    def test_repairs_old_dynamic_mapping_even_if_marker_exists(self):
        old = FIXTURE.replace(
            '"PinCabShare": Path("/home/pinball/Share")',
            '"PinCabShare": Path("/home/pinball/PinCabShare")',
        )
        patched, changed = patch_text(old)
        self.assertTrue(changed)
        self.assertIn(
            '"PinCabShare": Path("/home/pinball/Share")',
            patched,
        )


if __name__ == "__main__":
    unittest.main()
