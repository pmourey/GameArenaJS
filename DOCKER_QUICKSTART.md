# 🚀 Déploiement Docker - Quick Start

## ⚡ Déploiement en 3 commandes

```bash
# 1. Créer le fichier .env
cp .env.docker.example .env

# 2. Changer les secrets (OBLIGATOIRE en production)
nano .env  # Modifier SECRET_KEY et JWT_SECRET_KEY

# 3. Déployer
./deploy.sh prod
```

✅ **C'est tout !** L'application sera accessible sur http://localhost:3000

## 🎯 Ou avec Make

```bash
# Installation Docker complète
make quickstart-docker
```

## 📋 Commandes utiles

```bash
# Voir les logs
docker-compose logs -f

# Arrêter
docker-compose down

# Redémarrer
docker-compose restart

# Accéder au shell
docker-compose exec gamearena bash
```

## 📚 Documentation complète

Voir **[DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)** pour :
- Configuration avancée
- PostgreSQL
- Nginx reverse proxy
- Sécurité production
- Monitoring
- Dépannage

## 🔐 Sécurité

**⚠️ AVANT DE DÉPLOYER EN PRODUCTION** :

1. Changez `SECRET_KEY` et `JWT_SECRET_KEY` dans `.env`
2. Générez des secrets forts :
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
3. Configurez HTTPS (voir section Nginx dans docs)
4. Restreignez CORS (pas `origins='*'`)

## 📁 Structure

```
GameArena/
├── Dockerfile              # Multi-stage build
├── docker-compose.yml      # Services Docker
├── deploy.sh              # Script de déploiement
├── .env.docker.example    # Template config
└── DOCKER_DEPLOYMENT.md   # Documentation complète
```

## 🐛 Problèmes ?

```bash
# Vérifier les logs
docker-compose logs gamearena

# Rebuild complet
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

**Documentation complète** : [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md)
