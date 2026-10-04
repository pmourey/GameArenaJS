# 🐳 GameArena - Guide de Déploiement Docker

## 📋 Vue d'ensemble

Ce système de déploiement Docker permet de déployer GameArena avec :
- ✅ **Build multi-stage** : Frontend (Node.js) + Backend (Python Flask)
- ✅ **Production-ready** : Utilisateur non-root, health checks, limites de ressources
- ✅ **Script automatisé** : `deploy.sh` pour déploiement en une commande
- ✅ **Configuration flexible** : Variables d'environnement via `.env`

## 🚀 Démarrage rapide

### 1. Prérequis

- Docker Engine 20.10+
- Docker Compose 2.0+
- 2 GB RAM minimum
- 5 GB espace disque

### 2. Configuration

```bash
# Copier le fichier d'exemple
cp .env.docker.example .env

# Éditer .env et changer les secrets (OBLIGATOIRE en production)
nano .env
```

**Secrets à changer** :
```bash
SECRET_KEY=votre-secret-key-aleatoire-tres-longue
JWT_SECRET_KEY=votre-jwt-secret-aleatoire-tres-longue
```

Générer des secrets forts :
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Déploiement

```bash
# Rendre le script exécutable
chmod +x deploy.sh

# Déploiement complet (dev)
./deploy.sh dev

# ou Production
./deploy.sh prod
```

Le script va :
1. ✅ Vérifier les prérequis (Docker, Compose)
2. ✅ Construire les images (frontend + backend)
3. ✅ Démarrer les services
4. ✅ Initialiser la base de données
5. ✅ Afficher les informations d'accès

## 📦 Architecture

### Multi-stage Build

```
┌─────────────────────────────────────────┐
│ Stage 1: Frontend Builder (Node 18)    │
│ - npm install                           │
│ - npm run build                         │
│ → dist/                                 │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│ Stage 2: Python Runtime (3.11-slim)    │
│ - pip install requirements              │
│ - Copy backend code                     │
│ - Copy frontend dist → static/          │
│ → Image finale: ~500 MB                 │
└─────────────────────────────────────────┘
```

### Services Docker Compose

```yaml
gamearena:
  - Port 3000 exposé
  - Volumes: DB + persistent_bots
  - Health check: /api/referees
  - Limites: 2 CPU, 2GB RAM
```

## 🔧 Commandes utiles

### Gestion des services

```bash
# Démarrer
docker-compose up -d

# Arrêter
docker-compose down

# Redémarrer
docker-compose restart

# Voir les logs
docker-compose logs -f

# Logs d'un service spécifique
docker-compose logs -f gamearena

# Status des services
docker-compose ps
```

### Accès au conteneur

```bash
# Shell interactif
docker-compose exec gamearena bash

# Exécuter une commande Python
docker-compose exec gamearena python3 -c "from app import app; print(app.config)"

# Accéder à la DB
docker-compose exec gamearena sqlite3 gamearena.db
```

### Build et rebuild

```bash
# Build sans cache
docker-compose build --no-cache

# Build avec pull des images de base
docker-compose build --pull

# Rebuild et redémarrer
docker-compose up -d --build
```

## 🗄️ Gestion de la base de données

### SQLite (par défaut)

La DB est dans un volume Docker persistant :
```bash
# Sauvegarder
docker cp gamearena-app:/app/gamearena.db ./backup.db

# Restaurer
docker cp ./backup.db gamearena-app:/app/gamearena.db
docker-compose restart
```

### Migrer vers PostgreSQL (recommandé en production)

1. **Décommenter le service postgres** dans `docker-compose.yml`
2. **Modifier `.env`** :
   ```bash
   DB_PASSWORD=votre-mot-de-passe-securise
   DATABASE_URL=postgresql://gamearena:${DB_PASSWORD}@postgres:5432/gamearena
   ```
3. **Installer psycopg2** :
   ```bash
   # Ajouter à requirements.txt
   psycopg2-binary==2.9.9
   ```
4. **Rebuild et redémarrer** :
   ```bash
   docker-compose down
   docker-compose build --no-cache
   docker-compose up -d
   ```

## 🔐 Sécurité

### Checklist production

- [ ] **Secrets changés** : `SECRET_KEY`, `JWT_SECRET_KEY` dans `.env`
- [ ] **HTTPS activé** : Utiliser nginx avec SSL (voir section Nginx)
- [ ] **CORS restreint** : Ne pas utiliser `origins='*'` en prod
- [ ] **Docker socket** : Désactiver si pas besoin (commentez volume dans compose)
- [ ] **Rate limiting** : Implémenter limites de requêtes
- [ ] **Logs sécurisés** : Pas de secrets dans les logs
- [ ] **Sauvegardes** : Automatiser sauvegardes DB quotidiennes

### Désactiver l'exécution Docker des bots

Si vous voulez utiliser uniquement `subprocess` (pas Docker) :

1. **Modifier `.env`** :
   ```bash
   BOT_RUNNER=subprocess
   ```

2. **Commenter le volume Docker socket** dans `docker-compose.yml` :
   ```yaml
   # volumes:
   #   - /var/run/docker.sock:/var/run/docker.sock
   ```

3. **Redémarrer** :
   ```bash
   docker-compose restart
   ```

## 🌐 Nginx Reverse Proxy (Production)

### 1. Créer `nginx.conf`

```nginx
events {
    worker_connections 1024;
}

http {
    upstream gamearena {
        server gamearena:3000;
    }

    server {
        listen 80;
        server_name yourdomain.com;

        # Redirect HTTP to HTTPS
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name yourdomain.com;

        # SSL Configuration
        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        # Security Headers
        add_header Strict-Transport-Security "max-age=31536000" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;

        # Proxy to Flask
        location / {
            proxy_pass http://gamearena;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # WebSocket support (si nécessaire)
        location /ws {
            proxy_pass http://gamearena;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }
    }
}
```

### 2. Décommenter le service nginx dans `docker-compose.yml`

### 3. Générer certificats SSL

```bash
# Self-signed (dev/test uniquement)
mkdir ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/key.pem -out ssl/cert.pem

# Production: utiliser Let's Encrypt avec certbot
```

## 📊 Monitoring

### Logs

```bash
# Logs en temps réel
docker-compose logs -f

# Dernières 100 lignes
docker-compose logs --tail=100

# Filtrer par niveau
docker-compose logs | grep ERROR
```

### Health checks

```bash
# Vérifier le status
curl http://localhost:3000/api/referees

# Health check Docker
docker inspect gamearena-app | grep -A 10 Health
```

### Métriques

Pour monitoring avancé, ajouter :
- **Prometheus** : Métriques applicatives
- **Grafana** : Dashboards
- **Loki** : Agrégation de logs

## 🔄 Mises à jour

### Update de l'application

```bash
# Pull les changements
git pull

# Rebuild et redémarrer
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Vérifier les logs
docker-compose logs -f
```

### Backup avant mise à jour

```bash
# Script de backup automatique
cat > backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="backups/$DATE"
mkdir -p "$BACKUP_DIR"

# Backup DB
docker cp gamearena-app:/app/gamearena.db "$BACKUP_DIR/gamearena.db"

# Backup bots
docker cp gamearena-app:/app/persistent_bots "$BACKUP_DIR/persistent_bots"

echo "Backup créé: $BACKUP_DIR"
EOF

chmod +x backup.sh
./backup.sh
```

## 🐛 Dépannage

### Le service ne démarre pas

```bash
# Vérifier les logs
docker-compose logs gamearena

# Vérifier les erreurs de build
docker-compose build

# Redémarrer proprement
docker-compose down -v  # ⚠️ Supprime les volumes!
docker-compose up -d
```

### Erreur "Address already in use"

```bash
# Port 3000 déjà utilisé
lsof -ti:3000 | xargs kill -9

# Ou changer le port dans docker-compose.yml
ports:
  - "3001:3000"  # Exposer sur 3001 au lieu de 3000
```

### Problème de permissions

```bash
# Vérifier l'utilisateur
docker-compose exec gamearena whoami  # Doit afficher "gamearena"

# Fix permissions volumes
docker-compose exec -u root gamearena chown -R gamearena:gamearena /app
```

### Erreur Docker socket

```bash
# Vérifier les permissions du socket
ls -la /var/run/docker.sock

# Sur Linux, ajouter l'utilisateur au groupe docker
sudo usermod -aG docker $USER
```

## 📈 Performance

### Optimisations

1. **Multi-stage build** : Image finale ~500 MB (vs 1.5+ GB sans)
2. **Cache layers** : Copie requirements.txt séparément
3. **Production deps only** : `npm ci --only=production`
4. **Slim base image** : python:3.11-slim (vs full)

### Limites de ressources

Ajuster dans `docker-compose.yml` :
```yaml
deploy:
  resources:
    limits:
      cpus: '4'      # Augmenter pour plus de matchs parallèles
      memory: 4G     # Augmenter si beaucoup de bots
```

## 📚 Ressources

- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Flask in Production](https://flask.palletsprojects.com/en/2.3.x/deploying/)
- [Docker Compose Reference](https://docs.docker.com/compose/compose-file/)

## 🆘 Support

En cas de problème :
1. Vérifier les logs : `docker-compose logs -f`
2. Vérifier le health check : `curl http://localhost:3000/api/referees`
3. Consulter la documentation : Ce fichier
4. Créer une issue sur GitHub

---

**Happy Deploying! 🚀**
