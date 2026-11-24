"""Sauvegardes de la base (module backup + options de la CLI)."""
import sqlite3

import pytest
from typer.testing import CliRunner

from dna_sample_manager import cli
from dna_sample_manager.backup import (
    backup_database, default_backup_dir, list_backups, prune_backups, start_periodic_backups,
)


def make_db(path, rows=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE tube (id INTEGER PRIMARY KEY, barcode TEXT)')
    con.executemany('INSERT INTO tube (barcode) VALUES (?)', [(f'T{i}',) for i in range(rows)])
    con.commit()
    con.close()
    return path


def barcodes(path):
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute('SELECT barcode FROM tube ORDER BY id')]
    finally:
        con.close()


def test_sauvegarde_copie_complete_et_verifiee(tmp_path):
    db = make_db(tmp_path / 'dna_samples.db')
    dest = backup_database(db)
    assert dest.parent == default_backup_dir(db) == tmp_path / 'backups'
    assert dest.name.startswith('dna_samples_') and dest.suffix == '.db'
    assert barcodes(dest) == ['T0', 'T1', 'T2']
    assert not list(dest.parent.glob('*.tmp'))  # pas de fichier temporaire résiduel


def test_sauvegarde_lisible_uniquement_par_le_proprietaire(tmp_path):
    db = make_db(tmp_path / 'dna_samples.db')
    dest = backup_database(db)
    assert dest.stat().st_mode & 0o777 == 0o600
    assert dest.parent.stat().st_mode & 0o777 == 0o700


def test_sauvegarde_independante_de_la_source(tmp_path):
    db = make_db(tmp_path / 'dna_samples.db')
    dest = backup_database(db)
    con = sqlite3.connect(db)
    con.execute("DELETE FROM tube")
    con.commit()
    con.close()
    assert barcodes(dest) == ['T0', 'T1', 'T2']


def test_sauvegarde_pendant_une_ecriture_en_cours(tmp_path):
    """L'app peut écrire pendant la sauvegarde : seules les données validées sont copiées."""
    db = make_db(tmp_path / 'dna_samples.db')
    writer = sqlite3.connect(db, isolation_level=None)
    writer.execute('BEGIN')
    writer.execute("INSERT INTO tube (barcode) VALUES ('NON-VALIDE')")
    try:
        dest = backup_database(db)
    finally:
        writer.execute('ROLLBACK')
        writer.close()
    assert barcodes(dest) == ['T0', 'T1', 'T2']


def test_chemin_avec_caracteres_speciaux(tmp_path):
    """Ex. volume réseau /Volumes/@ghfc/... : le chemin doit être correctement échappé."""
    db = make_db(tmp_path / '@ghfc' / 'mon dossier' / 'dna_samples.db')
    assert barcodes(backup_database(db)) == ['T0', 'T1', 'T2']


def test_dossier_de_sauvegarde_personnalise(tmp_path):
    db = make_db(tmp_path / 'dna_samples.db')
    dest = backup_database(db, backup_dir=tmp_path / 'ailleurs' / 'bk')
    assert dest.parent == tmp_path / 'ailleurs' / 'bk'


def test_rotation_garde_les_plus_recentes(tmp_path):
    db = make_db(tmp_path / 'dna_samples.db')
    created = [backup_database(db, keep=100) for _ in range(12)]  # même seconde -> suffixes _1.._11
    assert list_backups(db) == created  # ordre chronologique, y compris _10 / _11
    removed = prune_backups(db, keep=3)
    assert removed == created[:9]
    assert list_backups(db) == created[-3:]


def test_rotation_automatique_et_fichiers_etrangers_intacts(tmp_path):
    db = make_db(tmp_path / 'dna_samples.db')
    bk = default_backup_dir(db)
    bk.mkdir()
    foreign = [bk / 'notes.txt', bk / 'autre_base_2026-01-01_000000.db', bk / 'dna_samples_manuel.db']
    for f in foreign:
        f.write_text('x')
    for _ in range(4):
        backup_database(db, keep=2)
    assert len(list_backups(db)) == 2
    assert all(f.exists() for f in foreign)


def test_base_introuvable(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / 'absente.db')
    assert not (tmp_path / 'backups').exists() or not any((tmp_path / 'backups').iterdir())


def test_sauvegarde_periodique(tmp_path):
    db = make_db(tmp_path / 'dna_samples.db')
    logs = []
    stop = start_periodic_backups(db, keep=5, interval_hours=0.2 / 3600, log=logs.append)  # 0,2 s
    try:
        for _ in range(50):
            if len(list_backups(db)) >= 2:
                break
            import time
            time.sleep(0.1)
    finally:
        stop.set()
    assert len(list_backups(db)) >= 2
    assert all(msg.startswith('Sauvegarde : ') for msg in logs)


def test_sauvegarde_periodique_survit_a_une_erreur(tmp_path):
    logs = []
    stop = start_periodic_backups(tmp_path / 'absente.db', interval_hours=0.1 / 3600, log=logs.append)
    import time
    time.sleep(0.5)
    stop.set()
    assert len(logs) >= 2 and all(msg.startswith('ERREUR') for msg in logs)


# --- CLI -------------------------------------------------------------------

def test_cli_backup_only(tmp_path, monkeypatch):
    db = make_db(tmp_path / 'dna_samples.db')
    monkeypatch.setattr('dna_sample_manager.app.create_app',
                        lambda **kw: pytest.fail('le serveur ne doit pas démarrer'))
    result = CliRunner().invoke(cli.app, [str(tmp_path), '--backup-only', '--keep', '2'])
    assert result.exit_code == 0, result.output
    assert 'Sauvegarde :' in result.output
    assert len(list_backups(db)) == 1


def test_cli_backup_only_erreur(tmp_path):
    (tmp_path / 'vide').mkdir()
    result = CliRunner().invoke(cli.app, [str(tmp_path / 'vide'), '--backup-only'])
    assert result.exit_code == 1


class FakeApp:
    def __init__(self):
        self.ran = False


def _patch_server(monkeypatch, calls):
    fake = FakeApp()

    def fake_create_app(db_path, behind_proxy=False):
        calls.append(('create_app', db_path))
        return fake

    def fake_serve(application, **kw):
        application.ran = True

    monkeypatch.setattr('dna_sample_manager.app.create_app', fake_create_app)
    monkeypatch.setattr(cli, 'serve', fake_serve)
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: None)
    monkeypatch.setattr(cli, 'start_periodic_backups',
                        lambda *a, **kw: calls.append(('periodic', a[3])))
    return fake


def test_cli_demarrage_sauvegarde_avant_create_app(tmp_path, monkeypatch):
    db = make_db(tmp_path / 'dna_samples.db')
    calls = []
    fake = _patch_server(monkeypatch, calls)
    original = cli.backup_database

    def spy(*a, **kw):
        calls.append(('backup',))
        return original(*a, **kw)

    monkeypatch.setattr(cli, 'backup_database', spy)
    result = CliRunner().invoke(cli.app, [str(tmp_path), '--backup-interval', '12', '--no-browser'])
    assert result.exit_code == 0, result.output
    assert [c[0] for c in calls] == ['backup', 'periodic', 'create_app']
    assert ('periodic', 12.0) in calls
    assert fake.ran and len(list_backups(db)) == 1


def test_cli_no_backup(tmp_path, monkeypatch):
    db = make_db(tmp_path / 'dna_samples.db')
    calls = []
    _patch_server(monkeypatch, calls)
    result = CliRunner().invoke(cli.app, [str(tmp_path), '--no-backup', '--no-browser'])
    assert result.exit_code == 0, result.output
    assert [c[0] for c in calls] == ['create_app']
    assert list_backups(db) == []
