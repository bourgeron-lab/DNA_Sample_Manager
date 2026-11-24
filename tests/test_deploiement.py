"""Mise en production : clé secrète stable, mode reverse proxy, serveur waitress."""
import stat

import pytest
from typer.testing import CliRunner

from dna_sample_manager import cli
from dna_sample_manager.app import (
    User, _load_secret_key, bcrypt, configure_behind_proxy, db, default_admin_password_in_use,
)


# --- Clé secrète -------------------------------------------------------------

def test_cle_creee_une_fois_puis_reutilisee(tmp_path, monkeypatch):
    """Régression : une clé aléatoire à chaque démarrage déconnectait tout le monde."""
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)
    db_path = tmp_path / 'dna_samples.db'
    first = _load_secret_key(str(db_path))
    key_file = tmp_path / 'secret_key'
    assert key_file.exists() and len(first) == 64
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert _load_secret_key(str(db_path)) == first  # « redémarrage » : même clé


def test_variable_d_environnement_prioritaire(tmp_path, monkeypatch):
    monkeypatch.setenv('FLASK_SECRET_KEY', 'x' * 40)
    assert _load_secret_key(str(tmp_path / 'dna_samples.db')) == 'x' * 40
    assert not (tmp_path / 'secret_key').exists()


def test_fichier_de_cle_vide_refuse(tmp_path, monkeypatch):
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)
    (tmp_path / 'secret_key').write_text('\n')
    with pytest.raises(RuntimeError, match='trop courte'):
        _load_secret_key(str(tmp_path / 'dna_samples.db'))


# --- Mode reverse proxy ------------------------------------------------------

@pytest.fixture
def proxied(app):
    """Active le mode proxy sur l'app de test, puis remet la configuration d'origine."""
    saved_cfg = dict(app.config)
    configure_behind_proxy(app)
    yield app
    app.config.clear()
    app.config.update(saved_cfg)


SITE = 'https://adn.example.org'


def _login_https(client, referer=SITE + '/login'):
    from conftest import PASSWORD, ApiClient
    token = ApiClient.extract_token(client.get('/login', base_url=SITE).get_data(as_text=True))
    return client.post('/login', base_url=SITE, headers={'Referer': referer},
                       data={'username': 'tech', 'password': PASSWORD, 'csrf_token': token})


def test_connexion_https_cookie_securise(proxied):
    c = proxied.test_client()
    r = _login_https(c)
    assert r.status_code == 302
    cookie = r.headers['Set-Cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    assert c.get('/api/tubes', base_url=SITE).status_code == 200


def test_csrf_https_refuse_un_referer_etranger(proxied):
    """En HTTPS, Flask-WTF vérifie en plus du jeton que la requête vient du même site."""
    c = proxied.test_client()
    _login_https(c, referer='https://pirate.example.com/')
    assert c.get('/api/tubes', base_url=SITE).status_code == 401


@pytest.fixture
def waitress_server():
    """Lance un vrai serveur waitress (options de production) autour d'une app WSGI."""
    import threading
    from waitress import create_server
    servers = []

    def start(wsgi_app, behind_proxy):
        opts = cli.waitress_options('127.0.0.1', 0, 2, behind_proxy)
        srv = create_server(wsgi_app, **opts)
        threading.Thread(target=srv.run, daemon=True).start()
        servers.append(srv)
        return f'http://127.0.0.1:{srv.effective_port}'
    yield start
    for srv in servers:
        srv.close()


def _echo_environ(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    keys = ('wsgi.url_scheme', 'HTTP_HOST', 'REMOTE_ADDR')
    return [repr({k: environ.get(k) for k in keys}).encode()]


def _get(url):
    import ast
    import urllib.request
    req = urllib.request.Request(url, headers={'X-Forwarded-Proto': 'https',
                                               'X-Forwarded-Host': 'adn.example.org',
                                               'X-Forwarded-For': '10.1.2.3'})
    return ast.literal_eval(urllib.request.urlopen(req, timeout=5).read().decode())


def test_waitress_derriere_nginx_voit_https_et_l_ip_du_client(waitress_server):
    """Régression : waitress supprimait les en-têtes X-Forwarded-* → l'app se croyait en HTTP
    derrière nginx (vérification CSRF stricte de HTTPS désactivée, IP clientes perdues)."""
    env = _get(waitress_server(_echo_environ, behind_proxy=True))
    assert env['wsgi.url_scheme'] == 'https'
    assert env['HTTP_HOST'].startswith('adn.example.org')
    assert env['REMOTE_ADDR'] == '10.1.2.3'


def test_waitress_sans_proxy_ignore_les_en_tetes_forges(waitress_server):
    """Sans --behind-proxy, un client ne peut pas se faire passer pour HTTPS ou une autre IP."""
    env = _get(waitress_server(_echo_environ, behind_proxy=False))
    assert env['wsgi.url_scheme'] == 'http'
    assert env['REMOTE_ADDR'] == '127.0.0.1'


def test_waitress_ne_fait_confiance_qu_a_127_0_0_1():
    opts = cli.waitress_options('127.0.0.1', 5003, 8, behind_proxy=True)
    assert opts['trusted_proxy'] == '127.0.0.1' and opts['trusted_proxy_count'] == 1
    assert opts['trusted_proxy_headers'] == {'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'}


# --- Mot de passe admin par défaut ------------------------------------------

def test_detection_mot_de_passe_admin_par_defaut(app):
    with app.app_context():
        assert not default_admin_password_in_use()  # pas de compte 'admin' dans le jeu de test
        user = User(username='admin', password_hash=bcrypt.generate_password_hash('admin', rounds=4).decode(),
                    is_admin=True)
        db.session.add(user)
        db.session.commit()
        assert default_admin_password_in_use()
        user.password_hash = bcrypt.generate_password_hash('autre-mot-de-passe', rounds=4).decode()
        db.session.commit()
        assert not default_admin_password_in_use()


# --- CLI / serveur -------------------------------------------------------------

def _run_cli(tmp_path, monkeypatch, *args):
    (tmp_path / 'dna_samples.db').touch()
    seen = {}
    monkeypatch.setattr('dna_sample_manager.app.create_app',
                        lambda db_path, behind_proxy=False: seen.update(db=db_path, proxy=behind_proxy) or 'APP')
    monkeypatch.setattr(cli, 'serve', lambda application, **kw: seen.update(app=application, opts=kw, **kw))
    opened = []
    monkeypatch.setattr(cli.threading, 'Timer', lambda delay, fn: type('T', (), {'start': lambda s: opened.append(1)})())
    result = CliRunner().invoke(cli.app, [str(tmp_path), '--no-backup', *args])
    assert result.exit_code == 0, result.output
    return seen, opened, result


def test_cli_lance_waitress(tmp_path, monkeypatch):
    seen, opened, _ = _run_cli(tmp_path, monkeypatch, '--port', '8080', '--threads', '4')
    assert seen['app'] == 'APP' and seen['port'] == 8080 and seen['threads'] == 4
    assert seen['host'] == '127.0.0.1' and seen['proxy'] is False
    assert opened == [1]  # navigateur ouvert par défaut (usage sur un poste)


def test_cli_mode_serveur(tmp_path, monkeypatch):
    seen, opened, result = _run_cli(tmp_path, monkeypatch, '--behind-proxy', '--no-browser')
    assert seen['proxy'] is True and opened == []
    assert seen['opts']['trusted_proxy'] == '127.0.0.1'  # en-têtes de nginx pris en compte
    assert 'ATTENTION' not in result.output


def test_cli_avertit_si_proxy_et_ecoute_publique(tmp_path, monkeypatch):
    _, _, result = _run_cli(tmp_path, monkeypatch, '--behind-proxy', '--host', '0.0.0.0', '--no-browser')
    assert 'ATTENTION' in result.output and '127.0.0.1' in result.output
