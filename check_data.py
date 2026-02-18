from app import app, db, Individual, Sample

with app.app_context():
    ind = Individual.query.first()
    print(f'Premier individu: {ind.individual_id}')
    print(f'Nombre de samples: {len(ind.samples)}')
    
    if ind.samples:
        print('Quelques samples:')
        for s in ind.samples[:3]:
            print(f'  - {s.sample_id}')
    
    # Check samples with individuals
    sample_with_ind = Sample.query.filter(Sample.individual_id != None).count()
    print(f'\nSamples avec individu: {sample_with_ind} / {Sample.query.count()}')
