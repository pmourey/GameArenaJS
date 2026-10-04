## Purpose

Ce fichier donne aux agents IA (Copilot/agents) l'essentiel pour être productifs rapidement
dans ce dépôt GameArena (prototype bot-arena). Il se concentre sur l'architecture, les
workflows de dev/test, les conventions projet-spécifiques et les points d'intégration.

## Vue d'ensemble (big picture)

- Backend: Flask (`app.py`) — expose une petite API JSON pour lister les referees, créer
  des parties et avancer des tours. Références: `app.py`, endpoints `/api/referees`,
  `/api/games`, `/api/games/<id>/step`, `/api/games/<id>/history`.
- Referees / règles: classes dérivées de `game_sdk.Referee` (ex : `referees/pacman_referee.py`).
- Execution des bots: abstraction `game_sdk.BotRunner` qui choisit entre Docker et subprocess
  (implémentation Docker dans `runner/docker_runner.py`).
- Frontend: React + Vite dans `frontend/` (éditeur Monaco, visualizer). Déploiement dev via
  `frontend/package.json` et build copy qui place les fichiers construits dans `static/`.

## Architecture & Design Patterns

### Principes SOLID (à respecter impérativement)

**S - Single Responsibility Principle**
- Chaque classe/module a UNE seule raison de changer
- ✅ `Referee` : gère uniquement les règles du jeu
- ✅ `BotRunner` : gère uniquement l'exécution des bots
- ✅ `DockerRunner` : gère uniquement l'isolation Docker
- ❌ Ne pas mélanger logique métier et persistence dans les referees

**O - Open/Closed Principle**
- Ouvert à l'extension, fermé à la modification
- ✅ Créer de nouveaux referees en héritant de `game_sdk.Referee`
- ✅ Ajouter de nouveaux runners en implémentant l'interface `BotRunner`
- ❌ Ne pas modifier `game_sdk.Referee` pour ajouter des règles spécifiques

**L - Liskov Substitution Principle**
- Toute sous-classe doit être substituable à sa classe parente
- ✅ Tous les `Referee` implémentent le même contrat (init_game, step, etc.)
- ✅ Tous les runners peuvent être utilisés de manière interchangeable
- ❌ Ne pas changer la signature des méthodes héritées

**I - Interface Segregation Principle**
- Pas de dépendances sur des interfaces non utilisées
- ✅ `Referee` expose uniquement les méthodes nécessaires au game engine
- ✅ `BotRunner` n'expose que `run()` au referee
- ❌ Ne pas forcer les referees à implémenter des méthodes inutiles

**D - Dependency Inversion Principle**
- Dépendre d'abstractions, pas d'implémentations concrètes
- ✅ `app.py` dépend de l'interface `Referee`, pas d'une implémentation
- ✅ Le referee dépend de `BotRunner` abstrait, pas de `DockerRunner`
- ❌ Ne pas instancier directement `DockerRunner` dans le referee

### Patterns de Design Utilisés

#### 1. Strategy Pattern (`BotRunner`)
```python
# BotRunner définit l'interface, les implémentations varient
class BotRunner:
    def run(code, input_data, timeout_ms): ...
    
# Stratégies concrètes
- SubprocessRunner : exécution locale rapide
- DockerRunner : exécution isolée sécurisée
- ParsedBotRunner : optimisation pour bots avec while-loop
```

**Avantages** :
- Changement de stratégie à runtime (auto-selection)
- Ajout de nouvelles stratégies sans modifier le code existant

#### 2. Template Method Pattern (`Referee`)
```python
class Referee:
    def run_game(self):  # Template method (ne pas override)
        self.init_game()
        while not self.is_finished():
            self.step()  # Appelle parse_bot_output, on_bot_timeout, etc.
    
    # Méthodes abstraites à implémenter
    def init_game(self): raise NotImplementedError
    def step(self): raise NotImplementedError
    def parse_bot_output(self, output): raise NotImplementedError
```

**Avantages** :
- Structure commune pour tous les jeux
- Points d'extension bien définis

#### 3. Factory Pattern (implicite dans `app.py`)
```python
# Création de referee basée sur le type de jeu
def get_referee(game_type):
    if game_type == 'pacman':
        return PacmanReferee()
    elif game_type == 'tictactoe':
        return TicTacToeReferee()
```

**À améliorer** : Créer un vrai `RefereeFactory` au lieu de if/elif

#### 4. Repository Pattern (persistance)
```python
# Actuellement dispersé dans app.py
# À refactoriser en :
class BotRepository:
    def save(bot): ...
    def find_by_id(bot_id): ...
    def find_by_user(user_id): ...

class GameRepository:
    def save_state(game_id, state): ...
    def load_state(game_id): ...
```

### Responsabilités des Composants

#### Backend

**`app.py` (API Layer)** ⚠️ Trop de responsabilités actuellement
- ✅ DOIT : Gérer les routes HTTP, validation des inputs, authentification JWT
- ❌ NE DOIT PAS : Logique métier, accès direct DB, parsing de code bot

**Refactoring recommandé** :
```
app.py (routes)
  ↓
services/
  - game_service.py (création/gestion parties)
  - bot_service.py (CRUD bots, validation code)
  - match_service.py (matchmaking, ranking)
repositories/
  - bot_repository.py (DB access bots)
  - game_repository.py (DB access games)
  - user_repository.py (DB access users)
```

**`game_sdk.Referee`** (Domain Logic)
- ✅ DOIT : Règles du jeu, validation des coups, détection fin de partie
- ❌ NE DOIT PAS : Exécution de code, gestion de processus, persistence

**`game_sdk.BotRunner`** (Execution Abstraction)
- ✅ DOIT : Interface pour exécuter du code Python avec timeout
- ❌ NE DOIT PAS : Connaître les règles du jeu, gérer la persistence

**`runner/docker_runner.py`** (Infrastructure)
- ✅ DOIT : Isolation Docker, gestion sécurité, cleanup ressources
- ❌ NE DOIT PAS : Parser la sortie du bot, connaître le format des commandes

**`referees/pacman_referee.py`** (Game-Specific Logic)
- ✅ DOIT : Logique Pacman (pellets, collisions, scores)
- ❌ NE DOIT PAS : Logique d'exécution, DB access, gestion utilisateurs

#### Frontend

**`PlaygroundPage.jsx`** ⚠️ Actuellement trop gros (~1200 lignes)
- ✅ DOIT : Orchestration UI, gestion état global page
- ❌ NE DOIT PAS : Logique réseau directe (utiliser services), logique métier

**Refactoring recommandé** :
```jsx
PlaygroundPage.jsx (orchestration)
  ↓
hooks/
  - useGameRunner.js (logique collecte/animation)
  - useBot.js (CRUD bot, save automatique)
  - useAuth.js (authentification)
services/
  - gameApi.js (appels API games)
  - botApi.js (appels API bots)
  - userApi.js (appels API user/avatar)
components/
  - BotSelectionPanel.jsx ✅ (déjà refactorisé)
  - MonacoEditor.jsx ✅
  - Visualizer.jsx ✅
  - BotStderrPanel.jsx ✅
```

**`BotSelectionPanel.jsx`** (UI Component)
- ✅ DOIT : Affichage avatars, modal sélection, gestion événements UI
- ❌ NE DOIT PAS : Appels API directs, logique métier, validation

**`Visualizer.jsx`** (Presentation)
- ✅ DOIT : Rendu PixiJS, animations, contrôles lecture
- ❌ NE DOIT PAS : Appels API, logique de jeu, gestion état global

## Patterns & conventions importantes à connaître

- Referee contract (implémenter dans une sous-classe): `init_game`, `get_protocol`,
  `get_state`, `is_finished`, `step`, `make_bot_input`, `parse_bot_output`, `on_bot_timeout` —
  voir `game_sdk.Referee` et `referees/pacman_referee.py`.
- BotRunner modes: `'auto'|'docker'|'subprocess'`. Par défaut `auto` (logique: petits
  timeouts -> subprocess, sinon essayer docker puis fallback). Voir `game_sdk.BotRunner`.
- Parsed-bot optimization: si le code du bot contient une boucle `while` top-level, on
  peut exécuter une phase d'init puis des tours via `parse_bot_code`, `run_parsed_init` et
  `run_parsed_turn` (garder l'état dans `parsed['globals']`). Le parsing est dans `game_sdk.py`.
- Persistant: les bots sauvegardés sont sous `persistent_bots/<bot_id>/bot.py` et l'index
  `persistent_bots/games_index.json` conserve métadonnées (utilisé par `app.py`).

## Variables d'environnement et flags utiles

- BOT_DOCKER_IMAGE : image Docker utilisée (ex: `gamearena-bot:latest` ou `python:3.11-slim`).
- BOT_RUNNER : `auto|docker|subprocess` pour forcer le runner.
- BOT_TMP_DIR : dossier de base pour tmpdir Docker (utile sur macOS pour File Sharing).
- BOT_DOCKER_AUTO_THRESHOLD_MS, BOT_DOCKER_STARTUP_MS : ajustent heuristiques startup.
- DOCKER_RUNNER_TRACE, DOCKER_RUNNER_PER_RUN_CHECKS : active logs/débogage du runner
  (`runner/docker_runner.py`) et collecte LAST_RUN_DEBUG.

## Dev / build / test workflows (concrets)

- Installer tout (backend + frontend): `make install` (crée `.venv` et fait `npm install`).
- Lancer backend: activez `.venv` puis `python3 app.py` (considéré default dev server).
- Lancer frontend dev: `cd frontend && npm run dev` (Vite). Configurez `VITE_API_BASE`
  si besoin pour pointer vers le backend.
- Build frontend pour servir via Flask: `make build` -> exécute `frontend/npm run build:copy`
  qui copie le build dans `static/` pour que `app.py` serve la UI statique.
- Runner tests: `make test-runner` / `make run-test-auto` (vérifie Docker ou fallback).
- Construire image bot locale: `make build-bot-image` (script `runner/build_bot_image.sh`).

## API JSON et exemples utiles

- `GET /api/referees` -> protocole par referee (utilisé par UI pour générer inputs).
- `POST /api/games` -> crée une partie. Corps JSON: `{ "referee":"pacman", "player_code": "..." }`.
  Réponse: `{ "game_id": "<uuid>" }`.
- `POST /api/games/<game_id>/step` -> avance un tour ; réponse inclut `history_entry`.
- `GET /api/games/<game_id>/history` -> replay complet (utilisé par la UI pour l'animation).

Exemple rapide (depuis README.md) :

```bash
curl -s -X POST http://127.0.0.1:5000/api/games \
  -H 'Content-Type: application/json' \
  -d '{"referee":"pacman","player_code":"print(\"MOVE 1 0\")"}' | jq
```

## Points de vigilance pour un agent IA qui modifie le code

### Principes SOLID - Rappels critiques

**Avant toute modification, vérifier** :
1. ✅ La classe modifiée a-t-elle UNE seule responsabilité ? (SRP)
2. ✅ Peut-on étendre sans modifier l'existant ? (OCP)
3. ✅ Les sous-classes sont-elles substituables ? (LSP)
4. ✅ Les interfaces sont-elles minimales ? (ISP)
5. ✅ Dépend-on d'abstractions, pas d'implémentations ? (DIP)

### Règles strictes

**NE JAMAIS** :
- ❌ Mélanger logique métier et DB access dans un même fichier
- ❌ Créer des dépendances circulaires entre modules
- ❌ Modifier le contrat de `Referee` sans mettre à jour tous les consumers
- ❌ Ajouter de la logique métier dans `app.py` (créer un service)
- ❌ Faire des appels API directs depuis les composants UI (utiliser des hooks/services)
- ❌ Hardcoder des chemins ou configurations (utiliser variables d'environnement)

**TOUJOURS** :
- ✅ Séparer concerns : API layer / Service layer / Repository layer / Domain
- ✅ Utiliser dependency injection (passer dependencies en paramètres)
- ✅ Créer des interfaces/abstractions avant les implémentations
- ✅ Écrire des tests unitaires pour toute nouvelle logique métier
- ✅ Documenter les contrats (docstrings, JSDoc) avec précision

### Sécurité et robustesse

- Ne pas modifier le contrat de `Referee` sans mettre à jour la UI et les consumers.
- Les per-turn timeouts et la logique `BotRunner` sont sensibles: préserver
  `BOT_DOCKER_AUTO_THRESHOLD_MS` et le fallback docker->subprocess.
- Si vous changez la stratégie d'exécution (docker vs subprocess), testez `make test-runner`
  et `runner/run_local_mount_test.sh` sur macOS (mount issues fréquents).
- Le mode "parsed bots" garde un état global dans `parsed['globals']` — attention
  aux effets de bord si vous modifiez la sérialisation ou la création des objets.
- **Validation des inputs** : Toujours valider côté backend, jamais faire confiance au frontend
- **Isolation Docker** : Ne jamais désactiver les limites de ressources (mem_limit, cpu_quota, pids_limit)
- **Gestion des erreurs** : Toujours logger les exceptions, retourner des messages clairs à l'utilisateur

## Fichiers clés et leurs responsabilités

### Backend (Python)

| Fichier | Responsabilité | Pattern | SOLID |
|---------|---------------|---------|-------|
| `app.py` | Routes HTTP, validation inputs | API Layer | ⚠️ Viole SRP (trop de responsabilités) |
| `game_sdk.py` | Abstractions Referee/BotRunner | Template Method, Strategy | ✅ Bon respect |
| `runner/docker_runner.py` | Isolation Docker | Strategy (implémentation) | ✅ SRP respecté |
| `referees/pacman_referee.py` | Règles Pacman | Template Method (impl) | ✅ OCP/LSP respectés |
| `models.py` | Modèles SQLAlchemy | Active Record | ⚠️ Mélange domain et DB |

**Refactoring prioritaire** : Extraire logique métier de `app.py` vers des services

### Frontend (React)

| Fichier | Responsabilité | Pattern | SOLID |
|---------|---------------|---------|-------|
| `PlaygroundPage.jsx` | Orchestration page | Container Component | ⚠️ Viole SRP (1200 lignes) |
| `BotSelectionPanel.jsx` | Sélection joueurs + modal | Compound Component | ✅ SRP respecté |
| `Visualizer.jsx` | Rendu PixiJS | Presentation Component | ✅ SRP respecté |
| `useGameRunner.js` | Logique collecte/animation | Custom Hook | ✅ SRP/SoC respecté |
| `MonacoEditor.jsx` | Éditeur code | Controlled Component | ✅ SRP respecté |

**Refactoring prioritaire** : Extraire services API et hooks métier de `PlaygroundPage.jsx`

## Dette technique identifiée

### Critique (à corriger en priorité)

1. **`app.py` trop large** (~1500 lignes)
   - Violation : SRP, DIP
   - Impact : Maintenance difficile, tests complexes
   - Action : Créer `services/` et `repositories/`

2. **`PlaygroundPage.jsx` trop complexe** (~1200 lignes)
   - Violation : SRP
   - Impact : Tests difficiles, réutilisation impossible
   - Action : Extraire hooks et services

3. **Pas de couche service**
   - Violation : SRP, DIP
   - Impact : Logique métier dispersée
   - Action : Créer `services/game_service.py`, `services/bot_service.py`

### Moyenne (à planifier)

4. **`models.py` mélange domain et persistence**
   - Violation : SRP
   - Action : Séparer entités domain et modèles DB

5. **Pas de validation centralisée des inputs**
   - Violation : DRY
   - Action : Créer `validators/` avec schemas

6. **Hardcoded configurations**
   - Violation : OCP
   - Action : Externaliser dans `config.py` et `.env`

## Checklist pour nouvelles fonctionnalités

Avant d'ajouter du code, vérifier :

- [ ] La fonctionnalité respecte-t-elle SRP ? (Une seule raison de changer)
- [ ] Peut-on l'étendre sans modifier l'existant ? (OCP)
- [ ] Les abstractions sont-elles bien définies ? (DIP)
- [ ] Les interfaces sont-elles minimales ? (ISP)
- [ ] Les tests unitaires sont-ils écrits ? (TDD si possible)
- [ ] La documentation est-elle à jour ? (README, docstrings)
- [ ] Les erreurs sont-elles bien gérées ? (try/except, logging)
- [ ] La sécurité est-elle vérifiée ? (validation, sanitization, isolation)

## Ressources et références

- [SOLID Principles (Uncle Bob)](https://en.wikipedia.org/wiki/SOLID)
- [Design Patterns (Gang of Four)](https://refactoring.guru/design-patterns)
- [Clean Architecture (Robert C. Martin)](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Flask Best Practices](https://flask.palletsprojects.com/en/2.3.x/patterns/)
- [React Patterns](https://reactpatterns.com/)

Si une section est incomplète ou si vous voulez des exemples supplémentaires (ex: explication
du format exact des `history_entry` ou tests unitaires à ajouter), dites-moi quelles
parties approfondir et j'itérerai. Merci de préciser les attentes (niveau de détail).
