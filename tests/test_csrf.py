"""Protection CSRF."""


def test_login_sans_jeton_refuse(anon):
    r = anon.c.post('/login', data={'username': 'tech', 'password': 'pw'})
    assert r.status_code == 302 and '/login' in r.location
    assert anon.get('/api/stats').status_code == 401  # pas connecté


def test_requetes_api_sans_jeton_refusees(tech, seed):
    tube_id = seed['tubes']['available']
    for method, url, body in [
        ('post', '/api/usages', {'tube_id': tube_id, 'volume_taken': 1}),
        ('put', f'/api/tubes/{tube_id}', {'notes': 'x'}),
        ('delete', f'/api/tubes/{tube_id}', None),
        ('post', '/api/boxes', {'name': 'B'}),
    ]:
        r = getattr(tech, method)(url, json=body, csrf=False)
        assert r.status_code == 400, (method, url)
        assert 'CSRF' in r.get_json()['error']


def test_jeton_invalide_refuse(tech, seed):
    r = tech.put(f"/api/tubes/{seed['tubes']['available']}", json={'notes': 'x'},
                 csrf=False, headers={'X-CSRFToken': 'faux'})
    assert r.status_code == 400


def test_requete_avec_jeton_acceptee(tech, seed):
    r = tech.put(f"/api/tubes/{seed['tubes']['available']}", json={'notes': 'ok'})
    assert r.status_code == 200
    assert r.get_json()['notes'] == 'ok'


def test_get_ne_demande_pas_de_jeton(tech):
    assert tech.get('/api/tubes').status_code == 200


def test_base_html_expose_le_jeton_et_le_wrapper_fetch(tech):
    html = tech.get('/').get_data(as_text=True)
    assert '<meta name="csrf-token"' in html
    assert 'X-CSRFToken' in html and 'window.fetch' in html
