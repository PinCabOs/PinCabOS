#!/usr/bin/env python3
"""Patch idempotent PinCab Explorer pour PinCab Links.

Conserve ``PinCabShare`` comme raccourci SMB historique vers
``/home/pinball/Share`` et ajoute, sous l'en-tête ``PinCab Links``, des
raccourcis dynamiques vers les CAB réellement exposés par PinCabShare V2 dans
``/home/pinball/PinCabShare``.

Le patch ne touche ni VPX, BGFX, VPinFE ni le moteur Multiplayer.
"""
from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_COMMANDER = Path("/opt/pincabos/web/pincabos_webapp_commander.py")
MARKER = "# PINCABOS_PINCAB_LINKS_MENU_V1"


def patch_text(text: str) -> tuple[str, bool]:
    changed = False

    # PinCabShare reste le partage SMB historique.
    wrong_mapping = '"PinCabShare": Path("/home/pinball/PinCabShare")'
    smb_mapping = '"PinCabShare": Path("/home/pinball/Share")'
    if wrong_mapping in text:
        text = text.replace(wrong_mapping, smb_mapping)
        changed = True

    if MARKER in text:
        return text, changed

    roots_start = text.find("def pcx_roots():")
    roots_end = text.find("\n\ndef pcx_resolve", roots_start)
    if roots_start < 0 or roots_end < 0:
        raise RuntimeError("fonction pcx_roots introuvable")

    new_roots = '''# PINCABOS_PINCAB_LINKS_MENU_V1\ndef pcx_pincab_links():\n    """Retourne les CAB dynamiques actuellement exposés par PinCabShare V2."""\n\n    view = Path("/home/pinball/PinCabShare")\n    local_data = Path("/srv/pincabshare/data")\n    remote_mounts = Path("/run/pincabshare-v2/mounts")\n    links = {}\n\n    try:\n        entries = sorted(view.iterdir(), key=lambda item: item.name.lower())\n    except Exception:\n        return links\n\n    for item in entries:\n        if not item.is_symlink():\n            continue\n\n        label = str(item.name).strip()\n        upper = label.upper()\n        cab_pos = upper.rfind("CAB")\n        if cab_pos < 0 or not upper[cab_pos + 3:].strip().isdigit():\n            continue\n\n        try:\n            raw_target = item.readlink()\n        except OSError:\n            continue\n\n        target = raw_target if raw_target.is_absolute() else item.parent / raw_target\n\n        is_local = target == local_data\n        is_remote = (\n            target.parent == remote_mounts\n            and target.name.startswith("CAB")\n            and target.name[3:].isdigit()\n        )\n\n        if not (is_local or is_remote):\n            continue\n\n        # La racine dynamique pointe directement vers le chemin autorisé.\n        # pcx_resolve conserve ensuite sa protection anti-évasion habituelle.\n        links[label] = target\n\n    return links\n\n\ndef pcx_roots():\n    roots = {\n        "Tables": pincabos_vpx_tables_dir(),\n        "Exports": Path("/home/pinball/Exports"),\n        "Imports": Path("/home/pinball/Downloads"),\n        "Home Pinball": Path("/home/pinball"),\n        "Logs": Path("/opt/pincabos/logs"),\n        "Backups": Path("/opt/pincabos/backups"),\n        "Medias": Path("/opt/pincabos/media"),\n\n        # PinCabShare reste le partage SMB historique.\n        "PinCabShare": Path("/home/pinball/Share"),\n    }\n\n    # Les CAB du Lobby apparaissent directement comme raccourcis dans le menu.\n    roots.update(pcx_pincab_links())\n\n    roots.update({\n        "Stockage USB": Path("/mnt/pincab-usb"),\n        "Lecteurs SMB": Path("/home/pinball/NetworkDrives"),\n    })\n\n    return roots\n'''

    text = text[:roots_start] + new_roots + text[roots_end:]

    sidebar_anchor = '''    sidebar = ""\n    for name in roots:\n'''
    sidebar_replacement = '''    sidebar = ""\n    pincab_link_names = set(pcx_pincab_links())\n    pincab_links_heading_added = False\n\n    for name in roots:\n        if name in pincab_link_names and not pincab_links_heading_added:\n            sidebar += (\n                '<div class="pcx-pincab-links-title" style="'\n                'margin:16px 4px 7px;'\n                'color:#ff8a1f;'\n                'font-weight:800;'\n                'font-size:.78rem;'\n                'letter-spacing:.04em;'\n                'text-transform:uppercase;'\n                '">🔗 PinCab Links</div>'\n            )\n            pincab_links_heading_added = True\n'''
    if sidebar_anchor not in text:
        raise RuntimeError("ancre sidebar introuvable")
    text = text.replace(sidebar_anchor, sidebar_replacement, 1)

    icon_anchor = '''        elif name == "PinCabShare":\n            icon = "📌"\n'''
    icon_replacement = '''        elif name in pincab_link_names:\n            icon = "🔗"\n        elif name == "PinCabShare":\n            icon = "📌"\n'''
    if icon_anchor not in text:
        raise RuntimeError("ancre icône PinCabShare introuvable")
    text = text.replace(icon_anchor, icon_replacement, 1)

    return text, True


def patch_file(path: Path, *, check_only: bool = False) -> bool:
    original = path.read_text(encoding="utf-8")
    patched, changed = patch_text(original)

    if check_only:
        return changed

    if changed:
        path.write_text(patched, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=str(DEFAULT_COMMANDER))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.is_file():
        raise SystemExit(f"NOGO [WEBAPP] fichier absent: {path}")

    try:
        changed = patch_file(path, check_only=args.check)
    except Exception as exc:
        raise SystemExit(f"NOGO [WEBAPP] {exc}") from exc

    if args.check:
        print("GO [WEBAPP] patch applicable" if changed else "GO [WEBAPP] déjà conforme")
    elif changed:
        print("GO [WEBAPP] PinCabShare=SMB; PinCab Links dynamiques installés")
    else:
        print("GO [WEBAPP] déjà conforme")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
