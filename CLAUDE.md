# CLAUDE.md — DNA Sample Manager

Ce fichier donne à Claude Code le contexte nécessaire pour travailler efficacement sur ce projet.

## Architecture

Application web Flask packagée pour `uvx` / `uv run`.

- **Backend** : Flask 3 + SQLAlchemy (ORM) + SQLite (base de données fichier)
- **Frontend** : Bootstrap 5 + Chart.js via CDN (pas de build step, pas de node_modules)
- **Packaging** : `uv_build` + `pyproject.toml`, entry point `dna-sample-manager`
- **CLI** : Typer (`cli.py`) — accepte `data_dir` (chemin vers le dossier contenant `dna_samples.db`)
- **Serveur** : waitress (multi-thread, UN seul processus — SQLite + thread de sauvegarde). Pas de gunicorn multi-workers

## Lancement

```bash
uv run dna-sample-manager ./instance/        # port 5003 par défaut
uv run dna-sample-manager ./instance/ --port 8080
uv run dna-sample-manager ./instance/ --no-browser
```

Le navigateur s'ouvre automatiquement (via `threading.Timer` + `webbrowser.open`), sauf `--no-browser`.

Production (VM Linux, systemd + nginx HTTPS) : `deploy/DEPLOIEMENT.md`. Le service lance
`dna-sample-manager /srv/dna-sample-manager --host 127.0.0.1 --behind-proxy --no-browser --backup-dir …`.

## Fichiers critiques

| Fichier | Rôle |
|---------|------|
| `src/dna_sample_manager/app.py` | Tout : modèles SQLAlchemy, helpers, ~50 routes Flask |
| `src/dna_sample_manager/cli.py` | Entry point CLI, instancie Flask via `create_app(db_path)`, lance les sauvegardes |
| `deploy/` | Service systemd, conf nginx, guide `DEPLOIEMENT.md` (testé sur Debian 12 dans Docker) |
| `src/dna_sample_manager/backup.py` | Sauvegarde SQLite (API `backup`, vérification, rotation, thread périodique) |
| `src/dna_sample_manager/templates/` | 8 templates Jinja2 (Bootstrap 5) |
| `instance/dna_samples.db` | Base de données SQLite — ne jamais supprimer |
| `pyproject.toml` | Dépendances : flask, flask-sqlalchemy, flask-login, flask-bcrypt, flask-wtf (CSRF), openpyxl, typer |
| `uv.lock` | Versions exactes — ne pas modifier manuellement |

## Modèles de données (`app.py`)

```
User (auth)

Individual  ─── (1:N) ──→  Sample  ─── (1:N) ──→  Tube
                                                      │
                                              Usage (historique)

AuditLog (journal des modifications, alimenté automatiquement)
Box ◄─── (N:1) ─────────────────────────────────── Tube
```

- **User** : `username` (unique), `password_hash`, `is_admin` — authentification Flask-Login + bcrypt
- **Individual** : `individual_id`, `aliases`, `family_id`, `sex`, `phenotype`, `projects`
- **Sample** : `sample_id`, `sample_type` (ADN/ARN/etc.), lié à un `Individual`
- **Tube** : `barcode`, `tube_type` (stock/working), `current_volume`, `initial_volume`, lié à `Sample` + `Box`
- **Box** : `name`, `freezer`, `rows`, `cols`
- **Usage** : `user_id` / `user_name` = compte connecté, fixés côté serveur (non modifiables via l'API)
- **AuditLog** : `timestamp` (UTC), `user_id`, `username`, `action` (create/update/delete), `entity`, `entity_id`, `label`, `changes` (JSON). Rempli par le listener SQLAlchemy `_write_audit_log` (`after_flush`) pour les tables de `AUDITED_ENTITIES` — ne pas écrire dedans à la main. Les opérations en masse (`query.update()`/`query.delete()`) ne sont PAS tracées : passer par l'ORM objet par objet

## Conventions de code

- `safe_int(value, default, min_val, max_val)` — toujours utiliser à la place de `int()` pour les paramètres HTTP
- `_build_tubes_query(search, box, status, tube_type, limit)` — helper réutilisé par `GET /api/tubes` et `GET /api/tubes/export`
- `_tubes_to_dicts(tubes)` — sérialise une liste de `Tube` en dicts avec batch-loading des relations
- `create_app(db_path=None, behind_proxy=False)` — factory Flask, appelée par `cli.py`. `db_path` est un chemin absolu vers le fichier SQLite
- Encodage TSV : `utf-8-sig` (BOM) pour compatibilité Excel Windows

## Authentification

- Flask-Login + Flask-Bcrypt, toutes les routes protégées via `@app.before_request`
- Seed automatique : si aucun utilisateur en base, crée `admin/admin` au démarrage
- `GET/POST /login` — page de connexion
- `GET /logout` — déconnexion
- `GET /admin/users` — gestion des utilisateurs (admin uniquement)
- `GET/POST/PUT/DELETE /api/users` — CRUD utilisateurs (admin uniquement)

## Routes principales

- `GET /` — tableau de bord
- `GET /tubes`, `GET /boxes`, `GET /sujets`, `GET /samples` — pages UI
- `GET /api/tubes?search=&box=&status=&type=&limit=&page=` — liste paginée avec filtres
- `GET /api/tubes/export?format=tsv|xlsx&search=&box=&status=&type=` — export (doit être avant `/api/tubes/<int:id>`)
- `GET /api/usages?tube=` — historique d'utilisation des tubes
- `POST /api/usages` — enregistrer une utilisation (déduit le volume du tube)
- `PUT /api/usages/<int:id>` — modifier un usage record (ajuste le volume du tube selon le delta)
- `GET /api/audit?entity=&entity_id=&user=&action=&search=&limit=` — journal des modifications (entrées `user` réservées aux admins)
- `GET /api/stats` — statistiques (optimisé : charge uniquement les colonnes nécessaires)
- `GET /api/projects` — liste des projets (extrait depuis la colonne `projects` des individus)

## Statuts des tubes (logique SQL dans `_build_tubes_query`)

- **Empty** : `current_volume IS NULL OR current_volume <= 0`
- **Critical** : `current_volume > 0 AND current_volume < 10`
- **Low** : `current_volume >= 10 AND initial_volume IS NOT NULL AND current_volume < initial_volume * 0.25`
- **Available** : `current_volume >= 10 AND (initial_volume IS NULL OR current_volume >= initial_volume * 0.25)`

`Tube.get_status()` (Python) doit rester cohérent avec ce filtre SQL — vérifié par `tests/test_tubes.py::test_filtre_sql_coherent_avec_get_status`.

## Archivage des tubes (`tube_type = 'deleted'`)

- Passage en `deleted` : position libérée (`box_id`, `position_row`, `position_col` → NULL) et préfixe `[Archivé le …] Boîte, Congélateur, Position` ajouté en tête des notes (fusionné avec les notes envoyées par le formulaire)
- Tant que le tube est archivé, `box_id`/`position_*` envoyés à `PUT /api/tubes/<id>` sont ignorés (le formulaire d'édition renvoie toujours les anciennes valeurs)
- Désarchivage : repasser `tube_type` à `stock`/`working` avec une nouvelle position
- Liste par défaut : exclut `deleted` (les tubes à `tube_type` NULL restent visibles)

## Sauvegardes (`backup.py`)

- Au démarrage (dans `cli.py`, AVANT `create_app` qui peut créer des tables) puis toutes les `--backup-interval` h (24 par défaut) via un thread daemon
- Dossier : `--backup-dir` (défaut `<dossier de la base>/backups`), rotation `--keep` (30). Noms `dna_samples_AAAA-MM-JJ_HHMMSS[_n].db`
- `--backup-only` : sauvegarde puis quitte ; `--no-backup` : désactive tout
- Toujours `backup_database()` (API SQLite `Connection.backup` + `integrity_check` + renommage atomique), jamais un `cp` de la base pendant que l'app tourne
- `prune_backups` ne supprime que les fichiers au format exact des sauvegardes
- Avant un import ou une migration avec les scripts utilitaires : `uv run dna-sample-manager ./instance/ --backup-only`

## Tests

```bash
uv run pytest                # ~107 tests, ~4 s
uv run pytest tests/test_tubes.py -k archivage
```

- `tests/conftest.py` : base SQLite temporaire, vidée et re-remplie avant chaque test (jamais la base de prod) ; clients `anon` / `admin` / `tech` qui gèrent login + jeton CSRF comme le navigateur
- Ajouter un test de régression pour chaque bug corrigé

## Scripts utilitaires (racine)

Scripts à usage ponctuel pour l'import/migration de données. Ne font pas partie du package.
Faire une sauvegarde (`--backup-only`) avant de les lancer sur la base de prod.
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

- `SECRET_KEY` (`_load_secret_key`) : `FLASK_SECRET_KEY` sinon fichier `secret_key` (600) à côté de la base, créé au 1er lancement — stable entre redémarrages (sinon tout le monde est déconnecté)
- `--behind-proxy` : waitress accepte `X-Forwarded-For/Proto/Host` UNIQUEMENT depuis 127.0.0.1 (`cli.waitress_options`) — par défaut waitress les supprime, l'app se croirait alors en HTTP et la vérification CSRF stricte du Referer (HTTPS) serait désactivée. Cookies `Secure`. Ne pas remplacer par `ProxyFix` (waitress supprime les en-têtes avant)
- Démarrage : avertissement dans les journaux si le compte `admin` a encore le mot de passe `admin`
- XSS : fonction `esc()` dans les templates pour échapper les données dans les template literals JS
- CSRF : Flask-WTF `CSRFProtect` sur toutes les requêtes POST/PUT/DELETE. `base.html` expose le jeton (`<meta name="csrf-token">`) et enveloppe `window.fetch` pour ajouter l'en-tête `X-CSRFToken` automatiquement ; les formulaires HTML classiques doivent inclure `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`
- Redirection après login : `?next=` n'accepte que des chemins locaux (`_safe_next_url`)
- API non authentifiée : 401 JSON (les pages redirigent vers `/login`)
- Authentification : Flask-Login avec mots de passe hashés (bcrypt). Admin par défaut `admin/admin`
