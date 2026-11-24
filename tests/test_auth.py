"""Authentification, redirections après login, droits admin."""
import pytest

PAGES = ['/', '/tubes', '/boxes', '/sujets', '/samples', '/history']


@pytest.mark.parametrize('url', PAGES + ['/admin/users'])
def test_pages_redirigent_vers_login_si_non_connecte(anon, url):
    r = anon.get(url)
    assert r.status_code == 302
    assert '/login' in r.location


def test_redirection_login_garde_un_chemin_relatif(anon):
    r = anon.get('/tubes?box=3')
    assert r.location.startswith('/login?next=/tubes')
    assert 'http' not in r.location.split('next=')[1]


@pytest.mark.parametrize('url', ['/api/tubes', '/api/stats', '/api/audit', '/api/users'])
def test_api_non_connectee_renvoie_401_json(anon, url):
    r = anon.get(url)
    assert r.status_code == 401
    assert r.get_json()['error']


def test_login_mauvais_mot_de_passe(anon):
    r = anon.login('tech', password='faux')
    assert r.status_code == 200  # reste sur la page de login
    assert 'incorrect' in r.get_data(as_text=True)
    assert anon.get('/api/stats').status_code == 401


def test_login_puis_logout(tech):
    assert tech.get('/api/stats').status_code == 200
    tech.get('/logout')
    assert tech.get('/api/stats').status_code == 401


@pytest.mark.parametrize('next_url', [
    'https://evil.com',
    '//evil.com',
    '/%5Cevil.com',          # /\evil.com : interprété comme //evil.com par les navigateurs
    'javascript:alert(1)',
    'evil.com',
])
def test_next_externe_rejete(anon, next_url):
    r = anon.login('tech', next_url=next_url)
    assert r.status_code == 302
    assert r.location in ('/', 'http://localhost/')


def test_next_local_accepte(anon):
    r = anon.login('tech', next_url='/tubes?box=3')
    assert r.location.endswith('/tubes?box=3')


@pytest.mark.parametrize('url', PAGES)
def test_pages_accessibles_connecte(tech, url):
    assert tech.get(url).status_code == 200


def test_page_admin_reservee_aux_admins(admin, tech):
    assert admin.get('/admin/users').status_code == 200
    assert tech.get('/admin/users').status_code == 403
    assert tech.get('/api/users').status_code == 403
    assert tech.post('/api/users', json={'username': 'x', 'password': 'xxxx'}).status_code == 403


def test_admin_cree_un_utilisateur(admin, anon):
    r = admin.post('/api/users', json={'username': 'nouveau', 'password': 'secret1'})
    assert r.status_code == 201
    assert anon.login('nouveau', password='secret1').status_code == 302
