"""
Quick import script for individuals and samples - version optimisée
"""

import csv
import sys
from datetime import datetime
from app import app, db, Individual, Sample


def import_tsv_fast(filepath, batch_size=100):
    """Import avec commits par batch pour éviter les blocages"""
    
    with app.app_context():
        counters = {
            'individuals': 0,
            'samples': 0,
            'errors': 0
        }
        
        batch_count = 0
        
        print(f"Ouverture du fichier {filepath}...")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            
            for row_num, row in enumerate(reader, start=2):
                try:
                    individual_id = row.get('ID', '').strip()
                    if not individual_id:
                        continue
                    
                    # Check if individual exists
                    ind = Individual.query.filter_by(individual_id=individual_id).first()
                    
                    if not ind:
                        # Parse data
                        sex = None
                        sex_str = row.get('Sex', '').strip()
                        if sex_str:
                            try:
                                sex = int(sex_str)
                            except:
                                pass
                        
                        # Create individual
                        ind = Individual(
                            individual_id=individual_id,
                            aliases=row.get('Aliases', '').strip() or None,
                            family_id=row.get('Family ID', '').strip() or None,
                            sex=sex,
                            phenotype=row.get('Phenotype', '').strip() or None,
                            projects=row.get('Projects', '').strip() or None,
                            other_family_codes=row.get('Other family codes', '').strip() or None
                        )
                        db.session.add(ind)
                        counters['individuals'] += 1
                    
                    # Add samples
                    samples_str = row.get('Samples', '').strip()
                    if samples_str:
                        for sample_code in samples_str.split(','):
                            sample_code = sample_code.strip()
                            if sample_code:
                                existing_sample = Sample.query.filter_by(sample_id=sample_code).first()
                                if not existing_sample:
                                    # Flush to get ind.id
                                    db.session.flush()
                                    
                                    sample = Sample(
                                        sample_id=sample_code,
                                        individual_id=ind.id
                                    )
                                    db.session.add(sample)
                                    counters['samples'] += 1
                    
                    batch_count += 1
                    
                    # Commit par batch
                    if batch_count >= batch_size:
                        db.session.commit()
                        print(f"  {row_num} lignes traitées... ({counters['individuals']} individus, {counters['samples']} échantillons)")
                        batch_count = 0
                        
                except Exception as e:
                    counters['errors'] += 1
                    if counters['errors'] <= 5:
                        print(f"Erreur ligne {row_num}: {e}")
                    continue
        
        # Final commit
        db.session.commit()
        
        print(f"\n{'='*60}")
        print(f"IMPORT TERMINÉ")
        print(f"{'='*60}")
        print(f"Individus créés: {counters['individuals']}")
        print(f"Échantillons créés: {counters['samples']}")
        print(f"Erreurs: {counters['errors']}")
        print(f"{'='*60}\n")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python import_individuals_fast.py <tsv_file>")
        sys.exit(1)
    
    import_tsv_fast(sys.argv[1])
