#!/usr/bin/env python3
"""Nettoyage fail-closed des auto-liens PinCabShare sans arrêter Samba."""
from pincabshare import close_intercab


if __name__ == "__main__":
    close_intercab("service_stopped")
