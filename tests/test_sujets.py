"""Sujets : liste paginée (compteurs échantillons / tubes, filtres) et export TSV / Excel."""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from dna_sample_manager.app import Individual, Sample, Tube, db


@pytest.fixture
def more_subjects(app, seed):
    """IND-000 : sans échantillon (trié AVANT IND-001) ; IND-002 : 2 échantillons, 1 tube."""
    with app.app_context():
        empty = Individual(individual_id='IND-000', family_id='FAM-0', sex=2)
        other = Individual(individual_id='IND-002', family_id='FAM-2', phenotype='=1+1')
        db.session.add_all([empty, other])
        db.session.flush()
        s1 = Sample(sample_id='S-002', individual_id=other.id)
        s2 = Sample(sample_id='S-003', individual_id=other.id)
        db.session.add_all([s1, s2])
        db.session.flush()
        db.session.add(Tube(barcode='T-OTHER', sample_id=s1.id, current_volume=30.0))
        db.session.commit()


def by_id(data):
    return {s['individual_id']: s for s in data['sujets']}


def test_liste_compte_les_tubes_et_les_echantillons(tech, more_subjects):
    """Régression : la colonne « Tubes » affichait le champ sample_count (mal nommé)."""
    data = tech.get('/api/sujets').get_json()
    rows = by_id(data)
    assert (rows['IND-001']['sample_count'], rows['IND-001']['tube_count']) == (1, 6)
    assert (rows['IND-002']['sample_count'], rows['IND-002']['tube_count']) == (2, 1)
    assert (rows['IND-000']['sample_count'], rows['IND-000']['tube_count']) == (0, 0)
    assert data['total'] == 3
    assert [s['individual_id'] for s in data['sujets']] == ['IND-000', 'IND-001', 'IND-002']


def test_filtre_avec_tubes_uniquement(tech, more_subjects):
    data = tech.get('/api/sujets?with_tubes=1').get_json()
    assert [s['individual_id'] for s in data['sujets']] == ['IND-001', 'IND-002']
    assert data['total'] == 2


def test_pagination(tech, more_subjects):
    data = tech.get('/api/sujets?per_page=2&page=2').get_json()
    assert [s['individual_id'] for s in data['sujets']] == ['IND-002']
    assert (data['total'], data['pages'], data['page']) == (3, 2, 2)


def test_recherche(tech, more_subjects):
    data = tech.get('/api/sujets?search=FAM-2').get_json()
    assert [s['individual_id'] for s in data['sujets']] == ['IND-002']


def test_export_tsv_sans_pagination_avec_filtres(tech, more_subjects):
    r = tech.get('/api/sujets/export?format=tsv&with_tubes=1&per_page=1')
    assert r.status_code == 200
    assert r.data.startswith(b'\xef\xbb\xbf')  # BOM utf-8-sig pour Excel Windows
    assert 'sujets_export_' in r.headers['Content-Disposition']
    lines = r.data.decode('utf-8-sig').splitlines()
    header = lines[0].split('\t')
    assert header[0] == 'ID Individu' and 'Tubes' in header and 'Échantillons' in header
    rows = [dict(zip(header, line.split('\t'))) for line in lines[1:]]
    assert [(r['ID Individu'], r['Échantillons'], r['Tubes']) for r in rows] == [
        ('IND-001', '1', '6'), ('IND-002', '2', '1')]


def test_export_tsv_zero_affiche(tech, more_subjects):
    """Un sujet sans tube a « 0 » dans l'export, pas une cellule vide."""
    text = tech.get('/api/sujets/export?format=tsv&search=IND-000').data.decode('utf-8-sig')
    header, row = (line.split('\t') for line in text.splitlines())
    assert dict(zip(header, row))['Tubes'] == '0'


def test_export_xlsx(tech, more_subjects):
    r = tech.get('/api/sujets/export?format=xlsx')
    assert r.status_code == 200
    ws = load_workbook(BytesIO(r.data)).active
    assert ws.title == 'Sujets'
    values = list(ws.values)
    header = values[0]
    rows = {row[0]: dict(zip(header, row)) for row in values[1:]}
    assert set(rows) == {'IND-000', 'IND-001', 'IND-002'}
    assert rows['IND-001']['Tubes'] == 6
    # Un texte commençant par « = » reste du texte, ce n'est pas une formule exécutée par Excel
    assert rows['IND-002']['Phénotype'] == '=1+1'
    cell = next(c for c in ws[4] if c.value == '=1+1')
    assert cell.data_type == 's'


def test_export_format_invalide(tech):
    assert tech.get('/api/sujets/export?format=pdf').status_code == 400


def test_export_non_authentifie(anon):
    assert anon.get('/api/sujets/export?format=tsv').status_code == 401


def test_detail_sujet_toujours_accessible(tech, seed):
    """La route /api/sujets/export ne doit pas masquer /api/sujets/<id>."""
    data = tech.get(f"/api/sujets/{seed['individual']}").get_json()
    assert data['tube_count'] == 6
