#!/usr/bin/env python3
"""
Import tubes and boxes from old MySQL dump into SQLite database
"""

import re
import sqlite3
from datetime import datetime

def parse_mysql_insert(file_path, table_name):
    """Extract INSERT INTO statements for a specific table from MySQL dump"""
    inserts = []
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    # Find INSERT INTO statements for the table
    pattern = rf"INSERT INTO `{table_name}` VALUES (.+?);"
    matches = re.findall(pattern, content, re.DOTALL)
    
    for match in matches:
        # Parse tuples from INSERT statement
        # This regex handles both simple values and complex ones with nested parentheses
        tuple_pattern = r'\(([^)]+(?:\([^)]*\)[^)]*)*)\)'
        tuples = re.findall(tuple_pattern, match)
        inserts.extend(tuples)
    
    return inserts


def parse_value(value):
    """Parse a MySQL value (handles NULL, strings, numbers)"""
    value = value.strip()
    if value == 'NULL':
        return None
    elif value.startswith("'") and value.endswith("'"):
        # String value - unescape
        return value[1:-1].replace("\\'", "'").replace('\\"', '"')
    else:
        # Try to convert to number
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except:
            return value


def split_values(row_string):
    """Split a row string into individual values, respecting quoted strings"""
    values = []
    current = []
    in_quote = False
    escape_next = False
    
    for char in row_string:
        if escape_next:
            current.append(char)
            escape_next = False
            continue
            
        if char == '\\':
            escape_next = True
            current.append(char)
            continue
            
        if char == "'":
            in_quote = not in_quote
            current.append(char)
            continue
            
        if char == ',' and not in_quote:
            values.append(''.join(current))
            current = []
            continue
            
        current.append(char)
    
    if current:
        values.append(''.join(current))
    
    return [parse_value(v) for v in values]


def import_boxes(mysql_dump, db_path):
    """Import boxes from MySQL dump to SQLite"""
    print("\n=== Importing Boxes ===")
    
    inserts = parse_mysql_insert(mysql_dump, 'boite')
    print(f"Found {len(inserts)} box records")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    imported = 0
    skipped = 0
    
    for row_str in inserts:
        try:
            values = split_values(row_str)
            if len(values) < 4:
                continue
                
            id_boite, nom_boite, type_boite, notes = values[:4]
            
            # Check if box already exists
            cursor.execute("SELECT id FROM box WHERE name = ?", (nom_boite,))
            if cursor.fetchone():
                skipped += 1
                continue
            
            # Insert box
            box_type = 'stock' if type_boite == 1 else 'working'
            cursor.execute("""
                INSERT INTO box (name, box_type, notes)
                VALUES (?, ?, ?)
            """, (nom_boite, box_type, notes or None))
            
            imported += 1
            
        except Exception as e:
            print(f"Error importing box: {e} - Row: {row_str[:100]}")
            continue
    
    conn.commit()
    print(f"✓ Imported {imported} boxes ({skipped} skipped - already exist)")
    
    # Return mapping of old box IDs to new box IDs
    cursor.execute("SELECT name, id FROM box")
    box_mapping = {}
    for name, new_id in cursor.fetchall():
        # Find old ID from inserts
        for row_str in inserts:
            values = split_values(row_str)
            if len(values) >= 2 and values[1] == name:
                box_mapping[values[0]] = new_id
                break
    
    conn.close()
    return box_mapping


def import_tubes(mysql_dump, db_path, box_mapping):
    """Import tubes from MySQL dump to SQLite"""
    print("\n=== Importing Tubes ===")
    
    inserts = parse_mysql_insert(mysql_dump, 'tube')
    print(f"Found {len(inserts)} tube records")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get sample mapping (sample_id string to database id)
    cursor.execute("SELECT sample_id, id FROM sample")
    sample_mapping = {sample_id: db_id for sample_id, db_id in cursor.fetchall()}
    
    imported = 0
    skipped = 0
    no_sample = 0
    
    for row_str in inserts:
        try:
            values = split_values(row_str)
            if len(values) < 13:
                continue
            
            (code_barre, id_arrivee, id_boite, position_h, position_v, 
             concentration, qualite, volume_init, volume_curr, 
             source, type_tube, notes) = values[:12]
            
            # Map barcode
            barcode = f"T{code_barre:06d}" if isinstance(code_barre, int) else str(code_barre)
            
            # Check if tube already exists
            cursor.execute("SELECT id FROM tube WHERE barcode = ?", (barcode,))
            if cursor.fetchone():
                skipped += 1
                continue
            
            # Map sample (id_arrivee corresponds to sample)
            sample_id = None
            if id_arrivee:
                # Try to find sample by arrival ID or sample_id
                # This is a simplified mapping - you may need to adjust
                cursor.execute("""
                    SELECT id FROM sample 
                    WHERE id = ? OR sample_id LIKE ?
                """, (id_arrivee, f"%{id_arrivee}%"))
                result = cursor.fetchone()
                if result:
                    sample_id = result[0]
                else:
                    no_sample += 1
            
            # Map box
            box_id = box_mapping.get(id_boite) if id_boite else None
            
            # Map tube type
            tube_type = 'stock' if type_tube == 1 else 'working'
            
            # Insert tube
            cursor.execute("""
                INSERT INTO tube (
                    barcode, sample_id, box_id, 
                    position_row, position_col,
                    concentration, quality, 
                    initial_volume, current_volume,
                    source, tube_type, notes,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                barcode, sample_id, box_id,
                position_h, position_v,
                concentration, qualite,
                volume_init, volume_curr,
                source, tube_type, notes,
                datetime.now()
            ))
            
            imported += 1
            
        except Exception as e:
            print(f"Error importing tube: {e} - Row: {row_str[:100]}")
            continue
    
    conn.commit()
    print(f"✓ Imported {imported} tubes")
    print(f"  - {skipped} skipped (already exist)")
    print(f"  - {no_sample} without sample mapping")
    conn.close()


def main():
    mysql_dump = '/Users/amathieu/Downloads/stock.sql'
    db_path = '/Volumes/@ghfc/sandbox/instance/dna_samples.db'
    
    print(f"Reading MySQL dump: {mysql_dump}")
    print(f"Target database: {db_path}")
    
    # Import boxes first
    box_mapping = import_boxes(mysql_dump, db_path)
    print(f"\nBox ID mapping created: {len(box_mapping)} boxes mapped")
    
    # Import tubes
    import_tubes(mysql_dump, db_path, box_mapping)
    
    # Show summary
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM box")
    box_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tube")
    tube_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tube WHERE sample_id IS NOT NULL")
    tubes_with_sample = cursor.fetchone()[0]
    
    conn.close()
    
    print("\n" + "="*50)
    print("IMPORT COMPLETE")
    print("="*50)
    print(f"Total boxes in database: {box_count}")
    print(f"Total tubes in database: {tube_count}")
    print(f"Tubes with sample link: {tubes_with_sample}")
    print(f"Tubes without sample: {tube_count - tubes_with_sample}")


if __name__ == '__main__':
    main()
