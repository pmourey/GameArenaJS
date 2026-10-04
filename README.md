# GameArena — plateforme prototype d'arène de bots

GameArena est un prototype d'une plateforme de programmation compétitive qui permet d'exécuter des "bots" (codes écrits par des programmeurs) qui s'affrontent dans une arène. Le rôle du `Referee` est de définir les règles du jeu et de piloter l'avancement tour par tour ; il n'est pas un adversaire : les joueurs sont les bots.

Résumé rapide
- But : démontrer une architecture modulaire et sécurisée pour organiser des matchs entre programmes intelligents (bots) et expérimenter des règles de jeux.
- Stack : Python (Flask) pour le backend, React + Vite pour le frontend, Docker pour l'isolation des bots.

Fonctionnalités clés
- Referee extensible : chaque jeu est implémenté comme une sous-classe de `game_sdk.Referee` (contrat : init_game, step, get_state, parse_bot_output, on_bot_timeout, ...). Le `Referee` définit le protocole, valide les actions des bots à chaque tour et met à jour l'état du jeu.
- BotRunner abstrait : exécute le code des bots via plusieurs stratégies (docker, subprocess, mode parsed optimisé) sans coupler la logique du jeu à l'exécution.
- Sandbox Docker : exécution isolée des bots avec nettoyage et limites ressources — fallback en `subprocess` si utile en dev.
- Frontend interactif : éditeur de code (Monaco), visualizer et panneau de logs pour rejouer l'historique d'une partie.
- Persistance minimale : bots persistants sous `persistent_bots/` et index JSON pour métadonnées.

Arenas, ligues et boss
- L'arène est organisée en ligues. Chaque ligue contient des joueurs (bots) qui s'affrontent entre eux selon les règles définies pour cette ligue.
- Chaque ligue peut comporter un "boss" (un bot spécial ou une entité) que les joueurs doivent vaincre pour prétendre à la promotion.
- Progression : les bots accumulent des victoires/points dans leur ligue ; lorsqu'ils remplissent les conditions (p.ex. classement suffisant et avoir vaincu le boss), ils peuvent être promus vers la ligue supérieure, qui peut ajouter des règles ou contraintes additionnelles.
- Ce modèle permet d'introduire des règles graduelles et des variantes de jeu entre ligues sans modifier les joueurs : le `Referee` associé à la ligue pilote ces règles.

Structure et rôles des composants

Backend (API)
- Fichier principal : `app.py` — gère les routes HTTP et la validation des entrées. Le fichier contient actuellement une logique qui peut être extraite en services.
- Recommandation structurelle : séparer l'API (routes) des services métier et des repositories (p.ex. `services/game_service.py`, `repositories/game_repository.py`). Cela améliore la testabilité et le respect du principe SRP.
- Endpoints clés :
  - GET  `/api/referees` — liste des referees et description du protocole attendu par le frontend.
  - POST `/api/games` — création d'une nouvelle partie (payload JSON avec `referee`, `player_code`, options).
  - POST `/api/games/<id>/step` — avancer une seule étape (tour) de la partie.
  - GET  `/api/games/<id>/history` — récupérer l'historique complet (format `history_entry` décrit ci‑dessous).

Domain (game_sdk)
- `game_sdk.py` contient les abstractions centrales :
  - `Referee` : contrat template-method pour exécuter une partie (init_game, step, is_finished, make_bot_input, parse_bot_output, on_bot_timeout, get_state).
  - `BotRunner` : interface/stratégie pour l'exécution de bots. Implémente `run(code, input_data, timeout_ms)` et gère la sélection de la stratégie (`auto|docker|subprocess`).
- Pattern utilisés : Template Method (Referee) et Strategy (BotRunner).

Referees (règles de jeu)
- Emplacement : `referees/`.
- Chaque referee implémente la logique métier du jeu : validation des mouvements, collisions, scoring, conditions de fin.
- Exemples de comportements que les referees peuvent implémenter :
  - MOVE vers une cellule non adjacente : accepter une action MOVE vers une cible distante et la convertir en une série de déplacements le long du plus court chemin (algorithme BFS/A* selon la topologie).
  - Evitement de collision : règles pour rejeter ou ajuster un MOVE si deux pacs tentent la même case (priorité, file d'attente, ou redirection automatique).
  - Fin anticipée : terminer la partie si un joueur a suffisamment de pellets pour être mathématiquement assuré de la victoire (score actuel > adversaire + pellets_restants).

BotRunner et runners concrets
- Implémentations :
  - `runner/docker_runner.py` : exécution isolée via Docker, gestion des limites (CPU, mémoire, pids), nettoyage et collecte de logs.
  - Subprocess runner : exécution locale plus rapide pour le dev, sans isolation forte.
  - Mode parsed : optimisation où le code du bot est analysé et exécuté en mode interactif (init + tours) pour éviter le coût de startup à chaque tour.
- Politique de sélection : par défaut `auto` (heuristique basée sur timeout et configuration), sinon respecter la variable `BOT_RUNNER`.

Persistance et stockage
- Bots persistants : `persistent_bots/<bot_id>/bot.py` et métadonnées dans `persistent_bots/games_index.json`.
- Base locale : SQLite (`gamearena.db`) utilisée pour stocker objets applicatifs (utilisateurs, parties, leagues) selon `models.py`.
- Recommandation : séparer entités domain et modèles SQLAlchemy si une refactorisation est entreprise.

Frontend
- Emplacement : `frontend/` (React + Vite). Contient l'éditeur (Monaco), la visualisation (PixiJS) et les composants UI.
- Fichiers notables :
  - `frontend/src/components/MonacoEditor.jsx` — éditeur de code.
  - `frontend/src/components/Visualizer.jsx` — rendu et animation.
  - `frontend/src/pages/PlaygroundPage.jsx` — orchestration (peut être découpée en hooks et services).
- Communication : le frontend consomme l'API JSON exposée par le backend. Pour le dev, configurez `VITE_API_BASE` si nécessaire.

Format `history_entry` (aperçu)
- Un `history_entry` représente l'état et les actions d'un tour. Exemple schématique :
  - { "turn": 3, "actions": [{"player_id":"p1","action":"MOVE 3 2"}, ...], "state": { ... }, "timestamp": "..." }
- Le frontend utilise la liste des `history_entry` pour reproduire la partie image par image.

## Détail exact du format `history_entry`

Ci-dessous la spécification complète et normative du format JSON renvoyé par l'API (`POST /api/games/<game_id>/step`) dans le champ `history_entry`, et stocké dans `Referee.history`.

Objectif
- Permettre au frontend (visualizer), aux outils d'analyse et aux tests de rejouer précisément chaque tour.
- Fournir suffisamment d'information pour : afficher l'état, montrer les sorties des bots, diagnostiquer erreurs et rejouer la logique côté client.

Contrat général (résumé)
- Type racine : objet JSON
- Champs principaux :
  - `turn` (int) : numéro du tour (0-based ou 1-based selon referee, vérifier le referee; la plupart des referees utilisent 0-based pour le premier état après init). Obligatoire.
  - `state` (object) : snapshot sérialisable de l'état du jeu après application des actions de ce tour. Obligatoire.
  - `actions` (array) : liste des actions demandées/appliquées ce tour. Optionnel mais recommandé (vide si aucun mouvement). Chaque entrée d'action décrit qui a joué et quelle action a été appliquée.
  - `bot_logs` (object) : logs produits par les runners pour chaque rôle/joueur (structure injectée côté API — voir `app.py`). Optionnel mais très utile pour debug.
  - `stdout`, `stderr` (string) : sorties textuelles provenant du referee (résumé du turn) — facultatif.
  - `__global_stdout`, `__global_stderr` (string) : champs spéciaux parfois ajoutés par l'API pour contenir sorties globales retournées lors d'un step `finished` (voir usage dans le frontend). Optionnel.
  - `timestamp` (string) : horodatage ISO 8601 du moment où le tour a été produit. Optionnel mais recommandé.
  - `meta` (object) : champ libre pour ajouter métadonnées (ex: events, collision resolution details, reason_for_end). Optionnel.

Exemple JSON minimal

{
  "turn": 12,
  "state": { /* état sérialisable pour UI (positions, scores, map, pellets, etc.) */ },
  "actions": [
    { "player_id": "player", "raw": "MOVE 5 3", "resolved": "MOVE 5 3" },
    { "player_id": "opponent", "raw": "SPEED", "resolved": "SPEED" }
  ],
  "bot_logs": {
    "player": { "stdout": "...", "stderr": "...", "rc": 0, "runner": "docker" },
    "opponent": { "stdout": "...", "stderr": "...", "rc": 0, "runner": "subprocess" }
  },
  "timestamp": "2025-11-20T12:34:56.789Z"
}

Schema détaillé (description)
- turn: integer — numéro du tour (obligatoire)

- state: object — représentation complète de l'état du jeu après le tour. Contenu dépend du Referee mais doit être entièrement sérialisable JSON et contenir au minimum les éléments nécessaires au visualizer :
  - positions des entités (pacs, players) avec leurs identifiants
  - carte / grille (si nécessaire) ou delta d'affichage
  - scores / points par joueur
  - pellets restants / leur valeur si applicable
  - flags game-specific (ex: abilities actives : speed_remaining, switched_type)

  Exemples de clés communes dans `state` (non obligatoires universellement) :
  - `players`: { "player": {"pacs": [{"id": "p1", "x": 3, "y": 2, "alive": true, "ability": null}], "score": 10 }, "opponent": {...} }
  - `map`: { "width": 10, "height": 8, "cells": ["....", "##..", ...] }
  - `turn`: duplicate facultatif du champ racine pour facilité

- actions: array of objects. Chaque objet d'action peut contenir :
  - `player_id` (string) — rôle/id du joueur (par ex. "player", "opponent", ou "bot:123")
  - `raw` (string) — la sortie brute du bot ou la commande demandée
  - `parsed` (object|string) — (optionnel) représentation parsée de l'action (ex: {"type":"MOVE","target":{"x":5,"y":3}})
  - `resolved` (string) — (optionnel) action réellement appliquée après validation/résolution de conflit
  - `notes` (string) — (optionnel) message expliquant invalidation ou ajustement

- bot_logs: object mapping role -> log object
  - pour chaque rôle attendu (p.ex. "player", "opponent") :
    - `stdout` (string) : sortie standard complète collectée pendant l'exécution (init + turn si parsed)
    - `stderr` (string) : sortie d'erreur
    - `rc` (int) : return code (0 pour succès, -1 ou autre pour erreur)
    - `runner` (string) : stratégie runner utilisée ("docker", "subprocess", "parsed", "exception")

  Observations :
  - `app.py` injecte ces logs après exécution via :
    entry['bot_logs'] = {'player': player_log, 'opponent': opponent_log}
  - Les champs peuvent contenir plusieurs lignes; le frontend concatène `stdout`/`stderr` pour l'affichage.

- stdout / stderr : chaînes (optionnel)
  - `stdout` et `stderr` peuvent contenir résumés ou sorties spécifiques générées par le Referee (ex: messages sur collisions, scoring changes). L'API ajoute parfois `__global_stdout` / `__global_stderr` pour messages envoyés lors d'une réponse `finished`.

- meta: object (optionnel)
  - `events`: liste d'événements survenus (p.ex. [ {"type":"collision","players":["player","opponent"],"pos":{"x":3,"y":2},"resolution":"player_survives"} ])
  - `end_reason`: si la partie se termine, fournir une explication technique (ex: "math_win_by_pellets_remaining")
  - `pathfinding_debug`: (optionnel) array ou object décrivant les chemins calculés pour MOVE non-adjacent

Bonnes pratiques pour la production des `history_entry`
- Rendre `state` aussi compacte que possible tout en conservant l'information nécessaire au visualizer (p.ex. serializer minimal des entités au lieu d'objets lourds).
- Utiliser des types simples (int/string/array/object) et éviter les objets non sérialisables (datetime natif, sets, objets Python complexes) — sérialiser en ISO8601 pour les timestamps.
- Toujours inclure `bot_logs` quand un bot a été exécuté : cela facilite le debug et l'audit.
- Documenter dans le `Referee.get_protocol()` les attentes sur le format `state` et les clés essentielles que le frontend utilisera.

Compatibilité frontend
- Le frontend s'attend à trouver au minimum : `turn`, `state` et/ou `stdout`/`stderr` pour chaque `history_entry`.
- Si l'API retourne des objets `__global_stdout` et `__global_stderr` lors d'un dernier step (finished), le frontend les traite comme des entrées globales séparées. Le champ `history` retourné par `GET /api/games/<id>/history` est une liste où certains éléments peuvent être des objets spéciaux contenant `__global_stdout` keys.

Exemples complets

1) Tour normal avec deux actions et logs :

{
  "turn": 5,
  "state": {
    "players": {
      "player": {"score": 12, "pacs": [{"id":"p1","x":4,"y":2,"alive":true}]},
      "opponent": {"score": 8, "pacs": [{"id":"o1","x":7,"y":1,"alive":true}]}
    },
    "map": {"width":10, "height":8}
  },
  "actions": [
    {"player_id":"player","raw":"MOVE 4 2","parsed":{"type":"MOVE","x":4,"y":2},"resolved":"MOVE 4 2"},
    {"player_id":"opponent","raw":"SPEED","resolved":"SPEED"}
  ],
  "bot_logs": {
    "player": {"stdout":"init\nMOVE 4 2\n","stderr":"","rc":0,"runner":"docker"},
    "opponent": {"stdout":"SPEED\n","stderr":"","rc":0,"runner":"subprocess"}
  },
  "timestamp": "2025-11-20T12:34:56.789Z"
}

2) Réponse finale (finished) — l'API peut renvoyer un `history` complet et des entrées globales :

[
  { /* history_entry tour 0 */ },
  { /* history_entry tour N */ },
  { "__global_stdout": "Match finished: player wins, final score 20-10" }
]

Notes pour les auteurs de Referee
- Lorsque vous remplissez `ref.history.append(entry)` dans votre Referee, respectez le contrat ci-dessus :
  - `entry['turn']` et `entry['state']` doivent toujours être présents.
  - Ajoutez `entry['bot_logs']` uniquement si votre Referee n'attend pas que l'API (layer supérieur) injecte les logs ; par défaut `app.py` injecte les logs côté route `step`.
  - Pour la compatibilité avec le visualizer, exposez les clés attendues (positions, scores, map).

Tests et validation
- Écrire des tests unitaires qui vérifient la présence des champs obligatoires et la sérialisation JSON (ex: tests/tests_referee_history.py).
- Exemple d'assertions :
  - `assert 'turn' in entry and isinstance(entry['turn'], int)`
  - `assert 'state' in entry and isinstance(entry['state'], dict)`
  - `if 'bot_logs' in entry: assert 'player' in entry['bot_logs']`

---

Si vous souhaitez que j'ajoute une section détaillée sur le format exact de `history_entry`, un diagramme d'architecture SVG simple, ou un guide pour écrire un nouveau `Referee` étape par étape, dites-moi lequel et je l'ajoute.
