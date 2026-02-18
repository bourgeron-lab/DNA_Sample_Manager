#!/usr/bin/env python3
"""
Import tubes and boxes from MySQL dump to SQLite database
Version 2 - Improved parsing
"""

import re
import sqlite3
import os

# Paths
MYSQL_DUMP = os.path.expanduser("~/Downloads/stock.sql")
SQLITE_DB = "/Volumes/@ghfc/sandbox/instance/dna_samples.db"


def parse_mysql_tuples(values_string):
    """
    Parse MySQL VALUES(...),(...),... into list of value lists
    Handles: integers, floats, NULL, quoted strings with escapes
    """
    records = []
    i = 0
    length = len(values_string)
    
    while i < length:
        # Skip whitespace and commas between tuples
        while i < length and values_string[i] in ' ,\n\r\t':
            i += 1
        
        if i >= length:
            break
            
        # Expect opening parenthesis
        if values_string[i] != '(':
            i += 1
            continue
            
        i += 1  # skip '('
        
        # Parse values within this tuple
        values = []
        current_value = []
        in_string = False
        escape = False
        
        while i < length:
            char = values_string[i]
            
            if escape:
                current_value.append(char)
                escape = False
                i += 1
                continue
            
            if char == '\\' and in_string:
                escape = True
                current_value.append(char)
                i += 1
                continue
            
            if char == "'":
                in_string = not in_string
                current_value.append(char)
                i += 1
                continue
            
            if not in_string:
                if char == ',':
                    # End of field
                    values.append(''.join(current_value).strip())
                    current_value = []
                    i += 1
                    continue
                    
                if char == ')':
                    # End of tuple
                    values.append(''.join(current_value).strip())
                    records.append(values)
                    i += 1
                    break
            
            current_value.append(char)
            i += 1
    
    return records


def parse_value(value_str):
    """Convert MySQL value string to Python value"""
    value_str = value_str.strip()
    
    if value_str == 'NULL':
        return None
    
    if value_str.startswith("'") and value_str.endswith("'"):
        # String: remove quotes and unescape
        s = value_str[1:-1]
        s = s.replace("\\'", "'")
        s = s.replace('\\"', '"')
        s = s.replace('\\\\', '\\')
        return s
    
    # Try numeric
    try:
        if '.' in value_str:
            return float(value_str)
        return int(value_str)
    except ValueError:
        return value_str


def extract_inserts_from_dump(dump_path, table_name):
    """Extract all INSERT statements for a table from MySQL dump"""
    print(f"Reading MySQL dump: {dump_path}")
    
    with open(dump_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Find all INSERT statements for the table
    pattern = rf"INSERT INTO `{table_name}` VALUES\s+(.+?);"
    matches = re.findall(pattern, content, re.DOTALL | re.IGNORECASE)
    
    all_records = []
    for match in matches:
        records = parse_mysql_tuples(match)
        all_records.extend(records)
    
    print(f"Found {len(all_records)} {table_name} records")
    return all_records


def import_boxes(conn):
    """Import boxes from MySQL dump"""
    print("\nImporting Boxes...")
    
    raw_records = extract_inserts_from_dump(MYSQL_DUMP, 'boite')
    
    cursor = conn.cursor()
    
    # Box structure: id_boite, nom_boite, boite_solution_mere_ou_fille, notes_boite
    imported = 0
    skipped = 0
    box_id_map = {}
    
    for raw_values in raw_records:
        if len(raw_values) != 4:
            print(f"Warning: Expected 4 fields for box, got {len(raw_values)}: {raw_values}")
            continue
        
        values = [parse_value(v) for v in raw_values]
        mysql_id, name, solution_type, notes = values
        
        # Check if box already exists by name
        cursor.execute("SELECT id FROM box WHERE name = ?", (name,))
        existing = cursor.fetchone()
        
        if existing:
            skipped += 1
            box_id_map[mysql_id] = existing[0]
            continue
        
        # Insert new box
        cursor.execute("""
            INSERT INTO box (name, notes)
            VALUES (?, ?)
        """, (name, notes or ''))
        
        sqlite_id = cursor.lastrowid
        box_id_map[mysql_id] = sqlite_id
        imported += 1
    
    conn.commit()
    print(f"✓ Imported {imported} boxes ({skipped} skipped)")
    print(f"Box ID mapping created: {len(box_id_map)} boxes mapped")
    
    return box_id_map


def import_arrivals(conn):
    """Import arrivals (arrivee) as samples"""
    print("\nImporting Arrivals as Samples...")
    
    raw_records = extract_inserts_from_dump(MYSQL_DUMP, 'arrivee')
    
    cursor = conn.cursor()
    
    # Arrival structure: id_arrivee, id_sujet, code_aom, code_c0733, code_adn, code_other, date_entree
    imported = 0
    skipped = 0
    arrivee_to_sample = {}
    
    # Get existing individual IDs to match id_sujet
    cursor.execute("SELECT individual_id, id FROM individual")
    individual_map = {row[0]: row[1] for row in cursor.fetchall()}
    
    for raw_values in raw_records:
        if len(raw_values) != 7:
            continue
        
        values = [parse_value(v) for v in raw_values]
        id_arrivee, id_sujet, code_aom, code_c0733, code_adn, code_other, date_entree = values
        
        # Use code_c0733 if available, otherwise code_aom, otherwise code_adn
        sample_id = code_c0733 or code_aom or code_adn or f"ARR{id_arrivee}"
        
        # Check if sample already exists
        cursor.execute("SELECT id FROM sample WHERE sample_id = ?", (sample_id,))
        existing = cursor.fetchone()
        
        if existing:
            arrivee_to_sample[id_arrivee] = existing[0]
            skipped += 1
            continue
        
        # Try to find individual by id_sujet (might be stored as individual_id)
        individual_pk = individual_map.get(str(id_sujet))
        
        # If no individual found, we'll leave it NULL (sample without individual)
        
        # Insert new sample
        try:
            cursor.execute("""
                INSERT INTO sample (sample_id, individual_id, arrival_date, notes)
                VALUES (?, ?, ?, ?)
            """, (
                sample_id,
                individual_pk,
                date_entree,
                f"Imported from MySQL arrivee id={id_arrivee}"
            ))
            
            sqlite_id = cursor.lastrowid
            arrivee_to_sample[id_arrivee] = sqlite_id
            imported += 1
        except sqlite3.IntegrityError:
            # Duplicate - try to find it
            cursor.execute("SELECT id FROM sample WHERE sample_id = ?", (sample_id,))
            existing = cursor.fetchone()
            if existing:
                arrivee_to_sample[id_arrivee] = existing[0]
                skipped += 1
    
    conn.commit()
    print(f"✓ Imported {imported} samples from arrivals ({skipped} already existed)")
    print(f"Arrivee-to-Sample mapping: {len(arrivee_to_sample)} entries")
    
    return arrivee_to_sample


def import_tubes(conn, box_id_map):
    """Import tubes from MySQL dump"""
    print("\nImporting Tubes...")
    
    # First import arrivals as samples
    arrivee_to_sample = import_arrivals(conn)
    
    # Now extract tubes
    raw_records = extract_inserts_from_dump(MYSQL_DUMP, 'tube')
    
    cursor = conn.cursor()
    
    # Tube structure in MySQL:
    # code_barre_tube, id_arrivee, id_boite, position_h_tube, position_v_tube,
    # concentration_adn, qualite_adn, volume_initial, volume_courant, source_adn,
    # solution_mere_ou_fille, notes_tube
    
    imported = 0
    skipped = 0
    no_sample = 0
    
    for raw_values in raw_records:
        if len(raw_values) != 12:
            print(f"Warning: Expected 12 fields for tube, got {len(raw_values)}")
            continue
        
        values = [parse_value(v) for v in raw_values]
        (mysql_code_barre, id_arrivee, mysql_box_id, pos_h, pos_v,
         concentration, qualite, vol_init, vol_current, source,
         solution_type, notes) = values
        
        # Map id_arrivee to sample_id
        sample_pk = arrivee_to_sample.get(id_arrivee)
        if not sample_pk:
            no_sample += 1
            continue
        
        # Generate barcode for tube
        barcode = f"T{mysql_code_barre:06d}"
        
        # Check if tube already exists
        cursor.execute("SELECT id FROM tube WHERE barcode = ?", (barcode,))
        if cursor.fetchone():
            skipped += 1
            continue
        
        # Map box_id (can be NULL)
        sqlite_box_id = box_id_map.get(mysql_box_id) if mysql_box_id else None
        
        # Insert tube
        try:
            cursor.execute("""
                INSERT INTO tube (
                    barcode, sample_id, box_id, position_row, position_col,
                    concentration, quality, initial_volume, current_volume, source, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                barcode,
                sample_pk,
                sqlite_box_id,
                pos_h,  # position_row
                pos_v,  # position_col
                concentration,
                qualite,
                vol_init,
                vol_current,
                source,
                notes or ''
            ))
            imported += 1
        except sqlite3.IntegrityError as e:
            print(f"Error importing tube {barcode}: {e}")
            skipped += 1
    
    conn.commit()
    
    print(f"\n✓ Imported {imported} tubes")
    if skipped > 0:
        print(f"  Skipped {skipped} duplicate tubes")
    if no_sample > 0:
        print(f"  Skipped {no_sample} tubes with no arrivee found")
    
    return imported


def main():
    print("=" * 60)
    print("MySQL Dump Import Tool - Version 2")
    print("=" * 60)
    print(f"Source: {MYSQL_DUMP}")
    print(f"Target: {SQLITE_DB}")
    print()
    
    # Connect to SQLite
    conn = sqlite3.connect(SQLITE_DB)
    
    try:
        # Import boxes first
        box_id_map = import_boxes(conn)
        
        # Import tubes
        tubes_imported = import_tubes(conn, box_id_map)
        
        # Summary
        print("\n" + "=" * 60)
        print("IMPORT COMPLETE")
        print("=" * 60)
        
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM box")
        total_boxes = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tube")
        total_tubes = cursor.fetchone()[0]
        
        print(f"Total boxes in database: {total_boxes}")
        print(f"Total tubes in database: {total_tubes}")
        
    finally:
        conn.close()


if __name__ == "__main__":
    main()
