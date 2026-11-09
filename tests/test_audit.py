"""Journal des modifications (audit_log)."""
from dna_sample_manager.app import AuditLog, Box, db


def audit(client, **params):
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    return client.get(f'/api/audit?{query}').get_json()


def test_modification_tube_tracee_avec_avant_apres(tech, seed):
    tube_id = seed['tubes']['available']
    tech.put(f'/api/tubes/{tube_id}', json={'concentration': 42.0, 'notes': 'note'})
    [entry] = audit(tech, entity='tube', entity_id=tube_id)
    assert entry['action'] == 'update'
    assert entry['username'] == 'tech' and entry['user_id'] == seed['tech']
    assert entry['label'] == 'T-AVAIL'
    assert entry['changes'] == {'concentration': [100.0, 42.0], 'notes': [None, 'note']}
    assert entry['timestamp'].endswith('+00:00')


def test_modification_sans_changement_non_tracee(tech, seed):
    tube_id = seed['tubes']['available']
    tech.put(f'/api/tubes/{tube_id}', json={'concentration': 100.0})  # même valeur
    assert audit(tech, entity='tube', entity_id=tube_id) == []


def test_archivage_trace(tech, seed):
    tube_id = seed['tubes']['available']
    tech.put(f'/api/tubes/{tube_id}', json={'tube_type': 'deleted'})
    [entry] = audit(tech, entity='tube', entity_id=tube_id)
    assert entry['changes']['tube_type'] == ['stock', 'deleted']
    assert entry['changes']['box_id'] == [seed['box'], None]
    assert entry['changes']['position_row'] == [1, None]


def test_creation_et_suppression_tracees(tech):
    tube = tech.post('/api/tubes', json={'barcode': 'NEW-1', 'current_volume': 30}).get_json()
    tech.delete(f"/api/tubes/{tube['id']}")
    entries = audit(tech, search='NEW-1')
    assert [e['action'] for e in entries] == ['delete', 'create']
    assert entries[1]['entity_id'] == tube['id']
    assert entries[1]['changes']['current_volume'] == 30
    assert 'notes' not in entries[1]['changes']  # champs vides omis


def test_usage_trace_avec_baisse_de_volume(tech, seed):
    tube_id = seed['tubes']['available']
    tech.post('/api/usages', json={'tube_id': tube_id, 'volume_taken': 5, 'purpose': 'PCR'})
    [usage_entry] = audit(tech, entity='usage')
    assert usage_entry['action'] == 'create'
    assert usage_entry['label'] == 'tube T-AVAIL'
    assert usage_entry['changes']['purpose'] == 'PCR'
    [tube_entry] = audit(tech, entity='tube', entity_id=tube_id)
    assert tube_entry['changes']['current_volume'] == [50.0, 45.0]
    # recherche par code-barres : trouve le tube et l'usage
    assert {e['entity'] for e in audit(tech, search='T-AVAIL')} == {'tube', 'usage'}


def test_mot_de_passe_jamais_dans_le_journal(admin, seed):
    admin.put(f"/api/users/{seed['tech']}", json={'password': 'nouveau-secret'})
    [entry] = audit(admin, entity='user', action='update')
    assert entry['changes']['password_hash'] == ['***', '*** (modifié)']
    body = admin.get('/api/audit?limit=2000').get_data(as_text=True)
    assert 'nouveau-secret' not in body and '$2b$' not in body


def test_entrees_utilisateurs_reservees_aux_admins(admin, tech):
    admin.post('/api/users', json={'username': 'x', 'password': 'xxxx'})
    assert audit(admin, entity='user')
    assert audit(tech, entity='user') == []
    assert all(e['entity'] != 'user' for e in audit(tech, limit=2000))


def test_filtres(tech, admin, seed):
    tech.put(f"/api/tubes/{seed['tubes']['low']}", json={'notes': 'a'})
    admin.put(f"/api/tubes/{seed['tubes']['critical']}", json={'notes': 'b'})
    assert [e['label'] for e in audit(tech, user='tech', entity='tube')] == ['T-LOW']
    assert [e['label'] for e in audit(tech, user='admin_test', entity='tube')] == ['T-CRIT']
    assert len(audit(tech, entity='tube', limit=1)) == 1


def test_modification_hors_requete_attribuee_au_systeme(app):
    """Scripts d'import / shell : auteur = 'système'."""
    with app.app_context():
        db.session.add(Box(name='BOX-SCRIPT'))
        db.session.commit()
        entry = AuditLog.query.filter_by(label='BOX-SCRIPT').one()
        assert entry.username == 'système' and entry.user_id is None
