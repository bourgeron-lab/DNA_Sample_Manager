"""Usages (prélèvements) : volumes et rattachement au compte connecté."""
import pytest


def test_usage_deduit_le_volume(tech, seed, get_tube):
    tube_id = seed['tubes']['available']  # 50 µL
    r = tech.post('/api/usages', json={'tube_id': tube_id, 'volume_taken': 7.5, 'purpose': 'PCR'})
    assert r.status_code == 201
    assert get_tube(tube_id).current_volume == pytest.approx(42.5)


def test_usage_au_nom_du_compte_connecte(tech, seed):
    r = tech.post('/api/usages', json={'tube_id': seed['tubes']['available'], 'volume_taken': 1,
                                       'user_name': 'quelqu_un_d_autre', 'user_id': 999})
    usage = r.get_json()
    assert usage['user_name'] == 'tech'
    assert usage['user_id'] == seed['tech']


def test_modifier_un_usage_ne_change_pas_l_utilisateur(tech, admin, seed):
    usage = tech.post('/api/usages', json={'tube_id': seed['tubes']['available'], 'volume_taken': 1}).get_json()
    r = admin.put(f"/api/usages/{usage['id']}", json={'user_name': 'autre', 'purpose': 'corrigé'})
    assert r.get_json()['user_name'] == 'tech'
    assert r.get_json()['purpose'] == 'corrigé'


@pytest.mark.parametrize('volume, message', [
    (51, 'insuffisant'),
    (0, 'positif'),
    (-3, 'positif'),
    ('abc', 'nombre'),
])
def test_usage_volume_invalide(tech, seed, get_tube, volume, message):
    tube_id = seed['tubes']['available']
    r = tech.post('/api/usages', json={'tube_id': tube_id, 'volume_taken': volume})
    assert r.status_code == 400
    assert message in r.get_json()['error']
    assert get_tube(tube_id).current_volume == 50  # inchangé


def test_usage_tube_inexistant(tech):
    assert tech.post('/api/usages', json={'tube_id': 99999, 'volume_taken': 1}).status_code == 404


def test_modifier_volume_ajuste_le_tube_selon_le_delta(tech, seed, get_tube):
    tube_id = seed['tubes']['available']  # 50 µL
    usage = tech.post('/api/usages', json={'tube_id': tube_id, 'volume_taken': 10}).get_json()
    assert get_tube(tube_id).current_volume == pytest.approx(40)

    tech.put(f"/api/usages/{usage['id']}", json={'volume_taken': 15})   # +5
    assert get_tube(tube_id).current_volume == pytest.approx(35)

    tech.put(f"/api/usages/{usage['id']}", json={'volume_taken': 4})    # -11 (rend du volume)
    assert get_tube(tube_id).current_volume == pytest.approx(46)


def test_modifier_volume_au_dela_du_disponible_refuse(tech, seed, get_tube):
    tube_id = seed['tubes']['available']
    usage = tech.post('/api/usages', json={'tube_id': tube_id, 'volume_taken': 10}).get_json()
    r = tech.put(f"/api/usages/{usage['id']}", json={'volume_taken': 100})
    assert r.status_code == 400
    assert get_tube(tube_id).current_volume == pytest.approx(40)


def test_date_invalide(tech, seed):
    r = tech.post('/api/usages', json={'tube_id': seed['tubes']['available'], 'volume_taken': 1,
                                       'date_out': '09/11/2026'})
    assert r.status_code == 400
