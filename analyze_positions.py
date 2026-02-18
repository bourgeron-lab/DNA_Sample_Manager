#!/usr/bin/env python3
"""Analyze box position issues"""
from app import app, db, Tube, Box

with app.app_context():
    # Check the 3 boxes with overflow
    for box_name in ['AU-FR-001', 'AU-FR-002', 'AU-FR-003']:
        box = Box.query.filter_by(name=box_name).first()
        if not box:
            continue
        tubes = Tube.query.filter_by(box_id=box.id).order_by(Tube.position_row, Tube.position_col).all()
        print(f'\n=== Box {box.name}: {len(tubes)} tubes ===')
        
        positions = {}
        for t in tubes:
            key = (t.position_row, t.position_col)
            if key not in positions:
                positions[key] = []
            positions[key].append(t.barcode)
        
        print(f'Positions uniques: {len(positions)}')
        
        dups = {k: v for k, v in positions.items() if len(v) > 1}
        if dups:
            print(f'Positions avec doublons ({len(dups)}):')
            for (r,c), barcodes in sorted(dups.items()):
                letter = chr(64+r) if r and r <= 9 else '?'
                print(f'  {letter}{c}: {barcodes}')
        
        oor = [(t.barcode, t.position_row, t.position_col) for t in tubes 
               if t.position_row and t.position_col and (t.position_row > 9 or t.position_col > 9)]
        if oor:
            print(f'Hors grille 9x9 ({len(oor)}):')
            for b, r, c in oor:
                print(f'  {b}: row={r}, col={c}')

    # Now check the TSV source to understand why
    print('\n\n=== Analyse du TSV source ===')
    import csv
    with open('merged_final_Nath_V2.tsv', 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter='\t')
        header = next(reader)
        
        box_positions = {}  # box_name -> {(posH, posV): [barcodes]}
        for row in reader:
            if len(row) < 12:
                continue
            barcode = row[0].strip()
            pos_h = row[4].strip()  # Position H (number = column)
            pos_v = row[5].strip()  # Position V (letter = row)
            nom_boite = row[9].strip()
            pos_num = row[10].strip()  # Position (numéro)
            
            if nom_boite in ['AU-FR-001', 'AU-FR-002', 'AU-FR-003']:
                if nom_boite not in box_positions:
                    box_positions[nom_boite] = {}
                key = (pos_h, pos_v, pos_num)
                if key not in box_positions[nom_boite]:
                    box_positions[nom_boite][key] = []
                box_positions[nom_boite][key].append(barcode)
        
        for bname, posdata in sorted(box_positions.items()):
            print(f'\n--- TSV: {bname} ({sum(len(v) for v in posdata.values())} lignes) ---')
            print(f'  Positions uniques (H,V,num): {len(posdata)}')
            
            # Show position ranges
            all_h = set()
            all_v = set()
            all_num = set()
            for (h,v,n), barcodes in posdata.items():
                all_h.add(h)
                all_v.add(v)
                all_num.add(n)
            
            print(f'  Position H values: {sorted(all_h, key=lambda x: int(x) if x.isdigit() else 0)}')
            print(f'  Position V values: {sorted(all_v)}')
            print(f'  Position (numéro) values: {sorted(all_num, key=lambda x: int(x) if x.isdigit() else 0)}')
            
            # Show duplicates
            dups = {k: v for k, v in posdata.items() if len(v) > 1}
            if dups:
                print(f'  Doublons de position ({len(dups)}):')
                for (h,v,n), barcodes in sorted(dups.items()):
                    print(f'    H={h},V={v},num={n}: {barcodes}')
