#!/usr/bin/env python3
"""
Script d'importation des données depuis le dump MySQL (stock.sql)
vers la base SQLite de l'application DNA Sample Manager
"""

import re
import sys
from datetime import datetime
from app import app, db, Sujet, Boite, Arrivee, Tube, Utilisation


def parse_value(val):
    """Parse une valeur SQL et retourne la valeur Python correspondante"""
    val = val.strip()
    if val == 'NULL':
        return None
    if val.startswith("'") and val.endswith("'"):
        # Retirer les quotes et gérer les échappements
        return val[1:-1].replace("\\'", "'").replace("\\n", "\n")
    try:
        # Essayer de parser comme nombre
        if '.' in val:
            return float(val)
        return int(val)
    except ValueError:
        return val


def parse_insert_statement(sql_line, table_name):
    """Parse une instruction INSERT et retourne les tuples de données"""
    # Pattern pour extraire les valeurs
    pattern = rf"INSERT INTO `{table_name}` VALUES\s*(.+);?"
    match = re.search(pattern, sql_line, re.IGNORECASE)
    
    if not match:
        return []
    
    values_str = match.group(1)
    rows = []
    
    # Parser les tuples de valeurs
    # On cherche les patterns (...),(...) 
    tuple_pattern = r'\(([^)]+)\)'
    
    for tuple_match in re.finditer(tuple_pattern, values_str):
        values_content = tuple_match.group(1)
        
        # Parser les valeurs individuelles (attention aux strings avec virgules)
        values = []
        current_val = ''
        in_string = False
        i = 0
        
        while i < len(values_content):
            char = values_content[i]
            
            if char == "'" and (i == 0 or values_content[i-1] != '\\'):
                in_string = not in_string
                current_val += char
            elif char == ',' and not in_string:
                values.append(parse_value(current_val))
                current_val = ''
            else:
                current_val += char
            i += 1
        
        if current_val:
            values.append(parse_value(current_val))
        
        rows.append(values)
    
    return rows


def parse_date(date_str):
    """Parse une date depuis un string"""
    if not date_str or date_str == '0000-00-00':
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        return None


def import_data(sql_file_path):
    """Importer les données depuis le fichier SQL"""
    
    print(f"Lecture du fichier {sql_file_path}...")
    
    with open(sql_file_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    # Trouver les instructions INSERT pour chaque table
    tables_data = {
        'sujet': [],
        'boite': [],
        'arrivee': [],
        'tube': [],
        'utilisation': []
    }
    
    # Diviser par lignes d'INSERT
    lines = content.split('\n')
    current_insert = ''
    current_table = None
    
    for line in lines:
        line = line.strip()
        
        # Détecter le début d'un INSERT
        for table in tables_data.keys():
            if f"INSERT INTO `{table}`" in line:
                if current_insert and current_table:
                    rows = parse_insert_statement(current_insert, current_table)
                    tables_data[current_table].extend(rows)
                current_table = table
                current_insert = line
                break
        else:
            # Continuation de l'INSERT précédent
            if current_table and line and not line.startswith('/*') and not line.startswith('--'):
                current_insert += ' ' + line
                
                # Vérifier si l'INSERT est terminé
                if line.endswith(';'):
                    rows = parse_insert_statement(current_insert, current_table)
                    tables_data[current_table].extend(rows)
                    current_insert = ''
                    current_table = None
    
    # Traiter le dernier INSERT si nécessaire
    if current_insert and current_table:
        rows = parse_insert_statement(current_insert, current_table)
        tables_data[current_table].extend(rows)
    
    print(f"\nDonnées extraites:")
    for table, data in tables_data.items():
        print(f"  - {table}: {len(data)} enregistrements")
    
    return tables_data


def insert_into_db(tables_data):
    """Insérer les données dans la base SQLite"""
    
    with app.app_context():
        # Supprimer les données existantes
        print("\nSuppression des données existantes...")
        Utilisation.query.delete()
        Tube.query.delete()
        Arrivee.query.delete()
        Boite.query.delete()
        Sujet.query.delete()
        db.session.commit()
        
        # Créer les tables si elles n'existent pas
        db.create_all()
        
        # Importer les sujets
        print("\nImportation des sujets...")
        for row in tables_data['sujet']:
            if len(row) >= 15:
                sujet = Sujet(
                    id_sujet=row[0],
                    code_aom=row[1],
                    code_c0733=row[2],
                    code_adn=row[3],
                    code_other=row[4],
                    sexe=row[5],
                    pedigree=row[6],
                    diagnostic=row[7],
                    id_father=row[8],
                    id_mother=row[9],
                    famille=row[10],
                    centre=row[11],
                    protocole=row[12],
                    recrutement=row[13],
                    notes_sujet=row[14] if len(row) > 14 else None
                )
                db.session.add(sujet)
        db.session.commit()
        print(f"  {Sujet.query.count()} sujets importés")
        
        # Importer les boîtes
        print("\nImportation des boîtes...")
        for row in tables_data['boite']:
            if len(row) >= 3:
                boite = Boite(
                    id_boite=row[0],
                    nom_boite=row[1],
                    boite_solution_mere_ou_fille=row[2],
                    notes_boite=row[3] if len(row) > 3 else None
                )
                db.session.add(boite)
        db.session.commit()
        print(f"  {Boite.query.count()} boîtes importées")
        
        # Importer les arrivées
        print("\nImportation des arrivées...")
        for row in tables_data['arrivee']:
            if len(row) >= 7:
                arrivee = Arrivee(
                    id_arrivee=row[0],
                    id_sujet=row[1],
                    code_aom=row[2],
                    code_c0733=row[3],
                    code_adn=row[4],
                    code_other=row[5],
                    date_entree=parse_date(row[6])
                )
                db.session.add(arrivee)
        db.session.commit()
        print(f"  {Arrivee.query.count()} arrivées importées")
        
        # Importer les tubes
        print("\nImportation des tubes...")
        for row in tables_data['tube']:
            if len(row) >= 11:
                tube = Tube(
                    code_barre_tube=row[0],
                    id_arrivee=row[1],
                    id_boite=row[2],
                    position_h_tube=row[3],
                    position_v_tube=row[4],
                    concentration_adn=row[5],
                    qualite_adn=row[6],
                    volume_initial=row[7],
                    volume_courant=row[8],
                    source_adn=row[9] if len(row) > 9 else None,
                    solution_mere_ou_fille=row[10] if len(row) > 10 else None,
                    notes_tube=row[11] if len(row) > 11 else ''
                )
                db.session.add(tube)
        db.session.commit()
        print(f"  {Tube.query.count()} tubes importés")
        
        # Importer les utilisations
        print("\nImportation des utilisations...")
        for row in tables_data['utilisation']:
            if len(row) >= 7:
                utilisation = Utilisation(
                    id_utilisation=row[0],
                    code_barre_tube=row[1],
                    id_puit=row[2],
                    id_utilisateur=row[3],
                    date_sortie=parse_date(row[4]),
                    date_retour=parse_date(row[5]),
                    volume_preleve=row[6],
                    notes_utilisation=row[7] if len(row) > 7 else None
                )
                db.session.add(utilisation)
        db.session.commit()
        print(f"  {Utilisation.query.count()} utilisations importées")
        
        print("\n✅ Importation terminée avec succès!")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sql_file = '/Users/amathieu/Downloads/stock.sql'
    else:
        sql_file = sys.argv[1]
    
    print(f"=== Importation de {sql_file} ===\n")
    
    try:
        data = import_data(sql_file)
        insert_into_db(data)
    except Exception as e:
        print(f"\n❌ Erreur lors de l'importation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
