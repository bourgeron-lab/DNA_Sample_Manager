# Mise en production sur un serveur Linux

Ce guide installe DNA Sample Manager sur une VM Linux (Debian, Ubuntu, Rocky…), accessible en
HTTPS par tout le labo.

```
navigateurs ──HTTPS──► nginx (:443) ──HTTP local──► dna-sample-manager (127.0.0.1:5003, waitress)
                                                       │
                                     /srv/dna-sample-manager/dna_samples.db  (SQLite)
                                     /srv/dna-sample-manager-backups/        (sauvegardes)
```

- **Un seul processus**. SQLite n'accepte qu'un écrivain à la fois, sur un disque local ;
  waitress traite les requêtes en parallèle avec des threads. Ne pas lancer plusieurs instances.
- **Sauvegardes**. La base est sauvegardée au démarrage du service puis toutes les 24 h, dans ce
  même processus.
- **Disque de la base**. La base doit être sur le **disque local** de la VM, jamais sur un partage
  réseau (NFS/SMB) : les verrous SQLite y sont peu fiables et la base peut se corrompre. Les
  *sauvegardes*, elles, peuvent et devraient aller sur un autre disque ou un partage.

## Prérequis (à demander à la DSI)

- Une VM Linux : 1 vCPU, 1 Go de RAM et 10 Go de disque suffisent largement (la base pèse ~10 Mo).
- Un nom DNS, par ex. `adn.<labo>.pasteur.fr`, et un **certificat TLS** pour ce nom.
- Idéalement, un espace de stockage **sur une autre machine** pour les sauvegardes, monté sur la VM.
- Un pare-feu qui n'ouvre que les ports 80 et 443, et seulement depuis le réseau interne.

Les chemins utilisés ci-dessous sont ceux de [`dna-sample-manager.service`](dna-sample-manager.service).
Si vous en changez, adaptez ce fichier.

## 1. Compte de service et dossiers

```bash
sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin dnasm
sudo install -d -o dnasm -g dnasm -m 700 /srv/dna-sample-manager /srv/dna-sample-manager-backups
```

Si les sauvegardes vont sur un montage réseau, montez-le sur `/srv/dna-sample-manager-backups`
(entrée dans `/etc/fstab`) **avant** de démarrer le service. Le service attend que ce montage soit
présent (`RequiresMountsFor`).

## 2. Code et environnement Python

```bash
# uv, installé pour tout le système
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh

# Code (dépôt privé : utiliser une clé de déploiement GitHub, ou copier le dossier avec scp)
sudo git clone https://github.com/bourgeron-lab/DNA_Sample_Manager.git /opt/dna-sample-manager
cd /opt/dna-sample-manager

# Python + dépendances dans /opt/dna-sample-manager (versions exactes de uv.lock).
# UV_PYTHON_INSTALL_DIR : sans lui, Python serait installé dans /root, invisible pour le service.
sudo env UV_PYTHON_INSTALL_DIR=/opt/dna-sample-manager/.python uv sync --frozen --no-dev
# Le service (compte dnasm) doit pouvoir lire le code, quel que soit le umask de root
sudo chmod -R a+rX /opt/dna-sample-manager
/opt/dna-sample-manager/.venv/bin/dna-sample-manager --help
```

Le code appartient à root et le service ne peut que le lire.

## 3. Transfert de la base depuis le Mac

Sur le **Mac**, arrêter l'app (Ctrl+C dans le terminal), puis lancer :

```bash
uv run dna-sample-manager ./instance/ --backup-only
scp instance/backups/dna_samples_<date la plus récente>.db <vous>@<vm>:/tmp/dna_samples.db
```

Sur la **VM** :

```bash
sudo install -o dnasm -g dnasm -m 600 /tmp/dna_samples.db /srv/dna-sample-manager/dna_samples.db
rm /tmp/dna_samples.db
```

À partir de là, la base de référence est celle du serveur. Ne relancez plus l'app sur le Mac avec
`instance/`, sinon les deux bases divergent. Renommez par exemple `instance/dna_samples.db` en
`instance/dna_samples.ANCIENNE-copie-du-<date>.db`.

## 4. Service systemd

```bash
sudo cp /opt/dna-sample-manager/deploy/dna-sample-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dna-sample-manager
systemctl status dna-sample-manager
journalctl -u dna-sample-manager -f        # journaux (Ctrl+C pour quitter)
curl -sI http://127.0.0.1:5003/login       # doit répondre « HTTP/1.1 200 OK »
```

Au démarrage, les journaux doivent afficher une ligne `Sauvegarde : /srv/dna-sample-manager-backups/…`.

Le service redémarre tout seul en cas de plantage et au redémarrage de la VM.

## 5. nginx + HTTPS

```bash
sudo apt install nginx            # (dnf install nginx sur Rocky/RHEL)
# Certificat fourni par la DSI :
sudo install -m 644 adn.crt /etc/ssl/certs/dna-sample-manager.crt
sudo install -m 600 adn.key /etc/ssl/private/dna-sample-manager.key

sudo cp /opt/dna-sample-manager/deploy/nginx-dna-sample-manager.conf /etc/nginx/sites-available/dna-sample-manager
sudo nano /etc/nginx/sites-available/dna-sample-manager      # adapter server_name (2 fois)
sudo ln -s /etc/nginx/sites-available/dna-sample-manager /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Sur Rocky/RHEL, les sites vont dans `/etc/nginx/conf.d/dna-sample-manager.conf`. SELinux doit aussi
autoriser nginx à se connecter à l'app : `sudo setsebool -P httpd_can_network_connect 1`.

Le port 5003 ne doit **pas** être ouvert dans le pare-feu. Seul nginx y accède, en local.

## 6. Première connexion

1. Ouvrir `https://adn.<labo>.pasteur.fr` et se connecter.
2. **Changer le mot de passe `admin`** dans *Administration › Utilisateurs*. Tant qu'il vaut encore
   `admin`, un avertissement apparaît dans les journaux à chaque démarrage.
3. Créer un compte nominatif par personne : le journal des modifications et l'historique
   d'utilisation des tubes s'appuient dessus.

## Opérations courantes

### Mettre à jour l'application

```bash
cd /opt/dna-sample-manager
sudo -u dnasm .venv/bin/dna-sample-manager /srv/dna-sample-manager \
     --backup-only --backup-dir /srv/dna-sample-manager-backups     # sauvegarde avant mise à jour
sudo git pull
sudo env UV_PYTHON_INSTALL_DIR=/opt/dna-sample-manager/.python uv sync --frozen --no-dev
sudo chmod -R a+rX /opt/dna-sample-manager
sudo systemctl restart dna-sample-manager
journalctl -u dna-sample-manager -n 30
```

`--backup-only` peut tourner pendant que le service est actif : la copie reste cohérente.

### Sauvegardes

- Les 30 sauvegardes les plus récentes, une par jour, se trouvent dans `/srv/dna-sample-manager-backups`.
  Pour modifier le nombre gardé ou la fréquence, éditer `--keep` / `--backup-interval` dans le
  fichier `.service`, puis lancer `daemon-reload` et `restart`.
- Si ce dossier est sur le même disque que la base, ajouter une copie hors de la VM, par exemple
  un `rsync` quotidien vers un partage du labo, ou la sauvegarde de la VM par la DSI.

### Restaurer une sauvegarde

```bash
sudo systemctl stop dna-sample-manager
sudo mv /srv/dna-sample-manager/dna_samples.db /srv/dna-sample-manager/dna_samples.db.avant-restauration
sudo install -o dnasm -g dnasm -m 600 /srv/dna-sample-manager-backups/dna_samples_<date>.db \
     /srv/dna-sample-manager/dna_samples.db
sudo systemctl start dna-sample-manager
```

### Lancer un script d'import ou de migration

Arrêter le service (`sudo systemctl stop dna-sample-manager`), faire une sauvegarde
(`--backup-only`), lancer le script sur `/srv/dna-sample-manager/dna_samples.db` en tant que
`dnasm`, puis redémarrer le service.

### Clé de session

Au premier démarrage, une clé est créée dans `/srv/dna-sample-manager/secret_key`, avec les
droits 600. Elle permet aux utilisateurs de rester connectés quand le service redémarre.

- La supprimer déconnecte tout le monde, sans autre conséquence.
- Pour la fournir vous-même, voir [`dna-sample-manager.env.example`](dna-sample-manager.env.example).

## Pourquoi pas Docker / Kubernetes ?

Ce serait possible, mais ça n'apporte rien ici. L'app tient dans **un seul processus** qui écrit
dans **un seul fichier SQLite** sur un disque local : on ne peut ni la répliquer, ni la déplacer
librement entre machines.

Un service systemd sur une VM est plus simple à maintenir et à sauvegarder. Si un jour
l'app doit servir beaucoup plus d'utilisateurs simultanés, il faudra d'abord passer de SQLite à
PostgreSQL.
