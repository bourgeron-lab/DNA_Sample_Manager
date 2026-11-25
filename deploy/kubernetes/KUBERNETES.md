# Déploiement sur Kubernetes

```
navigateurs ──HTTPS──► Ingress du cluster ──► Service ──► pod dna-sample-manager (1 seul)
                                                            ├── /data     volume « data »    (dna_samples.db, secret_key)
                                                            └── /backups  volume « backups » (sauvegardes)
```

Cette procédure a été testée de bout en bout sur k3s (v1.31, Ingress Traefik), avec une copie de
la base de prod. Les points vérifiés :
- le transfert de la base, la sauvegarde au démarrage et la connexion en HTTPS ;
- le rejet des requêtes CSRF falsifiées ;
- l'export Excel ;
- la recréation du pod, sans perte de données ni de session ;
- la mise à jour, avec jamais deux pods en même temps ;
- la NetworkPolicy et la restauration.

## Règles à ne pas enfreindre

- **Une seule copie de l'app** : `replicas: 1` et la stratégie `Recreate`. SQLite n'accepte qu'un
  processus écrivain. Pas d'autoscaling (HPA). Deux pods sur la même base peuvent la corrompre.
- **La base sur un stockage de type bloc** : un volume `ReadWriteOnce` (Ceph RBD, Longhorn, disque cloud…).
  **Jamais sur NFS, CephFS ou SMB** : les verrous SQLite n'y sont pas fiables.
- **Aucune donnée dans l'image.** La base, la clé de session et les sauvegardes sont sur les
  volumes. Le fichier `.dockerignore` exclut `instance/`, `*.db` et `*.tsv`.

## À demander aux administrateurs du cluster

| Question | Où le reporter |
|---|---|
| Namespace à utiliser (ou droit d'en créer un) | `kustomization.yaml` → `namespace` |
| Registre d'images où pousser l'image | `kustomization.yaml` → `images`, `maintenance.yaml` → `image` |
| Classe de stockage **bloc** (RWO) pour la base | `pvc.yaml` → `storageClassName` (volume `data`) |
| Classe de stockage pour les sauvegardes, idéalement un autre backend | `pvc.yaml` → `storageClassName` (volume `backups`) |
| Classe d'Ingress, nom DNS, certificat (cert-manager ?) | `ingress.yaml` |
| Namespace du contrôleur Ingress ; les NetworkPolicy sont-elles appliquées ? | `networkpolicy.yaml` |
| Les volumes sont-ils sauvegardés (Velero, snapshots) ? | voir « Sauvegardes » |

## 1. Construire et publier l'image

Depuis la racine du dépôt :

```bash
docker build -t registry.example.pasteur.fr/ghfc/dna-sample-manager:0.1.0 .
docker push registry.example.pasteur.fr/ghfc/dna-sample-manager:0.1.0
```

Si le cluster tourne sur des machines x86 et que l'image est construite sur un Mac Apple
Silicon, ajouter `--platform linux/amd64` au `docker build`.

## 2. Adapter les manifestes

Remplir les champs listés dans le tableau ci-dessus. Vérifier ensuite le résultat avec :

```bash
kubectl kustomize deploy/kubernetes/
```

## 3. Créer les volumes et y transférer la base

Il faut transférer la base **avant** le premier démarrage de l'app. Sinon, l'app crée une base vide.

```bash
NS=dna-sample-manager
kubectl create namespace $NS                       # si vous en avez le droit
kubectl apply -n $NS -f deploy/kubernetes/pvc.yaml

# Sur le Mac : arrêter l'app (Ctrl+C) puis faire une sauvegarde à jour
uv run dna-sample-manager ./instance/ --backup-only

# Pod de maintenance (même image que l'app) qui monte les volumes
kubectl apply -n $NS -f deploy/kubernetes/maintenance.yaml
kubectl wait -n $NS --for=condition=Ready pod/dna-sample-manager-maintenance --timeout=120s
kubectl cp -n $NS instance/backups/dna_samples_<date la plus récente>.db \
     dna-sample-manager-maintenance:/data/dna_samples.db
kubectl exec -n $NS dna-sample-manager-maintenance -- chmod 600 /data/dna_samples.db
kubectl delete -n $NS pod dna-sample-manager-maintenance
```

À partir de là, la base de référence est celle du cluster. Ne relancez plus l'app sur le Mac avec
`instance/`, sinon les deux bases divergent.

## 4. Déployer

```bash
# Certificat : inutile si cert-manager s'en charge (annotation dans ingress.yaml)
kubectl create secret tls dna-sample-manager-tls -n $NS --cert=adn.crt --key=adn.key

kubectl apply -k deploy/kubernetes/
kubectl rollout status -n $NS deploy/dna-sample-manager
kubectl logs -n $NS deploy/dna-sample-manager          # doit afficher « Sauvegarde : /backups/… »
```

Puis ouvrir `https://<nom DNS>`. **Changer tout de suite le mot de passe `admin`** dans
*Administration › Utilisateurs* : tant qu'il vaut `admin`, un avertissement s'affiche dans les
journaux à chaque démarrage.

## Opérations courantes

### Mettre à jour l'application

```bash
kubectl exec -n $NS deploy/dna-sample-manager -- \
     dna-sample-manager /data --backup-only --backup-dir /backups     # sauvegarde avant mise à jour
docker build -t registry.example.pasteur.fr/ghfc/dna-sample-manager:0.2.0 . && docker push …
# mettre à jour newTag dans kustomization.yaml (et maintenance.yaml), puis :
kubectl apply -k deploy/kubernetes/
kubectl rollout status -n $NS deploy/dna-sample-manager
```

Avec `Recreate`, il y a une courte interruption, de quelques secondes, pendant le remplacement du
pod : c'est voulu.

### Sauvegardes

- **Dans l'app** : une sauvegarde au démarrage du pod, puis toutes les 24 h. Les 30 plus récentes
  sont gardées sur le volume `backups`. Pour changer ces réglages, voir les `args` commentés dans
  `deployment.yaml`.
- **Lister les sauvegardes** :

  ```bash
  kubectl exec -n $NS deploy/dna-sample-manager -- ls -la /backups
  ```

- **Récupérer une copie hors du cluster** :

  ```bash
  kubectl cp -n $NS <pod>:/backups/dna_samples_<date>.db ./dna_samples_<date>.db
  ```

- Si les volumes du cluster sont sauvegardés (Velero, snapshots), inclure les deux volumes
  `dna-sample-manager-*`. Sinon, prévoir une copie régulière hors du cluster.

### Restaurer une sauvegarde

```bash
kubectl scale -n $NS deploy/dna-sample-manager --replicas=0
kubectl wait -n $NS --for=delete pod -l app.kubernetes.io/name=dna-sample-manager --timeout=60s
kubectl apply -n $NS -f deploy/kubernetes/maintenance.yaml
kubectl wait -n $NS --for=condition=Ready pod/dna-sample-manager-maintenance --timeout=120s
kubectl exec -n $NS dna-sample-manager-maintenance -- sh -c '
  mv /data/dna_samples.db /data/dna_samples.db.avant-restauration &&
  cp /backups/dna_samples_<date>.db /data/dna_samples.db && chmod 600 /data/dna_samples.db'
kubectl delete -n $NS pod dna-sample-manager-maintenance
kubectl scale -n $NS deploy/dna-sample-manager --replicas=1
```

### Lancer un script d'import ou de migration

Suivre la même procédure : arrêter l'app (`--replicas=0`), lancer le pod de maintenance, puis
copier la base hors du cluster avec `kubectl cp`. Lancer le script sur cette copie, la remettre en
place, puis redémarrer l'app.

### Clé de session

Elle est créée au premier démarrage dans `/data/secret_key`, sur le volume : les utilisateurs
restent connectés quand le pod est recréé. Pour la fournir vous-même :

```bash
kubectl create secret generic dna-sample-manager -n $NS \
     --from-literal=flask-secret-key="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

## Détails techniques

- **Image** : Python 3.12 slim, avec les versions exactes de `uv.lock`. Elle tourne sous un compte
  non-root (uid 10001), avec un système de fichiers en lecture seule et aucune capability.
- **Proxy** : l'app est lancée avec `--behind-proxy --trusted-proxy '*'`. Elle accepte les en-têtes
  `X-Forwarded-*` de l'Ingress (HTTPS, nom d'hôte, IP du client) et réserve les cookies au HTTPS.
  La NetworkPolicy garantit que seul l'Ingress joint le pod. Si le cluster ne les applique pas,
  un autre pod du cluster pourrait falsifier ces en-têtes ; c'est sans conséquence pour les données,
  car la connexion et le jeton CSRF restent exigés.
- **Sondes** : `GET /healthz`, sans authentification et sans cookie. Elle vérifie que la base répond.
