#!/usr/bin/env python3
"""Test script to debug tubes API"""
import sys
sys.path.insert(0, '/Users/amathieu/GHFC/sandbox_adn')

from app import app, db, Tube, Sample, Individual, Box

with app.app_context():
    # Get first 2 tubes
    tubes = Tube.query.limit(2).all()
    print(f"Found {len(tubes)} tubes")
    
    for t in tubes:
        print(f"\nTube {t.id}: {t.barcode}")
        print(f"  sample_id: {t.sample_id}")
        print(f"  box_id: {t.box_id}")
        
        # Try to_dict_light
        try:
            result = t.to_dict_light()
            print(f"  to_dict_light OK: {list(result.keys())}")
        except Exception as e:
            print(f"  ERROR in to_dict_light: {e}")
            import traceback
            traceback.print_exc()
