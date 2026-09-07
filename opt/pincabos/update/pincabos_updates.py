#!/usr/bin/env python3
from __future__ import annotations
import stat
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request
from pathlib import Path

CONFIG = Path('/etc/pincabos/updates.json')
STATE = Path('/var/lib/pincabos/updates/state.json')
CACHE = Path('/var/cache/pincabos/updates')
BACKUPS = Path('/opt/pincabos/backups/updates')
VERSION_FILES = [Path('/opt/pincabos/config/version.json'), Path('/opt/pincabos/version.json')]
SERVICES = ['pincabos-webapp.service','pincabos-vpinfe.service','pincabos-fulldmd.service','pincabos-dof.service']

class UpdateError(RuntimeError): pass

def load_json(path, default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception: return {} if default is None else default

def save_json(path, data):
    # PINCABOS_UPDATER_PRESERVE_METADATA_V3
    #
    # L'Updater peut tourner root.
    # os.replace() doit conserver uid/gid/mode
    # du fichier existant.

    p = Path(path)

    p.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    previous = None

    try:
        current = p.stat()

        previous = (
            current.st_uid,
            current.st_gid,
            stat.S_IMODE(current.st_mode),
        )

    except FileNotFoundError:
        pass

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{p.name}.",
        suffix=".tmp",
        dir=str(p.parent),
    )

    os.close(fd)

    temporary = Path(
        temporary_name
    )

    try:
        temporary.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )

        if previous is not None:
            uid, gid, mode = previous

            if os.geteuid() == 0:
                os.chown(
                    temporary,
                    uid,
                    gid,
                )

            os.chmod(
                temporary,
                mode,
            )

        else:
            os.chmod(
                temporary,
                0o644,
            )

        os.replace(
            temporary,
            p,
        )

    finally:
        try:
            temporary.unlink()

        except FileNotFoundError:
            pass

def config():
    d=load_json(CONFIG,{})
    return d.get('repository','PinCabOS/PinCabOS'), d.get('channel','beta')

def display_version_from_tag(tag):
    value=str(tag or '').strip()
    low=value.lower()
    if low.startswith('alpha2.'):
        core=value.split('-',1)[0]
        return 'Alpha 2.'+core.split('.',1)[1]
    return value

def local_tag():
    st=load_json(STATE,{})
    if st.get('installed_version'):
        return str(st['installed_version'])
    for p in VERSION_FILES:
        d=load_json(p,{})
        if d.get('version'):
            return str(d['version'])
    return 'unknown'

def local_version():
    st=load_json(STATE,{})
    if st.get('display_version'):
        return str(st['display_version'])
    if st.get('installed_version'):
        return display_version_from_tag(st['installed_version'])
    for p in VERSION_FILES:
        d=load_json(p,{})
        if d.get('version'):
            return str(d['version'])
    return 'unknown'

def sync_version_files(display):
    if not display:
        return
    stamp=subprocess.check_output(
        ['date','-u','+%Y-%m-%dT%H:%M:%SZ'],
        text=True
    ).strip()

    for p in VERSION_FILES:
        if not p.exists():
            continue
        d=load_json(p,{})
        if not isinstance(d,dict):
            continue
        d['version']=display
        if 'updated_at' in d:
            d['updated_at']=stamp.replace('T',' ').replace('Z','')
        if 'generated_at' in d:
            d['generated_at']=stamp
        save_json(p,d)

def api_json(url):
    req=urllib.request.Request(url, headers={'User-Agent':'PinCabOS-Updates/4','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8'))

def download(url, dest):
    req=urllib.request.Request(url, headers={'User-Agent':'PinCabOS-Updates/4','Accept':'application/octet-stream'})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest,'wb') as f:
        shutil.copyfileobj(r,f)

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

# PINCABOS_UPDATE_PENDING_PREFIXES_V1
# Un nouveau prefixe se livre en DEUX releases (voir PINCABOS_UPDATE_SCOPE_PREFIX_TRAP) :
#   release N   : le prefixe est ici, EN ATTENTE — le client installe l'accepte
#                 desormais, mais le constructeur ne l'embarque pas encore ;
#   release N+1 : le prefixe passe dans les prefixes livres (allowed) — le
#                 parc entier connait deja le nouveau perimetre.
# opt/pincabos/launchers/ n'a JAMAIS ete livre : les cabinets tournent avec la
# chaine de lancement de leur ISO (le lien pupvideos de #124, les chemins de
# #126 ne les ont jamais atteints).
# Depuis PINCABOS_UPDATER_SELF_UPDATE_V1 (3.44), les cabinets a jour installent
# d'abord l'updater de la release : le passage en deux temps ne protege plus que
# les cabinets encore en 3.43 ou moins.
PENDING_PREFIXES = (
    'opt/pincabos/launchers/',
    # PINCABOS_OVERLAYS_LIVRES_V1 : ajoute en attente ici ; a retirer a la
    # release suivante pour que les overlays partent vraiment.
    'opt/pincabos/overlays/',
    # PINCABOS_SPLASH_FROM_SCREENS_V3 : 'opt/pincabos/media/splash/' a attendu ici
    # en 3.69 ; le parc connait le prefixe depuis, les visuels partent maintenant.
)

def allowed_for_build(rel):
    """Perimetre que le CONSTRUCTEUR embarque : allowed() moins les prefixes en attente."""
    if str(rel).startswith(PENDING_PREFIXES):
        return False
    return allowed(rel)

def allowed(rel):
    # PINCABOS_UPDATE_SCOPE_V2
    # PINCABOS_UPDATE_SCOPE_PREFIX_TRAP
    # ⚠️ Ne JAMAIS ajouter ici un nouveau prefixe utilise par la release qui
    # l'introduit : le cabinet valide chaque chemin avec l'allowed() de sa
    # version INSTALLEE avant d'appliquer quoi que ce soit — updater compris.
    # Un fichier sous un prefixe inconnu fait refuser TOUTE la mise a jour
    # ("Path refused") et fige le parc. Alpha 3.25/3.26 ont ainsi ete
    # inapplicables (opt/pincabos/lib/). Un nouveau prefixe se livre en deux
    # temps : d'abord l'allowed() seul, puis les fichiers, une release plus tard.
    if not rel or rel.startswith('/') or '..' in Path(rel).parts: return False
    prefixes=(
      'opt/pincabos/web/','opt/pincabos/bin/','opt/pincabos/script/','opt/pincabos/scripts/',
      'opt/pincabos/update/','opt/pincabos/modules/','opt/pincabos/tools/','opt/pincabos/media/audio-voix/',
      'opt/pincabos/installer-gui/','opt/pincabos/apps/VPX_MultiPlayers/',
      # PINCABOS_OVERLAYS_LIVRES_V1 : les bibliotheques posees a cote des runtimes
      # (libdof pour VPX et VPinFE, surcouches DudesCab). Elles etaient hors
      # perimetre : un cab gardait la libdof de son ISO pour toujours, et l ecart
      # entre VPX et VPinFE a vecu trois mois sans pouvoir etre rattrape
      # (cab de Yann, 08/09/2026). En attente ci-dessous : les fichiers partent
      # a la release suivante, quand tout le parc connait le prefixe.
      'opt/pincabos/overlays/',
      # PINCABOS_SPLASH_FROM_SCREENS_V3 : visuels de demarrage (galeries portrait,
      # paysage, fonds GRUB). Prefixe en attente d abord (PENDING_PREFIXES), les
      # fichiers partent a la release suivante : la CI le verifie.
      'opt/pincabos/media/splash/',
      # PINCABOS_MODELES_JOUEUR_V1 : modeles du compte du joueur (en attente en 4.04, livres depuis)
      'opt/pincabos/templates/',
      'usr/local/bin/pincabos-','usr/local/sbin/pincabos-',
      'usr/local/lib/pincabos/','usr/local/libexec/pincabos/',
    )
    # Fichiers que PinCabOS ecrit lui-meme dans le compte du joueur. Chemins
    # EXACTS : ouvrir un repertoire ici autoriserait une release a ecraser les
    # donnees du joueur.
    exact={'usr/local/bin/getpcos','usr/local/sbin/getpcos',
           'home/pinball/.config/openbox/autostart'}
    if rel in exact: return True
    # Sous systemd, la regle porte sur le NOM du fichier et non sur le chemin :
    # sans cela « multi-user.target.wants/pincabos-x.service » tombe dehors et
    # l'unite arrive sans son activation.
    # PINCABOS_UPDATE_SCOPE_V3
    # Trois formes legitimes, et rien d'autre : l'unite, sa propre surcharge,
    # son lien d'activation. Un « pincabos-*.conf » depose dans le repertoire
    # de surcharge d'un service tiers n'en fait pas partie.
    if rel.startswith('etc/systemd/system/'):
        reste = rel[len('etc/systemd/system/'):].split('/')
        if len(reste) == 1:
            return reste[0].startswith('pincabos-')
        if len(reste) == 2:
            conteneur, fichier = reste
            if conteneur.endswith('.d'):
                return conteneur.startswith('pincabos-')
            if conteneur.endswith(('.wants', '.requires')):
                return fichier.startswith('pincabos-')
        return False
    # PINCABOS_UPDATE_SCOPE_V4
    # Repertoires de /etc ou un fichier de trop donne les pleins pouvoirs :
    # le fichier doit etre a nous, reconnu a son nom. Le prefixe numerique
    # d'ordonnancement est retire avant l'examen (91-pincabos-..., 99-pincab-...).
    SENSIBLES = ('etc/sudoers.d/', 'etc/polkit-1/rules.d/', 'etc/udev/rules.d/',
                 'etc/lightdm/lightdm.conf.d/', 'etc/tmpfiles.d/')
    for base in SENSIBLES:
        if rel.startswith(base):
            reste = rel[len(base):]
            # un seul niveau : ces emplacements n'ont pas de sous-repertoire
            if not reste or '/' in reste:
                return False
            return re.sub(r'^\d+[-_]', '', reste).startswith('pincab')

    if rel.startswith('home/pinball/.config/vpinfe/themes/PinCabOS/'): return True
    if rel.startswith(PENDING_PREFIXES) and '__pycache__' not in Path(rel).parts and not rel.endswith(('.pyc','.pyo')): return True
    if not rel.startswith(prefixes): return False
    forbidden=('opt/pincabos/web/.venv/','opt/pincabos/web/backups/','opt/pincabos/build/','opt/pincabos/backups/','opt/pincabos/logs/')
    return not rel.startswith(forbidden) and '__pycache__' not in Path(rel).parts and not rel.endswith(('.pyc','.pyo'))

# PINCABOS_UPDATER_LEGACY_ALIAS_V1
# Le depot a ete transfere de KarotsSugarpie/PinCabOS vers PinCabOS/PinCabOS.
# Les deux noms designent le meme depot (GitHub redirige) : la validation
# doit les traiter comme equivalents, sinon un cabinet configure avec un nom
# refuse les releases publiees sous l'autre — c'est l'oeuf-et-poule qui a
# bloque le parc sur la 3.06 juste apres le transfert (resolu par une
# release-pont 3.07 aux metadata a l'ancien nom).
# PINCABOS_UPDATER_SELF_UPDATE_V1
# L'updater contenu dans la release s'installe AVANT la validation des chemins,
# puis se relance : c'est SA table allowed() qui juge la release, plus celle de
# la version installee. Fin du piege de prefixe pour les cabinets en retard de
# plusieurs releases (3.30 -> 3.39 refusait opt/pincabos/apps/ malgre le pont
# 3.38) : ils sautent directement a la derniere. Conditions : archive deja
# verifiee (SHA256 de release.json), chemin de l'updater dans le perimetre
# courant, fichier compilable ; une seule relance (variable d'environnement).
UPDATER_REL = 'opt/pincabos/update/pincabos_updates.py'
REEXEC_ENV = 'PINCABOS_UPDATER_REEXEC'

def updater_candidate(archive, work):
    """L'updater embarque dans l'archive (extrait seul dans work), ou None."""
    try:
        subprocess.run(['tar', '--zstd', '-xf', str(archive), '-C', str(work), UPDATER_REL],
                       check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    candidate = Path(work) / UPDATER_REL
    return candidate if candidate.is_file() else None

def updater_differs(candidate, current):
    return sha256(candidate) != sha256(current)

def install_updater(candidate, current, backup):
    """Remplace l'updater en place, atomiquement, apres verification syntaxique ;
    l'ancien est copie dans backup. SyntaxError : rien n'est touche."""
    candidate, current, backup = Path(candidate), Path(current), Path(backup)
    source = candidate.read_bytes()
    compile(source, str(current), 'exec')
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current, backup)
    temporary = current.with_name(current.name + '.new')
    temporary.write_bytes(source)
    shutil.copymode(current, temporary)
    os.replace(temporary, current)

def self_update_then_reexec(archive, work, version):
    """Si la release embarque un updater different de celui qui tourne :
    l'installe et relance la meme commande avec lui (ne revient pas)."""
    current = Path(__file__).resolve()
    candidate = updater_candidate(archive, work)
    if not candidate or not allowed(UPDATER_REL) or not updater_differs(candidate, current):
        return
    if os.environ.get(REEXEC_ENV):
        print('INFO [--] updater deja relance : on poursuit avec celui en place.')
        return
    install_updater(candidate, current, CACHE / f'pincabos_updates.py.avant-{version}')
    print(f'GO [OK] Updater mis a jour depuis {version} ; relance de la mise a jour.')
    shutil.rmtree(work, ignore_errors=True)
    os.environ[REEXEC_ENV] = '1'
    sys.stdout.flush(); sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, '-u', str(current), *sys.argv[1:]])

def canonical_repo(name):
    return 'PinCabOS/PinCabOS' if str(name) == 'KarotsSugarpie/PinCabOS' else str(name)

def release():
    repo, channel=config()
    data=api_json(f'https://api.github.com/repos/{repo}/releases?per_page=30')
    for r in data:
        if r.get('draft'): continue
        if channel=='stable' and r.get('prerelease'): continue
        assets={a['name']:a for a in r.get('assets',[]) if a.get('name')}
        meta_asset=assets.get('release.json')
        if not meta_asset: continue
        try:
            meta=api_json(meta_asset['browser_download_url'])
        except Exception:
            continue
        if int(meta.get('schema',0)) < 4: continue
        if canonical_repo(meta.get('repository')) != canonical_repo(repo): continue
        if meta.get('version') != r.get('tag_name'): continue
        if channel!='dev' and meta.get('channel') != channel: continue
        meta['_release']=r; meta['_assets']=assets
        return meta
    return None

def status():
    repo, channel=config()
    print(f'Repository       : {repo}')
    print(f'Channel          : {channel}')
    display=local_version()
    if os.geteuid()==0:
        try:
            sync_version_files(display)
        except Exception:
            pass
    print(f'Installed version: {display}')
    st=load_json(STATE,{})
    if st.get('last_backup'): print(f'Last backup      : {st["last_backup"]}')

def check():
    status(); print()
    m=release()
    if not m:
        print('Available version: none compatible')
        return 2
    display=m.get('display_version') or display_version_from_tag(m["version"])
    print(f'Available version: {display}')
    print(f'Release tag      : {m["version"]}')
    print(f'Release URL      : {m["_release"].get("html_url","")}')
    return 0

def require_root():
    if os.geteuid()!=0: raise UpdateError('This command requires root.')

def validate_list(path):
    rows=[]
    for raw in Path(path).read_text(encoding='utf-8').splitlines():
        rel=raw.strip()
        if not rel: continue
        if not allowed(rel): raise UpdateError(f'Path refused: {rel}')
        rows.append(rel)
    return sorted(set(rows))

def active_services():
    out=[]
    for s in SERVICES:
        if subprocess.run(['systemctl','is-active','--quiet',s]).returncode==0: out.append(s)
    return out

def restart_services(items):
    subprocess.run(['systemctl','daemon-reload'],check=False)
    for s in items: subprocess.run(['systemctl','restart',s],check=False)

def validate_installed(rows):
    for rel in rows:
        p=Path('/')/rel
        if not p.exists() or p.is_symlink(): continue
        try: first=p.open('rb').readline(200).decode('utf-8','ignore').strip()
        except Exception: first=''
        if first.startswith('#!') and 'python' in first:
            subprocess.run(['python3','-m','py_compile',str(p)],check=True,env={**os.environ,'PYTHONPYCACHEPREFIX':'/tmp/pincabos-update-pycache'})
        elif first.startswith('#!') and ('bash' in first or first.endswith('/sh')):
            subprocess.run(['bash','-n',str(p)],check=True)
        elif rel.endswith('.py'):
            subprocess.run(['python3','-m','py_compile',str(p)],check=True,env={**os.environ,'PYTHONPYCACHEPREFIX':'/tmp/pincabos-update-pycache'})
        if rel.startswith('etc/sudoers.d/') and shutil.which('visudo'):
            subprocess.run(['visudo','-cf',str(p)],check=True,stdout=subprocess.DEVNULL)

def do_update():
    require_root()

    CACHE.mkdir(
        parents=True,
        exist_ok=True
    )

    BACKUPS.mkdir(
        parents=True,
        exist_ok=True
    )

    m = release()

    if not m:
        raise UpdateError(
            'No compatible GitHub Release found.'
        )

    if local_tag() == m['version']:
        print(
            f'GO [OK] Already up to date: '
            f'{m["version"]}'
        )
        return 0

    assets = m['_assets']

    names = [
        m.get(
            'archive',
            'pincabos-update.tar.zst'
        ),
        m.get(
            'files',
            'files.list'
        ),
        m.get(
            'remove',
            'remove.list'
        ),
    ]

    for name in names:
        if name not in assets:
            raise UpdateError(
                f'Missing Release asset: {name}'
            )

    work = Path(
        tempfile.mkdtemp(
            prefix='pincabos-update-',
            dir=str(CACHE)
        )
    )

    try:
        archive = work / names[0]
        files = work / names[1]
        remove = work / names[2]

        for name, target in zip(
            names,
            [archive, files, remove]
        ):
            download(
                assets[name][
                    'browser_download_url'
                ],
                target
            )

        expected_sha = str(
            m.get(
                'archive_sha256',
                ''
            )
        ).lower()

        actual_sha = sha256(
            archive
        ).lower()

        if actual_sha != expected_sha:
            raise UpdateError(
                'Archive SHA256 mismatch.'
            )

        # PINCABOS_UPDATER_SELF_UPDATE_V1 : l'updater de la release juge la release
        self_update_then_reexec(archive, work, m['version'])

        rows = validate_list(
            files
        )

        explicit_remove = (
            validate_list(remove)
            if remove.stat().st_size
            else []
        )

        previous_state = load_json(
            STATE,
            {}
        )

        previous_files = [
            str(x).strip()
            for x in previous_state.get(
                'installed_files',
                []
            )
            if str(x).strip()
            and allowed(str(x).strip())
        ]

        stale = sorted(
            set(previous_files)
            - set(rows)
        )

        removals = sorted(
            set(
                explicit_remove
                + stale
            )
        )

        if stale:
            print(
                'INFO [--] '
                f'{len(stale)} ancien(s) '
                'fichier(s) gere(s) '
                'seront retires.'
            )

        actual_archive = sorted(
            set(
                x.rstrip('/')
                for x
                in subprocess.check_output(
                    [
                        'tar',
                        '--zstd',
                        '-tf',
                        str(archive)
                    ],
                    text=True
                ).splitlines()
                if x
                and not x.endswith('/')
            )
        )

        if rows != actual_archive:
            raise UpdateError(
                'Archive content differs '
                'from files.list.'
            )

        stamp = subprocess.check_output(
            [
                'date',
                '+%Y%m%d-%H%M%S'
            ],
            text=True
        ).strip()

        backup_dir = (
            BACKUPS
            / stamp
        )

        backup_dir.mkdir(
            parents=True
        )

        existing = []
        new_files = []
        owners = {}

        for rel in sorted(
            set(
                rows
                + removals
            )
        ):
            target = (
                Path('/')
                / rel
            )

            if (
                target.exists()
                or target.is_symlink()
            ):
                existing.append(
                    rel
                )

                try:
                    stat = (
                        target.lstat()
                    )

                    owners[rel] = {
                        'uid': stat.st_uid,
                        'gid': stat.st_gid,
                    }

                except OSError:
                    pass

            else:
                new_files.append(
                    rel
                )

        (
            backup_dir
            / 'existing.list'
        ).write_text(
            ''.join(
                x + '\n'
                for x in existing
            ),
            encoding='utf-8'
        )

        (
            backup_dir
            / 'new.list'
        ).write_text(
            ''.join(
                x + '\n'
                for x in new_files
            ),
            encoding='utf-8'
        )

        (
            backup_dir
            / 'owners.json'
        ).write_text(
            json.dumps(
                owners,
                indent=2
            ) + '\n',
            encoding='utf-8'
        )

        (
            backup_dir
            / 'previous-version'
        ).write_text(
            local_tag()
            + '\n',
            encoding='utf-8'
        )

        (
            backup_dir
            / 'previous-state.json'
        ).write_text(
            json.dumps(
                previous_state,
                indent=2
            ) + '\n',
            encoding='utf-8'
        )

        if existing:
            subprocess.run(
                [
                    'tar',
                    '--zstd',
                    '-cpf',
                    str(
                        backup_dir
                        / 'backup.tar.zst'
                    ),
                    '-C',
                    '/',
                    '-T',
                    str(
                        backup_dir
                        / 'existing.list'
                    )
                ],
                check=True
            )

        services = active_services()

        for service in services:
            subprocess.run(
                [
                    'systemctl',
                    'stop',
                    service
                ],
                check=False
            )

        try:
            subprocess.run(
                [
                    'tar',
                    '--zstd',
                    '-xpf',
                    str(archive),
                    '-C',
                    '/'
                ],
                check=True
            )

            # Les fichiers deja existants
            # conservent leur UID/GID.
            for rel, meta in owners.items():
                target = (
                    Path('/')
                    / rel
                )

                if not (
                    target.exists()
                    or target.is_symlink()
                ):
                    continue

                try:
                    uid = int(
                        meta['uid']
                    )

                    gid = int(
                        meta['gid']
                    )

                    if target.is_symlink():
                        os.lchown(
                            target,
                            uid,
                            gid
                        )
                    else:
                        os.chown(
                            target,
                            uid,
                            gid
                        )

                except OSError as exc:
                    print(
                        'WARNING [--] '
                        'Owner restore failed '
                        f'for {rel}: {exc}'
                    )

            # Sécurité stricte sudoers.
            for rel in rows:
                if not rel.startswith(
                    'etc/sudoers.d/'
                ):
                    continue

                target = (
                    Path('/')
                    / rel
                )

                if (
                    target.exists()
                    and not target.is_symlink()
                ):
                    target.chmod(
                        0o440
                    )

            for rel in removals:
                target = (
                    Path('/')
                    / rel
                )

                if (
                    target.is_dir()
                    and not target.is_symlink()
                ):
                    shutil.rmtree(
                        target,
                        ignore_errors=True
                    )

                else:
                    try:
                        target.unlink()
                    except FileNotFoundError:
                        pass

            validate_installed(
                rows
            )

        except Exception:
            for rel in new_files:
                target = (
                    Path('/')
                    / rel
                )

                if (
                    target.is_dir()
                    and not target.is_symlink()
                ):
                    shutil.rmtree(
                        target,
                        ignore_errors=True
                    )

                else:
                    try:
                        target.unlink()
                    except FileNotFoundError:
                        pass

            backup_tar = (
                backup_dir
                / 'backup.tar.zst'
            )

            if backup_tar.exists():
                subprocess.run(
                    [
                        'tar',
                        '--zstd',
                        '-xpf',
                        str(backup_tar),
                        '-C',
                        '/'
                    ],
                    check=False
                )

            restart_services(
                services
            )

            raise

        restart_services(
            services
        )

        display = (
            m.get(
                'display_version'
            )
            or display_version_from_tag(
                m['version']
            )
        )

        reboot_required = bool(
            m.get(
                'reboot_required',
                False
            )
        )

        save_json(
            STATE,
            {
                'installed_version':
                    m['version'],

                'display_version':
                    display,

                'installed_files':
                    rows,

                'last_backup':
                    str(backup_dir),

                'channel':
                    config()[1],

                'reboot_required':
                    reboot_required,
            }
        )

        try:
            sync_version_files(
                display
            )
        except Exception as exc:
            print(
                'WARNING [--] '
                'Version files not '
                f'synchronized: {exc}'
            )

        print(
            'GO [OK] Update installed: '
            f'{display}'
        )

        print(
            'GO [OK] Release tag: '
            f'{m["version"]}'
        )

        print(
            'GO [OK] Backup: '
            f'{backup_dir}'
        )

        print(
            'Reboot required  : '
            + (
                'yes'
                if reboot_required
                else 'no'
            )
        )

        return 0

    finally:
        shutil.rmtree(
            work,
            ignore_errors=True
        )

def rollback_last():
    require_root(); st=load_json(STATE,{})
    bdir=Path(st.get('last_backup',''))
    if not bdir.is_dir(): raise UpdateError('No rollback backup available.')
    new=[x for x in (bdir/'new.list').read_text(encoding='utf-8').splitlines() if x]
    svcs=active_services()
    for s in svcs: subprocess.run(['systemctl','stop',s],check=False)
    for rel in new:
        if not allowed(rel): raise UpdateError(f'Rollback path refused: {rel}')
        p=Path('/')/rel
        if p.is_dir() and not p.is_symlink(): shutil.rmtree(p,ignore_errors=True)
        else:
            try: p.unlink()
            except FileNotFoundError: pass
    if (bdir/'backup.tar.zst').exists(): subprocess.run(['tar','--zstd','-xpf',str(bdir/'backup.tar.zst'),'-C','/'],check=True)
    prev=load_json(bdir/'previous-state.json',{})
    save_json(STATE,prev)
    restart_services(svcs)
    print(f'GO [OK] Rollback restored: {(bdir/"previous-version").read_text().strip()}')
    return 0

def main():
    ap=argparse.ArgumentParser(prog='getpcos'); ap.add_argument('command',choices=['status','check','update','rollback']); a=ap.parse_args()
    try:
        return {'status':lambda:(status() or 0),'check':check,'update':do_update,'rollback':rollback_last}[a.command]()
    except Exception as e:
        print(f'NOGO [!!] {e}',file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
