"""Tubes : statuts de volume, archivage, filtres, export."""
import pytest

from dna_sample_manager.app import Tube


# --- Statuts ---------------------------------------------------------------

@pytest.mark.parametrize('current, initial, expected', [
    (None, 100, 'Empty'),
    (0, 100, 'Empty'),
    (-1, 100, 'Empty'),
    (0.5, 100, 'Critical'),
    (9.99, 100, 'Critical'),
    (10, 100, 'Low'),        # >= 10 mais < 25 % de 100
    (24.9, 100, 'Low'),
    (25, 100, 'Available'),  # exactement 25 %
    (10, None, 'Available'), # pas de volume initial -> jamais Low
    (10, 20, 'Available'),
    (500, 100, 'Available'),
])
def test_get_status(current, initial, expected):
    assert Tube(current_volume=current, initial_volume=initial).get_status() == expected


def test_statuts_du_jeu_de_donnees(tech):
    by_barcode = {t['barcode']: t['status'] for t in tech.get('/api/tubes').get_json()}
    assert by_barcode == {
        'T-AVAIL': 'Available', 'T-LOW': 'Low', 'T-CRIT': 'Critical',
        'T-EMPTY': 'Empty', 'T-NULLVOL': 'Empty', 'T-NOINIT': 'Available',
    }


def test_filtre_sql_coherent_avec_get_status(tech):
    """Le filtre ?status= (SQL) doit renvoyer exactement les tubes de ce statut (Python)."""
    cases = [(None, 100), (0, 100), (5, 100), (9.99, 100), (10, 100), (24.9, 100),
             (25, 100), (10, None), (80, None), (30, 40)]
    for i, (current, initial) in enumerate(cases):
        r = tech.post('/api/tubes', json={'barcode': f'B-{i:02d}', 'current_volume': current,
                                          'initial_volume': initial})
        assert r.status_code == 201
    all_tubes = tech.get('/api/tubes?limit=5000').get_json()
    for status in ('Empty', 'Critical', 'Low', 'Available'):
        expected = {t['barcode'] for t in all_tubes if t['status'] == status}
        got = {t['barcode'] for t in tech.get(f'/api/tubes?status={status}&limit=5000').get_json()}
        assert got == expected, status


# --- Archivage ---------------------------------------------------------------

def form_payload(tube, **overrides):
    """Reproduit exactement ce qu'envoie saveTube() dans tubes.html (valeurs en chaînes)."""
    data = {
        'barcode': tube['barcode'],
        'sample_id': str(tube['sample_id']) if tube['sample_id'] else None,
        'box_id': str(tube['box_id']) if tube['box_id'] else None,
        'position_row': str(tube['position_row']) if tube['position_row'] else None,
        'position_col': str(tube['position_col']) if tube['position_col'] else None,
        'concentration': str(tube['concentration']) if tube['concentration'] else None,
        'initial_volume': str(tube['initial_volume']) if tube['initial_volume'] else None,
        'current_volume': str(tube['current_volume']) if tube['current_volume'] else None,
        'quality': tube['quality'],
        'source': tube['source'],
        'tube_type': tube['tube_type'],
        'notes': tube['notes'] or '',
    }
    data.update(overrides)
    return data


def test_archivage_via_formulaire_libere_la_position(tech, seed, get_tube):
    """Régression : le formulaire renvoie l'ancienne boîte/position, qui ne doit pas être réécrite."""
    tube_id = seed['tubes']['available']
    tube = tech.get(f'/api/tubes/{tube_id}').get_json()
    assert tube['box_id'] and tube['position_row']

    r = tech.put(f'/api/tubes/{tube_id}', json=form_payload(tube, tube_type='deleted'))
    assert r.status_code == 200

    t = get_tube(tube_id)
    assert t.tube_type == 'deleted'
    assert (t.box_id, t.position_row, t.position_col) == (None, None, None)
    assert t.sample_id == seed['sample']  # l'échantillon n'est pas perdu
    assert '[Archivé le' in t.notes and 'BOX-1' in t.notes and 'A1' in t.notes


def test_archivage_via_formulaire_garde_les_notes_saisies(tech, seed, get_tube):
    """Régression : les notes du formulaire écrasaient le préfixe « [Archivé le …] »."""
    tube_id = seed['tubes']['available']
    tube = tech.get(f'/api/tubes/{tube_id}').get_json()
    tech.put(f'/api/tubes/{tube_id}', json=form_payload(tube, tube_type='deleted', notes='tube cassé'))
    lines = get_tube(tube_id).notes.split('\n')
    assert lines[0].startswith('[Archivé le') and 'Position: A1' in lines[0]
    assert lines[1] == 'tube cassé'


def test_archivage_tube_sans_position_garde_les_notes(tech, seed, get_tube):
    tube_id = seed['tubes']['no_initial']  # pas de boîte
    tech.put(f'/api/tubes/{tube_id}', json={'tube_type': 'deleted', 'notes': 'perdu'})
    t = get_tube(tube_id)
    assert t.tube_type == 'deleted' and t.notes == 'perdu'


def test_archivage_minimal(tech, seed, get_tube):
    tube_id = seed['tubes']['low']
    assert tech.put(f'/api/tubes/{tube_id}', json={'tube_type': 'deleted'}).status_code == 200
    t = get_tube(tube_id)
    assert (t.box_id, t.position_row, t.position_col) == (None, None, None)
    assert 'A2' in t.notes


def test_tube_archive_ne_reprend_pas_de_position(tech, seed, get_tube):
    """Modifier un tube déjà archivé (ex. ses notes) ne doit pas lui redonner une place."""
    tube_id = seed['tubes']['available']
    tech.put(f'/api/tubes/{tube_id}', json={'tube_type': 'deleted'})
    r = tech.put(f'/api/tubes/{tube_id}', json={'notes': 'modif', 'box_id': seed['box'],
                                                 'position_row': 5, 'position_col': 5})
    assert r.status_code == 200
    t = get_tube(tube_id)
    assert (t.box_id, t.position_row) == (None, None)
    assert t.notes == 'modif'


def test_desarchivage_avec_nouvelle_position(tech, seed, get_tube):
    tube_id = seed['tubes']['available']
    tech.put(f'/api/tubes/{tube_id}', json={'tube_type': 'deleted'})
    r = tech.put(f'/api/tubes/{tube_id}', json={'tube_type': 'stock', 'box_id': seed['box'],
                                                 'position_row': 2, 'position_col': 7})
    assert r.status_code == 200
    t = get_tube(tube_id)
    assert (t.tube_type, t.box_id, t.position_row, t.position_col) == ('stock', seed['box'], 2, 7)


def test_tubes_archives_masques_par_defaut(tech, seed):
    tech.put(f"/api/tubes/{seed['tubes']['critical']}", json={'tube_type': 'deleted'})
    default = {t['barcode'] for t in tech.get('/api/tubes').get_json()}
    archived = {t['barcode'] for t in tech.get('/api/tubes?type=deleted').get_json()}
    assert 'T-CRIT' not in default
    assert archived == {'T-CRIT'}


def test_tube_sans_type_reste_visible(app, tech, seed):
    from dna_sample_manager.app import db
    with app.app_context():
        db.session.get(Tube, seed['tubes']['empty']).tube_type = None
        db.session.commit()
    assert 'T-EMPTY' in {t['barcode'] for t in tech.get('/api/tubes').get_json()}


def test_basculer_stock_working_garde_l_echantillon(tech, seed, get_tube):
    tube_id = seed['tubes']['available']
    r = tech.put(f'/api/tubes/{tube_id}', json={'tube_type': 'working', 'sample_id': None, 'box_id': None})
    assert r.status_code == 200
    t = get_tube(tube_id)
    assert t.tube_type == 'working'
    assert t.sample_id == seed['sample'] and t.box_id == seed['box']


def test_code_barres_en_double_refuse(tech):
    r = tech.post('/api/tubes', json={'barcode': 'T-AVAIL'})
    assert r.status_code == 400


def test_suppression_tube_avec_historique_refusee(tech, seed):
    tube_id = seed['tubes']['available']
    tech.post('/api/usages', json={'tube_id': tube_id, 'volume_taken': 1})
    assert tech.delete(f'/api/tubes/{tube_id}').status_code == 400


# --- Export ----------------------------------------------------------------

def test_export_tsv(tech):
    r = tech.get('/api/tubes/export?format=tsv')
    assert r.status_code == 200
    assert r.data.startswith(b'\xef\xbb\xbf')  # BOM utf-8-sig pour Excel Windows
    text = r.data.decode('utf-8-sig')
    assert text.splitlines()[0].startswith('Barcode\t')
    assert 'T-AVAIL' in text


def test_export_xlsx(tech):
    r = tech.get('/api/tubes/export?format=xlsx&status=Critical')
    assert r.status_code == 200
    assert r.data[:2] == b'PK'  # fichier zip (xlsx)
