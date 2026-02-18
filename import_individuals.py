"""
Import script for individuals and samples from TSV file
Format expected:
ID	Aliases	Family ID	Sex	Phenotype	Projects	Samples	Other family codes
"""

import csv
import sys
from datetime import datetime
from app import app, db, Individual, Sample


def import_tsv(filepath):
    """Import individuals and samples from TSV file"""
    
    with app.app_context():
        # Counters
        individuals_created = 0
        individuals_updated = 0
        samples_created = 0
        samples_linked = 0
        errors = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            
            for row_num, row in enumerate(reader, start=2):
                try:
                    # Parse individual data
                    individual_id = row.get('ID', '').strip()
                    if not individual_id:
                        continue
                    
                    aliases = row.get('Aliases', '').strip() or None
                    family_id = row.get('Family ID', '').strip() or None
                    
                    # Parse sex (0=Unknown, 1=Male, 2=Female)
                    sex_str = row.get('Sex', '').strip()
                    sex = None
                    if sex_str:
                        try:
                            sex = int(sex_str)
                        except ValueError:
                            sex = None
                    
                    phenotype = row.get('Phenotype', '').strip() or None
                    projects = row.get('Projects', '').strip() or None
                    samples_str = row.get('Samples', '').strip() or ''
                    other_family_codes = row.get('Other family codes', '').strip() or None
                    
                    # Check if individual already exists
                    existing = Individual.query.filter_by(individual_id=individual_id).first()
                    
                    if existing:
                        # Update existing individual
                        existing.aliases = aliases or existing.aliases
                        existing.family_id = family_id or existing.family_id
                        existing.sex = sex if sex is not None else existing.sex
                        existing.phenotype = phenotype or existing.phenotype
                        existing.projects = projects or existing.projects
                        existing.other_family_codes = other_family_codes or existing.other_family_codes
                        individual = existing
                        individuals_updated += 1
                    else:
                        # Create new individual
                        individual = Individual(
                            individual_id=individual_id,
                            aliases=aliases,
                            family_id=family_id,
                            sex=sex,
                            phenotype=phenotype,
                            projects=projects,
                            other_family_codes=other_family_codes
                        )
                        db.session.add(individual)
                        individuals_created += 1
                    
                    # Flush to get individual ID
                    db.session.flush()
                    
                    # Process samples (comma-separated)
                    if samples_str:
                        sample_codes = [s.strip() for s in samples_str.split(',') if s.strip()]
                        for sample_code in sample_codes:
                            # Check if sample already exists
                            existing_sample = Sample.query.filter_by(sample_id=sample_code).first()
                            
                            if existing_sample:
                                # Link sample to individual if not already linked
                                if existing_sample.individual_id != individual.id:
                                    existing_sample.individual_id = individual.id
                                    samples_linked += 1
                            else:
                                # Create new sample
                                sample = Sample(
                                    sample_id=sample_code,
                                    individual_id=individual.id
                                )
                                db.session.add(sample)
                                samples_created += 1
                    
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
                    continue
            
            # Commit all changes
            db.session.commit()
        
        # Print summary
        print("\n" + "="*60)
        print("IMPORT SUMMARY")
        print("="*60)
        print(f"Individuals created: {individuals_created}")
        print(f"Individuals updated: {individuals_updated}")
        print(f"Samples created: {samples_created}")
        print(f"Samples linked to individuals: {samples_linked}")
        
        if errors:
            print(f"\nErrors ({len(errors)}):")
            for err in errors[:10]:
                print(f"  - {err}")
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more errors")
        
        print("="*60 + "\n")
        
        return {
            'individuals_created': individuals_created,
            'individuals_updated': individuals_updated,
            'samples_created': samples_created,
            'samples_linked': samples_linked,
            'errors': errors
        }


def show_stats():
    """Show current database statistics"""
    with app.app_context():
        print("\n" + "="*60)
        print("DATABASE STATISTICS")
        print("="*60)
        print(f"Total individuals: {Individual.query.count()}")
        print(f"Total samples: {Sample.query.count()}")
        
        # Samples with individuals
        linked = Sample.query.filter(Sample.individual_id != None).count()
        print(f"Samples linked to individuals: {linked}")
        
        # Top families
        from sqlalchemy import func
        top_families = db.session.query(
            Individual.family_id, func.count(Individual.id)
        ).filter(Individual.family_id != None).group_by(
            Individual.family_id
        ).order_by(func.count(Individual.id).desc()).limit(10).all()
        
        print("\nTop 10 families:")
        for family, count in top_families:
            print(f"  {family}: {count} individuals")
        
        print("="*60 + "\n")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python import_individuals.py <tsv_file>")
        print("       python import_individuals.py --stats")
        sys.exit(1)
    
    if sys.argv[1] == '--stats':
        show_stats()
    else:
        filepath = sys.argv[1]
        print(f"Importing from: {filepath}")
        import_tsv(filepath)
        show_stats()
