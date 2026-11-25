# Déploiement sur Kubernetes (Institut Pasteur)

```
navigateurs (réseau Pasteur) ──HTTPS──► Traefik, classe « internal » ──► Service ──► pod dna-sample-manager (1 seul)
                                                                                   ├── /data     volume « data »    (dna_samples.db, secret_key)
                                                                                   └── /backups  volume « backups » (sauvegardes)
```

Les manifestes de ce dossier suivent la [documentation Kubernetes de la DSI](https://dsi-docs.pasteur.cloud/docs/hosting/containers/)
(Ingress Traefik, stockage Ceph, quotas) et le cours
[Kubernetes in a nutshell](https://hub.pages.pasteur.fr/kubernetes-in-a-nutshell/index.html).
Les deux sont accessibles depuis le réseau Pasteur ; le cours demande une connexion GitLab.

La procédure a été testée de bout en bout sur k3s (v1.31, Ingress Traefik), avec une copie de
la base de prod. Les points vérifiés :
- le transfert de la base, la sauvegarde au démarrage et la connexion en HTTPS ;
- le rejet des requêtes CSRF falsifiées ;
- l'export Excel ;
- la recréation du pod, sans perte de données ni de session ;
- la mise à jour, avec jamais deux pods en même temps ;
- la restauration.

Les manifestes adaptés à l'Institut Pasteur ont aussi été vérifiés sur k3s. Pour cela, on y a
créé une classe de stockage `ceph-block` et une classe d'Ingress `internal` pour Traefik. Les
points vérifiés :
- les volumes, les ressources et l'Ingress ;
- la connexion en HTTPS, le CSRF et l'export ;
- le pod de maintenance.

Elle n'a **pas encore été testée sur les clusters de l'Institut Pasteur eux-mêmes**.

## Règles à ne pas enfreindre

- **Une seule copie de l'app** : `replicas: 1` et la stratégie `Recreate`. SQLite n'accepte qu'un
  processus écrivain. Pas d'autoscaling (HPA). Deux pods sur la même base peuvent la corrompre.
- **La base sur `ceph-block`**, jamais sur `ceph-fs`. `ceph-fs` est un système de fichiers partagé,
  et les verrous SQLite n'y sont pas fiables.
- **Classe d'Ingress `internal`** : l'app n'est accessible que depuis le réseau Pasteur. La
  classe `external` publierait sur internet une base de données de sujets.
- **Aucune donnée dans l'image.** La base, la clé de session et les sauvegardes sont sur les
  volumes. Le fichier `.dockerignore` exclut `instance/`, `*.db` et `*.tsv`.

## Ce que fixe la plateforme de la DSI

| Sujet | À l'Institut Pasteur | Dans les manifestes |
|---|---|---|
| Clusters | `k8sprod-02` (production) et `k8sdev-01` (développement) | — |
| Namespace | créé par la DSI, nommé `<projet>-prod` / `<projet>-dev` | `kustomization.yaml` → `namespace` |
| Ingress | Traefik ; classe `internal` (réseau Pasteur) ou `external` (internet, ticket à la DSI) | `ingress.yaml` : `internal` |
| Nom d'hôte | `<nom>.pasteur.cloud` en prod, `<nom>.dev.pasteur.cloud` en dev | `ingress.yaml` → `host` |
| Certificat HTTPS | **automatique** pour ces domaines : pas de secret TLS à créer | — |
| Stockage | `ceph-block` (RWO, recommandé pour les bases), `ceph-fs` (RWX) | `pvc.yaml` : `ceph-block` |
| Isolation réseau | les namespaces sont isolés par la plateforme | pas de NetworkPolicy (fichier facultatif) |
| Quotas par namespace | 4 CPU, 12 Gi de mémoire, 20 Gi de stockage éphémère, 50 Gi de `ceph-block` | `deployment.yaml` → `resources` |
| Défauts par conteneur | 500m CPU, 512 Mi de mémoire, 256 Mi de stockage éphémère | remplacés par des valeurs explicites |
| Registre d'images | GitLab Pasteur (`registry-gitlab.pasteur.fr`) ou Harbor (`harbor.pasteur.fr`) | `kustomization.yaml` → `images`, `maintenance.yaml` |
| Code et déploiement | le projet doit être sur **gitlab.pasteur.fr** et déployé par un **job CI/CD** | voir « Dépôt GitLab et CI/CD » |

Les besoins de l'app restent très en dessous des quotas. Mesures faites sur la base actuelle :
- mémoire : environ 60 Mo au repos et 180 Mo pendant un export Excel de tous les sujets ;
- disque : environ 8 Mo pour la base, plus 30 sauvegardes.

## 0. Demander les namespaces à la DSI

Écrire à informatique@pasteur.fr avec les informations suivantes. C'est la liste demandée sur
[Requesting a namespace](https://dsi-docs.pasteur.cloud/docs/hosting/containers/request_namespace/).

- **Projet** : DNA Sample Manager (gestion des échantillons ADN du labo).
- **Namespaces** : `dna-sample-manager-prod` sur k8sprod-02. Ajouter `dna-sample-manager-dev` sur
  k8sdev-01 si vous voulez un environnement de test.
- **Projet GitLab** : l'identifiant (ID) du projet sur gitlab.pasteur.fr.
- **Ressources** : les quotas par défaut suffisent. Stockage `ceph-block` : 7 Gi par namespace
  (2 Gi pour la base, 5 Gi pour les sauvegardes).
- **Accès** : la liste des personnes, en lecture seule ou en lecture-écriture.
- **Alertes** : les adresses e-mail à prévenir, par exemple pour la production uniquement.

Questions à ajouter à la demande :
- Les volumes `ceph-block` sont-ils sauvegardés ou photographiés (snapshots) par la DSI ?
- Les requêtes en HTTP sont-elles redirigées vers HTTPS sur l'Ingress `internal` ?

## 1. Accès au cluster

Suivre [Authenticate on the kubernetes clusters](https://dsi-docs.pasteur.cloud/docs/hosting/containers/administration/authenticate/).

```bash
brew install vmware-tanzu/pinniped/pinniped-cli kubectl
```

Télécharger ensuite les fichiers `k8sprod-02.yaml` (et `k8sdev-01.yaml`) depuis cette page, puis :

```bash
export KUBECONFIG=~/Downloads/k8sprod-02.yaml
NS=dna-sample-manager-prod
kubectl get pods -n $NS          # ouvre la connexion WebSSO dans le navigateur
```

## 2. Construire et publier l'image

Le registre GitLab Pasteur est `registry-gitlab.pasteur.fr/<groupe>/<projet>`. Depuis la racine
du dépôt :

```bash
docker login registry-gitlab.pasteur.fr
docker build --platform linux/amd64 -t registry-gitlab.pasteur.fr/<groupe>/dna-sample-manager:0.1.0 .
docker push registry-gitlab.pasteur.fr/<groupe>/dna-sample-manager:0.1.0
```

`--platform linux/amd64` est nécessaire quand l'image est construite sur un Mac Apple Silicon.

Le registre est privé, le cluster a donc besoin d'un identifiant pour télécharger l'image.
1. Dans GitLab : *Settings › Repository › Deploy tokens*, créer un jeton avec le droit
   `read_registry`.
2. Puis :

```bash
kubectl create secret docker-registry registry-gitlab -n $NS \
     --docker-server=registry-gitlab.pasteur.fr \
     --docker-username=<utilisateur du jeton> --docker-password=<jeton>
```

Avec Harbor, l'image s'appelle `harbor.pasteur.fr/<projet>/dna-sample-manager`, et
`--docker-server=harbor.pasteur.fr` avec un compte robot.

## 3. Adapter les manifestes

| Fichier | Champ | Valeur |
|---|---|---|
| `kustomization.yaml` | `namespace` | le nom donné par la DSI (`dna-sample-manager-prod`) |
| `kustomization.yaml` | `images` → `newName`, `newTag` | l'image poussée à l'étape 2 |
| `maintenance.yaml` | `image` | la même image |
| `ingress.yaml` | `host` | par ex. `dna-sample-manager.pasteur.cloud` (prod) ou `dna-sample-manager.dev.pasteur.cloud` (dev) |

Vérifier ensuite le résultat :

```bash
kubectl kustomize deploy/kubernetes/
```

## 4. Créer les volumes et y transférer la base

Il faut transférer la base **avant** le premier démarrage de l'app. Sinon, l'app crée une base vide.

```bash
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

## 5. Déployer

```bash
kubectl apply -k deploy/kubernetes/
kubectl rollout status -n $NS deploy/dna-sample-manager
kubectl logs -n $NS deploy/dna-sample-manager          # doit afficher « Sauvegarde : /backups/… »
```

Puis ouvrir `https://<host>` depuis le réseau Pasteur, **en https**. En http, la connexion
échoue, car les cookies de session sont réservés au HTTPS. **Changer tout de suite le mot de
passe `admin`** dans *Administration › Utilisateurs* : tant qu'il vaut `admin`, un avertissement
s'affiche dans les journaux à chaque démarrage.

## Dépôt GitLab et CI/CD

La DSI demande que le projet soit sur **gitlab.pasteur.fr** et déployé par un job CI/CD. Le
dépôt est aujourd'hui sur GitHub. Deux possibilités :
- le **déplacer** sur gitlab.pasteur.fr ;
- le **refléter** (mirroring) depuis GitHub vers gitlab.pasteur.fr.

Le pipeline reprendrait les étapes 2 et 5 : construire et pousser l'image, puis
`kubectl apply -k`. Les étapes 0, 1 et 4 restent manuelles, et ne se font qu'une fois.

La DSI recommande Helm pour la production. Les manifestes kustomize de ce dossier restent
compatibles avec un déploiement par `kubectl apply`, comme au
[niveau 1 de leur tutoriel](https://dsi-docs.pasteur.cloud/docs/hosting/containers/tutorial/level1-manifest/).

## Opérations courantes

### Mettre à jour l'application

```bash
kubectl exec -n $NS deploy/dna-sample-manager -- \
     dna-sample-manager /data --backup-only --backup-dir /backups     # sauvegarde avant mise à jour
docker build --platform linux/amd64 -t registry-gitlab.pasteur.fr/<groupe>/dna-sample-manager:0.2.0 . && docker push …
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
- **Leur limite** : ce volume est sur le même stockage Ceph que la base. Il protège contre les
  erreurs de manipulation et la corruption, pas contre une panne du stockage. Si la DSI ne
  sauvegarde pas les volumes, prévoir une copie régulière hors du cluster, par exemple sur un
  partage du labo.
- **Lister les sauvegardes** :

  ```bash
  kubectl exec -n $NS deploy/dna-sample-manager -- ls -la /backups
  ```

- **Récupérer une copie hors du cluster** :

  ```bash
  POD=$(kubectl get pod -n $NS -l app.kubernetes.io/name=dna-sample-manager -o name | cut -d/ -f2)
  kubectl cp -n $NS $POD:/backups/dna_samples_<date>.db ./dna_samples_<date>.db
  ```

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
  non-root (uid 10001), avec un système de fichiers en lecture seule et aucune capability. C'est
  plus strict que le contexte de sécurité recommandé par la DSI.
- **Proxy** : l'app est lancée avec `--behind-proxy --trusted-proxy '*'`. Elle accepte les en-têtes
  `X-Forwarded-*` de Traefik (HTTPS, nom d'hôte, IP du client) et réserve les cookies au HTTPS.
  L'isolation des namespaces garantit que seul Traefik joint le pod, hors pods du même namespace.
  Une falsification de ces en-têtes serait de toute façon sans conséquence pour les données : la
  connexion et le jeton CSRF restent exigés.
- **Sondes** : `GET /healthz`, sans authentification et sans cookie. Elle vérifie que la base répond.
- **Autre cluster** : sans isolation des namespaces, ajouter `networkpolicy.yaml` à
  `kustomization.yaml`, avec le namespace du contrôleur Ingress. Remplacer aussi `ceph-block` et
  `internal` par les équivalents de ce cluster.
