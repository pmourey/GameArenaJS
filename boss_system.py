"""Système de Boss pour les ligues GameArena.

Chaque ligue a un Boss que les joueurs doivent battre pour être promus.
Les Boss utilisent les règles spécifiques de leur ligue et ont des stratégies
optimisées pour leur niveau.
"""

import logging
from typing import Optional, Dict, Any
from models import Bot, User, db
from leagues import League, LeagueManager, get_league_rules

logger = logging.getLogger(__name__)


class BossSystem:
    """Gestionnaire des Boss de ligue.
    
    Responsabilité (SRP): Gestion des Boss uniquement
    Pattern: Singleton pour accès global
    SOLID: Interface claire, extensible pour nouveaux Boss
    """
    
    # Noms et ELO cibles des Boss par ligue
    # Chaque Boss a son propre utilisateur dédié
    BOSS_CONFIG = {
        League.WOOD2: {
            'name': 'Wood 2 Boss',
            'username': 'boss_wood2',  # User dédié
            'elo': 750,  # Juste en dessous du seuil Wood 1 (800)
            'description': 'Boss de la ligue Wood 2 - Découverte du jeu avec 1 pac',
            'strategy': 'basic_greedy',
            'avatar': 'wood2_boss'
        },
        League.WOOD1: {
            'name': 'Wood 1 Boss',
            'username': 'boss_wood1',  # User dédié
            'elo': 1050,  # Juste en dessous du seuil Bronze (1100)
            'description': 'Boss de la ligue Wood 1 - Gestion de multiple pacs',
            'strategy': 'basic_multi_pac',
            'avatar': 'wood1_boss'
        },
        League.BRONZE: {
            'name': 'Bronze Boss',
            'username': 'boss_bronze',  # User dédié
            'elo': 1350,  # Juste en dessous du seuil Silver (1400)
            'description': 'Boss de la ligue Bronze - Gestion multi-pacs efficace',
            'strategy': 'multi_pac_coordinator',
            'avatar': 'bronze_boss'  # Avatar unique pour le Bronze Boss
        },
        League.SILVER: {
            'name': 'Silver Boss',
            'username': 'boss_silver',  # User dédié
            'elo': 1650,  # Juste en dessous du seuil Gold (1700)
            'description': 'Boss de la ligue Silver - Utilise les abilities et le fog of war',
            'strategy': 'advanced_abilities',
            'avatar': 'silver_boss'  # Avatar unique pour le Silver Boss
        },
        League.GOLD: {
            'name': 'Gold Boss',
            'username': 'boss_gold',  # User dédié
            'elo': 2100,  # Boss final, très difficile
            'description': 'Boss ultime de la ligue Gold - Maître stratège',
            'strategy': 'master_ai',
            'avatar': 'gold_boss'  # Avatar unique pour le Gold Boss
        }
    }
    
    @classmethod
    def get_boss_for_league(cls, league: League) -> Optional[Bot]:
        """Récupère le bot Boss pour une ligue donnée.
        
        Args:
            league: La ligue dont on veut le Boss
            
        Returns:
            Le bot Boss ou None si non trouvé
        """
        from models import User
        
        config = cls.BOSS_CONFIG.get(league)
        if not config:
            return None
        
        # Chercher l'utilisateur Boss par username
        boss_user = User.query.filter_by(username=config['username']).first()
        if not boss_user:
            logger.warning(f"Boss user {config['username']} not found for league {league.to_name()}")
            return None
        
        # Chercher le bot du Boss
        boss_bot = Bot.query.filter_by(
            user_id=boss_user.id,
            name=config['name']
        ).first()
        
        if not boss_bot:
            logger.warning(f"Boss bot {config['name']} not found for user {boss_user.username}")
        
        return boss_bot
    
    @classmethod
    def get_elo_floor_for_league(cls, league_index: int) -> int:
        """Retourne l'ELO minimum pour une ligue donnée.
        
        Un bot ne peut pas descendre en dessous de l'ELO du Boss de la ligue inférieure.
        Pour la ligue la plus basse (WOOD2), l'ELO minimum est 0.
        
        Args:
            league_index: Index de la ligue (1=WOOD2, 2=WOOD1, etc.)
            
        Returns:
            ELO minimum pour cette ligue
        """
        current_league = League.from_index(league_index)
        
        # WOOD2 est la ligue la plus basse, ELO minimum = 0
        if current_league == League.WOOD2:
            return 0
        
        # Pour les autres ligues, utiliser l'ELO du Boss de la ligue inférieure
        lower_league = League.from_index(league_index - 1)
        boss_config = cls.BOSS_CONFIG.get(lower_league)
        
        if boss_config:
            return boss_config['elo']
        
        # Fallback: pas de floor (0)
        return 0
    
    @classmethod
    def get_next_boss(cls, current_elo: int, current_league: int) -> Optional[tuple[League, Bot]]:
        """Trouve le prochain Boss à affronter pour progresser.
        
        Args:
            current_elo: ELO actuel du joueur
            current_league: Ligue actuelle (index)
            
        Returns:
            Tuple (league, boss_bot) ou None si pas de Boss à affronter
        """
        # Déterminer la ligue cible
        current_league_enum = League.from_index(current_league)
        
        # Si déjà Gold, pas de Boss suivant
        if current_league_enum == League.GOLD:
            return None
        
        # Boss de la ligue actuelle (pour progresser à la suivante)
        target_league = current_league_enum
        boss = cls.get_boss_for_league(target_league)
        
        if not boss:
            logger.error(f"Boss not found for league {target_league.to_name()}")
            return None
        
        return target_league, boss
    
    @classmethod
    def can_challenge_boss(cls, user: User) -> tuple[bool, str, Optional[Bot]]:
        """Vérifie si un joueur peut défier le Boss.
        
        Args:
            user: L'utilisateur qui veut défier
            
        Returns:
            Tuple (peut_defier, message, boss_bot)
        """
        # Récupérer le bot actif de l'utilisateur pour déterminer sa league
        player_bot = Bot.query.filter_by(
            user_id=user.id,
            is_active=True
        ).order_by(Bot.elo_rating.desc()).first()
        
        if not player_bot:
            return False, "Vous devez avoir un bot actif pour défier le Boss", None
        
        current_league = League.from_index(player_bot.league)
        
        # Si déjà Gold, pas de Boss à défier
        if current_league == League.GOLD:
            return False, "Vous êtes déjà dans la ligue Gold (maximum)", None
        
        # Vérifier l'ELO requis
        boss_config = cls.BOSS_CONFIG.get(current_league)
        if not boss_config:
            return False, "Configuration Boss non trouvée", None
        
        boss_elo = boss_config['elo']
        
        # Le joueur doit avoir un ELO au moins égal au Boss
        if player_bot.elo_rating < boss_elo:
            elo_needed = boss_elo - player_bot.elo_rating
            return False, f"ELO insuffisant. Il vous manque {elo_needed} points pour défier le {boss_config['name']} (requis: {boss_elo}, actuel: {player_bot.elo_rating})", None
        
        # Récupérer le Bot Boss
        boss = cls.get_boss_for_league(current_league)
        if not boss:
            return False, f"Boss {boss_config['name']} non trouvé en base de données", None
        
        return True, f"Vous pouvez défier le {boss_config['name']} !", boss
    
    @classmethod
    def check_promotion_after_boss_match(cls, user: User, player_bot: Bot, beat_boss: bool) -> tuple[bool, str]:
        """Vérifie et applique la promotion après un match contre un Boss.
        
        Args:
            user: L'utilisateur qui a joué
            player_bot: Le bot du joueur qui a combattu
            beat_boss: True si le joueur a battu le Boss
            
        Returns:
            Tuple (promoted, message)
        """
        if not beat_boss:
            return False, "Vous devez battre le Boss pour être promu."
        
        if not player_bot:
            return False, "Bot non trouvé."
        
        current_league = League.from_index(player_bot.league)
        
        # Si déjà Gold, pas de promotion possible
        if current_league == League.GOLD:
            return False, "Vous êtes déjà dans la ligue maximum."
        
        # Vérifier que l'ELO est suffisant (sécurité)
        next_league = League(current_league + 1)
        next_threshold = LeagueManager.ELO_THRESHOLDS.get(next_league)
        
        if player_bot.elo_rating < next_threshold:
            return False, f"ELO insuffisant pour la promotion. Requis: {next_threshold}, actuel: {player_bot.elo_rating}"
        
        # PROMOTION !
        old_league = current_league.to_name()
        player_bot.league = int(next_league)
        db.session.commit()
        
        logger.info(f"🎉🏆 Bot {player_bot.name} (user {user.username}) PROMOTED from {old_league} to {next_league.to_name()} after beating Boss!")
        
        return True, f"🎉 Félicitations ! Votre bot a été promu en ligue {next_league.to_name()} !"
    
    @classmethod
    def initialize_bosses(cls, force_recreate: bool = False) -> Dict[str, Any]:
        """Initialise tous les Boss en base de données.
        
        Args:
            force_recreate: Si True, recrée les Boss même s'ils existent
            
        Returns:
            Dictionnaire avec les résultats de l'initialisation
        """
        results = {
            'created': [],
            'updated': [],
            'errors': []
        }
        
        # Vérifier que le user système existe
        boss_user = User.query.get(cls.BOSS_USER_ID)
        if not boss_user:
            # Créer un user système
            boss_user = User(
                id=cls.BOSS_USER_ID,
                username='system_boss',
                email='boss@gamearena.local',
                password_hash='',  # Pas de connexion possible
                elo_rating=2000,
                league=4  # Gold par défaut
            )
            db.session.add(boss_user)
            db.session.commit()
            logger.info("Created system boss user")
        
        # Créer chaque Boss
        for league, config in cls.BOSS_CONFIG.items():
            try:
                existing_boss = cls.get_boss_for_league(league)
                
                if existing_boss and not force_recreate:
                    # Mettre à jour l'ELO seulement
                    existing_boss.elo_rating = config['elo']
                    results['updated'].append(config['name'])
                    logger.info(f"Updated {config['name']} ELO to {config['elo']}")
                else:
                    # Supprimer l'ancien si force_recreate
                    if existing_boss and force_recreate:
                        db.session.delete(existing_boss)
                        db.session.commit()
                    
                    # Créer le nouveau Boss avec le code approprié
                    boss_code = cls._get_boss_code(config['strategy'])
                    
                    new_boss = Bot(
                        name=config['name'],
                        user_id=cls.BOSS_USER_ID,
                        code=boss_code,
                        elo_rating=config['elo'],
                        is_active=True,
                        latest_version_number=1,
                        avatar=config.get('avatar', 'boss')  # Avatar spécifique au Boss
                    )
                    
                    db.session.add(new_boss)
                    results['created'].append(config['name'])
                    logger.info(f"Created {config['name']} with ELO {config['elo']}")
                
            except Exception as e:
                logger.exception(f"Error initializing {config['name']}")
                results['errors'].append(f"{config['name']}: {str(e)}")
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.exception("Error committing boss initialization")
            results['errors'].append(f"Commit error: {str(e)}")
        
        return results
    
    @classmethod
    def _get_boss_code(cls, strategy: str) -> str:
        """Retourne le code Python pour un Boss selon sa stratégie.
        
        Le code est chargé depuis bots/boss_codes/<strategy>.py
        
        Args:
            strategy: Type de stratégie du Boss
            
        Returns:
            Code Python du bot
        """
        import os
        
        # Mapping des stratégies vers les fichiers
        strategy_files = {
            'basic_greedy': 'wood_boss.py',
            'multi_pac_coordinator': 'bronze_boss.py',
            'advanced_abilities': 'silver_boss.py',
            'master_ai': 'gold_boss.py'
        }
        
        filename = strategy_files.get(strategy)
        if not filename:
            logger.error(f"Unknown boss strategy: {strategy}")
            return "# Error: Unknown strategy\nprint('MOVE 0 1 1')"
        
        # Chemin vers le fichier de code
        base_dir = os.path.dirname(os.path.abspath(__file__))
        code_path = os.path.join(base_dir, 'bots', 'boss_codes', filename)
        
        try:
            with open(code_path, 'r', encoding='utf-8') as f:
                code = f.read()
            logger.info(f"Loaded boss code from {code_path}")
            return code
        except FileNotFoundError:
            logger.error(f"Boss code file not found: {code_path}")
            return "# Error: Code file not found\nprint('MOVE 0 1 1')"
        except Exception as e:
            logger.exception(f"Error loading boss code from {code_path}")
            return f"# Error loading code: {str(e)}\nprint('MOVE 0 1 1')"
    
    @classmethod
    def _get_boss_code_inline_backup(cls, strategy: str) -> str:
        """Backup: Code inline si les fichiers ne sont pas disponibles.
        
        DEPRECATED: Utiliser _get_boss_code() qui lit depuis bots/boss_codes/
        """
        # Code de base (greedy simple)
        if strategy == 'basic_greedy':
            return '''import sys

# Wood Boss - Stratégie greedy basique
while True:
    my_score, opponent_score = [int(i) for i in input().split()]
    visible_pac_count = int(input())
    
    my_pacs = []
    for i in range(visible_pac_count):
        inputs = input().split()
        pac_id = int(inputs[0])
        mine = inputs[1] != "0"
        x, y = int(inputs[2]), int(inputs[3])
        if mine:
            my_pacs.append((pac_id, x, y))
    
    visible_pellet_count = int(input())
    pellets = []
    for i in range(visible_pellet_count):
        x, y, value = [int(j) for j in input().split()]
        pellets.append((x, y, value))
    
    # Prioriser les super pellets
    pellets.sort(key=lambda p: -p[2])
    
    commands = []
    for pac_id, px, py in my_pacs:
        if pellets:
            target = pellets.pop(0)
            commands.append(f"MOVE {pac_id} {target[0]} {target[1]}")
    
    print(" | ".join(commands) if commands else "MOVE 0 1 1")
'''
        
        elif strategy == 'multi_pac_coordinator':
            return '''import sys
from collections import defaultdict

def manhattan(x1, y1, x2, y2):
    return abs(x1 - x2) + abs(y1 - y2)

# Bronze Boss - Coordination multi-pacs
visited = set()
while True:
    my_score, opponent_score = [int(i) for i in input().split()]
    visible_pac_count = int(input())
    
    my_pacs = []
    enemy_pacs = []
    for i in range(visible_pac_count):
        inputs = input().split()
        pac_id = int(inputs[0])
        mine = inputs[1] != "0"
        x, y = int(inputs[2]), int(inputs[3])
        if mine:
            my_pacs.append((pac_id, x, y))
        else:
            enemy_pacs.append((x, y))
    
    visible_pellet_count = int(input())
    pellets = []
    for i in range(visible_pellet_count):
        x, y, value = [int(j) for j in input().split()]
        pellets.append((x, y, value))
    
    commands = []
    assigned = set()
    
    for pac_id, px, py in my_pacs:
        visited.add((px, py))
        best = None
        best_score = -999999
        
        for tx, ty, value in pellets:
            if (tx, ty) in assigned:
                continue
            dist = manhattan(px, py, tx, ty)
            score = value * 10 - dist
            if score > best_score:
                best_score = score
                best = (tx, ty)
        
        if best:
            assigned.add(best)
            commands.append(f"MOVE {pac_id} {best[0]} {best[1]}")
        else:
            # Explorer
            tx, ty = (px + 3) % 30, (py + 2) % 15
            commands.append(f"MOVE {pac_id} {tx} {ty}")
    
    print(" | ".join(commands) if commands else "MOVE 0 1 1")
'''
        
        elif strategy == 'advanced_abilities':
            return '''import sys

# Silver Boss - Avec abilities
turn = 0
while True:
    turn += 1
    my_score, opponent_score = [int(i) for i in input().split()]
    visible_pac_count = int(input())
    
    my_pacs = []
    for i in range(visible_pac_count):
        inputs = input().split()
        pac_id = int(inputs[0])
        mine = inputs[1] != "0"
        x, y = int(inputs[2]), int(inputs[3])
        type_id = inputs[4]
        speed_left = int(inputs[5])
        ability_cd = int(inputs[6])
        if mine:
            my_pacs.append((pac_id, x, y, type_id, speed_left, ability_cd))
    
    visible_pellet_count = int(input())
    pellets = []
    for i in range(visible_pellet_count):
        x, y, value = [int(j) for j in input().split()]
        pellets.append((x, y, value))
    
    commands = []
    for pac_id, px, py, ptype, speed, cd in my_pacs:
        # Utiliser SPEED tous les 10 tours si disponible
        if cd == 0 and turn % 10 == 0:
            commands.append(f"SPEED {pac_id}")
        elif pellets:
            target = max(pellets, key=lambda p: p[2] * 10 - abs(p[0]-px) - abs(p[1]-py))
            commands.append(f"MOVE {pac_id} {target[0]} {target[1]}")
    
    print(" | ".join(commands) if commands else "MOVE 0 1 1")
'''
        
        else:  # master_ai (Gold Boss)
            return '''import sys
import random

# Gold Boss - IA avancée
turn = 0
strategies = {}
while True:
    turn += 1
    my_score, opponent_score = [int(i) for i in input().split()]
    visible_pac_count = int(input())
    
    my_pacs = []
    enemies = []
    for i in range(visible_pac_count):
        inputs = input().split()
        pac_id = int(inputs[0])
        mine = inputs[1] != "0"
        x, y = int(inputs[2]), int(inputs[3])
        type_id = inputs[4]
        speed_left = int(inputs[5])
        ability_cd = int(inputs[6])
        if mine:
            my_pacs.append((pac_id, x, y, type_id, speed_left, ability_cd))
        else:
            enemies.append((x, y, type_id))
    
    visible_pellet_count = int(input())
    pellets = []
    for i in range(visible_pellet_count):
        x, y, value = [int(j) for j in input().split()]
        pellets.append((x, y, value))
    
    commands = []
    for pac_id, px, py, ptype, speed, cd in my_pacs:
        # Stratégie adaptative
        if not strategies.get(pac_id):
            strategies[pac_id] = random.choice(['aggressive', 'collector'])
        
        strategy = strategies[pac_id]
        
        if strategy == 'aggressive' and enemies and cd == 0:
            # SWITCH pour contrer l'ennemi le plus proche
            enemy = min(enemies, key=lambda e: abs(e[0]-px) + abs(e[1]-py))
            counter = {'ROCK': 'PAPER', 'PAPER': 'SCISSORS', 'SCISSORS': 'ROCK'}
            if enemy[2] in counter:
                commands.append(f"SWITCH {pac_id} {counter[enemy[2]]}")
            else:
                commands.append(f"MOVE {pac_id} {enemy[0]} {enemy[1]}")
        elif pellets:
            best = max(pellets, key=lambda p: p[2] * 15 - abs(p[0]-px) - abs(p[1]-py))
            if cd == 0 and abs(best[0]-px) + abs(best[1]-py) > 5:
                commands.append(f"SPEED {pac_id}")
            else:
                commands.append(f"MOVE {pac_id} {best[0]} {best[1]}")
    
    print(" | ".join(commands) if commands else "MOVE 0 1 1")
'''
