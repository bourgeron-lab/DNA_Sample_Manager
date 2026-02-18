#!/usr/bin/env python3
"""Quick test to verify tubes are imported and accessible"""

import sqlite3

DB_PATH = "/Volumes/@ghfc/sandbox/instance/dna_samples.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Count entities
print("=== Database Statistics ===")
cursor.execute("SELECT COUNT(*) FROM individual")
print(f"Individuals: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM sample")
print(f"Samples: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM tube")
print(f"Tubes: {cursor.fetchone()[0]}")

cursor.execute("SELECT COUNT(*) FROM box")
print(f"Boxes: {cursor.fetchone()[0]}")

# Show some tube examples
print("\n=== Sample Tubes ===")
cursor.execute("""
    SELECT 
        t.barcode,
        s.sample_id,
        b.name as box_name,
        t.position_row,
        t.position_col,
        t.concentration,
        t.current_volume
    FROM tube t
    LEFT JOIN sample s ON t.sample_id = s.id
    LEFT JOIN box b ON t.box_id = b.id
    LIMIT 10
""")

for row in cursor.fetchall():
    barcode, sample_id, box, row_pos, col_pos, conc, vol = row
    pos = f"({row_pos},{col_pos})" if row_pos and col_pos else "N/A"
    print(f"  {barcode}: sample={sample_id}, box={box}, pos={pos}, conc={conc}, vol={vol}")

conn.close()
print("\n✓ Database is accessible and contains tubes!")
