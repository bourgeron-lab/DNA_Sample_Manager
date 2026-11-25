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
uv run dna-sample-manager ./instance/ --no-browser          # ne pas ouvrir le navigateur
```

L'app est servie par [waitress](https://docs.pylonsproject.org/projects/waitress/), un serveur
de production multi-thread en un seul processus (ce qu'il faut pour SQLite). Pour un accès par
tout le labo, ne pas utiliser `--host 0.0.0.0` (pas de HTTPS) : voir [Mise en production](#mise-en-production).

## Structure du projet

```
sandbox_adn/
├── src/dna_sample_manager/   # Code de l'application
│   ├── app.py                # Routes Flask et modèles SQLAlchemy
│   ├── cli.py                # Point d'entrée CLI (Typer)
│   └── templates/            # Templates HTML (Bootstrap 5)
├── instance/
│   ├── dna_samples.db        # Base de données SQLite
│   ├── secret_key            # Clé de session (créée au 1er lancement, ne pas partager)
│   └── backups/              # Sauvegardes automatiques
│   ├── backup.py             # Sauvegardes de la base
├── deploy/                   # Mise en production : systemd + nginx (VM), kubernetes/
├── Dockerfile                # Image pour Kubernetes (aucune donnée dedans)
├── tests/                    # Tests pytest
├── pyproject.toml            # Dépendances et configuration du package
├── uv.lock                   # Versions exactes des dépendances
└── import_*.py               # Scripts d'import de données
```

## Authentification

Toutes les pages et API sont protégées par login. Au premier lancement, un compte admin est créé automatiquement :
- **Utilisateur** : `admin`
- **Mot de passe** : `admin`

Changez le mot de passe depuis la page **Utilisateurs** (visible uniquement pour les admins dans la sidebar).

Les requêtes qui modifient des données sont protégées contre le CSRF (jeton ajouté automatiquement par les pages).

## Traçabilité

- Chaque utilisation de tube est enregistrée au nom du compte connecté (non modifiable).
- Toute création, modification ou suppression (tubes, usages, samples, individus, boîtes, utilisateurs) est inscrite dans un **journal des modifications** (qui, quand, valeurs avant → après), consultable en bas de la page **Historique**. Les mots de passe n'y apparaissent jamais.

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
| GET | `/api/audit` | Journal des modifications (filtres : entity, entity_id, user, action, search, limit) |
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

## Sauvegardes

La base est sauvegardée **automatiquement** :
- au démarrage de l'application (avant toute modification du schéma) ;
- puis toutes les 24 h tant qu'elle tourne.

Les sauvegardes vont dans `instance/backups/` (`dna_samples_AAAA-MM-JJ_HHMMSS.db`) ; les **30 plus récentes** sont conservées. Chaque copie est faite avec l'API de sauvegarde de SQLite (cohérente même pendant que l'app écrit) et vérifiée (`PRAGMA integrity_check`) avant d'être gardée.

```bash
# Sauvegarde immédiate, sans démarrer le serveur (ex. avant un import ou une migration)
uv run dna-sample-manager ./instance/ --backup-only

# Sauvegardes sur un autre disque (recommandé : protège aussi d'une panne du disque de la base)
uv run dna-sample-manager ./instance/ --backup-dir /Volumes/autre_disque/dna_backups --keep 60

# Autre rythme, ou désactivation
uv run dna-sample-manager ./instance/ --backup-interval 6
uv run dna-sample-manager ./instance/ --no-backup
```

### Restaurer une sauvegarde

1. Arrêter l'application (`Ctrl+C`).
2. Mettre de côté la base actuelle (ne pas la supprimer) :
   ```bash
   mv instance/dna_samples.db instance/dna_samples.db.avant-restauration
   ```
3. Copier la sauvegarde choisie à la place :
   ```bash
   cp instance/backups/dna_samples_2026-11-24_170000.db instance/dna_samples.db
   ```
4. Relancer l'application.

## Tests

```bash
uv run pytest
```

Les tests utilisent une base SQLite temporaire : la base de production n'est jamais touchée.

## Mise en production

Pour que tout le labo y accède, l'app tourne sur une VM Linux :
- un service **systemd** (redémarrage automatique, compte dédié, droits limités) ;
- **nginx** devant, pour le HTTPS ;
- l'option `--behind-proxy`.

Le guide pas à pas, testé de bout en bout sur Debian 12, est dans
[deploy/DEPLOIEMENT.md](deploy/DEPLOIEMENT.md). Les fichiers prêts à copier sont aussi dans
`deploy/`.

**Sur Kubernetes** : une image (`Dockerfile`) et des manifestes kustomize sont dans
`deploy/kubernetes/`. Le guide est [deploy/kubernetes/KUBERNETES.md](deploy/kubernetes/KUBERNETES.md).
Il faut une seule copie de l'app, et la base sur un volume bloc RWO (pas de NFS).

## Technologies

- **Backend** : Python 3.12, Flask 3, SQLAlchemy
- **Base de données** : SQLite
- **Frontend** : Bootstrap 5, Chart.js (via CDN)
- **Export** : openpyxl (Excel), csv (TSV)
- **Packaging** : uv / uv_build
