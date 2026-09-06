# PinCabOS WebApp module: Audio / SSF V2, ALSA, PipeWire and SSF Commander.
# Generated from the monolithic app.py refactor.
# The host app injects legacy shared helpers during register().
from __future__ import annotations

import glob
try:
    import pincabos_ini
except ImportError:   # hors /opt (tests, depot) : le module vit a cote des outils
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "tools"))
    import pincabos_ini
import html
import json
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from flask import jsonify, redirect, request, send_file, session, url_for

from pincabos_webapp_core import (
    PINCABOS_VPINFE_INI,
    esc,
    pincabos_backup_config_file,
    pincabos_vpinfe_ini_path,
    pincabos_vpx_ini_path,
    pincabos_write_json_with_meta,
    shlex_quote,
)
from pincabos_webapp_gabarit import page

# Chemins audio (repris d'app.py)
AUDIO_VPX_INI = pincabos_vpx_ini_path()


AUDIO_VPINFE_INI = pincabos_vpinfe_ini_path()


AUDIO_BACKUP_DIR = Path("/opt/pincabos/backups/audio-ssf")

ROUTES: list[tuple[str, dict, object]] = []
BEFORE_REQUESTS: list[object] = []
AFTER_REQUESTS: list[object] = []

def route(rule: str, **options):
    """Record a Flask route locally; register() attaches it to the host app."""
    def decorator(func):
        ROUTES.append((rule, options, func))
        return func
    return decorator

def before_request(func):
    BEFORE_REQUESTS.append(func)
    return func

def after_request(func):
    AFTER_REQUESTS.append(func)
    return func

def register(host_app, runtime_globals=None):
    """Enregistre les routes et crochets du module. Autonome : ses dépendances sont importées en tête
    (PINCABOS_WEBAPP_AUTONOMIE_V1) ; `runtime_globals` n'est plus lu."""
    for before_func in BEFORE_REQUESTS:
        host_app.before_request(before_func)
    for after_func in AFTER_REQUESTS:
        host_app.after_request(after_func)
    for rule, options, view_func in ROUTES:
        host_app.add_url_rule(rule, endpoint=view_func.__name__, view_func=view_func, **options)



AUDIO_ROUTER_CONFIG = Path("/opt/pincabos/config/audio-router.json")


AUDIO_ROUTER_DEFAULT_CONFIG = {
    "audio_mode": "dual",
    "audio_backend": "alsa",
    "backbox_device": "",
    "playfield_device": "",
    "surround_device": "",
    "bass_device": "",
    "ssf_mode": "7.1",
    "invert_lr": False,
    "invert_front_rear": False,
    "enable_bass": True,
    "night_mode": False
}


def audio_run_cmd(cmd, timeout=5):
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return (r.stdout or "").strip()
    except Exception as e:
        return str(e)


def audio_load_config():
    cfg = AUDIO_ROUTER_DEFAULT_CONFIG.copy()

    if not AUDIO_ROUTER_CONFIG.exists():
        return cfg

    try:
        data = json.loads(AUDIO_ROUTER_CONFIG.read_text(errors="replace"))
        if isinstance(data, dict):
            cfg.update(data)
    except Exception:
        pass

    return cfg


def audio_save_config(cfg):
    pincabos_backup_config_file(AUDIO_ROUTER_CONFIG, "Audio / SSF V2 Save")
    pincabos_write_json_with_meta(AUDIO_ROUTER_CONFIG, cfg, "Audio / SSF V2 Save")


def audio_detect_alsa_devices():
    """
    Détection ALSA robuste pour PinCabOS.

    Supporte Ubuntu en anglais et en français:
      - anglais  : card X: NAME [LONG], device Y: DEV [LONGDEV]
      - français : carte X : NAME [LONG], périphérique Y : DEV [LONGDEV]

    Important:
    On force LC_ALL=C pour essayer d'obtenir une sortie anglaise stable.
    Si Ubuntu retourne quand même une sortie française, le regex FR la supporte.
    """
    devices = []
    output = audio_run_cmd("LC_ALL=C aplay -l 2>/dev/null || aplay -l 2>/dev/null || true")

    rx = re.compile(
        r"^(?:card|carte)\s+(\d+)\s*:\s*"
        r"(.+?)\s+\[(.+?)\]\s*,\s*"
        r"(?:device|périphérique|peripherique)\s+(\d+)\s*:\s*"
        r"(.+?)\s+\[(.+?)\]",
        re.IGNORECASE
    )

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = rx.match(line)
        if not m:
            continue

        card_num = m.group(1).strip()
        card_short = m.group(2).strip()
        card_name = m.group(3).strip()
        device_num = m.group(4).strip()
        device_short = m.group(5).strip()
        device_name = m.group(6).strip()

        devices.append({
            "id": f"hw:{card_num},{device_num}",
            "card": card_num,
            "device": device_num,
            "name": f"{card_name} / {device_name}",
            "description": f"{card_short} / {device_short}",
        })

    return devices, output


def audio_device_options(selected):
    devices, _raw = audio_detect_alsa_devices()
    rows = ['<option value="">Non configuré</option>']

    # PINCABOS_AUDIO_WAV_PIPEWIRE_V1
    # Les sorties PipeWire d'abord : ce sont les seules qui portent le
    # multicanal, et les seules jouables sans se heurter a la carte occupee.
    for sortie in audio_pipewire_sinks():
        valeur = f'pw:{sortie["name"]}'
        canaux = int(sortie.get("channels", 2) or 2)
        libelle = f'{sortie.get("description") or sortie["name"]} — {canaux} canaux — PipeWire'
        sel = "selected" if selected == valeur else ""
        rows.append(f'<option value="{esc(valeur)}" {sel}>{esc(libelle)}</option>')

    for dev in devices:
        dev_id = dev["id"]
        label = f'{dev["name"]} — {dev_id}'
        sel = "selected" if selected == dev_id else ""
        rows.append(f'<option value="{esc(dev_id)}" {sel}>{esc(label)}</option>')

    return "\n".join(rows)


def audio_bool_checked(cfg, key):
    return "checked" if cfg.get(key) else ""


def audio_selected(cfg, key, value):
    return "selected" if cfg.get(key) == value else ""


# PINCABOS_AUDIO_SSF_VPX_ROUTING_V2
PINCABOS_VPX_AUDIO_INI = Path(
    "/home/pinball/.local/share/VPinballX/10.8/VPinballX.ini"
)


def _pco_vpx_audio_values():
    path = str(PINCABOS_VPX_AUDIO_INI)

    return {
        key: (
            audio_ini_read_key(
                path,
                "Player",
                key,
            )
            or ""
        ).strip()
        for key in (
            "SoundDeviceBG",
            "SoundDevice",
            "Sound3D",
            "PlayMusic",
            "PlaySound",
            "MusicVolume",
            "SoundVolume",
        )
    }


def _pco_vpx_detect_output_names():
    import os as _os
    import subprocess as _subprocess

    values = _pco_vpx_audio_values()

    found = []
    seen = set()

    def add(value):
        value = str(value or "").strip()

        if (
            not value
            or "\n" in value
            or "\r" in value
        ):
            return

        folded = value.casefold()

        if folded in seen:
            return

        seen.add(folded)
        found.append(value)

    # Les valeurs déjà inscrites dans VPinballX.ini
    # restent toujours sélectionnables.
    add(values.get("SoundDeviceBG"))
    add(values.get("SoundDevice"))

    env = _os.environ.copy()

    env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    env["DBUS_SESSION_BUS_ADDRESS"] = (
        "unix:path=/run/user/1000/bus"
    )

    try:
        result = _subprocess.run(
            [
                "/usr/bin/pactl",
                "list",
                "sinks",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            env=env,
        )

        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()

            if line.startswith("Description:"):
                add(line.split(":", 1)[1])

    except Exception:
        pass

    return found


def _pco_vpx_device_options(selected):
    selected = str(selected or "").strip()
    devices = _pco_vpx_detect_output_names()

    if selected and selected not in devices:
        devices.insert(0, selected)

    rows = [
        '<option value=""'
        + (" selected" if not selected else "")
        + ">Périphérique par défaut de VPX</option>"
    ]

    for device in devices:
        rows.append(
            f'<option value="{esc(device)}"'
            f'{" selected" if device == selected else ""}>'
            f'{esc(device)}</option>'
        )

    return "".join(rows)


def _pco_vpx_sound3d_options(selected):
    selected = str(selected or "0").strip()

    if selected not in {"0", "1", "2", "3", "4", "5"}:
        selected = "0"

    # PINCABOS_SOUND3D_LABELS_V1
    # Intitules repris de VPinball : les modes 4 et 5 sont des modes a SIX
    # canaux, pas du 7.1. Les annoncer en 7.1 fait passer un fonctionnement
    # normal pour une panne.
    modes = (
        (
            "0",
            "2 canaux — avant",
        ),
        (
            "1",
            "2 canaux — arrière",
        ),
        (
            "2",
            "Jusqu'à 6 canaux — arrière au lockbar",
        ),
        (
            "3",
            "Jusqu'à 6 canaux — avant au lockbar",
        ),
        (
            "4",
            "6 canaux — latéral et arrière au lockbar, mixage historique",
        ),
        (
            "5",
            "6 canaux — latéral et arrière au lockbar, nouveau mixage",
        ),
    )

    return "".join(
        f'<option value="{value}"'
        f'{" selected" if value == selected else ""}>'
        f'{esc(label)} — Sound3D={value}</option>'
        for value, label in modes
    )


def _pco_vpx_mode_from_sound3d(value):
    value = str(value or "0").strip()

    if value in {"2", "3"}:
        return "5.1"

    if value in {"4", "5"}:
        return "7.1"

    return "individual"


def _pco_vpx_validate_device(value):
    value = str(value or "").strip()

    if "\n" in value or "\r" in value:
        raise ValueError(
            "Nom de périphérique audio invalide."
        )

    if len(value) > 240:
        raise ValueError(
            "Nom de périphérique audio trop long."
        )

    available = set(
        _pco_vpx_detect_output_names()
    )

    if value and value not in available:
        raise ValueError(
            "Périphérique VPX/PipeWire non détecté : "
            + value
        )

    return value


def _pco_vpx_validate_sound3d(value):
    value = str(value or "0").strip()

    if value not in {"0", "1", "2", "3", "4", "5"}:
        raise ValueError(
            "Valeur [Player] Sound3D invalide : "
            + value
        )

    return value


def _pco_vpx_write_audio(
    backglass,
    playfield,
    sound3d,
):
    import os as _os

    path = PINCABOS_VPX_AUDIO_INI

    if not path.is_file():
        raise FileNotFoundError(
            f"VPinballX.ini absent : {path}"
        )

    backglass = _pco_vpx_validate_device(
        backglass
    )

    playfield = _pco_vpx_validate_device(
        playfield
    )

    sound3d = _pco_vpx_validate_sound3d(
        sound3d
    )

    backup = audio_backup_file(path)

    if backup is None:
        raise RuntimeError(
            "Sauvegarde de VPinballX.ini impossible."
        )

    lines = audio_read_lines(path)

    lines = audio_set_ini_key_with_comment(
        lines,
        "Player",
        "SoundDeviceBG",
        backglass,
        "Audio SSF VPX Routing V2",
    )

    lines = audio_set_ini_key_with_comment(
        lines,
        "Player",
        "SoundDevice",
        playfield,
        "Audio SSF VPX Routing V2",
    )

    lines = audio_set_ini_key_with_comment(
        lines,
        "Player",
        "Sound3D",
        sound3d,
        "Audio SSF VPX Routing V2",
    )

    audio_write_lines(path, lines)

    try:
        _os.chown(path, 1000, 1000)
        _os.chmod(path, 0o644)
    except OSError:
        pass

    expected = {
        "SoundDeviceBG": backglass,
        "SoundDevice": playfield,
        "Sound3D": sound3d,
    }

    for key, wanted in expected.items():
        actual = (
            audio_ini_read_key(
                str(path),
                "Player",
                key,
            )
            or ""
        ).strip()

        if actual != wanted:
            raise RuntimeError(
                f"Validation {key} échouée : "
                f"attendu={wanted!r}, "
                f"obtenu={actual!r}"
            )

    return [
        f"Backup VPX : {backup}",
        (
            "[Player] SoundDeviceBG = "
            + (backglass or "(défaut VPX)")
        ),
        (
            "[Player] SoundDevice = "
            + (playfield or "(défaut VPX)")
        ),
        f"[Player] Sound3D = {sound3d}",
    ]


def audio_config_rows():
    cfg = audio_load_config()
    values = _pco_vpx_audio_values()

    backglass = values.get(
        "SoundDeviceBG",
        "",
    )

    playfield = values.get(
        "SoundDevice",
        "",
    )

    sound3d = values.get(
        "Sound3D",
        "0",
    )

    legacy_rows = []

    # PINCABOS_AUDIO_DEAD_ROWS_V1
    # Les cles d'un routage audio anterieur ne sont plus affichees : rien ne
    # les lit, et posees au milieu des vrais reglages elles se lisaient comme
    # des reglages. « Mode nuit », elle, a de vrais consommateurs.
    for label, key in (
        (
            "Mode nuit",
            "night_mode",
        ),
    ):
        legacy_rows.append(
            f"<tr><td>{esc(label)}</td>"
            f"<td><code>"
            f"{esc(cfg.get(key, '-'))}"
            f"</code></td></tr>"
        )

    return f"""
<tr>
  <td>
    <strong>Backglass / ROM / musique</strong><br>
    <small>
      <code>[Player] SoundDeviceBG</code>
    </small>
  </td>
  <td>
    <select
      name="backbox_device"
      style="width:100%;max-width:720px;padding:8px;"
    >
      {_pco_vpx_device_options(backglass)}
    </select>
  </td>
</tr>

<tr>
  <td>
    <strong>Underplayfield / SoundFX / SSF</strong><br>
    <small>
      <code>[Player] SoundDevice</code>
    </small>
  </td>
  <td>
    <select
      name="playfield_device"
      style="width:100%;max-width:720px;padding:8px;"
    >
      {_pco_vpx_device_options(playfield)}
    </select>
  </td>
</tr>

<tr>
  <td>
    <strong>Mode de sortie VPX</strong><br>
    <small>
      <code>[Player] Sound3D</code>
    </small>
  </td>
  <td>
    <select
      name="sound3d"
      style="width:100%;max-width:720px;padding:8px;"
    >
      {_pco_vpx_sound3d_options(sound3d)}
    </select>
  </td>
</tr>

{''.join(legacy_rows)}
"""

def audio_test_device(device_id, channels=2):
    if not device_id:
        return

    cmd = f"speaker-test -D {shlex_quote(device_id)} -c {int(channels)} -t wav -l 1"
    subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def audio_backup_file(src):
    if not src.exists():
        return None

    AUDIO_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = AUDIO_BACKUP_DIR / f"{src.name}.backup-{stamp}"
    shutil.copy2(src, dst)
    return dst


def audio_comment(function_name):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"; Modifié {stamp} par PinCabOS fonction({function_name})"


def audio_read_lines(path):
    if path.exists():
        return path.read_text(errors="replace").splitlines()
    return []


def audio_write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n")


def audio_find_section(lines, section):
    # PINCABOS_INI_UNIQUE_V1 : bornes de section par l ecrivain unique
    return pincabos_ini.Ini("\n".join(lines)).bornes(section)


def audio_set_ini_key_with_comment(lines, section, key, value, function_name):
    """
    Modifie une clé INI en conservant la structure existante.
    Ajoute toujours un commentaire timestamp juste au-dessus de la clé modifiée.
    """
    comment = audio_comment(function_name)
    start, end = audio_find_section(lines, section)

    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(comment)
        lines.append(f"[{section}]")
        lines.append(f"{key} = {value}")
        return lines

    key_lower = key.lower()
    key_index = None

    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue

        if "=" in stripped:
            existing_key = stripped.split("=", 1)[0].strip().lower()
            if existing_key == key_lower:
                key_index = i
                break

    if key_index is not None:
        # Retire uniquement l'ancien commentaire PinCabOS directement au-dessus,
        # pour éviter d'empiler 50 timestamps sur la même clé.
        if key_index > 0 and "par PinCabOS fonction(" in lines[key_index - 1]:
            lines[key_index - 1] = comment
        else:
            lines.insert(key_index, comment)
            key_index += 1

        lines[key_index] = f"{key} = {value}"
        return lines

    # Clé absente : ajoute en fin de section.
    insert_at = end
    lines.insert(insert_at, comment)
    lines.insert(insert_at + 1, f"{key} = {value}")
    return lines


def audio_set_pincabos_section(lines, section, values, function_name):
    """
    Section de suivi PinCabOS.
    Toutes les lignes écrites ont un commentaire timestamp avant le bloc.
    """
    comment = audio_comment(function_name)
    start, end = audio_find_section(lines, section)

    block = [comment, f"[{section}]"]
    for key, value in values.items():
        block.append(f"{key} = {value}")

    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block)
        return lines

    # Remplace seulement la section PinCabOS dédiée.
    return lines[:start] + block + lines[end:]


def audio_vpx_sound3d_value(ssf_mode):
    """
    VPX possède Sound3D dans [Player].
    On garde une logique prudente :
    - off / 2.1 = 0
    - 4.1 / 5.1 / 7.1 = 1
    """
    ssf_mode = str(ssf_mode or "").strip().lower()
    if ssf_mode in ["4.1", "5.1", "7.1"]:
        return "1"
    return "0"


def audio_apply_to_vpx_vpinfe():
    """
    Application audio safe.

    Important:
      - on ne force plus SoundDevice/SoundDeviceBG/MusicDevice/Sound3DDevice avec hw:X,Y,
        car VPX semble utiliser des IDs numériques dans [Player].
      - on garde audio-router.json comme source UI PinCabOS.
      - on applique seulement VPinFE [Settings] muteaudio=false.
      - aucune section PinCabOS.Audio n'est créée.
    """
    results = []

    vpinfe_ini = AUDIO_VPINFE_INI
    vpinfe_home_ini = PINCABOS_VPINFE_INI

    def set_ini_key_native(lines, section, key, value):
        # PINCABOS_INI_UNIQUE_V1 : delegue a l ecrivain INI unique.
        # PINCABOS_INI_APLATI_V1 (cab de Yann, 06/09/2026 : « no tables found »)
        # audio_read_lines() rend des lignes SANS fin de ligne (splitlines) : les
        # coller avec "" ecrasait tout le fichier sur une seule ligne, ou plus
        # aucune section n'etait reconnue. VPinFE, ne sachant plus le lire, le
        # reecrivait avec ses valeurs par defaut : tablerootdir vide, plus une
        # seule table. Meme convention des deux cotes : sans fin de ligne.
        ini = pincabos_ini.Ini("\n".join(lines))
        ini.poser(section, key, value)
        return list(ini.lignes)

    results.append("VPX: SoundDevice/SoundDeviceBG/MusicDevice/Sound3DDevice non modifiés automatiquement.")
    results.append("Raison: VPX semble utiliser des IDs numériques dans [Player], pas hw:X,Y ALSA.")

    for ini in [vpinfe_ini, vpinfe_home_ini]:
        try:
            if not ini.exists():
                results.append(f"VPinFE absent: {ini}")
                continue

            audio_backup_file(ini)
            lines = audio_read_lines(ini)
            lines = set_ini_key_native(lines, "Settings", "muteaudio", "false")
            audio_write_lines(ini, lines)
            subprocess.run(["/bin/chown", "pinball:pinball", str(ini)], timeout=5)
            results.append(f"VPinFE [Settings] muteaudio = false dans {ini}")
        except Exception as e:
            results.append(f"ERREUR VPinFE native audio {ini}: {e}")

    try:
        log_path = Path("/opt/pincabos/logs/audio-ssf-apply.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(results) + "\n", encoding="utf-8")
    except Exception:
        pass

    return results


def pincabos_safe_audio_alsa_card():
    try:
        return audio_alsa_test_card()
    except Exception as e:
        return f"""
<div class="card pco-audio-compact-card">
  <h2>Test des haut-parleurs</h2>
  <p class="warn">Sorties audio indisponibles : {esc(str(e))}</p>
</div>
"""


# PINCABOS_AUDIO_TEST_PIPEWIRE_V1
PINCABOS_SESSION_USER = "pinball"
PINCABOS_SESSION_UID = "1000"


def audio_session_prefix():
    """Prefixe de commande pour parler a la session audio de la seance.

    PINCABOS_AUDIO_SESSION_PREFIX_V1

    La webapp tourne deja sous le compte de la session : lui faire appeler
    runuser revient a lui demander un privilege qu'elle n'a pas, et l'appel
    echoue sans bruit. On ne bascule d'utilisateur que depuis root, cas des
    appels lances par un service systeme.
    """
    import os as _os

    environnement = [
        "/usr/bin/env",
        f"XDG_RUNTIME_DIR=/run/user/{PINCABOS_SESSION_UID}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{PINCABOS_SESSION_UID}/bus",
    ]

    if _os.geteuid() == 0:
        return ["/usr/sbin/runuser", "-u", PINCABOS_SESSION_USER, "--"] + environnement

    return environnement


def audio_pipewire_sinks():
    """Sorties vues par PipeWire : nom interne, libelle et nombre de canaux."""
    import subprocess as _sp

    try:
        brut = _sp.run(
            audio_session_prefix() + ["/usr/bin/pactl", "list", "sinks"],
            capture_output=True, text=True, timeout=8, check=False,
        ).stdout
    except Exception:
        return []

    sorties = []
    courant = {}
    for ligne in brut.splitlines():
        depouillee = ligne.strip()
        if depouillee.startswith("Name:"):
            if courant.get("name"):
                sorties.append(courant)
            courant = {"name": depouillee.split(":", 1)[1].strip()}
        elif depouillee.startswith("Description:") and courant:
            courant["description"] = depouillee.split(":", 1)[1].strip()
        elif depouillee.startswith("Sample Specification:") and courant:
            m = re.search(r"(\d+)ch", depouillee)
            courant["channels"] = int(m.group(1)) if m else 2
        elif depouillee.startswith("alsa.card ") and courant:
            # PINCABOS_AUDIO_CARD_MATCH_V2 — de quelle carte ALSA vient ce sink.
            m = re.search(r"(\d+)", depouillee)
            if m:
                courant["carte"] = int(m.group(1))
        elif depouillee.startswith("Channel Map:") and courant:
            # PINCABOS_AUDIO_PER_SPEAKER_V1 — l'ordre des canaux d'un 7.1
            # n'est pas universel : on prend celui que la sortie declare.
            courant["map"] = [
                p.strip() for p in depouillee.split(":", 1)[1].split(",") if p.strip()
            ]
    if courant.get("name"):
        sorties.append(courant)

    return [x for x in sorties if x.get("name")]



# PINCABOS_AUDIO_PER_SPEAKER_V1
PINCABOS_POSITIONS = {
    "front-left": "Avant gauche",
    "front-right": "Avant droit",
    "front-center": "Centre",
    "lfe": "Caisson (LFE)",
    "rear-left": "Arrière gauche",
    "rear-right": "Arrière droit",
    "side-left": "Latéral gauche",
    "side-right": "Latéral droit",
    "rear-center": "Arrière centre",
    "mono": "Mono",
}


def audio_nom_position(code):
    return PINCABOS_POSITIONS.get(str(code or "").strip(), str(code or "?"))


# PINCABOS_AUDIO_VOIX_V1
PINCABOS_VOIX_RACINE = Path("/opt/pincabos/media/audio-voix")
PINCABOS_VOIX_LANGUES = ("fr", "en", "es", "it", "de")

# Nom de chaque position chez ffmpeg. C'est la seule table de correspondance
# du test : ni index de canal, ni ordre a deviner.
PINCABOS_POSITION_FFMPEG = {
    "front-left": "FL",
    "front-right": "FR",
    "front-center": "FC",
    "lfe": "LFE",
    "rear-left": "BL",
    "rear-right": "BR",
    "rear-center": "BC",
    "side-left": "SL",
    "side-right": "SR",
    "mono": "FC",
}

PINCABOS_LAYOUT_FFMPEG = {
    # PINCABOS_AUDIO_QUAD_V1 — le selecteur propose « 4 canaux » : sans la
    # disposition correspondante, cliquer un haut-parleur repondait « position
    # non placable ». Le quadriphonique ne porte que les quatre coins, ni
    # centre ni caisson, ce que la table exprime d'elle-meme.
    2: "stereo",
    4: "quad",
    6: "5.1",
    8: "7.1",
}


def audio_langue_voix():
    """Langue des annonces : celle choisie a l'installation."""
    for chemin in ("/etc/default/locale", "/etc/locale.conf"):
        try:
            for ligne in Path(chemin).read_text(encoding="utf-8").splitlines():
                if ligne.startswith("LANG="):
                    code = ligne.split("=", 1)[1].strip().strip('"').lower()[:2]
                    if code in PINCABOS_VOIX_LANGUES:
                        return code
        except OSError:
            continue
    return "en"


def audio_voix_fichier(position):
    """Annonce pour cette position, dans la langue du cab sinon en anglais."""
    for langue in (audio_langue_voix(), "en"):
        fichier = PINCABOS_VOIX_RACINE / langue / f"{position}.opus"
        if fichier.is_file():
            return fichier
    return None


def audio_jouer_position(sink, position, canaux):
    """Joue l'annonce sur ce seul haut-parleur.

    ffmpeg place la voix dans le canal portant ce nom, puis pw-play envoie le
    flux sur la sortie choisie. Aucun numero de canal n'intervient.
    """
    import tempfile

    nom_ffmpeg = PINCABOS_POSITION_FFMPEG.get(position)
    layout = PINCABOS_LAYOUT_FFMPEG.get(int(canaux))

    if not nom_ffmpeg or not layout:
        return False, f"Position {position} non placable sur {canaux} canaux."

    voix = audio_voix_fichier(position)
    if not voix:
        return False, f"Annonce absente pour {position}."

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as sortie:
        chemin = sortie.name

    try:
        rendu = subprocess.run(
            ["/usr/bin/ffmpeg", "-v", "error", "-y", "-i", str(voix),
             "-af", f"pan={layout}|{nom_ffmpeg}=c0",
             "-c:a", "pcm_s16le", chemin],
            capture_output=True, text=True, timeout=20,
        )
        if rendu.returncode != 0:
            return False, (rendu.stderr or "ffmpeg a echoue").strip()

        lecture = subprocess.run(
            audio_session_prefix()
            + ["/usr/bin/pw-play", "--target", sink, chemin],
            capture_output=True, text=True, timeout=25,
        )
        if lecture.returncode != 0:
            return False, (lecture.stderr or "pw-play a echoue").strip()

        return True, f"{position} — canal {nom_ffmpeg} du flux {layout}"

    except Exception as exc:
        return False, str(exc)
    finally:
        try:
            Path(chemin).unlink(missing_ok=True)
        except Exception:
            pass


# PINCABOS_AUDIO_PRISES_V1
# Couleurs normalisees des broches HDA, telles que le codec les declare.
PINCABOS_COULEURS = {
    0: ("Inconnue", "#9ca3af"),
    1: ("Noire", "#3f3f46"),
    2: ("Grise", "#9ca3af"),
    3: ("Bleue", "#3b82f6"),
    4: ("Verte", "#22c55e"),
    5: ("Rouge", "#ef4444"),
    6: ("Orange", "#f97316"),
    7: ("Jaune", "#eab308"),
    8: ("Violette", "#a855f7"),
    9: ("Rose", "#ec4899"),
    14: ("Blanche", "#e5e7eb"),
    15: ("Autre", "#9ca3af"),
}

# Rang de la broche dans son groupe de sortie -> role, positions portees, et
# nom du controle de presence expose par le pilote.
PINCABOS_RANGS = {
    0: ("Avant", ("front-left", "front-right"), "Line Out Front Jack"),
    1: ("Centre et caisson", ("front-center", "lfe"), "Line Out CLFE Jack"),
    2: ("Arrière", ("rear-left", "rear-right"), "Line Out Surround Jack"),
    3: ("Latéral", ("side-left", "side-right"), "Line Out Side Jack"),
}


def audio_codec_analogique():
    """Codec portant les sorties analogiques, et son numero de carte ALSA."""
    import re as _re

    for codec in sorted(Path("/sys/class/sound").glob("hwC*D*")):
        broches = {}
        for fichier in ("init_pin_configs", "user_pin_configs"):
            try:
                for ligne in (codec / fichier).read_text(encoding="ascii").splitlines():
                    morceaux = ligne.split()
                    if len(morceaux) == 2:
                        broches[int(morceaux[0], 16)] = int(morceaux[1], 16)
            except OSError:
                continue

        sorties = [
            mot for mot in broches.values()
            if ((mot >> 20) & 0xF) == 0 and ((mot >> 30) & 0x3) in (0, 3)
        ]
        if len(sorties) >= 2:
            m = _re.match(r"hwC(\d+)D\d+", codec.name)
            return broches, (int(m.group(1)) if m else 0)

    return {}, -1


def audio_presence_jacks(carte):
    """Etat branche / vide de chaque prise, tel que le pilote le detecte."""
    import re as _re

    etats = {}
    liste = audio_run_cmd(f"amixer -c {int(carte)} controls 2>/dev/null")

    for ligne in liste.splitlines():
        if "Jack" not in ligne:
            continue
        num = _re.search(r"numid=(\d+)", ligne)
        nom = _re.search(r"name='([^']+)'", ligne)
        if not num or not nom:
            continue
        valeur = audio_run_cmd(
            f"amixer -c {int(carte)} cget numid={num.group(1)} 2>/dev/null"
        )
        etats[nom.group(1)] = "values=on" in valeur

    return etats


def audio_prises_analogiques():
    """Prises de sortie de la carte : couleur, role, positions, presence."""
    broches, carte = audio_codec_analogique()
    if carte < 0:
        return []

    presence = audio_presence_jacks(carte)
    prises = []

    for broche, mot in sorted(broches.items()):
        if ((mot >> 20) & 0xF) != 0 or ((mot >> 30) & 0x3) not in (0, 3):
            continue

        rang = mot & 0xF
        if rang not in PINCABOS_RANGS:
            continue

        role, positions, controle = PINCABOS_RANGS[rang]
        nom_couleur, code_couleur = PINCABOS_COULEURS.get(
            (mot >> 12) & 0xF, PINCABOS_COULEURS[0]
        )

        prises.append({
            "role": role,
            "couleur": nom_couleur,
            "code": code_couleur,
            "positions": list(positions),
            "branche": presence.get(controle),
        })

    return prises


def audio_carte_prises_html(prises):
    """Tableau des prises, pour la page."""
    if not prises:
        return ""

    lignes = []
    for prise in prises:
        if prise["branche"] is None:
            etat = "<span style='opacity:.6'>non détecté</span>"
        elif prise["branche"]:
            etat = "<strong style='color:#7ec97e'>branchée</strong>"
        else:
            etat = "<strong style='color:#f0a080'>vide</strong>"

        pastille = (
            f"<span style='display:inline-block;width:13px;height:13px;"
            f"border-radius:50%;background:{prise['code']};"
            f"border:1px solid rgba(255,255,255,.5);vertical-align:-2px;"
            f"margin-right:7px;'></span>"
        )

        lignes.append(
            f"<tr><td style='white-space:nowrap'>{pastille}"
            f"{esc(prise['couleur'])}</td>"
            f"<td>{esc(prise['role'])}</td>"
            f"<td>{etat}</td></tr>"
        )

    return f"""
  <details style="margin-top:10px;" open>
    <summary>Prises de la carte son</summary>
    <table style="width:100%;margin-top:6px;">
      <tr style="opacity:.7;font-size:12px;">
        <td>Prise</td><td>Porte</td><td>État</td>
      </tr>
      {''.join(lignes)}
    </table>
    <p><small>Couleur et rôle viennent de la carte mère elle-même ; l’état
    branché / vide est détecté en direct par le pilote.</small></p>
  </details>
"""


# PINCABOS_AUDIO_SORTIE_DEFAUT_V1
def audio_carte_retenue():
    """Numero ALSA de la carte que le cabinet utilise pour son multicanal.

    PINCABOS_AUDIO_CARD_MATCH_V2
    """
    try:
        nom = str(json.loads(
            Path("/opt/pincabos/config/audio/surround.json")
            .read_text(encoding="utf-8")
        ).get("card") or "")
    except Exception:
        return None

    if not nom:
        return None

    # Le nom PipeWire d'une carte et celui de ses sorties partagent leur
    # suffixe materiel : alsa_card.pci-0000_00_1f.3 donne
    # alsa_output.pci-0000_00_1f.3.analog-surround-71.
    suffixe = nom.split(".", 1)[-1]
    if not suffixe:
        return None

    for sortie in audio_pipewire_sinks():
        if suffixe in sortie.get("name", ""):
            return sortie.get("carte")

    return None


def audio_sortie_preferee(sorties):
    """Sortie a preselectionner : celle de VPX, sinon la plus capable."""
    if not sorties:
        return ""

    attendue = (_pco_vpx_audio_values().get("SoundDevice") or "").strip()
    if attendue:
        for sortie in sorties:
            if (sortie.get("description") or "").strip() == attendue:
                return f"pw:{sortie['name']}"

    # PINCABOS_AUDIO_CARD_MATCH_V2
    # A defaut du nom exact, on reste sur la carte que le cabinet a choisie
    # pour son multicanal : la plus capable des autres cartes ne le sert pas.
    retenues = sorties
    carte = audio_carte_retenue()
    if carte is not None:
        memes = [x for x in sorties if x.get("carte") == carte]
        if memes:
            retenues = memes

    plus_capable = max(retenues, key=lambda x: int(x.get("channels", 2) or 2))
    return f"pw:{plus_capable['name']}"


def audio_sorties_classees():
    """Sorties PipeWire, la plus capable en tete."""
    return sorted(
        audio_pipewire_sinks(),
        key=lambda x: (-int(x.get("channels", 2) or 2), x.get("description") or ""),
    )


# PINCABOS_AUDIO_SURROUND_UI_V1
PINCABOS_SURROUND_OUTIL = "/usr/local/sbin/pincabos-audio-surround"
PINCABOS_SURROUND_MODES = (
    ("stereo", "Stéréo", 2),
    ("5.1", "5.1", 6),
    ("7.1", "7.1", 8),
)


def audio_surround_etat():
    """Mode courant et modes atteignables par la carte analogique."""
    etat = {"mode": "", "canaux": 0, "possibles": [], "reaffectation": False}

    try:
        etat["mode"] = str(json.loads(
            Path("/opt/pincabos/config/audio/surround.json")
            .read_text(encoding="utf-8")
        ).get("mode") or "")
    except Exception:
        pass

    rapport = audio_run_cmd(f"{PINCABOS_SURROUND_OUTIL} detect 2>&1")

    for ligne in rapport.splitlines():
        depouillee = ligne.strip()
        if depouillee.startswith("canaux actuels"):
            chiffres = depouillee.split(":", 1)[-1].strip()
            etat["canaux"] = int(chiffres) if chiffres.isdigit() else 0
        elif depouillee.startswith("profils"):
            profils = depouillee.split(":", 1)[-1]
            for cle, _, _ in PINCABOS_SURROUND_MODES:
                marqueur = ("analog-stereo" if cle == "stereo"
                            else f"analog-surround-{cle.replace('.', '')}")
                if marqueur in profils:
                    etat["possibles"].append(cle)
        elif depouillee.startswith("7.1") and "possible en reaffectant" in depouillee:
            etat["reaffectation"] = True
            if "7.1" not in etat["possibles"]:
                etat["possibles"].append("7.1")

    return etat


def audio_carte_surround_html():
    """Carte de choix du mode multicanal."""
    etat = audio_surround_etat()
    if not etat["possibles"]:
        return ""

    boutons = []
    for cle, libelle, canaux in PINCABOS_SURROUND_MODES:
        if cle not in etat["possibles"]:
            continue

        courant = etat["mode"] == cle or etat["canaux"] == canaux
        classe = "button" if not courant else "button secondary"
        suffixe = " — actif" if courant else ""
        prevenir = (
            " (réaffecte la prise bleue)"
            if cle == "7.1" and etat["reaffectation"] and etat["canaux"] < 8
            else ""
        )
        boutons.append(
            f'<button class="{classe}" type="submit" name="mode" value="{cle}"'
            f'{" disabled" if courant else ""}>'
            f'{esc(libelle)} — {canaux} canaux{suffixe}{prevenir}</button>'
        )

    return f"""
<div class="card pco-audio-compact-card" id="pincabos-surround-card">
  <h2>Sortie multicanal</h2>
  <p>
    Le SSF a besoin d’un périphérique de 6 ou 8 canaux. Une carte analogique
    démarre toujours en stéréo : sans ce choix, aucune sortie multicanal
    n’existe et le SSF ne peut pas fonctionner.
  </p>
  <p>
    Mode enregistré : <code>{esc(etat['mode'] or 'aucun')}</code> —
    la carte fournit actuellement <strong>{etat['canaux']} canaux</strong>.
  </p>
  <form method="post" action="/audio-ssf/surround" target="pco-surround-frame">
    <p style="display:flex;gap:8px;flex-wrap:wrap;">{''.join(boutons)}</p>
  </form>
  <p><small>Le changement de mode relance brièvement la session audio.
  Le 7.1 réaffecte l’entrée ligne arrière — la prise bleue — en sortie
  latérale : c’est réversible, et c’est ce que fait le pilote du fabricant
  sous Windows.</small></p>
  <details style="margin-top:8px;" open>
    <summary>Résultat</summary>
    <iframe name="pco-surround-frame"
            style="width:100%;height:120px;background:rgba(0,0,0,.45);border:1px solid rgba(255,176,0,.25);border-radius:12px;"></iframe>
  </details>
</div>
"""


def audio_reponse_lisible(titre, lignes, ok=True):
    # PINCABOS_AUDIO_REPONSES_LISIBLES_V1 — toutes les reponses affichees
    # dans un cadre passent par ici : un cadre au fond sombre ne colore pas
    # le document qu'il accueille, et le texte brut s'y ecrit en noir.
    """Reponse affichee dans un cadre au fond sombre : couleurs explicites.

    Sans cela le document herite du fond du cadre et ecrit en noir dessus.
    """
    couleur = "#7ec97e" if ok else "#f08080"
    return (
        "<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<style>"
        "html,body{background:#14001f;color:#e8e0ef;font:13px/1.5 ui-monospace,monospace;"
        "margin:0;padding:10px}"
        f"h1{{font-size:13px;margin:0 0 8px;color:{couleur}}}"
        "pre{white-space:pre-wrap;word-break:break-word;margin:0}"
        "</style></head><body>"
        f"<h1>{esc(titre)}</h1><pre>{esc(chr(10).join(lignes))}</pre>"
        "</body></html>"
    ), 200, {"Content-Type": "text/html; charset=utf-8"}


def audio_alsa_test_card():
    devices, raw = audio_detect_alsa_devices()
    options = []

    # PINCABOS_AUDIO_TEST_PIPEWIRE_V1
    # PipeWire tient les cartes en permanence : ses sorties viennent en tete,
    # ce sont les seules testables sans arreter la session audio.
    # PINCABOS_AUDIO_SORTIE_DEFAUT_V1
    sorties_pw = audio_sorties_classees()
    preferee = audio_sortie_preferee(sorties_pw)

    for sortie in sorties_pw:
        canaux = int(sortie.get("channels", 2) or 2)
        libelle = sortie.get("description") or sortie["name"]
        carte = ",".join(sortie.get("map") or [])
        valeur = f'pw:{sortie["name"]}'
        marque = " selected" if valeur == preferee else ""
        options.append(
            f'<option value="{esc(valeur)}" data-canaux="{canaux}"{marque}'
            f' data-carte="{esc(carte)}" data-noms="{esc(",".join(audio_nom_position(p) for p in (sortie.get("map") or [])))}">'
            f'{esc(libelle)} — {canaux} canaux — PipeWire</option>'
        )

    for d in devices:
        hw = str(d.get("id", "") or "")
        card = str(d.get("card", "") or "")
        dev = str(d.get("device", "") or "")
        name = str(d.get("name", hw) or hw)
        desc = str(d.get("description", "") or "")

        plug = f"plughw:{card},{dev}" if card != "" and dev != "" else hw
        label = f"{name} — {desc} — {plug} — accès direct"
        options.append(f'<option value="{esc(plug)}">{esc(label)}</option>')

    if not options:
        options.append('<option value="">Aucun périphérique ALSA détecté</option>')

    raw_html = esc(raw or "")

    # PINCABOS_AUDIO_CANAUX_DEFAUT_V1
    canaux_preferes = next(
        (
            int(sortie.get("channels", 2) or 2)
            for sortie in sorties_pw
            if "pw:" + str(sortie["name"]) == preferee
        ),
        2,
    )
    canaux_options = "".join(
        '<option value="%d"%s>%s</option>'
        % (nombre, " selected" if nombre == canaux_preferes else "", libelle)
        for nombre, libelle in (
            (2, "2 canaux stéréo"),
            (4, "4 canaux"),
            (6, "6 canaux / 5.1"),
            (8, "8 canaux / 7.1"),
        )
    )

    # PINCABOS_AUDIO_PRISES_V1
    prises = audio_prises_analogiques()
    tableau_prises = audio_carte_prises_html(prises)
    prises_par_position = json.dumps({
        position: {"couleur": p["code"], "nom": p["couleur"],
                   "branche": p["branche"], "role": p["role"]}
        for p in prises for position in p["positions"]
    }, ensure_ascii=False)

    return f"""
<div class="card pco-audio-compact-card" id="pincabos-alsa-test-card">
  <script id="pco-prises" type="application/json">{prises_par_position}</script>
  <h2>Test des haut-parleurs</h2>
  <p>
    Lance un test court avec <code>speaker-test</code>. Choisis une sortie
    <strong>PipeWire</strong> : PipeWire tient les cartes en permanence, donc un
    accès direct <code>hw:</code> / <code>plughw:</code> répondra
    <code>Playback open error</code> tant qu’une session audio tourne.
  </p>
  <p>
    Pour vérifier un câblage SSF, clique un haut-parleur du schéma :
    il annonce sa position à voix haute, et lui seul reçoit le son.
  </p>
  <p><small>Le schéma donne la disposition habituelle d’un cabinet, pour
  situer les positions les unes par rapport aux autres. C’est le test,
  position par position, qui dit ce qui est réellement branché où.</small></p>

  <table style="width:100%;">
    <tr>
      <td style="width:150px;">Périphérique ALSA</td>
      <td>
        <select name="device" style="width:100%;max-width:520px;padding:7px;">
          {''.join(options)}
        </select>
      </td>
    </tr>
    <tr>
      <td>Canaux</td>
      <td>
        <select name="channels" style="padding:7px;">
          {canaux_options}
        </select>
      </td>
    </tr>
    <tr>
      <td>Signal</td>
      <td>
        <select name="signal" style="padding:7px;">
          <option value="wav">Nom des canaux — annoncé à voix haute</option>
          <option value="sine">Sinusoïde 440 Hz</option>
        </select>
      </td>
    </tr>
  </table>

  <form method="post" action="/audio-ssf/test-alsa-quick" target="pco-alsa-action-frame">
    <input type="hidden" name="device" id="pco-alsa-hidden-device" value="">
    <input type="hidden" name="channels" id="pco-alsa-hidden-channels" value="2">
    <input type="hidden" name="signal" id="pco-alsa-hidden-signal" value="wav">
    <input type="hidden" name="position" id="pco-alsa-hidden-position" value="">

    <!-- PINCABOS_AUDIO_CAB_MAP_V1 -->
    <div id="pco-hp-schema" style="margin:10px 0;display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start;">
      <svg id="pco-hp-svg" viewBox="0 0 320 420" role="img"
           aria-label="Schema du cabinet avec ses haut-parleurs"
           style="width:230px;max-width:100%;height:auto;flex:0 0 auto;">
        <!-- fronton -->
        <rect x="62" y="8" width="196" height="122" rx="10"
              fill="rgba(255,255,255,.04)" stroke="rgba(255,176,0,.45)" stroke-width="2"/>
        <text x="160" y="122" text-anchor="middle" font-size="11"
              fill="rgba(255,255,255,.38)">fronton</text>
        <!-- corps du cabinet -->
        <path d="M78 140 L242 140 L272 396 L48 396 Z"
              fill="rgba(255,255,255,.04)" stroke="rgba(255,176,0,.45)" stroke-width="2"/>
        <!-- lockbar -->
        <rect x="46" y="386" width="228" height="14" rx="7"
              fill="rgba(255,176,0,.18)" stroke="rgba(255,176,0,.45)" stroke-width="2"/>
        <text x="160" y="414" text-anchor="middle" font-size="11"
              fill="rgba(255,255,255,.38)">lockbar — côté joueur</text>
        <g id="pco-hp-couche"></g>
      </svg>
      <div style="flex:1 1 200px;min-width:180px;">
        <div id="pco-hp-legende" style="font-size:12px;opacity:.75;margin-bottom:6px;"></div>
        <div id="pco-hp-restants" style="display:flex;flex-wrap:wrap;gap:6px;"></div>
      </div>
    </div>
    <script>
    (function () {{
      var carte = document.getElementById("pincabos-alsa-test-card");
      if (!carte) return;
      var choix = carte.querySelector("select[name=device]");
      var couche = document.getElementById("pco-hp-couche");
      var restants = document.getElementById("pco-hp-restants");
      var legende = document.getElementById("pco-hp-legende");
      if (!choix || !couche) return;

      var SVGNS = "http://www.w3.org/2000/svg";

      // PINCABOS_AUDIO_CAB_MAP_V2
      // Seules les deux voies avant sont sur le fronton. Tout le reste vit
      // dans le corps du cabinet, sous le plateau : arriere en haut, caisson
      // au milieu, laterales au lockbar, cote joueur.
      var PLACES = {{
        "front-left":   [104, 52],
        "front-right":  [216, 52],
        "front-center": [160, 182],
        "rear-left":    [100, 214],
        "rear-right":   [220, 214],
        "lfe":          [160, 280],
        "rear-center":  [160, 330],
        "side-left":    [100, 368],
        "side-right":   [220, 368],
        "mono":         [160, 280]
      }};

      // PINCABOS_AUDIO_VOIX_V1 — on designe la position par son nom.
      function envoyer(code) {{
        document.getElementById("pco-alsa-hidden-device").value = choix.value;
        document.getElementById("pco-alsa-hidden-channels").value =
          choix.selectedOptions[0].dataset.canaux || "2";
        document.getElementById("pco-alsa-hidden-signal").value = "wav";
        document.getElementById("pco-alsa-hidden-position").value = code;
        couche.closest("form").submit();
      }}

      var PRISES = {{}};
      try {{
        PRISES = JSON.parse(document.getElementById("pco-prises").textContent);
      }} catch (e) {{ PRISES = {{}}; }}

      function enceinte(x, y, nom, canal, caisson) {{
        var prise = PRISES[canal] || {{}};
        var teinte = prise.couleur || "#ff8a00";
        var vide = prise.branche === false;
        var g = document.createElementNS(SVGNS, "g");
        g.setAttribute("transform", "translate(" + (x - 17) + "," + (y - 21) + ")");
        g.style.cursor = "pointer";
        g.setAttribute("tabindex", "0");
        g.setAttribute("role", "button");
        g.setAttribute("aria-label", nom);

        var corps = document.createElementNS(SVGNS, "rect");
        corps.setAttribute("width", "34");
        corps.setAttribute("height", "42");
        corps.setAttribute("rx", "5");
        corps.setAttribute("fill", vide ? "rgba(255,255,255,.04)" : "rgba(255,138,0,.20)");
        corps.setAttribute("stroke", teinte);
        corps.setAttribute("stroke-width", "2");
        if (vide) corps.setAttribute("stroke-dasharray", "4 3");
        g.appendChild(corps);
        g.setAttribute("opacity", vide ? "0.5" : "1");

        var cone = document.createElementNS(SVGNS, "circle");
        cone.setAttribute("cx", "17");
        cone.setAttribute("cy", caisson ? "21" : "27");
        cone.setAttribute("r", caisson ? "12" : "9");
        cone.setAttribute("fill", "none");
        cone.setAttribute("stroke", teinte);
        cone.setAttribute("stroke-width", "2");
        g.appendChild(cone);

        var centre = document.createElementNS(SVGNS, "circle");
        centre.setAttribute("cx", "17");
        centre.setAttribute("cy", caisson ? "21" : "27");
        centre.setAttribute("r", "3");
        centre.setAttribute("fill", teinte);
        g.appendChild(centre);

        if (!caisson) {{
          var aigu = document.createElementNS(SVGNS, "circle");
          aigu.setAttribute("cx", "17");
          aigu.setAttribute("cy", "10");
          aigu.setAttribute("r", "4");
          aigu.setAttribute("fill", "none");
          aigu.setAttribute("stroke", teinte);
          aigu.setAttribute("stroke-width", "2");
          g.appendChild(aigu);
        }}

        var titre = document.createElementNS(SVGNS, "title");
        titre.textContent = nom
          + (prise.nom ? " — prise " + prise.nom.toLowerCase() : "")
          + (vide ? " (prise vide)" : "")
          + " — cliquer pour jouer";
        g.appendChild(titre);

        function jouer() {{
          corps.setAttribute("fill", "rgba(255,138,0,.75)");
          g.setAttribute("opacity", "1");
          if (legende) legende.textContent = "Envoi sur : " + nom;
          envoyer(canal);
        }}

        g.addEventListener("click", jouer);
        g.addEventListener("keydown", function (e) {{
          if (e.key === "Enter" || e.key === " ") {{ e.preventDefault(); jouer(); }}
        }});
        g.addEventListener("mouseenter", function () {{
          corps.setAttribute("fill", "rgba(255,138,0,.45)");
          if (legende) {{
            legende.textContent = nom
              + (prise.nom ? " — prise " + prise.nom.toLowerCase() : "")
              + (vide ? " — cette prise est vide" : "");
          }}
        }});
        g.addEventListener("mouseleave", function () {{
          corps.setAttribute("fill", vide ? "rgba(255,255,255,.04)" : "rgba(255,138,0,.20)");
        }});

        return g;
      }}

      function dessiner() {{
        couche.replaceChildren();
        restants.replaceChildren();
        var option = choix.selectedOptions[0];
        var codes = (option && option.dataset.carte || "").split(",").filter(Boolean);
        var noms = (option && option.dataset.noms || "").split(",").filter(Boolean);

        if (!codes.length) {{
          legende.textContent =
            "Cette sortie ne declare pas ses positions : utilise le bouton de test complet.";
          return;
        }}

        legende.textContent = "Clique un haut-parleur pour n'envoyer le son que la.";

        codes.forEach(function (code, i) {{
          var nom = noms[i] || code;
          var place = PLACES[code.trim()];
          if (place) {{
            couche.appendChild(enceinte(place[0], place[1], nom, code.trim(),
                                        code.trim() === "lfe"));
            return;
          }}
          // Position inconnue du schema : bouton nomme, plutot que rien.
          var b = document.createElement("button");
          b.type = "button";
          b.className = "button secondary";
          b.style.cssText = "padding:6px 10px;font-size:12px;";
          b.textContent = nom;
          b.addEventListener("click", function () {{ envoyer(code.trim()); }});
          restants.appendChild(b);
        }});
      }}

      choix.addEventListener("change", dessiner);
      dessiner();
    }})();
    </script>
    <p style="margin:6px 0 8px 0;">
      <button class="button" type="submit"
        onclick="
          const card=this.closest('.card');
          document.getElementById('pco-alsa-hidden-device').value=card.querySelector('select[name=device]').value;
          document.getElementById('pco-alsa-hidden-channels').value=card.querySelector('select[name=channels]').value;
          document.getElementById('pco-alsa-hidden-signal').value=card.querySelector('select[name=signal]').value;
          document.getElementById('pco-alsa-hidden-position').value='';
        ">
        Tester 2 secondes
      </button>
      <a class="button secondary" href="/audio-ssf">Rafraîchir la page</a>
    </p>
  </form>

  <p><small><code>Playback open error</code> sur un accès direct signifie que
  PipeWire tient déjà la carte : passe par la sortie PipeWire correspondante.</small></p>

  {tableau_prises}

  <details style="margin-top:8px;" open>
    <summary>Log test audio</summary>
    <iframe name="pco-alsa-action-frame"
            style="width:100%;height:150px;background:rgba(0,0,0,.45);border:1px solid rgba(255,176,0,.25);border-radius:12px;"></iframe>
  </details>

  <details style="margin-top:8px;">
    <summary>Voir sortie brute <code>aplay -l</code></summary>
    <pre style="white-space:pre-wrap;max-height:260px;overflow:auto;background:rgba(0,0,0,.45);border:1px solid rgba(255,176,0,.25);border-radius:12px;padding:10px;">{raw_html}</pre>
  </details>
</div>
"""


def audio_wav_test_card():
    wav_dirs = [
        Path("/opt/pincabos/media/audio-tests"),
        Path("/opt/pincabos/media"),
        Path("/home/pinball/Share"),
    ]

    wav_files = []
    seen = set()

    for base in wav_dirs:
        try:
            if not base.exists() or not base.is_dir():
                continue
            for f in base.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in [".wav", ".wave"]:
                    continue
                real = str(f.resolve())
                if real in seen:
                    continue
                seen.add(real)
                wav_files.append(f.resolve())
        except Exception:
            continue

    wav_files = sorted(wav_files, key=lambda x: x.name.lower())

    wav_options = []
    for f in wav_files:
        label = f.name
        try:
            label = str(f.relative_to("/opt/pincabos/media"))
        except Exception:
            pass
        wav_options.append(f'<option value="{esc(str(f))}">{esc(label)}</option>')

    if not wav_options:
        wav_options.append('<option value="">Aucun fichier WAV installé</option>')

    devices, _raw = audio_detect_alsa_devices()
    device_options = []

    # PINCABOS_AUDIO_WAV_PIPEWIRE_V1
    # Sorties PipeWire en tete : ce sont les seules multicanal, et les seules
    # jouables sans se heurter a une carte que PipeWire tient deja.
    # PINCABOS_AUDIO_SORTIE_DEFAUT_V1 — meme preselection que le test.
    sorties_pw = audio_sorties_classees()
    preferee = audio_sortie_preferee(sorties_pw)

    for sortie in sorties_pw:
        canaux = int(sortie.get("channels", 2) or 2)
        libelle = sortie.get("description") or sortie["name"]
        valeur = f'pw:{sortie["name"]}'
        marque = " selected" if valeur == preferee else ""
        device_options.append(
            f'<option value="{esc(valeur)}"{marque}>'
            f'{esc(libelle)} — {canaux} canaux — PipeWire</option>'
        )

    for d in devices:
        hw = str(d.get("id", "") or "")
        card = str(d.get("card", "") or "")
        dev = str(d.get("device", "") or "")
        name = str(d.get("name", hw) or hw)
        desc = str(d.get("description", "") or "")
        plug = f"plughw:{card},{dev}" if card != "" and dev != "" else hw
        selected = ""  # PINCABOS_AUDIO_SORTIE_DEFAUT_V1 : la sortie PipeWire prime
        label = f"{name} — {desc} — {plug}"
        device_options.append(f'<option value="{esc(plug)}"{selected}>{esc(label)}</option>')

    if not device_options:
        device_options.append('<option value="">Aucune sortie audio détectée</option>')

    return f"""
<div class="card pco-audio-compact-card" id="pincabos-wav-test-card">
  <h2>Tests WAV PinCabOS</h2>
  <p>Tests WAV : bass shaker, sweep basses fréquences, gauche/droite et test 4 canaux.</p>

  <form id="pco-wav-real-form" method="post" target="pco-audio-action-frame">
    <table style="width:100%;margin-bottom:8px;">
      <tr>
        <td style="width:150px;">Fichier WAV</td>
        <td>
          <select name="wav_file" id="pco-real-wav-file" style="width:100%;max-width:520px;padding:7px;">
            {''.join(wav_options)}
          </select>
        </td>
      </tr>
      <tr>
        <td>Sortie ALSA</td>
        <td>
          <select name="device" id="pco-real-wav-device" style="width:100%;max-width:520px;padding:7px;">
            {''.join(device_options)}
          </select>
        </td>
      </tr>
    </table>

    <p style="margin:6px 0 8px 0;">
      <button class="button" type="submit" formaction="/audio-ssf/test-wav" formmethod="post">Jouer le WAV</button>
      <button class="button secondary" type="submit" formaction="/audio-ssf/test-wav-stop" formmethod="post">Stop audio</button>
    </p>

    <div class="pco-inline-volume"
         style="margin:8px 0;padding:8px;border:1px solid rgba(255,176,0,.22);border-radius:10px;background:rgba(0,0,0,.12);">
      <div style="font-weight:700;margin-bottom:6px;font-size:13px;">Volume / balance</div>

      <div style="display:grid;grid-template-columns:minmax(250px,1fr) 220px;gap:10px;align-items:start;">
        <div>
          <div style="display:grid;grid-template-columns:68px 150px 76px;gap:5px;align-items:center;font-size:11px;margin-bottom:5px;">
            <label>Volume</label>
            <input name="volume" id="pco-real-volume" type="range" min="0" max="100" value="70"
                   style="width:150px;margin:0;"
                   oninput="document.getElementById('pco-real-volume-val').textContent=this.value">
            <strong>&nbsp;&nbsp;&nbsp;<span id="pco-real-volume-val">70</span>%</strong>

            <label>Balance</label>
            <input name="balance" id="pco-real-balance" type="range" min="-100" max="100" value="0"
                   style="width:150px;margin:0;"
                   oninput="document.getElementById('pco-real-balance-val').textContent=(this.value==0?'centre':(this.value<0?'G '+Math.abs(this.value)+'%':'D '+this.value+'%'))">
            <strong>&nbsp;&nbsp;&nbsp;<span id="pco-real-balance-val">centre</span></strong>
          </div>

          <button class="button" type="submit" formaction="/audio-ssf/system-volume/apply" formmethod="post" style="padding:4px 8px;font-size:11px;">
            Appliquer
          </button>
          <button class="button secondary" type="submit" formaction="/audio-ssf/system-volume/get" formmethod="get" style="padding:4px 8px;font-size:11px;">
            Lire état
          </button>
        </div>
      </div>
    </div>
  </form>

  <details style="margin-top:8px;" open>
    <summary>Résultat des boutons</summary>
    <iframe name="pco-audio-action-frame"
            id="pco-audio-action-frame"
            style="width:100%;height:170px;background:rgba(0,0,0,.45);border:1px solid rgba(255,176,0,.25);border-radius:12px;color:white;"></iframe>
  </details>
</div>
"""


def audio_ini_read_key(path, section, key):
    """
    Lecture simple INI, sans modification.
    Retourne la valeur d'une clef dans une section.
    """
    p = Path(path)
    if not p.exists():
        return None

    current = None
    section_l = str(section).strip().lower()
    key_l = str(key).strip().lower()

    try:
        for line in p.read_text(errors="replace").splitlines():
            s = line.strip()

            if not s or s.startswith("#") or s.startswith(";"):
                continue

            if s.startswith("[") and s.endswith("]"):
                current = s[1:-1].strip().lower()
                continue

            if current == section_l and "=" in s:
                left, right = s.split("=", 1)
                if left.strip().lower() == key_l:
                    return right.strip()
    except Exception as e:
        return f"ERREUR lecture: {e}"

    return None


def audio_ini_value_cell(value):
    if value is None:
        return '<span class="warn">non trouvé</span>'
    if str(value).strip() == "":
        return '<span class="warn">vide</span>'
    return f'<code>{esc(str(value))}</code>'


def audio_ini_values_card():
    values = _pco_vpx_audio_values()

    rows = []

    for key, description in (
        (
            "SoundDeviceBG",
            "Backglass / ROM / musique",
        ),
        (
            "SoundDevice",
            "Underplayfield / SoundFX / SSF",
        ),
        (
            "Sound3D",
            "Mode de sortie VPX",
        ),
        (
            "PlayMusic",
            "Backglass / ROM activé",
        ),
        (
            "PlaySound",
            "SoundFX / playfield activé",
        ),
        (
            "MusicVolume",
            "Volume backglass",
        ),
        (
            "SoundVolume",
            "Volume playfield",
        ),
    ):
        rows.append(
            "<tr>"
            f"<td>{esc(description)}</td>"
            f"<td><code>[Player] {esc(key)}</code></td>"
            f"<td>"
            f"{audio_ini_value_cell(values.get(key))}"
            f"</td>"
            "</tr>"
        )

    muteaudio = audio_ini_read_key(
        "/home/pinball/.config/vpinfe/vpinfe.ini",
        "Settings",
        "muteaudio",
    )

    return f"""
<div
  class="card pco-audio-compact-card"
  id="pincabos-audio-ini-values-card"
>
  <h2>Valeurs audio réellement actives</h2>

  <p>
    Lecture directe de
    <code>{esc(str(PINCABOS_VPX_AUDIO_INI))}</code>
  </p>

  <table>
    <tr>
      <th>Fonction</th>
      <th>Clé exacte</th>
      <th>Valeur</th>
    </tr>
    {''.join(rows)}
  </table>

  <p>
    VPinFE :
    <code>[Settings] muteaudio</code>
    = {audio_ini_value_cell(muteaudio)}
  </p>
</div>
"""

def audio_system_run(cmd, timeout=8):
    # Keep PipeWire / Pulse commands functional when the WebApp runs as root.
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
    try:
        r = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return 99, "", str(e)


def audio_parse_alsa_hw(device):
    """
    Accepte hw:X,Y ou plughw:X,Y.
    Retourne (card, device) ou ("","").
    """
    import re
    m = re.search(r"(?:plug)?hw:(\d+),(\d+)", str(device or ""))
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def audio_pactl_find_sink_for_alsa_card(card):
    """
    Trouve un sink PipeWire/PulseAudio correspondant à alsa.card = X.
    Important: pactl doit être lancé comme user pinball avec XDG_RUNTIME_DIR.
    """
    if str(card).strip() == "":
        return ""

    # PINCABOS_AUDIO_WAV_PIPEWIRE_V1 — prefixe commun : runuser seulement
    # depuis root, sans quoi l'appel echoue et la sortie parait introuvable.
    cmd = audio_session_prefix() + ["/usr/bin/pactl", "list", "sinks"]

    rc, out, err = audio_system_run(cmd, timeout=6)
    if rc != 0 or not out.strip():
        return ""

    current_name = ""
    current_card = ""

    for line in out.splitlines():
        s = line.strip()

        if s.startswith("Name:"):
            current_name = s.split(":", 1)[1].strip()
            current_card = ""

        if "alsa.card =" in s:
            current_card = s.split("=", 1)[1].strip().strip('"')

        if current_name and current_card == str(card):
            return current_name

    return ""


def audio_system_volume_get(device=""):
    """
    Lecture best-effort du volume système pour le périphérique choisi.
    """
    card, dev = audio_parse_alsa_hw(device)
    out = []

    out.append(f"Périphérique demandé: {device or 'défaut'}")
    if card != "":
        out.append(f"Carte ALSA ciblée: card {card}, device {dev}")

    sink = audio_pactl_find_sink_for_alsa_card(card) if card != "" else ""
    if sink:
        out.append(f"Sink pactl correspondant: {sink}")
        rc, stdout, stderr = audio_system_run(["bash", "-lc", f"pactl get-sink-volume {sink} 2>/dev/null | head -n1"])
        if rc == 0 and stdout.strip():
            out.append("pactl:")
            out.append(stdout.strip())
    else:
        rc, stdout, stderr = audio_system_run(["bash", "-lc", "pactl get-sink-volume @DEFAULT_SINK@ 2>/dev/null | head -n1"])
        if rc == 0 and stdout.strip():
            out.append("pactl default:")
            out.append(stdout.strip())

    if card != "":
        rc2, stdout2, stderr2 = audio_system_run(["bash", "-lc", f"amixer -c {card} get Master 2>/dev/null | sed -n '1,10p'"])
        if rc2 == 0 and stdout2.strip():
            out.append("amixer Master:")
            out.append(stdout2.strip())
        else:
            rc3, stdout3, stderr3 = audio_system_run(["bash", "-lc", f"amixer -c {card} get PCM 2>/dev/null | sed -n '1,10p'"])
            if rc3 == 0 and stdout3.strip():
                out.append("amixer PCM:")
                out.append(stdout3.strip())
    else:
        rc2, stdout2, stderr2 = audio_system_run(["bash", "-lc", "amixer get Master 2>/dev/null | sed -n '1,10p'"])
        if rc2 == 0 and stdout2.strip():
            out.append("amixer default Master:")
            out.append(stdout2.strip())

    if len(out) <= 2:
        out.append("Aucun mixer système détecté pour ce périphérique via pactl/amixer.")

    return "\n".join(out)


def audio_system_volume_apply(volume, balance, device=""):
    """
    Applique volume général + balance gauche/droite au périphérique ciblé.

    device: hw:X,Y ou plughw:X,Y.
    volume: 0-100.
    balance: -100 gauche à +100 droite.
    """
    try:
        volume = int(volume)
    except Exception:
        volume = 70

    try:
        balance = int(balance)
    except Exception:
        balance = 0

    volume = max(0, min(100, volume))
    balance = max(-100, min(100, balance))

    if balance < 0:
        left = volume
        right = round(volume * (100 + balance) / 100)
    elif balance > 0:
        left = round(volume * (100 - balance) / 100)
        right = volume
    else:
        left = volume
        right = volume

    card, dev = audio_parse_alsa_hw(device)
    results = []
    results.append(f"Périphérique demandé: {device or 'défaut'}")
    results.append(f"Volume={volume}% Balance={balance}")
    results.append(f"Calcul: gauche={left}% droite={right}%")

    # PipeWire/PulseAudio: définir le sink par défaut si on trouve la carte.
    sink = audio_pactl_find_sink_for_alsa_card(card) if card != "" else ""
    if sink:
        rc_def, out_def, err_def = audio_system_run(["bash", "-lc", f"pactl set-default-sink {sink} 2>&1"])
        if rc_def == 0:
            results.append(f"OK pactl: sink système par défaut = {sink}")
        else:
            results.append("pactl set-default-sink non appliqué: " + (err_def.strip() or out_def.strip() or str(rc_def)))

        rc, stdout, stderr = audio_system_run(["bash", "-lc", f"pactl set-sink-volume {sink} {left}% {right}% 2>&1"])
        if rc == 0:
            results.append("OK pactl: volume/balance appliqués sur le sink ciblé.")
        else:
            results.append("pactl volume non appliqué: " + (stderr.strip() or stdout.strip() or f"code {rc}"))
    else:
        rc, stdout, stderr = audio_system_run(["bash", "-lc", f"pactl set-sink-volume @DEFAULT_SINK@ {left}% {right}% 2>&1"])
        if rc == 0:
            results.append("OK pactl: volume/balance appliqués sur le sink par défaut.")
        else:
            results.append("pactl non appliqué: " + (stderr.strip() or stdout.strip() or f"code {rc}"))

    # ALSA: viser la carte par numéro si possible.
    if card != "":
        applied = False
        for control in ["Master", "PCM", "Speaker"]:
            rc2, stdout2, stderr2 = audio_system_run(["bash", "-lc", f"amixer -c {card} sset {control} {left}%,{right}% 2>&1"])
            if rc2 == 0:
                results.append(f"OK amixer: card {card} contrôle {control} gauche/droite appliqué.")
                applied = True
                break

        if not applied:
            for control in ["Master", "PCM", "Speaker"]:
                rc3, stdout3, stderr3 = audio_system_run(["bash", "-lc", f"amixer -c {card} sset {control} {volume}% 2>&1"])
                if rc3 == 0:
                    results.append(f"OK amixer: card {card} contrôle {control} volume général appliqué; balance non supportée.")
                    applied = True
                    break

        if not applied:
            results.append(f"amixer: aucun contrôle Master/PCM/Speaker utilisable sur card {card}.")
    else:
        rc2, stdout2, stderr2 = audio_system_run(["bash", "-lc", f"amixer sset Master {left}%,{right}% 2>&1"])
        if rc2 == 0:
            results.append("OK amixer: Master default gauche/droite appliqué.")
        else:
            results.append("amixer default non appliqué: " + (stderr2.strip() or stdout2.strip() or f"code {rc2}"))

    results.append("")
    results.append("État après application:")
    results.append(audio_system_volume_get(device))

    return "\n".join(results)


def audio_system_vu_meter(device=""):
    return '{"ok": false, "left_db": null, "right_db": null, "left_pct": 0, "right_pct": 0, "source": ""}'


def audio_system_volume_card():
    devices, raw = audio_detect_alsa_devices()
    cfg = audio_load_config()
    selected = cfg.get("playfield_device") or cfg.get("backbox_device") or ""

    options = []
    for d in devices:
        hw = str(d.get("id", "") or "")
        card = str(d.get("card", "") or "")
        dev = str(d.get("device", "") or "")
        name = str(d.get("name", hw) or hw)
        desc = str(d.get("description", "") or "")
        plug = f"plughw:{card},{dev}" if card != "" and dev != "" else hw

        for value, suffix in [(plug, "plughw recommandé"), (hw, "hw direct")]:
            sel = " selected" if value == selected else ""
            label = f"{name} — {desc} — {value} ({suffix})"
            options.append(f'<option value="{esc(value)}"{sel}>{esc(label)}</option>')

    if not options:
        options.append('<option value="">Aucun périphérique ALSA détecté</option>')

    return f"""
<div class="card pco-audio-compact-card" id="pincabos-system-volume-card">
  <h3>Volume système / balance</h3>
  <p>
    Contrôle le mixer du périphérique sélectionné et tente aussi de le définir comme sortie système.
    N’écrit rien dans <code>VPinballX.ini</code> ni <code>vpinfe.ini</code>.
  </p>

  <table style="width:100%;">
    <tr>
      <td>Périphérique à contrôler</td>
      <td>
        <select id="pco-system-audio-device" style="width:100%;max-width:520px;padding:8px;">
          {''.join(options)}
        </select>
      </td>
    </tr>
    <tr>
      <td>Volume général</td>
      <td>
        <input id="pco-system-volume" type="range" min="0" max="100" value="70" style="width:70%;">
        <strong><span id="pco-system-volume-val">70</span>%</strong>
      </td>
    </tr>
    <tr>
      <td>Balance gauche / droite</td>
      <td>
        <input id="pco-system-balance" type="range" min="-100" max="100" value="0" style="width:70%;">
        <strong><span id="pco-system-balance-val">centre</span></strong>
      </td>
    </tr>
  </table>

  <p>
    <button class="button" type="button" id="pco-system-volume-apply">Appliquer volume/balance</button>
    <button class="button secondary" type="button" id="pco-system-volume-read">Lire état mixer</button>
  </p>

  <h4>VU meter sortie système</h4>
  <div style="display:grid;grid-template-columns:80px 1fr 70px;gap:8px;align-items:center;">
    <div>Gauche</div>
    <div style="height:16px;background:rgba(0,0,0,.45);border-radius:8px;overflow:hidden;border:1px solid rgba(255,176,0,.25);">
      <div id="pco-vu-left-bar" style="height:100%;width:0%;background:linear-gradient(90deg,#22c55e,#eab308,#ef4444);"></div>
    </div>
    <div><code id="pco-vu-left-db">-- dB</code></div>

    <div>Droite</div>
    <div style="height:16px;background:rgba(0,0,0,.45);border-radius:8px;overflow:hidden;border:1px solid rgba(255,176,0,.25);">
      <div id="pco-vu-right-bar" style="height:100%;width:0%;background:linear-gradient(90deg,#22c55e,#eab308,#ef4444);"></div>
    </div>
    <div><code id="pco-vu-right-db">-- dB</code></div>
  </div>
  <p><small id="pco-vu-source">VU meter prêt. Lance un test audio pour voir bouger les niveaux.</small></p>

  <details style="margin-top:12px;">
    <summary>Log volume système</summary>
    <pre id="pco-system-volume-log" style="white-space:pre-wrap;max-height:260px;overflow:auto;background:rgba(0,0,0,.45);border:1px solid rgba(255,176,0,.25);border-radius:12px;padding:12px;">Prêt.</pre>
  </details>

  <script>
  (function() {{
    const dev = document.getElementById("pco-system-audio-device");
    const vol = document.getElementById("pco-system-volume");
    const bal = document.getElementById("pco-system-balance");
    const volVal = document.getElementById("pco-system-volume-val");
    const balVal = document.getElementById("pco-system-balance-val");
    const log = document.getElementById("pco-system-volume-log");

    const vuL = document.getElementById("pco-vu-left-bar");
    const vuR = document.getElementById("pco-vu-right-bar");
    const dbL = document.getElementById("pco-vu-left-db");
    const dbR = document.getElementById("pco-vu-right-db");
    const vuSource = document.getElementById("pco-vu-source");

    function findWavDeviceSelect() {{
      return document.getElementById("pco-wav-device")
        || document.querySelector('select[name="wav_device"]')
        || document.querySelector('select[name="device"]');
    }}

    function syncFromWavSelect() {{
      const wavSel = findWavDeviceSelect();
      if (wavSel && dev && wavSel.value) {{
        dev.value = wavSel.value;
      }}
    }}

    function updateLabels() {{
      if (volVal && vol) volVal.textContent = vol.value;

      if (balVal && bal) {{
        const v = parseInt(bal.value || "0", 10);
        if (v === 0) balVal.textContent = "centre";
        else if (v < 0) balVal.textContent = "gauche " + Math.abs(v) + "%";
        else balVal.textContent = "droite " + v + "%";
      }}
    }}

    async function applyVolume() {{
      if (log) log.textContent = "Application en cours...";

      try {{
        const r = await fetch("/audio-ssf/system-volume/apply", {{
          method: "POST",
          headers: {{"Content-Type": "application/x-www-form-urlencoded"}},
          body: new URLSearchParams({{
            device: dev ? dev.value : "",
            volume: vol ? vol.value : "70",
            balance: bal ? bal.value : "0"
          }})
        }});
        const t = await r.text();
        if (log) log.textContent = t;
      }} catch (e) {{
        if (log) log.textContent = "Erreur: " + e;
      }}
    }}

    async function readVolume() {{
      if (log) log.textContent = "Lecture en cours...";

      try {{
        const r = await fetch("/audio-ssf/system-volume/get?device=" + encodeURIComponent(dev ? dev.value : ""), {{method: "GET"}});
        const t = await r.text();
        if (log) log.textContent = t;
      }} catch (e) {{
        if (log) log.textContent = "Erreur: " + e;
      }}
    }}

    if (vol) vol.addEventListener("input", updateLabels);
    if (bal) bal.addEventListener("input", updateLabels);

    document.addEventListener("click", function(e) {{
      if (e.target && e.target.id === "pco-system-volume-apply") applyVolume();
      if (e.target && e.target.id === "pco-system-volume-read") readVolume();
    }});

    document.addEventListener("change", function(e) {{
      const wavSel = findWavDeviceSelect();
      if (wavSel && dev && e.target === wavSel && wavSel.value) {{
        dev.value = wavSel.value;
      }}
    }});

    syncFromWavSelect();
    updateLabels();
}})();
  </script>

</div>
"""


@route("/audio-ssf")
def pincabos_audio_ssf_page_fixed():
    cfg = audio_load_config()

    saved_rows = ""
    try:
        saved_rows = f"""
<table>
  <tr><td>Backend</td><td><code>{esc(cfg.get('audio_backend', ''))}</code></td></tr>
  <tr><td>Backbox / ROM / Musique</td><td><code>{esc(cfg.get('backbox_device', ''))}</code></td></tr>
  <tr><td>Playfield / SSF</td><td><code>{esc(cfg.get('playfield_device', ''))}</code></td></tr>
  <tr><td>Surround VPX</td><td><code>{esc(cfg.get('surround_device', ''))}</code></td></tr>
  <tr><td>Bass shaker</td><td><code>{esc(cfg.get('bass_device', ''))}</code></td></tr>
  <tr><td>Fichier</td><td><code>{esc(str(AUDIO_ROUTER_CONFIG))}</code></td></tr>
</table>
"""
    except Exception as e:
        saved_rows = f"<p class='warn'>Erreur lecture configuration sauvegardée: {esc(str(e))}</p>"

    body = f"""

<style id="pco-audio-ssf-layout-final-css">
  .pco-audio-grid-tests,
  .pco-audio-grid-config {{
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important;
    gap: 10px !important;
    align-items: start !important;
    width: 100% !important;
    margin-bottom: 10px !important;
  }}

  .pco-audio-grid-tests > .card,
  .pco-audio-grid-config > .card,
  .pco-audio-grid-tests > .pco-audio-compact-card,
  .pco-audio-grid-config > .pco-audio-compact-card {{
    width: 100% !important;
    max-width: none !important;
    box-sizing: border-box !important;
    margin: 0 !important;
  }}

  .pco-audio-grid-tests iframe,
  .pco-audio-grid-config iframe {{
    max-width: 100% !important;
  }}

  @media (max-width: 1100px) {{
    .pco-audio-grid-tests,
    .pco-audio-grid-config {{
      grid-template-columns: 1fr !important;
    }}
  }}
</style>


<style id="pco-audio-ssf-equal-4-cards-css">
  .pco-audio-grid-tests,
  .pco-audio-grid-config {{
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important;
    gap: 12px !important;
    align-items: stretch !important;
    width: 100% !important;
    margin-bottom: 12px !important;
  }}

  .pco-audio-grid-tests > .card,
  .pco-audio-grid-config > .card,
  .pco-audio-grid-tests > form.card,
  .pco-audio-grid-config > form.card,
  .pco-audio-grid-tests > .pco-audio-compact-card,
  .pco-audio-grid-config > .pco-audio-compact-card {{
    width: 100% !important;
    max-width: none !important;
    min-height: 520px !important;
    box-sizing: border-box !important;
    margin: 0 !important;
    display: flex !important;
    flex-direction: column !important;
  }}

  .pco-audio-grid-config > .card,
  .pco-audio-grid-config > form.card {{
    min-height: 430px !important;
  }}

  .pco-audio-compact-card h2,
  .pco-audio-saved-full h2,
  .pco-audio-grid-config h2 {{
    margin-top: 0 !important;
    margin-bottom: 8px !important;
  }}

  .pco-audio-compact-card p,
  .pco-audio-saved-full p,
  .pco-audio-grid-config p {{
    margin-top: 6px !important;
    margin-bottom: 8px !important;
  }}

  .pco-audio-compact-card table,
  .pco-audio-saved-full table,
  .pco-audio-grid-config table {{
    width: 100% !important;
    margin-top: 4px !important;
    margin-bottom: 8px !important;
  }}

  .pco-audio-compact-card td,
  .pco-audio-saved-full td,
  .pco-audio-grid-config td {{
    padding-top: 4px !important;
    padding-bottom: 4px !important;
    vertical-align: middle !important;
  }}

  .pco-audio-compact-card iframe {{
    max-width: 100% !important;
  }}

  #pincabos-alsa-test-card iframe,
  #pco-audio-action-frame {{
    height: 130px !important;
  }}

  #pincabos-wav-test-card .pco-inline-volume {{
    margin-top: 8px !important;
    margin-bottom: 8px !important;
  }}

  .pco-audio-saved-full {{
    overflow: hidden !important;
  }}

  .pco-audio-saved-full table {{
    font-size: 0.95em !important;
  }}

  @media (max-width: 1100px) {{
    .pco-audio-grid-tests,
    .pco-audio-grid-config {{
      grid-template-columns: 1fr !important;
    }}

    .pco-audio-grid-tests > .card,
    .pco-audio-grid-config > .card,
    .pco-audio-grid-tests > form.card,
    .pco-audio-grid-config > form.card {{
      min-height: auto !important;
    }}
  }}
</style>

<h1>Audio / SSF V2</h1>

<p>
  Configuration native PinCabOS pour le choix des cartes de son :
  Backbox / ROM / musique, effets sous playfield / SSF, surround VPX et bass shaker.
</p>

<p>
  <a class="button" href="/audio-ssf/commander">🎚️ Ouvrir SSF Commander</a>
  <a class="button secondary" href="/audio-ssf">Rafraîchir</a>
</p>

<p class="warn">
  Les réglages Sons seulement / Mécanique seulement / Sons + mécanique ne sont plus dans cette page.
  Ils sont maintenant dans SSF Commander.
</p>

{audio_carte_surround_html()}

<div class="grid pco-audio-grid-tests">
  {pincabos_safe_audio_alsa_card()}
  {audio_wav_test_card()}
</div>

<div class="pco-audio-grid-config">
  <form method="post" action="/audio-ssf/save" class="card pco-audio-compact-card">
    <h2>Mode audio</h2>
    <table>
      {audio_config_rows()}
    </table>
    <p>
      <button class="button" type="submit">Sauvegarder configuration audio</button>
      <a class="button secondary" href="/audio-ssf/commander">🎚️ SSF Commander</a>
      <a class="button secondary" href="/audio-ssf">Rafraîchir</a>
    </p>
  </form>

  <div class="card pco-audio-compact-card pco-audio-saved-full">
    <h2>Configuration sauvegardée</h2>
    {saved_rows}
  </div>
</div>

{audio_ini_values_card()}
"""
    return page("Audio / SSF V2", body)


@route("/audio-ssf/surround", methods=["POST"])
def audio_ssf_surround():
    """PINCABOS_AUDIO_SURROUND_UI_V1"""
    mode = request.form.get("mode", "").strip()

    if mode not in {cle for cle, _, _ in PINCABOS_SURROUND_MODES}:
        return audio_reponse_lisible("Mode inconnu", [mode], ok=False)

    # La règle sudo n'autorise que ces trois modes, écrits en toutes lettres :
    # aucun argument libre n'atteint l'outil.
    resultat = audio_run_cmd(
        f"/usr/bin/sudo -n {PINCABOS_SURROUND_OUTIL} enable {mode} 2>&1"
    )

    ok = "GO:" in resultat
    suite = []

    # PINCABOS_AUDIO_SURROUND_SUIVI_V1
    # Le nom du peripherique change avec le mode. Sans report, VPX cherche une
    # sortie disparue et retombe sur le peripherique par defaut, en stereo.
    if ok:
        # PINCABOS_AUDIO_SURROUND_SUIVI_V2
        # La sortie est detruite puis recreee : on la laisse revenir avant de
        # lire son nom, sinon on ecrit dans le vide.
        import time as _time

        libelle = ""
        for _ in range(10):
            sorties = audio_sorties_classees()
            attendus = 2 if mode == "stereo" else (6 if mode == "5.1" else 8)
            # PINCABOS_AUDIO_CARD_MATCH_V2 — le nombre de canaux ne suffit
            # pas : sur deux cartes analogiques, il designe la mauvaise.
            carte = audio_carte_retenue()
            candidate = next(
                (
                    x for x in sorties
                    if int(x.get("channels", 2) or 2) == attendus
                    and (carte is None or x.get("carte") == carte)
                ),
                None,
            )
            if candidate:
                libelle = candidate.get("description") or candidate["name"]
                break
            _time.sleep(1)

        if libelle:
            try:
                suite = _pco_vpx_write_audio(libelle, libelle,
                                             audio_ini_read_key(
                                                 str(PINCABOS_VPX_AUDIO_INI),
                                                 "Player", "Sound3D") or "0")
                suite = [f"VPX pointe maintenant sur : {libelle}"] + list(suite)
            except Exception as exc:
                suite = [f"VPX non mis à jour : {exc}"]
        else:
            suite = ["Sortie non revenue à temps : VPX n'a pas été redirigé.",
                     "Ouvre la page Audio et enregistre la configuration."]

    return audio_reponse_lisible(
        f"Mode {mode} appliqué" if ok else f"Mode {mode} refusé",
        [resultat.strip() or "(aucune sortie)", ""] + suite + [
            "",
            "Recharge la page pour voir le nouveau schéma."],
        ok=ok,
    )


@route("/audio-ssf/test-alsa-quick", methods=["POST"])
def audio_ssf_test_alsa_quick():
    """PINCABOS_AUDIO_TEST_RUN_V1 + PINCABOS_AUDIO_VOIX_V1"""
    device = request.form.get("device", "").strip()
    channels = request.form.get("channels", "2").strip()
    signal = request.form.get("signal", "wav").strip()
    position = request.form.get("position", "").strip()

    if not device:
        return audio_reponse_lisible(
            "Aucune sortie sélectionnée",
            ["Choisis une sortie dans la liste, puis relance le test."],
            ok=False,
        )

    if channels not in ("2", "4", "6", "8"):
        channels = "2"
    if signal not in ("wav", "sine"):
        signal = "wav"

    # La sortie demandée doit figurer parmi celles que le système déclare :
    # rien de ce qui vient du formulaire n'est transmis tel quel.
    sorties = audio_pipewire_sinks()
    connues = {f"pw:{x['name']}" for x in sorties}
    for d in audio_detect_alsa_devices()[0]:
        connues.add(str(d.get("id") or ""))
        connues.add(f"plughw:{d.get('card')},{d.get('device')}")

    if device not in connues:
        return audio_reponse_lisible(
            "Sortie inconnue",
            [f"{device} n'est plus déclarée par le système.",
             "Rafraîchis la page pour recharger la liste."],
            ok=False,
        )

    # PINCABOS_AUDIO_VOIX_V1
    # Un haut-parleur désigné par son nom : le son est placé dans le canal
    # qui porte ce nom, et annoncé dans la langue du cabinet.
    if position and device.startswith("pw:"):
        if position not in PINCABOS_POSITION_FFMPEG:
            return audio_reponse_lisible(
                "Position inconnue", [position], ok=False,
            )

        sink = device[3:]
        carte = next(
            (x.get("map") or [] for x in sorties if x["name"] == sink), []
        )
        if position not in carte:
            return audio_reponse_lisible(
                "Position absente de cette sortie",
                [f"{position} n'existe pas sur {sink}.",
                 "Positions disponibles : " + ", ".join(carte)],
                ok=False,
            )

        ok, detail = audio_jouer_position(sink, position, len(carte))
        return audio_reponse_lisible(
            "Annonce jouée" if ok else "Annonce impossible",
            [f"Sortie   : {sink}",
             f"Langue   : {audio_langue_voix()}",
             "",
             detail],
            ok=ok,
        )

    # Tour complet : speaker-test annonce lui-même chaque canal.
    secondes = 4 + int(channels) * 3 if signal == "wav" else 4

    test = ["/usr/bin/speaker-test", "-c", channels, "-t", signal, "-l", "1"]
    if signal == "sine":
        test += ["-f", "440"]

    if device.startswith("pw:"):
        # Le PCM s'appelle « pipewire » — « pulse » est le plugin de
        # PulseAudio, absent ici — et la sortie visée se choisit par
        # PIPEWIRE_NODE.
        cmd = (
            audio_session_prefix()
            + [f"PIPEWIRE_NODE={device[3:]}", "/usr/bin/timeout", str(secondes)]
            + test + ["-D", "pipewire"]
        )
        route_lisible = f"PipeWire → {device[3:]}"
    else:
        cmd = ["/usr/bin/timeout", str(secondes)] + test + ["-D", device]
        route_lisible = f"accès direct → {device}"

    try:
        r = subprocess.run(
            cmd, text=True, capture_output=True, timeout=secondes + 6,
        )
    except Exception as exc:
        return audio_reponse_lisible("Test impossible", [str(exc)], ok=False)

    sortie = (r.stdout or "") + (r.stderr or "")

    lignes = [
        f"Sortie   : {route_lisible}",
        f"Canaux   : {channels} — tour complet",
        f"Signal   : {'nom des canaux' if signal == 'wav' else 'sinusoïde 440 Hz'}",
        "",
    ]

    # timeout coupe speaker-test en pleine lecture : « Interrupted system
    # call » est la fin normale de l'essai, pas une panne.
    ok = (
        r.returncode in (0, 124)
        and "open error" not in sortie.lower()
        and "unknown pcm" not in sortie.lower()
    )

    if "unknown pcm" in sortie.lower():
        lignes += [
            "Le pont ALSA vers PipeWire est absent (paquet pipewire-alsa).",
            "",
        ]
    elif "open error" in sortie.lower() and not device.startswith("pw:"):
        lignes += [
            "Le périphérique est occupé : PipeWire tient la carte en permanence.",
            "Reprends le test sur la sortie PipeWire correspondante.",
            "",
        ]
    elif ok:
        lignes += ["Test joué. Note quels haut-parleurs ont répondu.", ""]

    lignes += [sortie.strip() or "(aucune sortie)"]

    return audio_reponse_lisible(
        "Test terminé" if ok else "Test en échec", lignes, ok=ok,
    )


@route("/audio-ssf/system-volume/get", methods=["GET"])
def audio_ssf_system_volume_get():
    device = request.args.get("device", "").strip()
    return audio_reponse_lisible(
        "Volume système", str(audio_system_volume_get(device)).splitlines(), ok=True,
    )


@route("/audio-ssf/system-volume/apply", methods=["POST"])
def audio_ssf_system_volume_apply():
    device = request.form.get("device", "").strip()
    volume = request.form.get("volume", "70")
    balance = request.form.get("balance", "0")
    return audio_reponse_lisible(
        "Volume appliqué",
        str(audio_system_volume_apply(volume, balance, device)).splitlines(),
        ok=True,
    )


@route("/audio-ssf/system-volume/meter-html", methods=["GET", "POST"])
def audio_ssf_system_volume_meter_html():
    return "", 204


PINCABOS_SSF_CONTROLLER_INI = "/home/pinball/.local/share/VPinballX/10.8/VPinballX.ini"


PINCABOS_SSF_EFFECTS = [
    ("DOFKnocker", "Knocker"),
    ("DOFContactors", "Contacteurs"),
    ("DOFFlippers", "Flippers"),
    ("DOFShaker", "Shaker"),
    ("DOFTargets", "Targets"),
    ("DOFDropTargets", "Drop Targets"),
    ("DOFChimes", "Chimes"),
    ("DOFBell", "Bell"),
    ("DOFGear", "Gear Motor"),
]


PINCABOS_SSF_LABELS = {
    "": "Non configuré",
    "0": "Sons seulement",
    "1": "Mécanique seulement",
    "2": "Sons + mécanique",
}


def ssf_commander_escape(value):
    import html
    return html.escape(str(value), quote=True)


def ssf_commander_read_controller():
    from pathlib import Path

    ini = Path(PINCABOS_SSF_CONTROLLER_INI)
    values = {"ForceDisableB2S": ""}
    for key, label in PINCABOS_SSF_EFFECTS:
        values[key] = ""

    if not ini.exists():
        return values, f"Fichier introuvable: {ini}"

    lines = ini.read_text(errors="replace").splitlines()
    in_controller = False

    for line in lines:
        stripped = line.strip()
        if stripped.lower() == "[controller]":
            in_controller = True
            continue
        if stripped.startswith("[") and stripped.endswith("]") and in_controller:
            break
        if not in_controller:
            continue
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key in values:
            values[key] = raw_value.strip()

    return values, ""


def ssf_commander_write_controller(new_values, function_name="SSF Commander"):
    from pathlib import Path
    from datetime import datetime
    import shutil
    import subprocess

    ini = Path(PINCABOS_SSF_CONTROLLER_INI)
    if not ini.exists():
        raise FileNotFoundError(str(ini))

    backup_dir = Path("/opt/pincabos/backups/ssf-commander")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"VPinballX.ini.backup-ssf-commander-{stamp}"
    shutil.copy2(ini, backup)

    lines = ini.read_text(errors="replace").splitlines()

    managed_keys = ["ForceDisableB2S"] + [key for key, label in PINCABOS_SSF_EFFECTS]
    allowed = {"", "0", "1", "2"}

    normalized = {}

    normalized["ForceDisableB2S"] = str(new_values.get("ForceDisableB2S", "0")).strip()
    if normalized["ForceDisableB2S"] not in {"0", "1"}:
        normalized["ForceDisableB2S"] = "0"

    for key, label in PINCABOS_SSF_EFFECTS:
        value = str(new_values.get(key, "")).strip()
        if value not in allowed:
            value = ""
        normalized[key] = value

    stamp_human = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    comment = f"; Modifié {stamp_human} par PinCabOS fonction({function_name})"

    start = None
    end = None

    for i, line in enumerate(lines):
        if line.strip().lower() == "[controller]":
            start = i
            end = len(lines)
            for j in range(i + 1, len(lines)):
                s = lines[j].strip()
                if s.startswith("[") and s.endswith("]"):
                    end = j
                    break
            break

    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[Controller]")
        start = len(lines) - 1
        end = len(lines)

    before = lines[:start + 1]
    section = lines[start + 1:end]
    after = lines[end:]

    cleaned = []

    for line in section:
        stripped = line.strip()

        if "PinCabOS fonction(SSF Commander" in line:
            continue

        if "=" in line and not stripped.startswith((";", "#")):
            key = line.split("=", 1)[0].strip()
            if key in managed_keys:
                continue

        cleaned.append(line)

    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    if cleaned:
        cleaned.append("")

    new_managed = [comment]

    for key in managed_keys:
        new_managed.append(f"{key} = {normalized[key]}")

    new_lines = before + cleaned + new_managed + after

    ini.write_text(chr(10).join(new_lines) + chr(10))

    try:
        subprocess.run(["chown", "pinball:pinball", str(ini)], timeout=10)
    except Exception:
        pass

    return str(backup)


def ssf_commander_select_html(key, current):
    current = str(current or "").strip()
    options = [
        ("", "Non configuré"),
        ("0", "Sons seulement"),
        ("1", "Mécanique seulement"),
        ("2", "Sons + mécanique"),
    ]
    html_options = []
    for value, label in options:
        selected = " selected" if value == current else ""
        html_options.append(f'<option value="{value}"{selected}>{label}</option>')
    return f'<select name="{ssf_commander_escape(key)}">' + "".join(html_options) + "</select>"


@route("/audio-ssf/test-wav", methods=["POST"])
def audio_ssf_test_wav():
    wav_file = (
        request.form.get("wav_file", "")
        or request.form.get("file", "")
        or request.form.get("wav", "")
    ).strip()

    device = (
        request.form.get("device", "")
        or request.form.get("alsa_device", "")
        or request.form.get("output", "")
    ).strip()

    if not wav_file:
        return audio_reponse_lisible(
            "Aucun fichier WAV sélectionné",
            ["Choisis un fichier dans la liste, puis relance la lecture."],
            ok=False,
        )

    if not device:
        return audio_reponse_lisible(
            "Aucune sortie sélectionnée",
            ["Choisis une sortie dans la liste, puis relance la lecture."],
            ok=False,
        )

    wav_path = Path(wav_file)

    try:
        resolved = wav_path.resolve()
    except Exception as e:
        return audio_reponse_lisible("Chemin WAV invalide", [str(e)], ok=False)

    allowed_roots = [
        Path("/opt/pincabos/media").resolve(),
        Path("/home/pinball/Share").resolve(),
    ]

    if not resolved.exists() or not resolved.is_file():
        return audio_reponse_lisible("Fichier WAV absent", [str(resolved)], ok=False)

    if resolved.suffix.lower() not in [".wav", ".wave"]:
        return audio_reponse_lisible("Ce fichier n\'est pas un WAV", [str(resolved)], ok=False)

    if not any(str(resolved).startswith(str(root) + "/") or resolved == root for root in allowed_roots):
        return audio_reponse_lisible(
            "Chemin WAV non autorisé", [str(resolved)], ok=False,
        )

    # Nettoie les anciens tests et les captures VU courtes avant lecture.
    for kill_cmd in [
        ["/usr/bin/pkill", "-x", "aplay"],
        ["/usr/bin/pkill", "-x", "pw-play"],
        ["/usr/bin/pkill", "-x", "parec"],
        ["/usr/bin/pkill", "-f", "pincabos-audio-wav-test"],
    ]:
        try:
            subprocess.run(kill_cmd, timeout=2)
        except Exception:
            pass

    # PINCABOS_AUDIO_WAV_PIPEWIRE_V1
    # Une sortie PipeWire choisie explicitement est utilisee telle quelle ;
    # sinon on cherche celle qui correspond a la carte ALSA demandee. L'acces
    # direct ne reste qu'en dernier recours : PipeWire tient les cartes en
    # permanence, il repondra « Device or resource busy ».
    if device.startswith("pw:"):
        sink = device[3:]
    else:
        card, dev = audio_parse_alsa_hw(device)
        sink = audio_pactl_find_sink_for_alsa_card(card) if card != "" else ""

    if sink:
        cmd = audio_session_prefix() + [
            "/usr/bin/pw-play", "--target", sink, str(resolved),
        ]
        printable = f"pw-play --target {sink} {resolved}"
    else:
        cmd = ["/usr/bin/aplay", "-D", device, str(resolved)]
        printable = " ".join(cmd)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            stdout, stderr = proc.communicate(timeout=1.0)
            out = [
                "Commande: " + printable,
                "Code retour: " + str(proc.returncode),
            ]
            if stdout:
                out += ["", "STDOUT:", stdout]
            if stderr:
                out += ["", "STDERR:", stderr]
            return audio_reponse_lisible(
                "Lecture terminée" if proc.returncode == 0 else "Lecture en échec",
                out, ok=proc.returncode == 0,
            )

        except subprocess.TimeoutExpired:
            return audio_reponse_lisible(
                "Lecture en cours",
                [f"Fichier : {resolved}",
                 f"Sortie  : {sink or device}",
                 f"Routage : {'PipeWire' if sink else 'accès direct ALSA'}",
                 "",
                 "Utilise « Stop audio » pour interrompre."],
                ok=True,
            )

    except Exception as e:
        return audio_reponse_lisible("Lancement impossible", [str(e)], ok=False)


@route("/audio-ssf/test-wav-stop", methods=["POST"])
def audio_ssf_test_wav_stop_fixed():
    out = []
    for cmd in [
        ["/usr/bin/pkill", "-x", "aplay"],
        ["/usr/bin/pkill", "-x", "pw-play"],
        ["/usr/bin/pkill", "-x", "parec"],
        ["/usr/bin/pkill", "-f", "pincabos-audio-wav-test"],
    ]:
        try:
            r = subprocess.run(cmd, text=True, capture_output=True, timeout=3)
            out.append(" ".join(cmd) + f" => {r.returncode}")
        except Exception as e:
            out.append(" ".join(cmd) + f" => ERREUR {e}")
    return audio_reponse_lisible("Lecture interrompue", out, ok=True)




# ---- Fixed routes that were referenced by the page but absent from the legacy app. ----
@route("/audio-ssf/save", methods=["POST"])
def audio_ssf_save():
    cfg = audio_load_config()

    backglass = request.form.get(
        "backbox_device",
        (
            audio_ini_read_key(
                str(PINCABOS_VPX_AUDIO_INI),
                "Player",
                "SoundDeviceBG",
            )
            or ""
        ),
    ).strip()

    playfield = request.form.get(
        "playfield_device",
        (
            audio_ini_read_key(
                str(PINCABOS_VPX_AUDIO_INI),
                "Player",
                "SoundDevice",
            )
            or ""
        ),
    ).strip()

    sound3d = request.form.get(
        "sound3d",
        (
            audio_ini_read_key(
                str(PINCABOS_VPX_AUDIO_INI),
                "Player",
                "Sound3D",
            )
            or "0"
        ),
    ).strip()

    try:
        backglass = _pco_vpx_validate_device(
            backglass
        )

        playfield = _pco_vpx_validate_device(
            playfield
        )

        sound3d = _pco_vpx_validate_sound3d(
            sound3d
        )

        # Préserve les anciens champs PinCabOS.
        for key in (
            "audio_mode",
            "audio_backend",
            "backbox_device",
            "playfield_device",
            "surround_device",
            "bass_device",
            "ssf_mode",
        ):
            if key in request.form:
                cfg[key] = request.form.get(
                    key,
                    "",
                ).strip()

        for key in (
            "invert_lr",
            "invert_front_rear",
            "enable_bass",
            "night_mode",
        ):
            if key in request.form:
                cfg[key] = (
                    request.form.get(key) == "1"
                )

        cfg["backbox_device"] = backglass
        cfg["playfield_device"] = playfield
        cfg["sound3d"] = sound3d

        cfg["ssf_mode"] = (
            _pco_vpx_mode_from_sound3d(sound3d)
        )

        audio_save_config(cfg)

        output_lines = []

        # Préserve l’ancien comportement PinCabOS,
        # notamment muteaudio=false dans VPinFE.
        try:
            legacy_output = (
                audio_apply_to_vpx_vpinfe()
            )

            if legacy_output:
                output_lines.append(
                    str(legacy_output).strip()
                )

        except Exception as legacy_error:
            output_lines.append(
                "AVERTISSEMENT application PinCabOS "
                "existante : "
                + str(legacy_error)
            )

        # Écriture finale exacte dans VPinballX.ini.
        output_lines.extend(
            _pco_vpx_write_audio(
                backglass,
                playfield,
                sound3d,
            )
        )

        return page(
            "Audio / SSF V2",
            """
<div class="card">
  <h2>Configuration audio VPX sauvegardée</h2>

  <p class="ok">
    Les clés officielles de VPinballX.ini ont été
    écrites et relues avec succès.
  </p>

  <pre>"""
            + esc(
                "\n".join(output_lines)
                or "GO"
            )
            + """</pre>

  <p class="warn">
    Ferme et relance VPX pour appliquer
    le nouveau routage.
  </p>

  <p>
    <a class="button" href="/audio-ssf">
      Retour Audio / SSF
    </a>
  </p>
</div>
""",
        )

    except Exception as exc:
        return page(
            "Audio / SSF V2",
            """
<div class="card">
  <h2>Erreur de sauvegarde audio VPX</h2>

  <p class="bad">
    <code>"""
            + esc(str(exc))
            + """</code>
  </p>

  <p>
    VPinballX.ini est sauvegardé avant
    chaque écriture.
  </p>

  <p>
    <a
      class="button secondary"
      href="/audio-ssf"
    >
      Retour Audio / SSF
    </a>
  </p>
</div>
""",
        ), 500

@route("/audio-ssf/commander", methods=["GET"])
def audio_ssf_commander_page():
    values, error = ssf_commander_read_controller()
    rows = []
    for key, label in PINCABOS_SSF_EFFECTS:
        rows.append(
            "<tr><td><strong>" + esc(label) + "</strong><br><code>" + esc(key) + "</code></td><td>" +
            ssf_commander_select_html(key, values.get(key, "")) + "</td></tr>"
        )
    force = str(values.get("ForceDisableB2S", "0")).strip()
    force0 = " selected" if force != "1" else ""
    force1 = " selected" if force == "1" else ""
    warning = ("<p class='warn'>" + esc(error) + "</p>") if error else ""
    return page("SSF Commander", """
<div class="card">
  <h1>🎚️ SSF Commander</h1>
  <p>Configure le comportement Sons / Mécanique pour les effets VPX dans <code>[Controller]</code>.</p>
  """ + warning + """
  <form method="post" action="/audio-ssf/commander/save">
    <table>
      <tr><th>Effet</th><th>Mode</th></tr>
      <tr><td><strong>Force Disable B2S</strong></td><td><select name="ForceDisableB2S"><option value="0""" + force0 + """>Non</option><option value="1""" + force1 + """>Oui</option></select></td></tr>
      """ + "".join(rows) + """
    </table>
    <p><button class="button" type="submit">Sauvegarder SSF Commander</button>
    <a class="button secondary" href="/audio-ssf">Retour Audio / SSF</a></p>
  </form>
</div>
""")


@route("/audio-ssf/commander/save", methods=["POST"])
def audio_ssf_commander_save():
    values = {"ForceDisableB2S": request.form.get("ForceDisableB2S", "0")}
    for key, _label in PINCABOS_SSF_EFFECTS:
        values[key] = request.form.get(key, "")
    try:
        backup = ssf_commander_write_controller(values)
        return page("SSF Commander", """
<div class="card"><h2>SSF Commander sauvegardé</h2>
<p class="ok">La section <code>[Controller]</code> a été mise à jour.</p>
<p>Backup : <code>""" + esc(backup) + """</code></p>
<p><a class="button" href="/audio-ssf/commander">Retour SSF Commander</a></p></div>
""")
    except Exception as exc:
        return page("SSF Commander", """
<div class="card"><h2>Erreur SSF Commander</h2>
<p class="bad"><code>""" + esc(str(exc)) + """</code></p>
<p><a class="button secondary" href="/audio-ssf/commander">Retour</a></p></div>
"""), 500


@route("/audio")
def pincabos_audio_page_alias():
    return redirect("/audio-ssf", code=302)
