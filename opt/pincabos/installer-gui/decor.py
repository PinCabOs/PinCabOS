#!/usr/bin/env python3
"""Fonds d'écran des dalles secondaires pendant l'installation (PINCABOS_INSTALLEUR_DECOR_V1, Yann).

Une fois la disposition appliquée, chaque dalle qui n'est pas le playfield
(backglass, full DMD, topper, dalles non attribuées) reçoit un visuel de la
galerie de démarrage (Miss Tilt en vedette), plein écran, sous le kiosque et
sans jamais prendre le focus (règles « pincabos-decor-N » du kiosk-rc.xml).
Le programme reste jusqu'à ce qu'on le tue (nouvelle application, redémarrage).

  python3 decor.py --monitors '{"DP-0": "/opt/pincabos/media/splash/paysage2.jpg"}'
"""
import argparse
import json
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

TITRE = "pincabos-decor-{n}"     # repris tel quel par kiosk-rc.xml (calque en dessous, jamais le focus)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitors", default="{}", help="JSON {connecteur: chemin d image}")
    args = ap.parse_args()
    images = json.loads(args.monitors or "{}")
    app = Gtk.Application(application_id="org.pincabos.installer.decor")

    def on_activate(app):
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background-color: #050007; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        mons = Gdk.Display.get_default().get_monitors()
        poses = 0
        for i in range(mons.get_n_items()):
            mon = mons.get_item(i)
            chemin = images.get(mon.get_connector() or "")
            if not chemin:
                continue
            win = Gtk.ApplicationWindow(application=app)
            win.set_decorated(False)
            win.set_title(TITRE.format(n=i + 1))
            pic = Gtk.Picture.new_for_filename(chemin)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            win.set_child(pic)
            win.present()
            win.fullscreen_on_monitor(mon)
            poses += 1
        if poses == 0:
            print("aucune dalle a habiller", file=sys.stderr)
            app.quit()

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    main()
