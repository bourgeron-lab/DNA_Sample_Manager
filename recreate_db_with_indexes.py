"""
Script pour recréer la base de données avec les index optimisés
"""

from app import app, db

def recreate_db_with_indexes():
    """Drop and recreate all tables with indexes"""
    with app.app_context():
        print("Suppression des anciennes tables...")
        db.drop_all()
        
        print("Création des nouvelles tables avec index...")
        db.create_all()
        
        print("✓ Base de données recréée avec succès!")
        print("\nLes index suivants ont été ajoutés:")
        print("  - Individual.individual_id (index)")
        print("  - Individual.family_id (index)")
        print("  - Sample.sample_id (index)")
        print("  - Sample.individual_id (index)")
        print("  - Sample.sample_type (index)")
        print("  - Sample.created_at (index)")
        print("  - Tube.barcode (index)")
        print("  - Tube.sample_id (index)")
        print("  - Tube.box_id (index)")
        print("\nVous pouvez maintenant réimporter les données avec:")
        print("  python3 import_individuals_fast.py individuals_2026-01-26-14h58m09s.tsv")

if __name__ == '__main__':
    recreate_db_with_indexes()
