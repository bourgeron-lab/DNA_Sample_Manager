#!/usr/bin/env python3
"""
Reimport tubes and boxes from merged_final_Nath_V2.tsv
- Deletes ALL existing tubes, boxes, and usages
- Keeps individuals and samples intact
- Creates new boxes and tubes from the TSV file
- Links tubes to existing individuals via "Code principal"
"""

import csv
import re
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Individual, Sample, Tube, Box, Usage

TSV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'merged_final_Nath_V2.tsv')


def parse_volume(value):
    """Parse volume value - handles '<100', commas, empty strings"""
    if not value or value.strip() == '':
        return None
    value = value.strip()
    # Remove '<' prefix (e.g., '<100' -> 100)
    value = value.lstrip('<')
    # Replace comma with dot for decimal
    value = value.replace(',', '.')
    try:
        return float(value)
    except ValueError:
        return None


def parse_concentration(value):
    """Parse concentration value - handles commas, empty strings"""
    if not value or value.strip() == '':
        return None
    value = value.strip()
    value = value.replace(',', '.')
    try:
        return float(value)
    except ValueError:
        return None


def parse_position_v(letter):
    """Convert Position V letter to row number: A=1, B=2, ..., I=9"""
    if not letter or letter.strip() == '':
        return None
    letter = letter.strip().upper()
    if len(letter) == 1 and 'A' <= letter <= 'I':
        return ord(letter) - ord('A') + 1
    return None


def parse_position_h(value):
    """Parse Position H (column number)"""
    if not value or value.strip() == '':
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def build_freezer_info(frigo, etage):
    """Build freezer info string from frigo and étage"""
    parts = []
    if frigo and frigo.strip():
        parts.append(f"Frigo {frigo.strip()}")
    if etage and etage.strip():
        parts.append(f"Étage {etage.strip()}")
    return ", ".join(parts) if parts else None


def build_notes(code_alias, degrade, wga):
    """Build notes from various fields"""
    parts = []
    if code_alias and code_alias.strip():
        parts.append(f"Alias: {code_alias.strip()}")
    if degrade and degrade.strip():
        parts.append(f"Dégradé: {degrade.strip()}")
    if wga and wga.strip():
        parts.append(f"WGA: {wga.strip()}")
    return "; ".join(parts) if parts else None


def main():
    with app.app_context():
        print("=" * 70)
        print("REIMPORT TUBES & BOITES depuis merged_final_Nath_V2.tsv")
        print("=" * 70)

        # =============================================================
        # STEP 1: Show current state
        # =============================================================
        print(f"\n--- État actuel de la base ---")
        print(f"  Individus:  {db.session.query(Individual).count()}")
        print(f"  Samples:    {db.session.query(Sample).count()}")
        print(f"  Tubes:      {db.session.query(Tube).count()}")
        print(f"  Boîtes:     {db.session.query(Box).count()}")
        print(f"  Usages:     {db.session.query(Usage).count()}")

        # =============================================================
        # STEP 2: Purge tubes, boxes, usages
        # =============================================================
        print(f"\n--- Purge des tubes, boîtes et usages ---")
        
        n_usages = db.session.query(Usage).delete()
        print(f"  Usages supprimés: {n_usages}")
        
        n_tubes = db.session.query(Tube).delete()
        print(f"  Tubes supprimés: {n_tubes}")
        
        n_boxes = db.session.query(Box).delete()
        print(f"  Boîtes supprimées: {n_boxes}")
        
        db.session.commit()
        print("  ✓ Purge terminée")

        # =============================================================
        # STEP 3: Read TSV file
        # =============================================================
        print(f"\n--- Lecture du fichier TSV ---")
        print(f"  Fichier: {TSV_FILE}")
        
        rows = []
        with open(TSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter='\t')
            header = next(reader)
            print(f"  Colonnes: {header}")
            for row in reader:
                if len(row) >= 12:  # Minimum required columns
                    rows.append(row)
        
        print(f"  Lignes lues: {len(rows)}")

        # =============================================================
        # STEP 4: Load existing individuals into a lookup dict
        # =============================================================
        print(f"\n--- Chargement des individus existants ---")
        individuals = Individual.query.all()
        individual_map = {ind.individual_id: ind.id for ind in individuals}
        print(f"  Individus en base: {len(individual_map)}")

        # Also load existing samples by individual_id for reuse
        # Use raw SQL to avoid date parsing issues
        sample_rows = db.session.execute(
            db.text("SELECT id, individual_id, sample_id FROM sample WHERE individual_id IS NOT NULL")
        ).fetchall()
        # Map: individual_db_id -> first sample_db_id
        sample_by_individual = {}
        # Map: sample_id (text code) -> sample_db_id
        sample_by_code = {}
        for row in sample_rows:
            sid, ind_id, sample_code = row[0], row[1], row[2]
            if ind_id not in sample_by_individual:
                sample_by_individual[ind_id] = sid
            if sample_code:
                sample_by_code[sample_code] = sid
        
        # Also load samples without individual
        orphan_rows = db.session.execute(
            db.text("SELECT id, sample_id FROM sample WHERE individual_id IS NULL AND sample_id IS NOT NULL")
        ).fetchall()
        for row in orphan_rows:
            sid, sample_code = row[0], row[1]
            if sample_code and sample_code not in sample_by_code:
                sample_by_code[sample_code] = sid
        
        print(f"  Samples existants avec individu: {len(sample_by_individual)}")
        print(f"  Samples indexés par code: {len(sample_by_code)}")

        # =============================================================
        # STEP 5: Create boxes from unique box names
        # =============================================================
        print(f"\n--- Création des boîtes ---")
        
        # Collect unique box info: key = Nom Boîte
        box_info = {}  # name -> {freezer, box_type, numero}
        for row in rows:
            nom_boite = row[9].strip() if len(row) > 9 else ''
            if not nom_boite:
                continue
            
            if nom_boite not in box_info:
                frigo = row[6].strip() if len(row) > 6 else ''
                etage = row[7].strip() if len(row) > 7 else ''
                numero = row[8].strip() if len(row) > 8 else ''
                box_type = row[11].strip() if len(row) > 11 else ''
                
                box_info[nom_boite] = {
                    'freezer': build_freezer_info(frigo, etage),
                    'box_type': box_type or 'stock',
                    'numero': numero
                }
        
        # Create boxes
        box_name_to_id = {}
        for name, info in box_info.items():
            box = Box(
                name=name,
                box_type=info['box_type'],
                freezer=info['freezer'],
                notes=f"N° boîte: {info['numero']}" if info['numero'] else None
            )
            db.session.add(box)
            db.session.flush()  # Get the ID
            box_name_to_id[name] = box.id
        
        db.session.commit()
        print(f"  Boîtes créées: {len(box_name_to_id)}")
        for name, bid in sorted(box_name_to_id.items()):
            info = box_info[name]
            print(f"    {name} (id={bid}) - {info['freezer'] or 'pas de frigo'} - {info['box_type']}")

        # =============================================================
        # STEP 6: Create tubes
        # =============================================================
        print(f"\n--- Création des tubes ---")
        
        created = 0
        skipped_dup_barcode = 0
        skipped_dup_position = 0
        skipped_no_barcode = 0
        linked_to_individual = 0
        not_linked = 0
        samples_created = 0
        samples_reused = 0
        seen_barcodes = set()
        seen_positions = set()  # (box_name, pos_h, pos_v) to avoid >81 tubes per box
        
        for i, row in enumerate(rows):
            barcode = row[0].strip() if len(row) > 0 else ''
            code_principal = row[1].strip() if len(row) > 1 else ''
            code_alias = row[2].strip() if len(row) > 2 else ''
            volume_str = row[3] if len(row) > 3 else ''
            pos_h_str = row[4] if len(row) > 4 else ''
            pos_v_str = row[5] if len(row) > 5 else ''
            # Columns 6,7,8 = frigo, etage, numero (already used for boxes)
            nom_boite = row[9].strip() if len(row) > 9 else ''
            pos_num = row[10].strip() if len(row) > 10 else ''
            # Column 11 = type boite (already used)
            concentration_str = row[12] if len(row) > 12 else ''
            degrade = row[13].strip() if len(row) > 13 else ''
            tissus = row[14].strip() if len(row) > 14 else ''
            wga = row[15].strip() if len(row) > 15 else ''
            
            # Skip if no barcode
            if not barcode:
                skipped_no_barcode += 1
                continue
            
            # Skip duplicate barcodes (keep first occurrence)
            if barcode in seen_barcodes:
                skipped_dup_barcode += 1
                continue
            seen_barcodes.add(barcode)
            
            # Skip duplicate positions within the same box (keep first occurrence)
            if nom_boite and pos_h_str.strip() and pos_v_str.strip():
                pos_key = (nom_boite, pos_h_str.strip(), pos_v_str.strip())
                if pos_key in seen_positions:
                    skipped_dup_position += 1
                    continue
                seen_positions.add(pos_key)
            
            # Find box
            box_id = box_name_to_id.get(nom_boite)
            
            # Find individual and sample
            sample_id = None
            if code_principal:
                # Clean code principal (remove † and other markers)
                clean_code = code_principal.rstrip('†').strip()
                individual_db_id = individual_map.get(clean_code)
                
                if individual_db_id:
                    linked_to_individual += 1
                    
                    # Check if individual already has a sample
                    if individual_db_id in sample_by_individual:
                        sample_id = sample_by_individual[individual_db_id]
                        samples_reused += 1
                    else:
                        # Create a new sample for this individual
                        # Use a unique sample_id - check if code_principal is already taken
                        new_sample_id = clean_code
                        suffix = 1
                        while new_sample_id in sample_by_code:
                            new_sample_id = f"{clean_code}_T{suffix}"
                            suffix += 1
                        
                        sample = Sample(
                            sample_id=new_sample_id,
                            individual_id=individual_db_id,
                            sample_type=tissus if tissus else None,
                            notes=f"Alias: {code_alias}" if code_alias else None
                        )
                        db.session.add(sample)
                        db.session.flush()
                        sample_id = sample.id
                        sample_by_individual[individual_db_id] = sample.id
                        sample_by_code[new_sample_id] = sample.id
                        samples_created += 1
                else:
                    not_linked += 1
            else:
                not_linked += 1
            
            # Parse position
            position_row = parse_position_v(pos_v_str)  # Letter -> row number
            position_col = parse_position_h(pos_h_str)   # Number -> column
            
            # Parse values
            current_volume = parse_volume(volume_str)
            concentration = parse_concentration(concentration_str)
            
            # Build quality from dégradé field
            quality = degrade if degrade else None
            
            # Build notes
            notes = build_notes(code_alias, degrade, wga)
            
            # Determine source (tissue type)
            source = tissus if tissus else None
            
            # Create tube
            tube = Tube(
                barcode=barcode,
                sample_id=sample_id,
                box_id=box_id,
                position_row=position_row,
                position_col=position_col,
                concentration=concentration,
                quality=quality,
                initial_volume=current_volume,  # Use current as initial (no other info)
                current_volume=current_volume,
                source=source,
                tube_type='stock',
                notes=notes
            )
            db.session.add(tube)
            created += 1
            
            # Commit in batches
            if created % 500 == 0:
                db.session.commit()
                print(f"  ... {created} tubes créés")
        
        db.session.commit()
        
        print(f"\n  --- Résumé tubes ---")
        print(f"  Tubes créés:            {created}")
        print(f"  Doublons barcode ignorés: {skipped_dup_barcode}")
        print(f"  Doublons position ignorés: {skipped_dup_position}")
        print(f"  Sans barcode:           {skipped_no_barcode}")
        print(f"  Liés à un individu:     {linked_to_individual}")
        print(f"  Non liés (individu non trouvé): {not_linked}")
        print(f"  Samples réutilisés:     {samples_reused}")
        print(f"  Samples créés:          {samples_created}")

        # =============================================================
        # STEP 7: Final state
        # =============================================================
        print(f"\n--- État final de la base ---")
        print(f"  Individus:  {db.session.query(Individual).count()}")
        print(f"  Samples:    {db.session.query(Sample).count()}")
        print(f"  Tubes:      {db.session.query(Tube).count()}")
        print(f"  Boîtes:     {db.session.query(Box).count()}")
        print(f"  Usages:     {db.session.query(Usage).count()}")
        
        # Show some example tubes
        print(f"\n--- Exemples de tubes importés ---")
        example_tubes = Tube.query.limit(5).all()
        for t in example_tubes:
            sample_code = ''
            individual_code = ''
            if t.sample:
                sample_code = t.sample.sample_id
                if t.sample.individual:
                    individual_code = t.sample.individual.individual_id
            box_name = t.box.name if t.box else 'N/A'
            print(f"  Barcode={t.barcode}, Individu={individual_code}, "
                  f"Boîte={box_name}, Position={t.get_position_display()}, "
                  f"Vol={t.current_volume}, Conc={t.concentration}, "
                  f"Source={t.source}")
        
        # Show box stats
        print(f"\n--- Statistiques boîtes ---")
        from sqlalchemy import func
        box_stats = db.session.query(
            Box.name, func.count(Tube.id)
        ).outerjoin(Tube, Tube.box_id == Box.id).group_by(Box.id).order_by(Box.name).all()
        for name, count in box_stats:
            print(f"  {name}: {count} tubes")
        
        print(f"\n✅ Import terminé avec succès!")


if __name__ == '__main__':
    main()
