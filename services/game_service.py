"""Game Service - Logique métier des parties.

Responsabilité (SRP) : Orchestration des parties de jeu.
- Création de parties
- Exécution des tours
- Gestion du state des parties
- PAS d'accès direct DB (utilise repositories)
"""
import os
import logging
from typing import Dict, Any, Optional, Tuple
import uuid
from game_sdk import Referee, make_bot_runner, BotRunner
from repositories.game_repository import GameRepository
from repositories.bot_repository import BotRepository


class GameService:
    """Service pour la gestion métier des parties.
    
    Pattern: Service Layer
    SOLID:
        - SRP (logique métier parties uniquement)
        - DIP (dépend d'abstractions repositories)
        - OCP (extensible pour nouveaux types de jeux)
    """
    
    def __init__(self, referees: Dict[str, type], 
                 game_repository: GameRepository = None,
                 bot_repository: BotRepository = None):
        """Initialise le service avec dependency injection.
        
        Args:
            referees: Mapping {referee_name: RefereeClass}
            game_repository: Repository pour persistence parties
            bot_repository: Repository pour accès bots
        """
        self.referees = referees
        self.game_repo = game_repository or GameRepository()
        self.bot_repo = bot_repository or BotRepository()
        self.logger = logging.getLogger(__name__)
        
        # In-memory store for active games
        self.active_games: Dict[str, Dict[str, Any]] = {}
    
    def create_game(self, referee_name: str, mode: str = 'player-vs-bot',
                   player_code: str = None, opponent: str = 'Boss',
                   player_bot_id: int = None, bot1: str = None, bot2: str = None,
                   bot_runner: str = None, user_league: int = None) -> Dict[str, Any]:
        """Crée une nouvelle partie.
        
        Args:
            referee_name: Nom du referee (ex: 'pacman')
            mode: Mode de jeu ('player-vs-bot' ou 'bot-vs-bot')
            player_code: Code du joueur (mode player-vs-bot)
            opponent: Nom de l'opposant (mode player-vs-bot)
            player_bot_id: ID du bot joueur (optionnel)
            bot1: Premier bot (mode bot-vs-bot)
            bot2: Second bot (mode bot-vs-bot)
            bot_runner: Type de runner ('auto', 'docker', 'subprocess')
            user_league: Index de la ligue de l'utilisateur (1-4)
            
        Returns:
            Dictionnaire avec game_id et infos
            
        Raises:
            ValueError: Si referee inconnu ou paramètres invalides
        """
        # Validation
        referee_class = self.referees.get(referee_name)
        if not referee_class:
            raise ValueError(f"Unknown referee: {referee_name}")
        
        # Récupération des règles de ligue
        init_params = {}
        if user_league is not None:
            from leagues import League, LeagueRules
            try:
                league = League(user_league)
                rules = LeagueRules(league)
                init_params = rules.get_init_params()
                self.logger.info(f"Creating game with {league.name} league rules: {init_params}")
            except Exception as e:
                self.logger.warning(f"Failed to load league rules: {e}")
        
        # Création du referee
        ref: Referee = referee_class()
        ref.init_game(init_params)
        
        # Génération ID unique
        game_id = str(uuid.uuid4())
        
        # Construction de l'entrée de partie
        if mode == 'bot-vs-bot':
            game_entry = {
                'id': game_id,
                'ref': ref,
                'mode': 'bot-vs-bot',
                'bot1': bot1 or 'Boss',
                'bot2': bot2 or 'Boss',
                'bot_runner': bot_runner,
                'history': []
            }
        else:
            game_entry = {
                'id': game_id,
                'ref': ref,
                'mode': 'player-vs-bot',
                'player_code': player_code,
                'player_bot_id': player_bot_id,
                'opponent': opponent or 'Boss',
                'bot_runner': bot_runner,
                'history': []
            }
        
        game_entry['history'] = ref.history
        
        # Sauvegarde dans le repository
        self.game_repo.save_games_index_entry(game_id, {
            'player_bot_id': game_entry.get('player_bot_id'),
            'opponent': game_entry.get('opponent'),
            'bot_runner': game_entry.get('bot_runner'),
            'referee': referee_name
        })
        
        # Stockage en mémoire
        self.active_games[game_id] = game_entry
        
        self.logger.info(
            f"Created game {game_id}, mode={mode}, "
            f"opponent={game_entry.get('opponent')}, "
            f"player_bot_id={game_entry.get('player_bot_id')}"
        )
        
        return {'game_id': game_id}
    
    def get_game(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Récupère une partie active ou la restore depuis l'index.
        
        Args:
            game_id: ID de la partie
            
        Returns:
            Dictionnaire de la partie ou None
        """
        game = self.active_games.get(game_id)
        if not game:
            # Tenter de restaurer depuis l'index
            metadata = self.game_repo.get_game_metadata(game_id)
            if metadata:
                # Restauration simplifiée (à améliorer)
                referee_name = metadata.get('referee', 'pacman')
                referee_class = self.referees.get(referee_name)
                if referee_class:
                    ref = referee_class()
                    ref.init_game({})
                    game = {
                        'id': game_id,
                        'ref': ref,
                        'player_bot_id': metadata.get('player_bot_id'),
                        'opponent': metadata.get('opponent'),
                        'bot_runner': metadata.get('bot_runner'),
                        'history': []
                    }
                    self.active_games[game_id] = game
        
        return game
    
    def load_bot_code(self, game: Dict[str, Any], role: str) -> Tuple[Optional[str], Optional[str]]:
        """Charge le code d'un bot pour un rôle donné.
        
        Args:
            game: Dictionnaire de la partie
            role: 'player' ou 'opponent'
            
        Returns:
            Tuple (bot_code, bot_path)
        """
        bot_code = None
        bot_path = None
        
        is_arena_match = game.get('is_arena_match', False)
        mode = game.get('mode', 'player-vs-bot')
        
        # Bot-vs-bot mode
        if mode == 'bot-vs-bot':
            bot_setting = game.get('bot1') if role == 'player' else game.get('bot2')
            
            # Essayer de charger depuis la DB
            try:
                bot_id = int(bot_setting)
                bot = self.bot_repo.find_by_id(bot_id)
                if bot:
                    if is_arena_match and bot.latest_version_number > 0:
                        active_version = bot.get_active_version()
                        if active_version:
                            bot_code = active_version.code
                            bot_path = f'db:bot:{bot_id}:v{active_version.version_number}'
                            self.logger.info(
                                f'Using bot from Arena ({role}): '
                                f'id={bot_id}, name={bot.name}, '
                                f'version={active_version.version_name}'
                            )
                        else:
                            bot_code = bot.code
                            bot_path = f'db:bot:{bot_id}'
                    else:
                        bot_code = bot.code
                        bot_path = f'db:bot:{bot_id}:draft'
                        self.logger.info(f'Using bot draft ({role}): id={bot_id}, name={bot.name}')
            except (ValueError, TypeError):
                # Fallback to Boss or file-based bot
                if bot_setting == 'Boss' or not bot_setting:
                    bot_path = 'bots/Boss.py'
                    bot_code = self.game_repo.load_bot_file(bot_path)
        
        # Player-vs-bot mode
        elif role == 'player':
            player_bot_id = game.get('player_bot_id')
            if player_bot_id:
                bot = self.bot_repo.find_by_id(player_bot_id)
                if bot:
                    if is_arena_match and bot.latest_version_number > 0:
                        active_version = bot.get_active_version()
                        if active_version:
                            bot_code = active_version.code
                            bot_path = f'db:bot:{player_bot_id}:v{active_version.version_number}'
                            self.logger.info(
                                f'Using player bot from Arena: '
                                f'id={player_bot_id}, name={bot.name}, '
                                f'version={active_version.version_name}'
                            )
                        else:
                            bot_code = bot.code
                            bot_path = f'db:bot:{player_bot_id}'
                            self.logger.warning(
                                f'Player bot {player_bot_id} has no Arena version, '
                                'using draft code'
                            )
                    else:
                        bot_code = bot.code
                        bot_path = f'db:bot:{player_bot_id}:draft'
                        self.logger.info(
                            f'Using player bot draft from Playground: '
                            f'id={player_bot_id}, name={bot.name}'
                        )
            
            # Fallback to legacy paths
            if not bot_code:
                bot_path = game.get('player_bot_path')
                if bot_path:
                    bot_code = self.game_repo.load_bot_file(bot_path)
            
            if not bot_code:
                bot_code = game.get('player_code')
        
        # Opponent in player-vs-bot mode
        elif role == 'opponent':
            opponent = game.get('opponent', 'Boss')
            if opponent == 'Boss' or not opponent:
                bot_path = 'bots/Boss.py'
                bot_code = self.game_repo.load_bot_file(bot_path)
        
        # Fallback par défaut
        if not bot_code:
            bot_code = 'print("STAY")'
        
        return bot_code, bot_path
    
    def step_game(self, game_id: str, 
                  bot_runner_factory=None) -> Dict[str, Any]:
        """Exécute un tour de jeu.
        
        Args:
            game_id: ID de la partie
            bot_runner_factory: Factory pour créer BotRunner (injectable)
            
        Returns:
            Résultat du tour avec state et logs
            
        Raises:
            ValueError: Si partie introuvable
        """
        game = self.get_game(game_id)
        if not game:
            raise ValueError(f"Game {game_id} not found")
        
        ref: Referee = game['ref']
        
        # Récupération contraintes
        protocol = ref.get_protocol()
        timeout_ms = protocol.get('constraints', {}).get('time_ms', 50)
        memory_mb = protocol.get('constraints', {}).get('memory_mb', 64)
        cpus = protocol.get('constraints', {}).get('cpus', 0.5)
        
        # Vérification fin de partie
        if ref.is_finished():
            return {
                'finished': True,
                'state': ref.get_state(),
                'history': ref.history
            }
        
        # Cette méthode délègue l'exécution des bots
        # Le code d'exécution détaillé reste dans app.py pour l'instant
        # (sera extrait dans une prochaine itération)
        
        return {
            'finished': False,
            'game': game,
            'timeout_ms': timeout_ms,
            'memory_mb': memory_mb,
            'cpus': cpus
        }
