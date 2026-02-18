#!/usr/bin/env python3
"""Quick test for tubes endpoint"""
import sys
sys.path.insert(0, '/Users/amathieu/GHFC/sandbox_adn')

try:
    print("Importing app...")
    from app import app, db, Tube
    
    print("Creating test client...")
    with app.test_client() as client:
        print("Calling /api/tubes?limit=1...")
        response = client.get('/api/tubes?limit=1')
        print(f"Status: {response.status_code}")
        print(f"Data: {response.get_json()}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
