# Système ELO par Ligue - Documentation

## Vue d'ensemble

Le nouveau système utilise un **ELO local par ligue** au lieu d'un ELO global. Chaque bot recommence à 0 dans chaque nouvelle ligue.

## Changements principaux

### 1. ELO local par ligue (`league_elo`)

- **Nouveau champ** : `Bot.league_elo` (INTEGER, default 0)
- **Reset automatique** : À chaque promotion de ligue, `league_elo` retombe à 0
- **ELO global conservé** : `Bot.elo_rating` reste pour historique mais n'est plus utilisé pour le classement

### 2. Boss ELO dynamique

**Ancien système** :
- Boss ELO était **constant** (ne changeait jamais)
- Paliers fixes : Wood2=800, Wood1=900, Bronze=1000, Silver=1200, Gold=1400

**Nouveau système** :
- Boss ELO **fluctue** après chaque match (comme les autres bots)
- ELO de référence initial par ligue :
  - **Wood2** : 300 ELO
  - **Wood1** : 500 ELO
  - **Bronze** : 700 ELO
  - **Silver** : 900 ELO
  - **Gold** : 1100 ELO

### 3. Classement modifié

#### Classement global (`GET /api/leaderboard`)
- Affiche **tous les bots** (pas les Boss)
- Groupés par ligue (Gold → Silver → Bronze → Wood1 → Wood2)
- Triés par `league_elo` dans chaque ligue
- Boss **exclus** du classement global

#### Classement par ligue (`GET /api/leaderboard?league=bronze`)
- Affiche les **bots + Boss** de la ligue
- Triés par `league_elo` décroissant
- Boss **inclus** dans le classement de sa ligue

### 4. Affichage frontend

**Playground (header)** :
```
GameArena - React Prototype - [LeagueBadge] - Rang X / Y
```

Au lieu de :
```
GameArena - React Prototype - [LeagueBadge] - 1200 ELO (45%)
```

### 5. Progression multi-ligues

**Soumission d'un bot** :
1. Bot démarre avec `league_elo = 0` dans sa ligue actuelle
2. Phase 1 : 25 matchs préparation (gain d'ELO)
3. Phase 2 : Combat Boss (continue tant que ratio > 50%)
4. **Si promotion** :
   - Bot passe à la ligue supérieure
   - `league_elo` reset à 0
   - **Continuation automatique** : Phase 1 + Phase 2 dans la nouvelle ligue
   - Répète jusqu'à échec de promotion ou atteinte de Gold

**Exemple** :
```
Wood2 (league_elo=0) → 25 matchs → Boss fight → WIN
  ↓ Promotion + Reset
Wood1 (league_elo=0) → 25 matchs → Boss fight → WIN
  ↓ Promotion + Reset
Bronze (league_elo=0) → 25 matchs → Boss fight → FAIL (ratio < 50%)
  ↓ Stop
Bot reste en Bronze
```

## Fichiers modifiés

### Backend
- `models.py` : Ajout champ `league_elo`, mise à jour `to_dict()`
- `arena.py` : Modification `complete_match()` pour utiliser `league_elo`, Boss ELO dynamique
- `app.py` :
  - `get_league_ranking()` : Calcul du rang dans la ligue
  - `api_get_user_league()` : Retourne `{league, league_elo, rank, total_bots}`
  - `api_get_leaderboard()` : Nouveau système de classement
  - `placement_matches()` : Reset `league_elo=0`, utilise `league_elo` pour comparaisons
- `leagues.py` : Ajout `League.get_boss_initial_elo()`

### Frontend
- `PlaygroundPage.jsx` : Affiche `Rang X / Y`, supprimé alert soumission, auto-refresh

### Migrations
- `migrate_add_league_elo.py` : Ajoute colonne `league_elo` à table `bots`
- `init_boss_elo.py` : Initialise Boss avec ELO de référence

## API Endpoints mis à jour

### `GET /api/user/league`
**Avant** :
```json
{
  "league": "Bronze",
  "elo": 1050,
  "progress_percent": 35
}
```

**Après** :
```json
{
  "current_league": "Bronze",
  "league_id": 3,
  "elo": 450,
  "rank": 5,
  "total_bots": 12,
  "progress_percent": 0
}
```

### `GET /api/leaderboard`
**Sans paramètre** : Classement global (tous bots, pas Boss)
**Avec `?league=bronze`** : Classement Bronze (bots + Boss)

## Avantages du nouveau système

1. **Progression claire** : Chaque ligue = nouveau défi, ELO reset
2. **Boss réaliste** : ELO fluctue selon performances
3. **Classement fair** : Comparaison au sein de chaque ligue
4. **Motivation** : Reset ELO empêche stagnation
5. **Multi-ligues** : Progression automatique jusqu'à blocage

## Migration

Pour les bases existantes :
```bash
python3 migrate_add_league_elo.py  # Ajoute colonne league_elo
python3 init_boss_elo.py           # Init Boss avec ELO référence
```

## Tests

TODO : Créer test de progression multi-ligues
- Bot Wood2 → Wood1 → Bronze → Silver (avec reset ELO à chaque étape)
