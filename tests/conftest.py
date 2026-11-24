"""Fixtures pytest communes.

- `app` : application Flask sur une base SQLite temporaire (une par session de tests)
- `seed` (autouse) : base vidée puis remplie avant CHAQUE test avec un jeu de données
  minimal et connu -> les tests sont indépendants les uns des autres
- `anon`, `admin`, `tech` : clients HTTP (anonyme, admin, utilisateur simple) ;
  les clients connectés ajoutent eux-mêmes le jeton CSRF, comme le fait base.html

La base de production (instance/dna_samples.db) n'est jamais utilisée.
"""
import re

import pytest

from dna_sample_manager.app import (
    AuditLog, Box, Individual, Sample, Tube, User, bcrypt, create_app, db,
)

PASSWORD = 'pw'


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    db_path = tmp_path_factory.mktemp('db') / 'test.db'
    application = create_app(db_path=str(db_path))
    application.config['TESTING'] = True
    return application


@pytest.fixture(autouse=True)
def seed(app):
    """Base remise à zéro + jeu de données. Renvoie les ids utiles aux tests."""
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()

        # Hash bcrypt à coût réduit : la vérification au login reste correcte et rapide
        pw_hash = bcrypt.generate_password_hash(PASSWORD, rounds=4).decode()
        admin = User(username='admin_test', password_hash=pw_hash, is_admin=True)
        tech = User(username='tech', password_hash=pw_hash, is_admin=False)
        box = Box(name='BOX-1', freezer='Frigo 1')
        ind = Individual(individual_id='IND-001', family_id='FAM-1', sex=1)
        db.session.add_all([admin, tech, box, ind])
        db.session.flush()
        sample = Sample(sample_id='S-001', individual_id=ind.id, sample_type='DNA')
        db.session.add(sample)
        db.session.flush()

        def tube(barcode, current, initial, row=None, col=None, **kw):
            t = Tube(barcode=barcode, sample_id=sample.id, current_volume=current,
                     initial_volume=initial, box_id=box.id if row else None,
                     position_row=row, position_col=col, **kw)
            db.session.add(t)
            return t

        tubes = {
            'available': tube('T-AVAIL', 50.0, 100.0, row=1, col=1, concentration=100.0),
            'low': tube('T-LOW', 12.0, 100.0, row=1, col=2),
            'critical': tube('T-CRIT', 5.0, 100.0, row=1, col=3),
            'empty': tube('T-EMPTY', 0.0, 100.0, row=1, col=4),
            'null_volume': tube('T-NULLVOL', None, None),
            'no_initial': tube('T-NOINIT', 20.0, None),
        }
        db.session.commit()
        # Le jeu de données lui-même ne doit pas apparaître dans le journal des tests
        AuditLog.query.delete()
        db.session.commit()

        ids = {
            'admin': admin.id, 'tech': tech.id, 'box': box.id,
            'individual': ind.id, 'sample': sample.id,
            'tubes': {k: t.id for k, t in tubes.items()},
        }
    yield ids
    with app.app_context():
        db.session.remove()


class ApiClient:
    """Client de test qui se connecte et envoie le jeton CSRF comme le navigateur."""

    def __init__(self, flask_client):
        self.c = flask_client
        self._token = None

    @staticmethod
    def extract_token(html):
        m = re.search(r'(?:name="csrf_token" value|name="csrf-token" content)="([^"]+)"', html)
        assert m, 'jeton CSRF introuvable dans la page'
        return m.group(1)

    def login(self, username, password=PASSWORD, next_url=None):
        token = self.extract_token(self.c.get('/login').get_data(as_text=True))
        url = '/login' + (f'?next={next_url}' if next_url is not None else '')
        return self.c.post(url, data={'username': username, 'password': password, 'csrf_token': token})

    @property
    def token(self):
        if self._token is None:
            self._token = self.extract_token(self.c.get('/').get_data(as_text=True))
        return self._token

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def _send(self, method, url, json=None, csrf=True, **kw):
        headers = kw.pop('headers', {})
        if csrf:
            headers['X-CSRFToken'] = self.token
        return getattr(self.c, method)(url, json=json, headers=headers, **kw)

    def post(self, url, json=None, **kw):
        return self._send('post', url, json, **kw)

    def put(self, url, json=None, **kw):
        return self._send('put', url, json, **kw)

    def delete(self, url, **kw):
        return self._send('delete', url, **kw)


@pytest.fixture
def anon(app):
    return ApiClient(app.test_client())


@pytest.fixture
def admin(app):
    client = ApiClient(app.test_client())
    assert client.login('admin_test').status_code == 302
    return client


@pytest.fixture
def tech(app):
    client = ApiClient(app.test_client())
    assert client.login('tech').status_code == 302
    return client


@pytest.fixture
def get_tube(app):
    """Relit un tube en base (hors requête HTTP)."""
    def _get(tube_id):
        with app.app_context():
            t = db.session.get(Tube, tube_id)
            db.session.expunge(t)
            return t
    return _get
