"""Pacman Referee v2 - Transposé du CG Spring Challenge 2020.

Compatible avec le système de ligues (Wood/Bronze/Silver/Gold).

RÈGLES COMPLÈTES IMPLÉMENTÉES
==============================

1. TYPES DE PACMAN (Rock-Paper-Scissors)
----------------------------------------
- ROCK (0)     : bat SCISSORS
- PAPER (1)    : bat ROCK
- SCISSORS (2) : bat PAPER
- NEUTRAL (-1) : ne peut ni battre ni être battu

2. ABILITIES
-----------
a) SPEED
   - Double la vitesse (2 cases/tour au lieu de 1)
   - Durée : 6 tours
   - Cooldown : 10 tours
   - Commande : "SPEED <pac_id>"

b) SWITCH
   - Change le type du pac (cycle Rock→Paper→Scissors→Rock)
   - Instantané
   - Cooldown : 10 tours
   - Commande : "SWITCH <pac_id> <target_type>"
     où target_type = ROCK, PAPER ou SCISSORS

3. FORMAT DES COMMANDES
-----------------------
Les commandes sont séparées par "|" (pipe) pour chaque pac :
- "MOVE <pac_id> <x> <y>" : Déplacer vers (x,y)
- "SPEED <pac_id>" : Activer l'ability vitesse
- "SWITCH <pac_id> <type>" : Changer de type
- Multiple pacs : "MOVE 0 5 3 | SPEED 1 | MOVE 2 8 4"

4. DÉPLACEMENT
-------------
- Horizontal ou vertical uniquement (pas de diagonales)
- 1 case par tour (2 cases si SPEED actif)
- Calcul automatique du plus court chemin (BFS)
- Les pacs peuvent se bloquer mutuellement

5. COLLISIONS ET COMBAT
-----------------------
Quand deux pacs adverses se rencontrent :
- Si types différents → le type dominant mange l'autre
- Si types identiques → aucun ne meurt
- Si l'un est NEUTRAL → aucun ne meurt

Exemples :
- ROCK vs SCISSORS → ROCK gagne
- PAPER vs PAPER → aucun ne meurt
- ROCK vs NEUTRAL → aucun ne meurt

6. PELLETS
----------
- Pellets normaux : 1 point
- Cherries (super-pellets) : 10 points
- Distribution : pellets sur toutes les cases floor, quelques cherries aléatoires

7. VISION (FOG OF WAR)
---------------------
Optionnel selon la configuration :
- fog_enabled=False : vision complète de la carte
- fog_enabled=True : vision limitée autour des pacs

8. CONDITIONS DE FIN
-------------------
Le jeu se termine si :
- Tous les pellets sont mangés
- Maximum de tours atteint (200)
- Un joueur a une avance insurmontable
- Un joueur n'a plus aucun pac vivant
- Un bot timeout ou crash

9. SCORING
----------
Score = nombre de pellets mangés (1 pt pour pellet, 10 pts pour cherry)
Victoire : plus haut score à la fin
"""
from game_sdk import Referee
from typing import Dict, Any, Tuple, List, Set, Optional
from collections import deque
import random

class PacType:
    """Types de Pacman selon rock-paper-scissors."""
    ROCK = 0
    PAPER = 1
    SCISSORS = 2
    NEUTRAL = -1
    
    @staticmethod
    def beats(type1: int, type2: int) -> bool:
        """Retourne True si type1 bat type2."""
        if type1 == PacType.NEUTRAL or type2 == PacType.NEUTRAL:
            return False
        if type1 == PacType.ROCK and type2 == PacType.SCISSORS:
            return True
        if type1 == PacType.PAPER and type2 == PacType.ROCK:
            return True
        if type1 == PacType.SCISSORS and type2 == PacType.PAPER:
            return True
        return False
    
    @staticmethod
    def from_string(s: str) -> int:
        """Convertit un string en type."""
        s = s.upper()
        if s == 'ROCK': return PacType.ROCK
        if s == 'PAPER': return PacType.PAPER
        if s == 'SCISSORS': return PacType.SCISSORS
        if s == 'NEUTRAL': return PacType.NEUTRAL
        return PacType.NEUTRAL
    
    @staticmethod
    def to_string(t: int) -> str:
        """Convertit un type en string."""
        if t == PacType.ROCK: return 'ROCK'
        if t == PacType.PAPER: return 'PAPER'
        if t == PacType.SCISSORS: return 'SCISSORS'
        return 'NEUTRAL'

class Pac:
    """Représente un Pacman avec ses attributs."""
    def __init__(self, pac_id: int, owner: str, position: Tuple[int, int], pac_type: int = PacType.NEUTRAL):
        self.id = pac_id
        self.owner = owner  # 'player' ou 'opponent'
        self.position = position
        self.type = pac_type
        self.speed = 1  # 1 = normal, 2 = speed boost
        self.ability_duration = 0  # tours restants avec ability active
        self.ability_cooldown = 0  # tours avant de pouvoir réutiliser ability
        self.dead = False
        self.message = ''
        self.path = []  # Chemin parcouru ce tour pour animation
    
    def can_use_ability(self) -> bool:
        """Peut utiliser une ability si pas en cooldown."""
        return self.ability_cooldown == 0
    
    def activate_speed(self):
        """Active l'ability SPEED."""
        if self.can_use_ability():
            self.speed = 2
            self.ability_duration = 6
            self.ability_cooldown = 10
            return True
        return False
    
    def switch_type(self, new_type: int):
        """Change le type du pac."""
        if self.can_use_ability():
            self.type = new_type
            self.ability_cooldown = 10
            return True
        return False
    
    def tick(self):
        """Met à jour les compteurs (appelé à chaque tour)."""
        if self.ability_duration > 0:
            self.ability_duration -= 1
            if self.ability_duration == 0:
                self.speed = 1  # Retour à vitesse normale
        if self.ability_cooldown > 0:
            self.ability_cooldown -= 1
    
    def to_dict(self) -> Dict:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            'id': self.id,
            'owner': self.owner,
            'position': list(self.position),
            'type': PacType.to_string(self.type),
            'speed': self.speed,
            'ability_duration': self.ability_duration,
            'ability_cooldown': self.ability_cooldown,
            'dead': self.dead,
            'path': [list(p) for p in self.path] if self.path else [list(self.position)]
        }

class PacmanRefereeV2(Referee):
    """Referee Pacman v2 avec règles complètes du Spring Challenge 2020."""
    
    def __init__(self):
        super().__init__()
        self.width = 31  # Default au milieu de la plage 28-33
        self.height = 13  # Default au milieu de la plage 10-15
        self.grid = []  # '#' = wall, ' ' = floor
        self.pellets = set()  # Set de (x, y)
        self.cherries = set()  # Set de (x, y) - valent 10 points
        self.pacs = {}  # pac_id -> Pac object
        self.scores = {"player": 0, "opponent": 0}
        self.max_turns = 200
        self.turn = 0
        self.history = []
        self.logs = []
        self.bot_failed = None
        
        # Configuration (defaults - peut être override par init_game)
        self.cherry_score = 10
        self.num_cherries = 6
        self.fog_enabled = False
        self.pacs_per_player = 3  # Nombre de pacs par joueur
        self.speed_ability_available = True
        self.switch_ability_available = True
        self.provide_dead_pacs = True
    
    def init_game(self, init_params: Dict[str, Any]):
        """Initialise la partie avec la configuration donnée.
        
        Supporte les paramètres de ligues via LeagueRules.get_init_params()
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"🎮 PacmanRefereeV2.init_game called with params: {init_params}")
        
        self.width = init_params.get('width', self.width)
        self.height = init_params.get('height', self.height)
        self.num_cherries = init_params.get('num_cherries', self.num_cherries)
        self.pacs_per_player = init_params.get('pacs_per_player', self.pacs_per_player)
        self.fog_enabled = init_params.get('fog_enabled', self.fog_enabled)
        self.speed_ability_available = init_params.get('speed_ability_available', self.speed_ability_available)
        self.switch_ability_available = init_params.get('switch_ability_available', self.switch_ability_available)
        self.provide_dead_pacs = init_params.get('provide_dead_pacs', self.provide_dead_pacs)
        
        logger.info(f"📊 Initialized with: pacs_per_player={self.pacs_per_player}, cherries={self.num_cherries}, fog={self.fog_enabled}")
        
        # Générer une grille simple (pour l'instant sans murs complexes)
        self.grid = [[" " for _ in range(self.width)] for _ in range(self.height)]
        
        # Ajouter quelques murs pour rendre ça plus intéressant
        self._generate_walls()
        
        # Placer les pellets sur toutes les cases floor
        for y in range(self.height):
            for x in range(self.width):
                if self.grid[y][x] == ' ':
                    self.pellets.add((x, y))
        
        # Placer les pacs (positions de spawn)
        self._spawn_pacs()
        
        # Enlever les pellets des positions de spawn
        for pac in self.pacs.values():
            self.pellets.discard(pac.position)
        
        # Placer quelques cherries aléatoirement
        self._place_cherries()
        
        self.turn = 0
        self.history = []
        self.logs = []
        
        # État initial
        initial_state = self.get_state()
        self.history.append({
            'turn': 0,
            'state': initial_state,
            'actions': {},
            'stdout': '',
            'stderr': ''
        })
    
    def _generate_walls(self):
        """Génère un labyrinthe avec l'algorithme Tetris."""
        from referees.maze_generator import MazeGenerator
        
        generator = MazeGenerator()
        self.grid = generator.generate_with_horizontal_symmetry(self.width, self.height)
    
    def _spawn_pacs(self):
        """Place les pacs aux positions de spawn.
        
        Garantit exactement le même nombre de pacs pour chaque équipe
        avec des positions symétriques.
        
        Types utilisés :
        - NEUTRAL (-1) en ligue Wood (switch_ability_available=False)
        - ROCK (0), PAPER (1), SCISSORS (2) pour Bronze+ (switch_ability_available=True)
        """
        # En Wood: tous NEUTRAL, sinon cycle ROCK/PAPER/SCISSORS
        if not self.switch_ability_available:
            types = [PacType.NEUTRAL]
        else:
            types = [PacType.ROCK, PacType.PAPER, PacType.SCISSORS]
        
        # Trouver des positions valides (couloirs) à gauche et à droite
        left_positions = []
        right_positions = []
        
        for y in range(1, self.height - 1):
            for x in range(1, self.width // 2):
                if self.grid[y][x] == ' ':
                    left_positions.append((x, y))
            for x in range(self.width // 2 + 1, self.width - 1):
                if self.grid[y][x] == ' ':
                    right_positions.append((x, y))
        
        # Trier par distance au bord pour avoir des positions proches des côtés
        left_positions.sort(key=lambda pos: pos[0])
        right_positions.sort(key=lambda pos: self.width - pos[0])
        
        # Répartir verticalement
        left_positions.sort(key=lambda pos: pos[1])
        right_positions.sort(key=lambda pos: pos[1])
        
        pac_id = 1
        
        # Player pacs (gauche)
        step = max(1, len(left_positions) // (self.pacs_per_player + 1))
        for i in range(self.pacs_per_player):
            idx = min((i + 1) * step, len(left_positions) - 1)
            pos = left_positions[idx]
            pac_type = types[i % len(types)]
            self.pacs[pac_id] = Pac(pac_id, 'player', pos, pac_type)
            pac_id += 1
        
        # Opponent pacs (droite)
        step = max(1, len(right_positions) // (self.pacs_per_player + 1))
        for i in range(self.pacs_per_player):
            idx = min((i + 1) * step, len(right_positions) - 1)
            pos = right_positions[idx]
            pac_type = types[i % len(types)]
            self.pacs[pac_id] = Pac(pac_id, 'opponent', pos, pac_type)
            pac_id += 1
    
    def _place_cherries(self):
        """Place des cherries aléatoirement sur la carte."""
        available = list(self.pellets - set(pac.position for pac in self.pacs.values()))
        if len(available) < self.num_cherries:
            self.num_cherries = len(available)
        
        cherry_positions = random.sample(available, self.num_cherries)
        for pos in cherry_positions:
            self.cherries.add(pos)
            self.pellets.discard(pos)  # Les cherries remplacent les pellets
    
    def get_protocol(self):
        """Retourne le protocole du jeu."""
        return {
            'init_inputs': 'width height and the map representation',
            'turn_inputs': 'scores, visible pacs, visible pellets',
            'turn_output': 'Commands separated by | : MOVE <id> <x> <y> | SPEED <id> | SWITCH <id> <type>',
            'constraints': {
                'max_turns': self.max_turns,
                'time_ms': 1000,
                'pacs_per_player': self.pacs_per_player
            }
        }
    
    def get_state(self):
        """Retourne l'état actuel du jeu."""
        # Inclure TOUS les pacs (vivants et morts) pour permettre l'animation de mort
        state = {
            'turn': self.turn,
            'pacs': [pac.to_dict() for pac in self.pacs.values()],
            'pellets': list(self.pellets),
            'cherries': list(self.cherries),
            'scores': self.scores.copy(),
            'grid': [''.join(row) for row in self.grid]
        }
        
        if self.is_finished():
            state['winner'] = self.get_winner()
            if self.bot_failed:
                winner = self.get_winner()
                state['final_message'] = f"Winner: {winner} (opponent timeout/error)"
        
        return state
    
    def get_winner(self) -> str:
        """Détermine le vainqueur."""
        p_score = self.scores.get('player', 0)
        o_score = self.scores.get('opponent', 0)
        
        if p_score > o_score:
            return 'player'
        elif o_score > p_score:
            return 'opponent'
        else:
            return 'draw'
    
    def is_finished(self) -> bool:
        """Vérifie si le jeu est terminé."""
        # Bot failed
        if self.bot_failed:
            return True
        
        # Max turns (200)
        if self.turn >= self.max_turns:
            return True
        
        # Un joueur n'a plus aucun pac vivant
        player_alive = any(p.owner == 'player' and not p.dead for p in self.pacs.values())
        opponent_alive = any(p.owner == 'opponent' and not p.dead for p in self.pacs.values())
        
        if not player_alive or not opponent_alive:
            # Accorder toutes les pastilles restantes au survivant
            remaining = len(self.pellets) + len(self.cherries) * self.cherry_score
            if not player_alive and opponent_alive:
                self.scores['opponent'] += remaining
            elif not opponent_alive and player_alive:
                self.scores['player'] += remaining
            return True
        
        # Plus assez de pastilles pour changer l'issue (avance insurmontable)
        remaining = len(self.pellets) + len(self.cherries) * self.cherry_score
        if abs(self.scores['player'] - self.scores['opponent']) > remaining:
            return True
        
        return False
    
    def make_bot_input(self, bot_id: str) -> str:
        """Génère l'input pour un bot au format CG."""
        # Line 1: my_score opponent_score
        my_score = self.scores[bot_id]
        opp_id = 'opponent' if bot_id == 'player' else 'player'
        opp_score = self.scores[opp_id]
        
        lines = [f"{my_score} {opp_score}"]
        
        # Line 2+: visible pacs
        visible_pacs = self._get_visible_pacs(bot_id)
        lines.append(str(len(visible_pacs)))
        
        for pac in visible_pacs:
            mine = 1 if pac.owner == bot_id else 0
            lines.append(
                f"{pac.id} {mine} {pac.position[0]} {pac.position[1]} "
                f"{pac.type} {pac.ability_duration} {pac.ability_cooldown}"
            )
        
        # Visible pellets + cherries
        visible_pellets = self._get_visible_pellets(bot_id)
        visible_cherries = self._get_visible_cherries(bot_id)
        
        lines.append(str(len(visible_pellets) + len(visible_cherries)))
        
        for x, y in visible_pellets:
            lines.append(f"{x} {y} 1")
        
        for x, y in visible_cherries:
            lines.append(f"{x} {y} {self.cherry_score}")
        
        return '\n'.join(lines)
    
    def _get_visible_pacs(self, bot_id: str) -> List[Pac]:
        """Retourne les pacs visibles pour un bot."""
        if not self.fog_enabled:
            return [p for p in self.pacs.values() if not p.dead]
        
        # TODO: implémenter fog of war
        return [p for p in self.pacs.values() if not p.dead]
    
    def _get_visible_pellets(self, bot_id: str) -> Set[Tuple[int, int]]:
        """Retourne les pellets visibles."""
        if not self.fog_enabled:
            return self.pellets
        
        # TODO: fog of war
        return self.pellets
    
    def _get_visible_cherries(self, bot_id: str) -> Set[Tuple[int, int]]:
        """Retourne les cherries visibles."""
        if not self.fog_enabled:
            return self.cherries
        
        # TODO: fog of war
        return self.cherries
    
    def parse_bot_output(self, bot_id: str, output_str: str) -> str:
        """Parse et normalise la sortie du bot."""
        s = (output_str or '').strip()
        if not s:
            return ''
        
        # Prend la première ligne non vide
        first_line = ''
        for ln in s.splitlines():
            if ln and ln.strip():
                first_line = ln.strip()
                break
        
        if not first_line:
            return ''
        
        # Les commandes sont séparées par |
        commands = [c.strip() for c in first_line.split('|') if c.strip()]
        normalized = []
        
        for cmd in commands:
            parts = cmd.split()
            if not parts:
                continue
            
            cmd_type = parts[0].upper()
            
            if cmd_type == 'MOVE' and len(parts) >= 4:
                try:
                    pac_id = int(parts[1])
                    x, y = int(parts[2]), int(parts[3])
                    normalized.append(f"MOVE {pac_id} {x} {y}")
                except:
                    continue
            
            elif cmd_type == 'SPEED' and len(parts) >= 2:
                try:
                    pac_id = int(parts[1])
                    normalized.append(f"SPEED {pac_id}")
                except:
                    continue
            
            elif cmd_type == 'SWITCH' and len(parts) >= 3:
                try:
                    pac_id = int(parts[1])
                    new_type = PacType.from_string(parts[2])
                    normalized.append(f"SWITCH {pac_id} {new_type}")
                except:
                    continue
        
        return ' | '.join(normalized) if normalized else ''
    
    def _bfs_path(self, start: Tuple[int, int], target: Tuple[int, int]) -> Optional[List[Tuple[int, int]]]:
        """Calcule le plus court chemin avec BFS (supporte wrapping horizontal)."""
        if start == target:
            return [start]
        
        queue = deque([(start, [start])])
        visited = {start}
        
        while queue:
            (x, y), path = queue.popleft()
            
            for dx, dy in [(0, -1), (1, 0), (0, 1), (-1, 0)]:
                nx, ny = x + dx, y + dy
                
                # Wrapping horizontal (tunnels gauche-droite)
                if nx < 0:
                    nx = self.width - 1
                elif nx >= self.width:
                    nx = 0
                
                # Pas de wrapping vertical
                if not (0 <= ny < self.height):
                    continue
                
                if self.grid[ny][nx] == '#':
                    continue
                
                if (nx, ny) in visited:
                    continue
                
                new_path = path + [(nx, ny)]
                
                if (nx, ny) == target:
                    return new_path
                
                visited.add((nx, ny))
                queue.append(((nx, ny), new_path))
        
        return None
    
    def step(self, actions_by_bot: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
        """Exécute un tour de jeu."""
        import logging
        logger = logging.getLogger(__name__)
        
        stdout = ''
        stderr = ''
        
        # Phase 0: Nettoyage des pacs morts du tour précédent
        pacs_to_remove = [pac_id for pac_id, pac in self.pacs.items() if pac.dead]
        if pacs_to_remove:
            logger.info(f"🧹 Cleaning up dead pacs from previous turn: {pacs_to_remove}")
            for pac_id in pacs_to_remove:
                del self.pacs[pac_id]
        
        # Phase 1: Décrémenter les compteurs (cooldowns et durées)
        for pac in self.pacs.values():
            if not pac.dead:
                pac.tick()
        
        # Phase 2: Exécuter les compétences (SPEED et SWITCH)
        intentions = {}  # pac_id -> {'action': 'MOVE'|'SPEED'|'SWITCH', 'target': ..., 'path': ...}
        
        for bot_id, action_str in actions_by_bot.items():
            if not action_str:
                continue
            
            commands = [c.strip() for c in action_str.split('|') if c.strip()]
            
            # Traiter SPEED et SWITCH en premier
            for cmd in commands:
                parts = cmd.split()
                if not parts:
                    continue
                
                cmd_type = parts[0].upper()
                
                if cmd_type == 'SPEED' and len(parts) >= 2:
                    if not self.speed_ability_available:
                        stderr += f"{bot_id}: SPEED ability not available in this league\n"
                        continue
                    
                    pac_id = int(parts[1])
                    pac = self.pacs.get(pac_id)
                    
                    if not pac or pac.dead or pac.owner != bot_id:
                        continue
                    
                    if pac.activate_speed():
                        stdout += f"{bot_id}: Pac {pac_id} activated SPEED\n"
                    else:
                        stderr += f"{bot_id}: Pac {pac_id} cannot use SPEED (cooldown)\n"
                
                elif cmd_type == 'SWITCH' and len(parts) >= 3:
                    if not self.switch_ability_available:
                        stderr += f"{bot_id}: SWITCH ability not available in this league\n"
                        continue
                    
                    pac_id = int(parts[1])
                    new_type = int(parts[2])
                    pac = self.pacs.get(pac_id)
                    
                    if not pac or pac.dead or pac.owner != bot_id:
                        continue
                    
                    if pac.switch_type(new_type):
                        stdout += f"{bot_id}: Pac {pac_id} switched to {PacType.to_string(new_type)}\n"
                    else:
                        stderr += f"{bot_id}: Pac {pac_id} cannot SWITCH (cooldown)\n"
            
            # Traiter MOVE après (pour utiliser le speed mis à jour)
            for cmd in commands:
                parts = cmd.split()
                if not parts:
                    continue
                
                cmd_type = parts[0].upper()
                
                if cmd_type == 'MOVE' and len(parts) >= 4:
                    pac_id = int(parts[1])
                    target_x, target_y = int(parts[2]), int(parts[3])
                    
                    pac = self.pacs.get(pac_id)
                    if not pac or pac.dead or pac.owner != bot_id:
                        stderr += f"{bot_id}: Invalid pac {pac_id}\n"
                        continue
                    
                    path = self._bfs_path(pac.position, (target_x, target_y))
                    if not path:
                        stderr += f"{bot_id}: No path from {pac.position} to ({target_x},{target_y})\n"
                        continue
                    
                    intentions[pac_id] = {
                        'action': 'MOVE',
                        'path': path,
                        'steps': pac.speed  # 1 ou 2 selon speed boost (maintenant à jour)
                    }
        
        # Phase 3: Résolution des mouvements avec gestion des collisions
        # Sauvegarder positions de départ et initialiser path
        old_positions = {pac_id: self.pacs[pac_id].position for pac_id in self.pacs.keys()}
        for pac in self.pacs.values():
            pac.path = [pac.position]  # Commencer avec position actuelle
        
        # Calculer les mouvements pour chaque pac (1 case à la fois)
        for move_step in range(2):  # Max 2 steps pour SPEED
            # Au step 1 (move_step=1), seuls les pacs avec SPEED peuvent bouger
            # Calculer les nouvelles positions pour ce step
            step_moves = {}
            for pac_id, intent in intentions.items():
                if intent['action'] != 'MOVE':
                    continue
                pac = self.pacs[pac_id]
                if pac.dead:
                    continue
                # Au 2ème step, seuls les pacs avec speed > 1 peuvent bouger
                if move_step == 1 and pac.speed <= 1:
                    continue
                if move_step >= intent['steps']:
                    continue
                    
                path = intent['path']
                next_pos_idx = move_step + 1
                if next_pos_idx < len(path):
                    step_moves[pac_id] = path[next_pos_idx]
            
            if not step_moves:
                break
            
            # Résolution des collisions (itératif jusqu'à stabilisation)
            max_iterations = 10
            for iteration in range(max_iterations):
                collisions_found = False
                blocked_pacs = set()
                
                # Détecter collisions sur même case
                target_counts = {}
                for pac_id, pos in step_moves.items():
                    if pac_id in blocked_pacs:
                        continue
                    pac = self.pacs[pac_id]
                    target_counts.setdefault(pos, []).append((pac_id, pac.owner, pac.type))
                
                for pos, pac_list in target_counts.items():
                    if len(pac_list) > 1:
                        owners = set(owner for _, owner, _ in pac_list)
                        types = set(ptype for _, _, ptype in pac_list)
                        
                        # Collision si même joueur OU même type
                        if len(owners) == 1 or len(types) == 1:
                            logger.info(f"💥 Collision at {pos}: {[pid for pid, _, _ in pac_list]} blocked")
                            for pac_id, _, _ in pac_list:
                                blocked_pacs.add(pac_id)
                                # Retour à la position initiale
                                self.pacs[pac_id].position = old_positions[pac_id]
                            collisions_found = True
                
                # Détecter croisements
                for pac1_id, new_pos1 in step_moves.items():
                    if pac1_id in blocked_pacs:
                        continue
                    pac1 = self.pacs[pac1_id]
                    old_pos1 = pac1.position
                    
                    for pac2_id, new_pos2 in step_moves.items():
                        if pac2_id <= pac1_id or pac2_id in blocked_pacs:
                            continue
                        pac2 = self.pacs[pac2_id]
                        old_pos2 = pac2.position
                        
                        # Croisement détecté
                        if old_pos1 == new_pos2 and old_pos2 == new_pos1:
                            # Même joueur ou même type → blocage
                            if pac1.owner == pac2.owner or pac1.type == pac2.type:
                                logger.info(f"🔀 Crossing collision: {pac1_id} and {pac2_id} blocked")
                                blocked_pacs.add(pac1_id)
                                blocked_pacs.add(pac2_id)
                                # Retour à la position initiale
                                self.pacs[pac1_id].position = old_positions[pac1_id]
                                self.pacs[pac2_id].position = old_positions[pac2_id]
                                collisions_found = True
                            # Types différents: pac faible bloqué
                            elif PacType.beats(pac1.type, pac2.type):
                                logger.info(f"🔀 Crossing: {pac2_id} blocked by stronger {pac1_id}")
                                blocked_pacs.add(pac2_id)
                                self.pacs[pac2_id].position = old_positions[pac2_id]
                                collisions_found = True
                            elif PacType.beats(pac2.type, pac1.type):
                                logger.info(f"🔀 Crossing: {pac1_id} blocked by stronger {pac2_id}")
                                blocked_pacs.add(pac1_id)
                                self.pacs[pac1_id].position = old_positions[pac1_id]
                                collisions_found = True
                
                # Retirer les pacs bloqués
                for pac_id in blocked_pacs:
                    if pac_id in step_moves:
                        del step_moves[pac_id]
                
                if not collisions_found:
                    break
            
            # Appliquer les mouvements validés
            for pac_id, new_pos in step_moves.items():
                pac = self.pacs[pac_id]
                pac.position = new_pos
                pac.path.append(new_pos)  # Enregistrer dans le chemin
                stdout += f"{pac.owner}: Pac {pac_id} moved to {new_pos}\n"
        
        # Phase 4: Tuer les pacs qui ont perdu lors de collisions (combat)
        combat_pairs = set()
        for pac1 in self.pacs.values():
            if pac1.dead:
                continue
            for pac2 in self.pacs.values():
                if pac2.dead or pac1.id >= pac2.id:
                    continue
                if pac1.owner == pac2.owner:
                    continue
                if pac1.position == pac2.position:
                    pair_key = tuple(sorted([pac1.id, pac2.id]))
                    if pair_key in combat_pairs:
                        continue
                    combat_pairs.add(pair_key)
                    
                    logger.info(f"⚔️ COMBAT at {pac1.position}: Pac {pac1.id} ({PacType.to_string(pac1.type)}) vs Pac {pac2.id} ({PacType.to_string(pac2.type)})")
                    if PacType.beats(pac1.type, pac2.type):
                        pac2.dead = True
                        stdout += f"Combat: Pac {pac1.id} defeated Pac {pac2.id}\n"
                    elif PacType.beats(pac2.type, pac1.type):
                        pac1.dead = True
                        stdout += f"Combat: Pac {pac2.id} defeated Pac {pac1.id}\n"
                        break
        
        # Phase 5: Ingestion des pastilles
        for pac in self.pacs.values():
            if pac.dead:
                continue
            
            pos = pac.position
            
            if pos in self.pellets:
                self.pellets.remove(pos)
                self.scores[pac.owner] += 1
                stdout += f"{pac.owner}: Pac {pac.id} ate pellet at {pos} (+1)\n"
            
            if pos in self.cherries:
                self.cherries.remove(pos)
                self.scores[pac.owner] += self.cherry_score
                stdout += f"{pac.owner}: Pac {pac.id} ate cherry at {pos} (+{self.cherry_score})\n"
        

        
        self.turn += 1
        state = self.get_state()
        
        self.history.append({
            'turn': self.turn,
            'state': state,
            'actions': actions_by_bot.copy(),
            'stdout': stdout,
            'stderr': stderr
        })
        
        self.logs.append(stdout + stderr)
        
        return state, stdout, stderr
    
    def on_bot_timeout(self, bot_id: str, turn: int, reason: str = ''):
        """Gère le timeout d'un bot."""
        self.bot_failed = bot_id
        self.scores[bot_id] = 0
        self.turn = self.max_turns
        
        try:
            self.history.append({
                'turn': self.turn,
                'state': self.get_state(),
                'actions': {},
                'stdout': '',
                'stderr': f"Bot '{bot_id}' timeout on turn {turn}: {reason}"
            })
        except:
            pass
