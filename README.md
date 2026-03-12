# DNA Sample Manager

Application web de gestion de biobanque ADN : individus, échantillons, tubes et boîtes de stockage.

## Prérequis

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installé

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Lancement

```bash
uv run dna-sample-manager ./instance/
```

Le navigateur s'ouvre automatiquement sur `http://127.0.0.1:5003`.

### Options

```bash
uv run dna-sample-manager ./instance/ --port 8080
uv run dna-sample-manager ./instance/ --host 0.0.0.0 --port 5003
```

## Structure du projet

```
sandbox_adn/
├── src/dna_sample_manager/   # Code de l'application
│   ├── app.py                # Routes Flask et modèles SQLAlchemy
│   ├── cli.py                # Point d'entrée CLI (Typer)
│   └── templates/            # Templates HTML (Bootstrap 5)
├── instance/
│   └── dna_samples.db        # Base de données SQLite
├── pyproject.toml            # Dépendances et configuration du package
├── uv.lock                   # Versions exactes des dépendances
├── run.sh                    # Lanceur alternatif (gunicorn)
└── import_*.py               # Scripts d'import de données
```

## Authentification

Toutes les pages et API sont protégées par login. Au premier lancement, un compte admin est créé automatiquement :
- **Utilisateur** : `admin`
- **Mot de passe** : `admin`

Changez le mot de passe depuis la page **Utilisateurs** (visible uniquement pour les admins dans la sidebar).

## API REST

| Méthode | Route | Description |
|---------|-------|-------------|
| GET/POST | `/api/users` | Gestion des utilisateurs (admin) |
| PUT/DELETE | `/api/users/<id>` | Modifier/supprimer un utilisateur (admin) |
| GET | `/api/individuals` | Liste des individus (pagination, recherche) |
| GET/POST | `/api/sujets` | Individus (alias) |
| GET | `/api/samples` | Échantillons |
| GET | `/api/tubes` | Tubes (filtres : search, box, status, type) |
| GET | `/api/tubes/export` | Export tubes (`?format=tsv` ou `?format=xlsx`) |
| GET | `/api/boxes` | Boîtes de stockage |
| GET | `/api/usages` | Historique d'utilisation des tubes |
| POST | `/api/usages` | Enregistrer une utilisation |
| PUT | `/api/usages/<id>` | Modifier un usage record |
| GET | `/api/stats` | Statistiques du tableau de bord |

## Scripts utilitaires

Ces scripts servent à importer/migrer des données et doivent être lancés directement avec `uv run python <script>` :

| Script | Usage |
|--------|-------|
| `import_data.py` | Import général depuis TSV |
| `import_individuals.py` | Import des individus |
| `import_individuals_fast.py` | Import individus (mode rapide) |
| `import_tubes_from_mysql.py` | Import tubes depuis MySQL |
| `reimport_tubes_boxes.py` | Réimport tubes et boîtes |
| `recreate_db_with_indexes.py` | Recrée la DB avec index optimisés |
| `check_data.py` | Vérification de cohérence des données |
| `analyze_positions.py` | Analyse des positions dans les boîtes |

## Déploiement sur VM

```bash
# Installer uv sur la VM
curl -LsSf https://astral.sh/uv/install.sh | sh

# Copier instance/dna_samples.db sur la VM, puis lancer
uvx --from /chemin/vers/dna_sample_manager-0.1.0-py3-none-any.whl \
    dna-sample-manager /chemin/vers/données/ --host 0.0.0.0
```

## Technologies

- **Backend** : Python 3.12, Flask 3, SQLAlchemy
- **Base de données** : SQLite
- **Frontend** : Bootstrap 5, Chart.js (via CDN)
- **Export** : openpyxl (Excel), csv (TSV)
- **Packaging** : uv / uv_build
