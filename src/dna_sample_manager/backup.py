"""Sauvegarde de la base SQLite.

- Copie cohérente via l'API de sauvegarde de SQLite (`Connection.backup`) : sûre même
  pendant que l'application tourne et écrit dans la base (contrairement à un `cp`).
- Copie écrite dans un fichier temporaire, vérifiée (`PRAGMA integrity_check`), puis
  renommée : une sauvegarde présente dans le dossier est toujours complète.
- Rotation : seules les `keep` sauvegardes les plus récentes sont conservées.
  Seuls les fichiers créés par ce module (`<nom>_AAAA-MM-JJ_HHMMSS.db`) sont supprimés.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DEFAULT_KEEP = 30
DEFAULT_INTERVAL_HOURS = 24
_TIMESTAMP_FORMAT = '%Y-%m-%d_%H%M%S'


def default_backup_dir(db_path: Path) -> Path:
    return Path(db_path).parent / 'backups'


def _backup_pattern(stem: str) -> re.Pattern:
    return re.compile(rf'^{re.escape(stem)}_(\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}})(?:_(\d+))?\.db$')


def list_backups(db_path: Path, backup_dir: Path | None = None) -> list[Path]:
    """Sauvegardes existantes de cette base, de la plus ancienne à la plus récente."""
    db_path = Path(db_path)
    backup_dir = Path(backup_dir) if backup_dir else default_backup_dir(db_path)
    if not backup_dir.is_dir():
        return []
    pattern = _backup_pattern(db_path.stem)
    found = []
    for p in backup_dir.iterdir():
        m = pattern.match(p.name)
        if m and p.is_file():
            # (horodatage triable, numéro si plusieurs sauvegardes dans la même seconde)
            found.append(((m.group(1), int(m.group(2) or 0)), p))
    return [p for _, p in sorted(found)]


def prune_backups(db_path: Path, backup_dir: Path | None = None, keep: int = DEFAULT_KEEP) -> list[Path]:
    """Supprime les sauvegardes les plus anciennes au-delà de `keep`. Renvoie les fichiers supprimés."""
    if keep < 1:
        raise ValueError('keep doit être >= 1')
    backups = list_backups(db_path, backup_dir)
    removed = backups[:-keep] if len(backups) > keep else []
    for path in removed:
        path.unlink()
    return removed


def backup_database(db_path: Path, backup_dir: Path | None = None, keep: int = DEFAULT_KEEP) -> Path:
    """Crée une sauvegarde vérifiée de `db_path` et applique la rotation. Renvoie le fichier créé."""
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f'Base introuvable : {db_path}')
    backup_dir = Path(backup_dir) if backup_dir else default_backup_dir(db_path)
    if not backup_dir.exists():
        backup_dir.mkdir(parents=True)
        _restrict(backup_dir, 0o700)  # données personnelles : dossier réservé au propriétaire

    stamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    dest = backup_dir / f'{db_path.stem}_{stamp}.db'
    n = 1
    while dest.exists():  # deux sauvegardes dans la même seconde
        dest = backup_dir / f'{db_path.stem}_{stamp}_{n}.db'
        n += 1
    tmp = dest.with_name(dest.name + '.tmp')

    # Lecture seule sur la base source (URI correctement échappée : chemins avec @, espaces...)
    src = sqlite3.connect(f'{db_path.as_uri()}?mode=ro', uri=True, timeout=30)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            result = dst.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            dst.close()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        src.close()

    if result != 'ok':
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f'Sauvegarde corrompue (integrity_check : {result})')

    _restrict(tmp, 0o600)  # pas plus lisible que nécessaire (la base contient des données personnelles)
    tmp.replace(dest)
    prune_backups(db_path, backup_dir, keep)
    return dest


def _restrict(path: Path, mode: int) -> None:
    """chmod best effort (peut être refusé/ignoré sur certains volumes réseau)."""
    try:
        path.chmod(mode)
    except OSError:
        pass


def start_periodic_backups(db_path: Path, backup_dir: Path | None = None, keep: int = DEFAULT_KEEP,
                           interval_hours: float = DEFAULT_INTERVAL_HOURS,
                           log=print) -> threading.Event:
    """Lance un thread qui sauvegarde la base toutes les `interval_hours` heures.

    La première sauvegarde a lieu après un intervalle (celle du démarrage est faite à part).
    Une erreur est affichée mais n'arrête ni le thread ni l'application.
    Renvoie un Event : `event.set()` arrête le thread.
    """
    stop = threading.Event()

    def run():
        while not stop.wait(interval_hours * 3600):
            try:
                path = backup_database(db_path, backup_dir, keep)
                log(f'Sauvegarde : {path}')
            except Exception as e:  # ne jamais faire tomber l'application
                log(f'ERREUR de sauvegarde : {e}')

    threading.Thread(target=run, name='db-backup', daemon=True).start()
    return stop
