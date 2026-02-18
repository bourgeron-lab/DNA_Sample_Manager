# CLAUDE.md — DNA Sample Manager

Ce fichier donne à Claude Code le contexte nécessaire pour travailler efficacement sur ce projet.

## Architecture

Application web Flask packagée pour `uvx` / `uv run`.

- **Backend** : Flask 3 + SQLAlchemy (ORM) + SQLite (base de données fichier)
- **Frontend** : Bootstrap 5 + Chart.js via CDN (pas de build step, pas de node_modules)
- **Packaging** : `uv_build` + `pyproject.toml`, entry point `dna-sample-manager`
- **CLI** : Typer (`cli.py`) — accepte `data_dir` (chemin vers le dossier contenant `dna_samples.db`)

## Lancement

```bash
uv run dna-sample-manager ./instance/        # port 5003 par défaut
uv run dna-sample-manager ./instance/ --port 8080
```

Le navigateur s'ouvre automatiquement (via `threading.Timer` + `webbrowser.open`).

## Fichiers critiques

| Fichier | Rôle |
|---------|------|
| `src/dna_sample_manager/app.py` | Tout : modèles SQLAlchemy, helpers, ~50 routes Flask |
| `src/dna_sample_manager/cli.py` | Entry point CLI, instancie Flask via `create_app(db_path)` |
| `src/dna_sample_manager/templates/` | 8 templates Jinja2 (Bootstrap 5) |
| `instance/dna_samples.db` | Base de données SQLite — ne jamais supprimer |
| `pyproject.toml` | Dépendances : flask, flask-sqlalchemy, openpyxl, typer |
| `uv.lock` | Versions exactes — ne pas modifier manuellement |

## Modèles de données (`app.py`)

```
Individual  ─── (1:N) ──→  Sample  ─── (1:N) ──→  Tube
                                                      │
                                              TubeUsage (historique)
Box ◄─── (N:1) ─────────────────────────────────── Tube
```

- **Individual** : `individual_id`, `aliases`, `family_id`, `sex`, `phenotype`, `projects`
- **Sample** : `sample_id`, `sample_type` (ADN/ARN/etc.), lié à un `Individual`
- **Tube** : `barcode`, `tube_type` (stock/working), `current_volume`, `initial_volume`, lié à `Sample` + `Box`
- **Box** : `name`, `freezer`, `rows`, `cols`

## Conventions de code

- `safe_int(value, default, min_val, max_val)` — toujours utiliser à la place de `int()` pour les paramètres HTTP
- `_build_tubes_query(search, box, status, tube_type, limit)` — helper réutilisé par `GET /api/tubes` et `GET /api/tubes/export`
- `_tubes_to_dicts(tubes)` — sérialise une liste de `Tube` en dicts avec batch-loading des relations
- `create_app(db_path=None)` — factory Flask, appelée par `cli.py`. `db_path` est un chemin absolu vers le fichier SQLite
- Encodage TSV : `utf-8-sig` (BOM) pour compatibilité Excel Windows

## Routes principales

- `GET /` — tableau de bord
- `GET /tubes`, `GET /boxes`, `GET /sujets`, `GET /samples` — pages UI
- `GET /api/tubes?search=&box=&status=&type=&limit=&page=` — liste paginée avec filtres
- `GET /api/tubes/export?format=tsv|xlsx&search=&box=&status=&type=` — export (doit être avant `/api/tubes/<int:id>`)
- `GET /api/stats` — statistiques (optimisé : charge uniquement les colonnes nécessaires)
- `GET /api/projects` — liste des projets (extrait depuis la colonne `projects` des individus)

## Statuts des tubes (logique SQL dans `_build_tubes_query`)

- **Empty** : `current_volume IS NULL OR current_volume <= 0`
- **Critical** : `current_volume > 0 AND current_volume < 10`
- **Low** : `current_volume >= 10 AND initial_volume IS NOT NULL AND current_volume < initial_volume * 0.25`
- **Available** : `current_volume >= 10 AND (initial_volume IS NULL OR current_volume >= initial_volume * 0.25)`

## Scripts utilitaires (racine)

Scripts à usage ponctuel pour l'import/migration de données. Ne font pas partie du package.
Lancer avec : `uv run python <script>.py`

- `import_individuals.py` / `import_individuals_fast.py` — import depuis TSV
- `import_tubes_from_mysql.py` / `_v2.py` — import depuis MySQL
- `reimport_tubes_boxes.py` — réimport tubes et boîtes
- `recreate_db_with_indexes.py` — recrée le schéma avec index
- `check_data.py`, `analyze_positions.py` — diagnostic et analyse

## Ce qu'il ne faut pas toucher

- `instance/dna_samples.db` — données de production
- `uv.lock` — ne modifier qu'en changeant `pyproject.toml` puis `uv lock`
- L'ordre des routes Flask dans `app.py` : `/api/tubes/export` doit rester avant `/api/tubes/<int:id>`

## Sécurité

- `SECRET_KEY` via `os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))`
- XSS : fonction `esc()` dans les templates pour échapper les données dans les template literals JS
- Pas d'authentification (usage interne réseau uniquement)
