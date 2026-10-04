"""Flask backend for bot arena prototype (refactored).

Architecture:
- API Layer (app.py): Routes HTTP, validation inputs
- Service Layer (services/): Logique métier
- Repository Layer (repositories/): Accès données
- Domain Layer (game_sdk, models): Entités et règles métier

SOLID compliant avec séparation des responsabilités.
"""
from flask import Flask, jsonify, request, send_from_directory, send_file
from werkzeug.utils import secure_filename
from referees.pacman_referee_v2 import PacmanRefereeV2
import os
import pathlib
from game_sdk import Referee, make_bot_runner, BotRunner
from runner.docker_runner import get_last_run_debug, set_console_tracing, is_console_tracing_enabled
from flask_cors import CORS
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from models import db, User, Bot, Match
from auth import register_user, login_user, get_current_user
from arena import ArenaManager
from boss_system import BossSystem
from leagues import League, LeagueManager
import uuid
import subprocess
import logging
import errno
import json
import re
import traceback
import datetime as dt

# Import des services et repositories (DIP)
from services.bot_service import BotService
from services.game_service import GameService
from repositories.bot_repository import BotRepository
from repositories.game_repository import GameRepository
from repositories.user_repository import UserRepository

# Configure basic logging so INFO logs appear in the Flask console by default
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
# Ensure Flask and werkzeug loggers propagate at INFO level
logging.getLogger('werkzeug').setLevel(logging.INFO)

app = Flask(__name__, static_folder=None)  # Désactiver le static folder automatique
# Ensure app logger level
app.logger.setLevel(logging.INFO)

# Configuration
import secrets
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', secrets.token_hex(32))
app.config['WTF_CSRF_ENABLED'] = True
app.config['WTF_CSRF_TIME_LIMIT'] = None
app.config['WTF_CSRF_CHECK_DEFAULT'] = False  # Désactiver vérification auto, on vérifie manuellement
app.config['JWT_TOKEN_LOCATION'] = ['headers']
app.config['JWT_HEADER_NAME'] = 'Authorization'
app.config['JWT_HEADER_TYPE'] = 'Bearer'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.abspath('instance/gamearena.db')}")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
# Configuration CORS étendue pour Private Network Access
CORS(app, 
     supports_credentials=True, 
     origins='*',
     allow_headers=['Content-Type', 'Authorization', 'X-CSRF-Token', 'Access-Control-Request-Private-Network'],
     expose_headers=['Access-Control-Allow-Private-Network'])
db.init_app(app)
jwt = JWTManager(app)

from flask_wtf.csrf import CSRFProtect
csrf = CSRFProtect(app)

# Middleware pour Private Network Access (CORS preflight)
@app.after_request
def add_private_network_headers(response):
    """Ajoute les headers nécessaires pour Private Network Access.
    
    Permet les requêtes depuis des domaines publics vers localhost.
    Voir: https://developer.chrome.com/blog/private-network-access-preflight/
    """
    # Si la requête contient le header de demande d'accès au réseau privé
    if request.headers.get('Access-Control-Request-Private-Network'):
        response.headers['Access-Control-Allow-Private-Network'] = 'true'
    
    # Ajouter les headers CORS standards pour toutes les réponses
    response.headers['Access-Control-Allow-Origin'] = request.headers.get('Origin', '*')
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Access-Control-Request-Private-Network'
    
    return response

# JWT error handlers
@jwt.invalid_token_loader
def invalid_token_callback(error):
    return jsonify({'error': 'Invalid token', 'message': str(error)}), 422

@jwt.unauthorized_loader
def missing_token_callback(error):
    return jsonify({'error': 'Authorization required', 'message': str(error)}), 401

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({'error': 'Token has expired'}), 401

# Initialize arena manager
arena_manager = ArenaManager(referee_type='pacman')

# Create tables
with app.app_context():
    db.create_all()

# Directory where edited player bots are persisted so they can be mounted into Docker
PERSISTENT_BOTS_DIR = os.environ.get('PERSISTENT_BOTS_DIR', 'persistent_bots')
try:
    pathlib.Path(PERSISTENT_BOTS_DIR).mkdir(parents=True, exist_ok=True)
except OSError as e:
    if e.errno != errno.EEXIST:
        raise

# Simple games index persisted to disk to allow short-lived server restarts without losing game ids
GAMES_INDEX_PATH = os.path.join(PERSISTENT_BOTS_DIR, 'games_index.json')

# In-memory games store (legacy, sera progressivement remplacé par GameService)
GAMES = {}

# Import du nouveau referee v2
from referees.pacman_referee_v2 import PacmanRefereeV2

REFEREES = {
    'pacman': PacmanRefereeV2,  # V2 est maintenant le referee par défaut (support ligues)
    'pacman_v2': PacmanRefereeV2  # Alias explicite
}

# -------------------- Service Layer Initialization (DIP) --------------------
# Les services sont injectés avec leurs dépendances (repositories)
# Pattern: Dependency Injection pour faciliter les tests et respecter SOLID

game_repository = GameRepository(PERSISTENT_BOTS_DIR, 'games_index.json')
bot_repository = BotRepository()
user_repository = UserRepository()

bot_service = BotService(bot_repository, game_repository)
game_service = GameService(REFEREES, game_repository, bot_repository)

# -------------------- helpers --------------------

def load_games_index():
    try:
        if os.path.exists(GAMES_INDEX_PATH):
            with open(GAMES_INDEX_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        logging.getLogger(__name__).exception('failed to load games index')
    return {}


def save_games_index_entry(game_id: str, meta: dict):
    idx = load_games_index()
    idx[game_id] = meta
    try:
        with open(GAMES_INDEX_PATH, 'w', encoding='utf-8') as f:
            json.dump(idx, f)
    except Exception:
        logging.getLogger(__name__).exception('failed to write games index')


def restore_game_from_index(game_id: str):
    idx = load_games_index()
    meta = idx.get(game_id)
    if not meta:
        return None
    maker = REFEREES.get(meta.get('referee', 'pacman'))
    if not maker:
        return None
    ref = maker()
    ref.init_game({})
    game_entry = {
        'id': game_id,
        'ref': ref,
        'player_code': None,
        'player_bot_id': meta.get('player_bot_id'),
        'opponent': meta.get('opponent', 'Boss'),
        'bot_runner': meta.get('bot_runner'),
        'history': ref.history
    }
    GAMES[game_id] = game_entry
    # Log restore so operator sees which opponent is associated
    try:
        logging.getLogger(__name__).info('restored game %s from index, opponent=%s, player_bot_id=%s', game_id, game_entry.get('opponent'), game_entry.get('player_bot_id'))
    except Exception:
        pass
    return game_entry


# Helper: run bot code in a subprocess (unused normally, kept for debugging)
def run_bot_python(bot_code: str, input_str: str, timeout_ms: int = 50):
    cmd = ['python3', '-c', bot_code]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = proc.communicate(input=input_str, timeout=timeout_ms/1000.0)
            return out, err, proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            return '', 'timeout', -1
    except Exception as e:
        return '', str(e), -1


# Validate action text
# V1: Une seule commande MOVE
ACTION_RE_V1 = re.compile(r'^(MOVE\s+-?\d+\s+-?\d+(?:\s+-?\d+)?)$', re.IGNORECASE)
# V2: Multiples commandes séparées par |
ACTION_RE_V2 = re.compile(r'^((MOVE|SPEED|SWITCH)\s+[^|]+)(\s*\|\s*(MOVE|SPEED|SWITCH)\s+[^|]+)*$', re.IGNORECASE)

def validate_action_format(raw_output: str, normalized_action: str, allow_multi_commands: bool = False):
    # Check if bot produced no output
    if not raw_output or not raw_output.strip():
        return normalized_action, 'no output from bot'
    first_line = ''
    for ln in raw_output.splitlines():
        if ln and ln.strip():
            first_line = ln.strip()
            break
    if not first_line:
        return normalized_action, 'no valid output from bot'
    
    # Vérifier selon le format attendu
    if allow_multi_commands:
        # V2: accepter plusieurs commandes
        if ACTION_RE_V2.match(first_line) or ACTION_RE_V1.match(first_line):
            return normalized_action, ''
    else:
        # V1: une seule commande
        if ACTION_RE_V1.match(first_line):
            return normalized_action, ''
    
    return normalized_action, f'invalid action format: "{first_line}"'


# Run a bot for a role using BotRunner (file or inline code)
def _run_bot_for_role(game: dict, ref: Referee, role: str, bot_cli_input: str, initial_map_block: str, timeout_ms: int, memory_mb: int, cpus: float):
    bot_code = None
    bot_path = None
    is_arena_match = game.get('is_arena_match', False)
    mode = game.get('mode', 'player-vs-bot')
    
    # Bot-vs-bot mode: map player/opponent roles to bot1/bot2
    if mode == 'bot-vs-bot':
        bot_setting = game.get('bot1') if role == 'player' else game.get('bot2')
        try:
            bot_id = int(bot_setting)
            from models import Bot
            bot = Bot.query.get(bot_id)
            if bot:
                if is_arena_match and bot.latest_version_number > 0:
                    active_version = bot.get_active_version()
                    if active_version:
                        bot_code = active_version.code
                        bot_path = f'db:bot:{bot_id}:v{active_version.version_number}'
                        logging.getLogger(__name__).info(f'Using bot from Arena ({role}): id=%s, name=%s, version=%s', 
                                                        bot_id, bot.name, active_version.version_name)
                    else:
                        bot_code = bot.code
                        bot_path = f'db:bot:{bot_id}'
                else:
                    bot_code = bot.code
                    bot_path = f'db:bot:{bot_id}:draft'
                    logging.getLogger(__name__).info(f'Using bot draft ({role}): id=%s, name=%s', bot_id, bot.name)
        except (ValueError, TypeError):
            # Fallback to Boss or other default
            if bot_setting == 'Boss' or not bot_setting:
                bot_path = 'bots/Boss.py'
                if os.path.exists(bot_path):
                    try:
                        with open(bot_path, 'r', encoding='utf-8') as f:
                            bot_code = f.read()
                    except Exception:
                        pass
        
        if not bot_code:
            bot_code = 'print("STAY")'
        
    elif role == 'player':
        # Check if player is specified by bot ID (Arena match)
        player_bot_id = game.get('player_bot_id')
        if player_bot_id:
            from models import Bot
            bot = Bot.query.get(player_bot_id)
            if bot:
                if is_arena_match and bot.latest_version_number > 0:
                    # Use Arena version for player
                    active_version = bot.get_active_version()
                    if active_version:
                        bot_code = active_version.code
                        bot_path = f'db:bot:{player_bot_id}:v{active_version.version_number}'
                        logging.getLogger(__name__).info('Using player bot from Arena: id=%s, name=%s, version=%s', 
                                                        player_bot_id, bot.name, active_version.version_name)
                    else:
                        bot_code = bot.code
                        bot_path = f'db:bot:{player_bot_id}'
                        logging.getLogger(__name__).warning('Player bot %s has no Arena version, using draft code', player_bot_id)
                else:
                    # Use current working draft (Playground)
                    bot_code = bot.code
                    bot_path = f'db:bot:{player_bot_id}:draft'
                    logging.getLogger(__name__).info('Using player bot draft from Playground: id=%s, name=%s', player_bot_id, bot.name)
        
        # Fallback to legacy player_bot_path or player_code
        if not bot_code:
            bot_path = game.get('player_bot_path')
            if bot_path and os.path.exists(bot_path):
                try:
                    with open(bot_path, 'r', encoding='utf-8') as f:
                        bot_code = f.read()
                except Exception:
                    bot_code = None
        if not bot_code:
            bot_code = game.get('player_code')
    else:
        opp_setting = game.get('opponent')
        # Check if opponent is a bot ID (integer or string digit)
        try:
            bot_id = int(opp_setting)
            from models import Bot
            bot = Bot.query.get(bot_id)
            if bot:
                # For Arena matches, use the latest submitted version
                # For Playground testing, use current working code
                if is_arena_match and bot.latest_version_number > 0:
                    # Use Arena version
                    active_version = bot.get_active_version()
                    if active_version:
                        bot_code = active_version.code
                        bot_path = f'db:bot:{bot_id}:v{active_version.version_number}'
                        logging.getLogger(__name__).info('Using bot from Arena: id=%s, name=%s, version=%s', 
                                                        bot_id, bot.name, active_version.version_name)
                    else:
                        bot_code = bot.code
                        bot_path = f'db:bot:{bot_id}'
                        logging.getLogger(__name__).warning('Bot %s has no Arena version, using draft code', bot_id)
                else:
                    # Use current working draft (Playground)
                    bot_code = bot.code
                    bot_path = f'db:bot:{bot_id}:draft'
                    logging.getLogger(__name__).info('Using bot draft from Playground: id=%s, name=%s', bot_id, bot.name)
        except (ValueError, TypeError):
            # Not a bot ID, check if it's a file path
            if opp_setting and os.path.exists(opp_setting):
                bot_path = opp_setting
                try:
                    with open(bot_path, 'r', encoding='utf-8') as f:
                        bot_code = f.read()
                except Exception:
                    bot_code = None
            else:
                # Default opponent (Boss)
                default_opp = os.path.join('bots', 'Boss.py')
                if os.path.exists(default_opp):
                    bot_path = default_opp
                    try:
                        with open(bot_path, 'r', encoding='utf-8') as f:
                            bot_code = f.read()
                    except Exception:
                        bot_code = None

    if not bot_code:
        try:
            ref.on_bot_timeout(role, ref.turn, 'no bot implementation')
        except Exception:
            pass
        logging.getLogger(__name__).info('game %s role=%s: no bot implementation (path=%s)', game.get('id'), role, bot_path)
        return 'STAY', {'stdout': '', 'stderr': 'no bot implementation', 'rc': -1, 'runner': 'engine', 'path': bot_path}

    # If the bot source contains a top-level while loop we can run it in parsed-mode
    # so that initialization runs once and the per-turn body is invoked repeatedly.
    # This avoids running the whole script in a subprocess where stdin is closed after
    # sending a single combined input (which causes EOFError on the next input()).
    try:
        # prepare storage for parsed bots per game
        parsed_store = game.setdefault('parsed_bots', {})
        parsed_entry = parsed_store.get(role)
        if not parsed_entry:
             # Try to parse bot code and detect a per-turn loop
            try:
                from game_sdk import parse_bot_code, run_parsed_init, run_parsed_turn
                parsed = parse_bot_code(bot_code)
                # Run init once using the initial_map_block
                logging.getLogger(__name__).debug('game %s role=%s: running parsed init with map block length=%d', game.get('id'), role, len(initial_map_block or ''))
                out_init, err_init, rc_init = run_parsed_init(parsed, initial_map_block or '', timeout_ms=max(2000, timeout_ms))
                # Check if init succeeded
                if rc_init != 0:
                    logging.getLogger(__name__).warning('game %s role=%s: parsed init failed (rc=%d, stderr=%s)', game.get('id'), role, rc_init, err_init)
                    parsed_entry = None
                else:
                    # store parsed object and its init outputs for subsequent turns
                    parsed_store[role] = {'parsed': parsed, 'init_stdout': out_init or '', 'init_stderr': err_init or ''}
                    parsed_entry = parsed_store[role]
                    logging.getLogger(__name__).debug('game %s role=%s: parsed init succeeded', game.get('id'), role)
            except Exception as e:
                logging.getLogger(__name__).exception('game %s role=%s: exception during parsed init', game.get('id'), role)
                parsed_entry = None
        # If we have a parsed entry with turn code, run it for this turn
        if parsed_entry:
            try:
                from game_sdk import run_parsed_turn
                parsed_obj = parsed_entry.get('parsed') if isinstance(parsed_entry, dict) else parsed_entry
                out, err, rc = run_parsed_turn(parsed_obj, bot_cli_input or '', timeout_ms=max(2000, timeout_ms))
                runner_used = 'parsed'
                if rc == -1:
                    try:
                        ref.on_bot_timeout(role, ref.turn, err or 'timeout')
                    except Exception:
                        pass
                    logging.getLogger(__name__).info('game %s role=%s: parsed execution failed/timeout (path=%s) runner=%s', game.get('id'), role, bot_path, runner_used)
                    return 'STAY', {'stdout': out or '', 'stderr': err or 'timeout', 'rc': rc, 'runner': runner_used, 'parsed': True, 'path': bot_path}
                action = ref.parse_bot_output(role, out)
                # V2 referee accepte plusieurs commandes
                allow_multi = ref.__class__.__name__ == 'PacmanRefereeV2'
                action, fmt_err = validate_action_format(out, action, allow_multi_commands=allow_multi)
                # Treat invalid actions as fatal errors
                if fmt_err:
                    try:
                        ref.on_bot_timeout(role, ref.turn, fmt_err)
                    except Exception:
                        pass
                    logging.getLogger(__name__).warning('game %s role=%s: invalid action detected (path=%s) error=%s', game.get('id'), role, bot_path, fmt_err)
                    return 'STAY', {'stdout': out or '', 'stderr': fmt_err, 'rc': -1, 'runner': runner_used, 'parsed': True, 'path': bot_path}
                stderr_field = (err or '') + (('; ' + fmt_err) if fmt_err else '')
                # include init stderr if present (helps debug init failures)
                if isinstance(parsed_entry, dict):
                    if parsed_entry.get('init_stderr'):
                        stderr_field = (parsed_entry.get('init_stderr') or '') + (('; ' + stderr_field) if stderr_field else '')
                # logging.getLogger(__name__).info('game %s role=%s: executed parsed bot (path=%s) runner=%s', game.get('id'), role, bot_path, runner_used)
                return action, {'stdout': out, 'stderr': stderr_field, 'rc': rc, 'runner': runner_used, 'parsed': True, 'path': bot_path}
            except Exception as e:
                # parsing-based execution failed; fall back to normal runner below
                logging.getLogger(__name__).exception('parsed execution failed for role %s in game %s', role, game.get('id'))
                # remove parsed entry to avoid repeated failures
                try:
                    parsed_store.pop(role, None)
                except Exception:
                    pass
        # Fallback: run via BotRunner (docker/subprocess)
        game_runner_mode = game.get('bot_runner')
        runner = BotRunner(mode=game_runner_mode) if game_runner_mode else make_bot_runner()
        full_input = (initial_map_block or '') + (bot_cli_input or '')
        out, err, rc, runner_used = runner.run(bot_code, full_input, timeout_ms=timeout_ms, memory_mb=memory_mb, cpus=cpus, host_bot_dir=(os.path.dirname(bot_path) if bot_path else None))
        if rc == -1:
            try:
                ref.on_bot_timeout(role, ref.turn, err or 'timeout')
            except Exception:
                pass
            logging.getLogger(__name__).info('game %s role=%s: runner execution failed (path=%s) runner=%s err=%s', game.get('id'), role, bot_path, runner_used, err)
            return 'STAY', {'stdout': out or '', 'stderr': err or 'timeout', 'rc': rc, 'runner': runner_used, 'path': bot_path}
        action = ref.parse_bot_output(role, out)
        # V2 referee accepte plusieurs commandes
        allow_multi = ref.__class__.__name__ == 'PacmanRefereeV2'
        action, fmt_err = validate_action_format(out, action, allow_multi_commands=allow_multi)
        # Treat invalid actions as fatal errors
        if fmt_err:
            try:
                ref.on_bot_timeout(role, ref.turn, fmt_err)
            except Exception:
                pass
            logging.getLogger(__name__).warning('game %s role=%s: invalid action detected (path=%s) error=%s', game.get('id'), role, bot_path, fmt_err)
            return 'STAY', {'stdout': out or '', 'stderr': fmt_err, 'rc': -1, 'runner': runner_used, 'path': bot_path}
        stderr_field = (err or '') + (('; ' + fmt_err) if fmt_err else '')
        logging.getLogger(__name__).info('game %s role=%s: executed runner bot (path=%s) runner=%s', game.get('id'), role, bot_path, runner_used)
        return action, {'stdout': out, 'stderr': stderr_field, 'rc': rc, 'runner': runner_used, 'path': bot_path}
    except Exception as e:
        logging.getLogger(__name__).exception('game %s role=%s: unexpected error executing bot at path=%s', game.get('id'), role, bot_path)
        return 'STAY', {'stdout': '', 'stderr': str(e), 'rc': -1, 'runner': 'runner', 'path': bot_path}


# -------------------- HTTP endpoints --------------------

@app.route('/api/csrf-token', methods=['GET'])
def get_csrf_token():
    from flask_wtf.csrf import generate_csrf
    token = generate_csrf()
    response = jsonify({'csrf_token': token})
    # S'assurer que le cookie de session est défini
    response.set_cookie('csrf_token', token, samesite='Lax')
    return response

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path):
    """
    Route principale qui sert index.html pour toutes les routes SPA React Router.
    Gère aussi le logging des connexions clientes et les fichiers statiques.
    """
    STATIC_DIR = 'static'
    
    # Si le path demandé correspond à un fichier statique existant, le servir
    if path and not path.startswith('api/'):
        static_file = os.path.join(STATIC_DIR, path)
        if os.path.exists(static_file) and os.path.isfile(static_file):
            return send_from_directory(STATIC_DIR, path)
    
    # Logging des connexions (seulement pour la route racine)
    if not path:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        ua_string = request.headers.get('User-Agent', '')
        client_os = 'Unknown'
        browser = 'Unknown'
        if 'Windows' in ua_string:
            client_os = 'Windows'
        elif 'Mac' in ua_string or 'Darwin' in ua_string:
            client_os = 'macOS'
        elif 'Linux' in ua_string:
            client_os = 'Linux'
        if 'Chrome' in ua_string:
            browser = 'Chrome'
        elif 'Firefox' in ua_string:
            browser = 'Firefox'
        elif 'Safari' in ua_string:
            browser = 'Safari'
        date = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logging.getLogger(__name__).info('Client connected: IP=%s, OS=%s, Browser=%s, Date=%s', ip, client_os, browser, date)
    
    # Servir index.html pour toutes les routes React Router
    return send_from_directory(STATIC_DIR, 'index.html')


@app.route('/api/referees')
def list_referees():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    ua_string = request.headers.get('User-Agent', '')
    os = 'Unknown'
    browser = 'Unknown'
    if 'Windows' in ua_string:
        os = 'Windows'
    elif 'Mac' in ua_string or 'Darwin' in ua_string:
        os = 'macOS'
    elif 'Linux' in ua_string:
        os = 'Linux'
    if 'Chrome' in ua_string:
        browser = 'Chrome'
    elif 'Firefox' in ua_string:
        browser = 'Firefox'
    elif 'Safari' in ua_string:
        browser = 'Safari'
    date = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    logging.getLogger(__name__).info('Client connected: IP=%s, OS=%s, Browser=%s, Date=%s', ip, os, browser, date)
    data = {}
    for name, maker in REFEREES.items():
        ref = maker()
        data[name] = ref.get_protocol()
    return jsonify(data)


@app.route('/api/template')
@app.route('/api/player/template')
def get_player_template():
    try:
        tpl_path = os.path.join('bots', 'player_template.py')
        with open(tpl_path, 'r', encoding='utf-8') as f:
            src = f.read()
        return jsonify({'template': src})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Old /api/player/code endpoint removed - bot code now stored in database only


@app.route('/api/games', methods=['POST'])
@jwt_required(optional=True)
def create_game():
    """Crée une nouvelle partie.
    
    API Layer: Validation des inputs et délégation au GameService.
    Responsabilité: HTTP handling uniquement (SRP).
    """
    body = request.json or {}
    
    # Extraction et validation des paramètres
    referee_name = body.get('referee', 'pacman_v2')  # Utiliser v2 par défaut (support des ligues)
    mode = body.get('mode', 'player-vs-bot')
    bot_runner = body.get('bot_runner')
    
    # Récupérer la ligue de l'utilisateur courant (déterminée par son bot principal)
    user_league = None
    try:
        user = get_current_user()
        if user and user.bots:
            # Utiliser le bot avec le plus haut ELO pour déterminer la ligue
            user_bot = max(user.bots, key=lambda b: b.elo_rating) if user.bots else None
            if user_bot:
                user_league = LeagueManager.get_league_from_elo(user_bot.elo_rating).value
                logging.getLogger(__name__).info(f"Creating game for user {user.username} in league {user_league}")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Could not get user league: {e}")
    
    try:
        # Délégation à la couche service (SRP + DIP)
        if mode == 'bot-vs-bot':
            result = game_service.create_game(
                referee_name=referee_name,
                mode='bot-vs-bot',
                bot1=body.get('bot1', 'Boss'),
                bot2=body.get('bot2', 'Boss'),
                bot_runner=bot_runner,
                user_league=user_league
            )
        else:
            result = game_service.create_game(
                referee_name=referee_name,
                mode='player-vs-bot',
                player_code=body.get('player_code'),
                opponent=body.get('opponent', 'Boss'),
                player_bot_id=body.get('player_bot_id'),
                bot_runner=bot_runner,
                user_league=user_league
            )
        
        # Sync avec le store legacy (transition progressive)
        game_id = result['game_id']
        game_entry = game_service.get_game(game_id)
        if game_entry:
            GAMES[game_id] = game_entry
        
        return jsonify(result), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to create game')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/games/<game_id>', methods=['GET'])
def get_game_info(game_id):
    """Récupère les informations d'une partie.
    
    API Layer: Validation et délégation au GameService.
    """
    try:
        # Essai avec le store legacy d'abord (transition)
        g = GAMES.get(game_id)
        if not g:
            g = game_service.get_game(game_id)
        if not g:
            g = restore_game_from_index(game_id)
        
        if not g:
            return jsonify({'error': 'Game not found'}), 404
        
        info = {
            'id': g.get('id'),
            'player_bot_id': g.get('player_bot_id'),
            'opponent': g.get('opponent')
        }
        return jsonify({'game': info}), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get game info')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/games/<game_id>/step', methods=['POST'])
def step_game(game_id):
    try:
        game = GAMES.get(game_id)
        if not game:
            game = restore_game_from_index(game_id)
        if not game:
            return jsonify({'error': 'not found'}), 404

        logging.getLogger(__name__).debug('step_game called for game_id=%s', game_id)
        ref: Referee = game['ref']

        timeout_ms = ref.get_protocol().get('constraints', {}).get('time_ms', 50)
        memory_mb = ref.get_protocol().get('constraints', {}).get('memory_mb', 64)
        cpus = ref.get_protocol().get('constraints', {}).get('cpus', 0.5)

        if ref.is_finished():
            return jsonify({'finished': True, 'state': ref.get_state(), 'history': ref.history})

        actions = {}
        player_log = {'stdout': '', 'stderr': '', 'rc': 0, 'runner': ''}
        opponent_log = {'stdout': '', 'stderr': '', 'rc': 0, 'runner': ''}

        player_input = ref.make_bot_input('player')
        opponent_input = ref.make_bot_input('opponent')

        try:
            width = getattr(ref, 'width')
            height = getattr(ref, 'height')
            rows = [''.join(ref.grid[y]) for y in range(height)]
            initial_map_block = f"{width} {height}\n" + '\n'.join(rows) + '\n'
        except Exception:
            initial_map_block = ''

        try:
            action_player, player_log = _run_bot_for_role(game, ref, 'player', player_input, initial_map_block, timeout_ms, memory_mb, cpus)
        except Exception as e:
            logging.getLogger(__name__).exception('error running player bot for game %s', game.get('id'))
            action_player, player_log = 'STAY', {'stdout': '', 'stderr': str(e), 'rc': -1, 'runner': 'exception'}
        actions['player'] = action_player or 'STAY'

        # Log which opponent will be used for this step so it's visible in console
        # try:
        #     # Use info level so the opponent name is visible in normal Flask logs
        #     logging.getLogger(__name__).info('game %s: opponent=%s', game_id, game.get('opponent'))
        # except Exception:
        #     pass

        try:
            action_opp, opponent_log = _run_bot_for_role(game, ref, 'opponent', opponent_input, initial_map_block, timeout_ms, memory_mb, cpus)
        except Exception as e:
            logging.getLogger(__name__).exception('error running opponent bot for game %s', game.get('id'))
            action_opp, opponent_log = 'STAY', {'stdout': '', 'stderr': str(e), 'rc': -1, 'runner': 'exception'}
        actions['opponent'] = action_opp or 'STAY'

        state, stdout, stderr = ref.step(actions)
        entry = ref.history[-1]
        entry['bot_logs'] = {'player': player_log, 'opponent': opponent_log}
        entry['__global_stdout'] = stdout
        entry['__global_stderr'] = stderr

        return jsonify({'state': state, 'history_entry': entry})

    except Exception as e:
        logging.getLogger(__name__).exception('Error in step_game for game_id=%s', game_id)
        return jsonify({'error': 'internal error', 'detail': str(e)}), 500


@app.route('/api/games/<game_id>/history')
def get_history(game_id):
    game = GAMES.get(game_id)
    if not game:
        game = restore_game_from_index(game_id)
    if not game:
        return jsonify({'error': 'not found'}), 404
    ref: Referee = game['ref']
    return jsonify({'history': ref.history})


@app.route('/api/runner/check')
def check_runner():
    try:
        proc = subprocess.run(['docker', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        if proc.returncode == 0:
            return jsonify({'available': True, 'version': proc.stdout.strip()})
        else:
            return jsonify({'available': False, 'error': proc.stderr.strip() or proc.stdout.strip()}), 500
    except FileNotFoundError:
        return jsonify({'available': False, 'error': 'docker not found'}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'available': False, 'error': 'docker timeout'}), 500


@app.route('/api/runner/verify', methods=['GET'])
def verify_runner_execution():
    test_code = """import sys
_ = sys.stdin.read()
print('PING')
"""
    timeout_ms = 2000
    old_flag = os.environ.get('DOCKER_RUNNER_PER_RUN_CHECKS')
    os.environ['DOCKER_RUNNER_PER_RUN_CHECKS'] = '1'
    try:
        runner = make_bot_runner()
        out, err, rc, runner_used = runner.run(test_code, "", timeout_ms=timeout_ms, memory_mb=64, cpus=0.5)
        debug = get_last_run_debug()
        return jsonify({'ok': True, 'runner_used': runner_used, 'stdout': out, 'stderr': err, 'rc': rc, 'debug': debug})
    except Exception as e:
        debug = get_last_run_debug()
        return jsonify({'ok': False, 'error': str(e), 'debug': debug}), 500
    finally:
        if old_flag is None:
            os.environ.pop('DOCKER_RUNNER_PER_RUN_CHECKS', None)
        else:
            os.environ['DOCKER_RUNNER_PER_RUN_CHECKS'] = old_flag


@app.route('/api/runner/logging', methods=['GET'])
def get_runner_logging():
    try:
        enabled = is_console_tracing_enabled()
        return jsonify({'enabled': bool(enabled)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/runner/logging', methods=['POST'])
def set_runner_logging():
    body = request.json or {}
    if 'enabled' not in body:
        return jsonify({'error': 'missing "enabled" boolean in request body'}), 400
    try:
        enabled = bool(body.get('enabled'))
        set_console_tracing(enabled)
        return jsonify({'enabled': is_console_tracing_enabled()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/runner/env', methods=['GET'])
def get_runner_env():
    import pkgutil
    import subprocess as _subp
    import sys as _sys
    import json as _json
    try:
        limit = int(request.args.get('limit', '200'))
        if limit < 0:
            limit = 0
    except Exception:
        limit = 200

    try:
        py_exec = _sys.executable
        py_version = _sys.version
        all_mods = sorted([m.name for m in pkgutil.iter_modules()])
        subprocess_info = {'executable': py_exec, 'version': py_version, 'modules_count': len(all_mods), 'modules_sample': all_mods[:limit]}
    except Exception as e:
        subprocess_info = {'error': str(e)}

    docker_image = os.environ.get('BOT_DOCKER_IMAGE', 'python:3.11-slim')
    docker_info = {'image': docker_image, 'available': False}

    try:
        check = _subp.run(['docker', '--version'], stdout=_subp.PIPE, stderr=_subp.PIPE, text=True, timeout=3)
        docker_info['available'] = (check.returncode == 0)
        docker_info['docker_version'] = (check.stdout or check.stderr or '').strip()
    except Exception as e:
        docker_info['available'] = False
        docker_info['error'] = str(e)

    if docker_info.get('available'):
        try:
            snippet = """import sys,pkgutil,json
mods = sorted([m.name for m in pkgutil.iter_modules()])
print(json.dumps({'version': sys.version, 'modules': mods}))
"""
            cmd = ['docker', 'run', '--rm', '--network', 'none', docker_image, 'python3', '-c', snippet]
            proc = _subp.run(cmd, stdout=_subp.PIPE, stderr=_subp.PIPE, text=True, timeout=30)
            if proc.returncode == 0:
                try:
                    payload = _json.loads(proc.stdout)
                    mods = payload.get('modules', []) or []
                    docker_info['python_version'] = payload.get('version')
                    docker_info['modules_count'] = len(mods)
                    docker_info['modules_sample'] = mods[:limit]
                except Exception as e:
                    docker_info['error'] = f'failed to parse docker output: {e}'; docker_info['raw_stdout'] = proc.stdout[:2000]
            else:
                docker_info['error'] = (proc.stderr or proc.stdout).strip()
        except Exception as e:
            docker_info['available'] = False
            docker_info['error'] = str(e)

    return jsonify({'subprocess': subprocess_info, 'docker': docker_info})


@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory('static', path)


@app.errorhandler(Exception)
def _handle_unexpected_error(e):
    logging.getLogger(__name__).exception('Unhandled exception in request')
    try:
        pathlib.Path(PERSISTENT_BOTS_DIR).mkdir(parents=True, exist_ok=True)
        err_path = os.path.join(PERSISTENT_BOTS_DIR, 'error.log')
        with open(err_path, 'a', encoding='utf-8') as ef:
            ef.write('\n==== Exception on request ====' + '\n')
            ef.write(traceback.format_exc())
            ef.write('\n')
    except Exception:
        logging.getLogger(__name__).exception('failed to write persistent error log')
    try:
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify({'error': str(e)}), e.code
    except Exception:
        pass
    return jsonify({'error': str(e)}), 500


# ==================== AUTHENTICATION ENDPOINTS ====================

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    """Register a new user."""
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    user_dict, error = register_user(username, email, password)
    if error:
        return jsonify({'error': error}), 400
    
    return jsonify({'user': user_dict, 'message': 'User registered successfully'}), 201


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    """Login and get JWT tokens."""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    result, error = login_user(username, password)
    if error:
        return jsonify({'error': error}), 401
    
    return jsonify(result), 200


@app.route('/api/auth/debug', methods=['GET'])
def api_debug_auth():
    """Debug endpoint to check authentication headers."""
    headers = dict(request.headers)
    auth_header = request.headers.get('Authorization', 'NOT_FOUND')
    return jsonify({
        'authorization_header': auth_header,
        'all_headers': headers
    }), 200


@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def api_get_current_user():
    """Get current user info from JWT token."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({'user': user.to_dict()}), 200


@app.route('/api/user/profile', methods=['GET'])
@jwt_required()
def api_get_user_profile():
    """Get current user's profile information."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({'user': user.to_dict()}), 200


@app.route('/api/user/avatar', methods=['GET'])
@jwt_required()
def api_get_user_avatar():
    """Get current user's avatar."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({'avatar': user.avatar or 'my_bot'}), 200


@app.route('/api/user/avatar', methods=['POST'])
@jwt_required()
def api_set_user_avatar():
    """Set current user's avatar."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    avatar = data.get('avatar')
    
    if not avatar:
        return jsonify({'error': 'Avatar is required'}), 400
    
    # Validate avatar (optional - list of allowed avatars)
    allowed_avatars = ['my_bot', 'boss', 'ninja', 'warrior', 'wizard', 'knight', 'archer', 'alien']
    if not avatar.startswith('custom_') and avatar not in allowed_avatars:
        return jsonify({'error': 'Invalid avatar'}), 400
    
    user.avatar = avatar
    db.session.commit()
    
    return jsonify({'success': True, 'avatar': user.avatar}), 200


@app.route('/api/user/avatar/upload', methods=['POST'])
@jwt_required()
def api_upload_avatar():
    """Upload a custom avatar image."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if file is present
    if 'avatar' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Validate file type
    if not file.content_type or not file.content_type.startswith('image/'):
        return jsonify({'error': 'File must be an image'}), 400
    
    # Get file extension
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
        return jsonify({'error': 'Invalid image format'}), 400
    
    # Create avatars directory if it doesn't exist
    avatars_dir = os.path.join(app.instance_path, 'avatars')
    os.makedirs(avatars_dir, exist_ok=True)
    
    # Save file with user ID as name
    avatar_filename = f'{user.id}{ext}'
    filepath = os.path.join(avatars_dir, avatar_filename)
    
    # Delete old custom avatar if exists
    for old_ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
        old_path = os.path.join(avatars_dir, f'{user.id}{old_ext}')
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception as e:
                app.logger.warning(f"Failed to delete old avatar: {e}")
    
    # Save new file
    try:
        file.save(filepath)
    except Exception as e:
        app.logger.error(f"Failed to save avatar: {e}")
        return jsonify({'error': 'Failed to save file'}), 500
    
    # Update user avatar reference
    avatar_id = f'custom_{user.id}'
    user.avatar = avatar_id
    db.session.commit()
    
    return jsonify({'success': True, 'avatar': avatar_id}), 200


@app.route('/api/user/avatar/image', methods=['GET'])
@jwt_required()
def api_get_avatar_image():
    """Serve custom avatar image for current user."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if user has custom avatar
    if not user.avatar or not user.avatar.startswith('custom_'):
        return jsonify({'error': 'No custom avatar'}), 404
    
    # Find the avatar file
    avatars_dir = os.path.join(app.instance_path, 'avatars')
    
    for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
        filepath = os.path.join(avatars_dir, f'{user.id}{ext}')
        if os.path.exists(filepath):
            # Determine mimetype
            mimetype = 'image/svg+xml' if ext == '.svg' else f'image/{ext[1:]}'
            return send_file(filepath, mimetype=mimetype)
    
    return jsonify({'error': 'Avatar file not found'}), 404


@app.route('/api/user/<int:user_id>/avatar/image', methods=['GET'])
@jwt_required()
def api_get_user_avatar_image(user_id):
    """Serve custom avatar image for a specific user (for displaying bot owner avatars)."""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if user has custom avatar
    if not user.avatar or not user.avatar.startswith('custom_'):
        return jsonify({'error': 'No custom avatar'}), 404
    
    # Find the avatar file
    avatars_dir = os.path.join(app.instance_path, 'avatars')
    
    for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
        filepath = os.path.join(avatars_dir, f'{user.id}{ext}')
        if os.path.exists(filepath):
            # Determine mimetype
            mimetype = 'image/svg+xml' if ext == '.svg' else f'image/{ext[1:]}'
            return send_file(filepath, mimetype=mimetype)
    
    return jsonify({'error': 'Avatar file not found'}), 404


# ==================== LEAGUE ENDPOINTS ====================

@app.route('/api/leagues', methods=['GET'])
def api_get_leagues():
    """Get all available leagues with their rules."""
    from leagues import League, LeagueRules
    
    leagues = []
    for league in [League.WOOD2, League.WOOD1, League.BRONZE, League.SILVER, League.GOLD]:
        rules = LeagueRules(league)
        leagues.append({
            'name': league.to_name(),
            'index': int(league),
            'rules': rules.to_dict()
        })
    
    return jsonify({'leagues': leagues}), 200


@app.route('/api/user/league', methods=['GET'])
@jwt_required()
def api_get_user_league():
    """Get current user's active bot league information with ranking."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Récupérer le bot actif de l'utilisateur
    user_bot = Bot.query.filter_by(user_id=user.id, is_active=True).first()
    
    if not user_bot:
        # Si aucun bot actif, retourner la ligue par défaut (Wood2)
        return jsonify({
            'current_league': 'Wood2',
            'league_id': 1,
            'elo': 0,  # New bots start at 0 league_elo
            'rank': 0,
            'total_bots': 0,
            'has_bot': False
        }), 200
    
    # Récupérer les informations de ligue basées sur l'ELO du bot
    league_info = LeagueManager.get_league_info(user_bot.elo_rating)
    
    # Calculer le ranking dans la ligue (utiliser la ligue déterminée par ELO)
    current_league = LeagueManager.get_league_from_elo(user_bot.elo_rating)
    ranking = get_league_ranking(user_bot.id, current_league.value)
    
    return jsonify({
        'current_league': league_info['current_league'],
        'league_id': current_league.value,  # Utiliser la ligue déterminée par ELO
        'elo': user_bot.league_elo,  # ELO local à la ligue
        'rank': ranking['rank'],
        'total_bots': ranking['total_bots'],
        'progress_percent': league_info.get('progress_percent', 0),  # Deprecated but kept for compatibility
        'has_bot': True,
        'bot_id': user_bot.id,
        'bot_name': user_bot.name
    }), 200


@app.route('/api/leaderboard', methods=['GET'])
@jwt_required(optional=True)
def api_get_leaderboard():
    """Get leaderboard with league information.
    
    NEW SYSTEM:
    - Global leaderboard: All bots (NO BOSS) sorted by league, then by league_elo
    - League leaderboard: Bots + Boss in specific league, sorted by league_elo
    
    Query params:
    - league: Filter by league name (wood2, wood1, bronze, silver, gold)
              If omitted, returns global leaderboard (all leagues, no Boss)
    - limit: Number of results per league (default 100)
    """
    league_filter = request.args.get('league', '').lower()
    limit = int(request.args.get('limit', 100))
    
    if league_filter:
        # ============================================================
        # CLASSEMENT PAR LIGUE: Bots + Boss de la ligue
        # ============================================================
        try:
            # Normaliser le nom de la ligue
            normalized = league_filter.replace(' ', '').lower()
            if normalized == 'wood':
                normalized = 'wood2'
            
            league = League.from_name(normalized)
            
            # Récupérer tous les bots actifs et déterminer leur ligue par ELO
            all_bots = Bot.query.filter_by(is_active=True).all()
            
            # Filtrer les bots de cette ligue (déterminée par leur ELO global ou ligue assignée pour les boss)
            league_bots = []
            for bot in all_bots:
                try:
                    # Pour les boss, utiliser leur ligue assignée directement
                    if bot.is_boss and bot.league is not None:
                        # bot.league peut être un nombre (index) ou un nom
                        if isinstance(bot.league, int):
                            bot_league = League(bot.league)
                        else:
                            bot_league = League.from_name(bot.league)
                    else:
                        bot_league = LeagueManager.get_league_from_elo(bot.elo_rating)
                    
                    if bot_league == league:
                        league_bots.append(bot)
                except (ValueError, AttributeError, TypeError):
                    # Ignorer les bots avec ligue invalide
                    continue
            
            # Trier par league_elo décroissant et limiter
            league_bots.sort(key=lambda b: b.league_elo, reverse=True)
            league_bots = league_bots[:limit]
            
            # Construire la liste des entrées avec rangs
            entries = []
            for rank, bot in enumerate(league_bots, start=1):
                owner = User.query.get(bot.user_id)
                # Utiliser la ligue filtrée (celle qui a été déterminée lors du filtrage)
                league_obj = league
                
                entries.append({
                    'rank': rank,
                    'bot_id': bot.id,
                    'bot_name': bot.name,
                    'username': owner.username if owner else 'Unknown',
                    'elo': bot.league_elo,  # ELO local à la ligue
                    'league': league_obj.to_name(),
                    'league_index': league_obj.value,
                    'avatar': owner.avatar if owner else 'my_bot',
                    'is_boss': bot.is_boss,
                    'matches': bot.match_count,
                    'wins': bot.win_count,
                    'win_rate': round((bot.win_count / bot.match_count * 100), 1) if bot.match_count > 0 else 0.0
                })
            
            return jsonify({
                'leaderboard': entries,
                'league': league.to_name(),
                'total': len(entries)
            }), 200
            
        except Exception as e:
            logging.getLogger(__name__).exception('Error getting league leaderboard')
            return jsonify({'error': 'Invalid league'}), 400
    
    else:
        # ============================================================
        # CLASSEMENT GLOBAL: Tous les bots (SANS Boss), groupés par ligue
        # ============================================================
        # Récupérer tous les bots actifs NON-BOSS
        bots = Bot.query.filter_by(
            is_active=True,
            is_boss=False  # EXCLURE les Boss du classement global
        ).all()
        
        # Grouper par ligue et trier
        entries_by_league = {}
        for league in League:
            entries_by_league[int(league)] = []
        
        for bot in bots:
            owner = User.query.get(bot.user_id)
            # Déterminer la ligue actuelle du bot par son ELO global
            league_obj = LeagueManager.get_league_from_elo(bot.elo_rating)
            
            entries_by_league[int(league_obj)].append({
                'bot_id': bot.id,
                'bot_name': bot.name,
                'username': owner.username if owner else 'Unknown',
                'elo': bot.league_elo,  # ELO local à la ligue
                'league': league_obj.to_name(),  # Utilise la ligue déterminée par ELO
                'league_index': league_obj.value,  # Utilise l'index de la ligue déterminée par ELO
                'avatar': owner.avatar if owner else 'my_bot',
                'is_boss': False,
                'matches': bot.match_count,
                'wins': bot.win_count,
                'win_rate': round((bot.win_count / bot.match_count * 100), 1) if bot.match_count > 0 else 0.0
            })
        
        # Trier chaque ligue par league_elo décroissant
        for league_id in entries_by_league:
            entries_by_league[league_id].sort(key=lambda x: x['elo'], reverse=True)
        
        # Construire la liste finale : Gold -> Silver -> Bronze -> Wood1 -> Wood2
        all_entries = []
        for league in reversed(list(League)):  # Du plus haut (Gold) au plus bas (Wood2)
            league_entries = entries_by_league[int(league)][:limit]  # Limiter par ligue
            all_entries.extend(league_entries)
        
        # Ajouter les rangs (global, tous les bots confondus)
        leaderboard = []
        for rank, entry in enumerate(all_entries, 1):
            entry['rank'] = rank
            leaderboard.append(entry)
        
        return jsonify({
            'leaderboard': leaderboard,
            'total': len(leaderboard)
        }), 200


# ==================== BOT/ARENA ENDPOINTS ====================

@app.route('/api/bots', methods=['GET'])
@jwt_required(optional=True)
def api_get_bots():
    """Get bots - if authenticated, return user's bots; if 'all' param, return all active bots.
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        # Check if requesting all bots (for opponent selection)
        get_all = request.args.get('all', 'false').lower() == 'true'
        
        if get_all:
            # Return all active bots from all users for opponent selection
            bots = bot_service.get_all_active_bots()
            return jsonify({'bots': bots}), 200
        
        # Return user's own bots (requires authentication)
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        
        bots = bot_service.get_user_bots(user.id, include_inactive=False)
        return jsonify({'bots': bots}), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get bots')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/my', methods=['GET'])
@jwt_required()
def api_get_my_bots():
    """Get all bots owned by current user (including drafts and inactive).
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Return ALL user bots (including inactive ones for Playground)
        bots = bot_service.get_user_bots(user.id, include_inactive=True)
        return jsonify(bots), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get user bots')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/by-league', methods=['GET'])
@jwt_required()
def api_get_bots_by_league():
    """Get bots filtered by user's current league + Boss of that league.
    
    Returns bots from:
    - Same league as current user
    - Boss of current league (for challenges)
    
    Response:
    {
        "bots": [...],  # Bots de la ligue
        "boss": {...},  # Boss de la ligue (si existe)
        "user_league": "Bronze",
        "user_elo": 1274
    }
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Récupérer le bot actif de l'utilisateur pour déterminer sa ligue
        user_bot = Bot.query.filter_by(
            user_id=user.id,
            is_active=True
        ).order_by(Bot.elo_rating.desc()).first()
        
        if not user_bot:
            return jsonify({'error': 'Vous devez avoir un bot actif'}), 400
        
        # Déterminer la ligue de l'utilisateur par son ELO le plus élevé
        user_league = LeagueManager.get_league_from_elo(user_bot.elo_rating)
        league_info = LeagueManager.get_league_info(user_bot.elo_rating)
        
        # Récupérer le Boss de la ligue d'abord
        boss = BossSystem.get_boss_for_league(user_league)
        
        # Récupérer tous les IDs des Boss pour les exclure de la liste des bots
        all_boss_ids = set()
        for league in League:
            league_boss = BossSystem.get_boss_for_league(league)
            if league_boss:
                all_boss_ids.add(league_boss.id)
        
        # Récupérer tous les bots actifs
        all_bots = Bot.query.filter_by(is_active=True).all()
        
        # Filtrer par ligue (en excluant TOUS les Boss qui seront gérés séparément)
        league_bots = []
        for bot in all_bots:
            # Sauter tous les Boss, seul le Boss de la ligue courante sera retourné dans boss_data
            if bot.id in all_boss_ids:
                continue
                
            # Filtrer par league du bot (déterminée par son ELO global)
            bot_league = LeagueManager.get_league_from_elo(bot.elo_rating)
            if bot_league == user_league:
                owner = User.query.get(bot.user_id)
                league_bots.append({
                    'id': bot.id,
                    'name': bot.name,
                    'user_id': bot.user_id,
                    'owner_username': owner.username if owner else 'Unknown',
                    'owner_avatar': owner.avatar if owner else 'my_bot',
                    'elo_rating': bot.league_elo,  # Utiliser league_elo pour cohérence
                    'league': bot_league.value,  # Utiliser la ligue déterminée par ELO
                    'match_count': bot.match_count,
                    'win_count': bot.win_count,
                    'avatar': owner.avatar if owner else 'my_bot',
                    'is_boss': False
                })
        
        # Construire les données du Boss avec avatar spécifique à la ligue
        boss_data = None
        if boss:
            boss_owner = User.query.get(boss.user_id)
            # Avatar du Boss selon la ligue
            boss_avatar_map = {
                League.WOOD2: 'wood2_boss',
                League.WOOD1: 'wood1_boss',
                League.BRONZE: 'bronze_boss',
                League.SILVER: 'silver_boss',
                League.GOLD: 'gold_boss'
            }
            boss_avatar = boss_avatar_map.get(user_league, 'boss')
            
            boss_data = {
                'id': boss.id,
                'name': boss.name,
                'user_id': boss.user_id,
                'owner_username': boss_owner.username if boss_owner else 'System',
                'owner_avatar': boss_avatar,
                'elo_rating': boss.league_elo,  # Utiliser league_elo
                'league': LeagueManager.get_league_from_elo(boss.elo_rating).value,  # Utiliser ligue déterminée par ELO
                'match_count': boss.match_count,
                'win_count': boss.win_count,
                'avatar': boss_avatar,
                'is_boss': True
            }
        
        return jsonify({
            'bots': league_bots,
            'boss': boss_data,
            'user_league': league_info['current_league'],
            'user_league_index': user_league.value,
            'user_elo': user_bot.elo_rating
        }), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get bots by league')
        return jsonify({'error': str(e)}), 500


@app.route('/api/bots', methods=['POST'])
@jwt_required()
def api_create_bot():
    """Create a new bot (Playground).
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        name = data.get('name')
        code = data.get('code', '')
        
        # Délégation au service avec validation intégrée
        bot_dict = bot_service.create_bot(
            user_id=user.id,
            name=name,
            code=code
        )
        
        return jsonify({'bot': bot_dict, 'message': 'Bot created successfully'}), 201
        
    except ValueError as e:
        # Erreur de validation
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to create bot')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/<int:bot_id>/save', methods=['PUT'])
@jwt_required()
def api_save_bot_code(bot_id):
    """Save bot code (Playground only - does NOT create version).
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        code = data.get('code')
        
        if code is None:  # Permet code vide mais pas None
            return jsonify({'error': 'Code is required'}), 400
        
        # Délégation au service avec vérification propriété
        bot_dict = bot_service.save_bot_code(
            bot_id=bot_id,
            code=code,
            user_id=user.id
        )
        
        return jsonify({'bot': bot_dict, 'message': 'Bot code saved'}), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to save bot code')
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# HELPER: League Ranking
# ============================================================

def get_league_ranking(bot_id, league_level):
    """Calculate bot's rank within its league.
    
    Args:
        bot_id: ID of the bot to rank
        league_level: League index (1-5)
    
    Returns:
        dict: {
            'rank': int,          # Bot's position (1=best)
            'total_bots': int,    # Total bots in league
            'league_elo': int     # Bot's ELO in this league
        }
    """
    # Récupérer tous les bots actifs et les grouper par ligue déterminée par ELO
    all_active_bots = Bot.query.filter_by(is_active=True).all()
    
    # Filtrer les bots de la ligue spécifiée
    bots_in_league = []
    target_league = League.from_index(league_level)
    
    for bot in all_active_bots:
        bot_league = LeagueManager.get_league_from_elo(bot.elo_rating)
        if bot_league == target_league:
            bots_in_league.append(bot)
    
    # Trier par league_elo décroissant
    bots_in_league.sort(key=lambda b: b.league_elo, reverse=True)
    
    total_bots = len(bots_in_league)
    rank = 0
    bot_league_elo = 0
    
    # Trouver le rang du bot
    for i, bot in enumerate(bots_in_league, start=1):
        if bot.id == bot_id:
            rank = i
            bot_league_elo = bot.league_elo
            break
    
    return {
        'rank': rank,
        'total_bots': total_bots,
        'league_elo': bot_league_elo
    }


def _execute_arena_match(game_id, player_bot_id, opponent_bot_id, is_placement_match=False):
    """Execute a complete arena match and update ELO ratings.
    
    Args:
        game_id: Unique game ID
        player_bot_id: ID of the first bot
        opponent_bot_id: ID of the second bot
        is_placement_match: If True, skip league update (will be done at the end of placement)
    
    Returns:
        dict: Match result with winner, scores, and turns
    """
    try:
        # Create game entry
        maker = REFEREES.get('pacman')
        if not maker:
            return {'error': 'Referee not found'}
        
        ref = maker()
        ref.init_game({})
        
        # Get initial map from referee (use referee attributes directly)
        width = getattr(ref, 'width', 0)
        height = getattr(ref, 'height', 0)
        # Generate simple map rows (grid is initialized by init_game)
        grid = getattr(ref, 'grid', [])
        if grid and width > 0 and height > 0:
            rows = [''.join(row) for row in grid]
            initial_map_block = f"{width} {height}\n" + '\n'.join(rows) + '\n'
        else:
            initial_map_block = ''
        
        game_entry = {
            'id': game_id,
            'ref': ref,
            'player_bot_id': player_bot_id,
            'opponent': str(opponent_bot_id),
            'is_arena_match': True,  # Use Arena versions
            'is_placement_match': is_placement_match,  # Flag for skipping league update
            'bot_runner': 'auto',
            'initial_map_block': initial_map_block,
            'history': ref.history
        }
        
        GAMES[game_id] = game_entry
        
        # Run game until completion
        max_turns = 200
        turn_count = 0
        
        while not ref.is_finished() and turn_count < max_turns:
            try:
                # Execute one turn
                _execute_game_turn(game_entry, ref)
                turn_count += 1
            except Exception as e:
                logging.getLogger(__name__).exception(f"Error in arena match turn {turn_count}")
                break
        
        # Determine winner
        state = ref.get_state()
        scores = state.get('scores', {})
        player_score = scores.get('player', 0)
        opponent_score = scores.get('opponent', 0)
        
        if player_score > opponent_score:
            winner = 'player'
        elif opponent_score > player_score:
            winner = 'opponent'
        else:
            winner = 'draw'
        
        # Update match in database
        match = Match.query.filter_by(game_id=game_id).first()
        if match:
            # Skip league update during placement matches - will be done at the end
            is_placement = game_entry.get('is_placement_match', False)
            arena_manager.complete_match(
                match.id,
                winner=winner,
                player_score=player_score,
                opponent_score=opponent_score,
                turns=turn_count,
                skip_league_update=is_placement
            )
        
        return {
            'winner': winner,
            'player_score': player_score,
            'opponent_score': opponent_score,
            'turns': turn_count
        }
    except Exception as e:
        logging.getLogger(__name__).exception(f"Error executing arena match {game_id}")
        return {'error': str(e)}


def _execute_game_turn(game_entry, ref):
    """Execute a single turn of the game (extracted from step_game endpoint)."""
    timeout_ms = ref.get_protocol().get('constraints', {}).get('time_ms', 50)
    memory_mb = ref.get_protocol().get('constraints', {}).get('memory_mb', 64)
    cpus = ref.get_protocol().get('constraints', {}).get('cpus', 0.5)
    
    initial_map_block = game_entry.get('initial_map_block') or ''
    
    # Log turn number and state before actions
    state_before = ref.get_state()
    turn_num = state_before.get('turn', 0)
    scores_before = state_before.get('scores', {})
    pellets_before = state_before.get('pellets', [])
    # logging.getLogger(__name__).info(f"Turn {turn_num}: scores={scores_before}, pellets_count={len(pellets_before)}")
    
    # Run player bot
    player_input = ref.make_bot_input('player')
    player_action, player_meta = _run_bot_for_role(
        game_entry, ref, 'player', player_input, initial_map_block,
        timeout_ms, memory_mb, cpus
    )
    
    # Run opponent bot  
    opp_input = ref.make_bot_input('opponent')
    opp_action, opp_meta = _run_bot_for_role(
        game_entry, ref, 'opponent', opp_input, initial_map_block,
        timeout_ms, memory_mb, cpus
    )
    
    # Log actions received
    #logging.getLogger(__name__).info(f"Turn {turn_num}: player_action='{player_action}', opponent_action='{opp_action}'")
    
    # Apply actions (step expects a dict)
    actions_by_bot = {
        'player': player_action,
        'opponent': opp_action
    }
    ref.step(actions_by_bot)
    
    # Log state after step
    state_after = ref.get_state()
    scores_after = state_after.get('scores', {})
    pellets_after = state_after.get('pellets', [])
    # logging.getLogger(__name__).info(f"Turn {turn_num}: after step: scores={scores_after}, pellets_count={len(pellets_after)}")


@app.route('/api/bots/<int:bot_id>/submit-to-arena', methods=['POST'])
@jwt_required()
def api_submit_bot_to_arena(bot_id):
    """Submit bot to Arena (creates BotVersion) and run placement matches.
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    
    TODO (dette technique): La logique des placement matches devrait être
    dans un MatchService (SRP violation). Pour l'instant, conservée ici.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json() or {}
        version_name = data.get('version_name')
        description = data.get('description', '')
        
        # Délégation création version au service
        version_info = bot_service.submit_to_arena(
            bot_id, 
            version_name=version_name, 
            description=description,
            user_id=user.id
        )
        
        # Placement matches progressifs: commencer par les plus faibles, monter graduellement
        import random
        
        # Déterminer la ligue du joueur basée sur son ELO actuel
        player_bot = Bot.query.get(bot_id)
        if not player_bot:
            return jsonify({'error': 'Bot not found'}), 404
        
        player_league = LeagueManager.get_league_from_elo(player_bot.elo_rating)
        
        # Récupérer tous les adversaires de la même ligue, triés par ELO croissant
        # INCLURE LE BOSS dans la liste des adversaires pour qu'il apparaisse dans son palier
        # Filtrer dynamiquement par ligue déterminée par ELO
        all_active_bots = Bot.query.filter(
            Bot.id != bot_id,
            Bot.is_active == True,
            db.or_(
                Bot.latest_version_number > 0,  # Bots normaux avec version
                Bot.is_boss == True  # Boss (même sans version)
            )
        ).all()
        
        # Filtrer les bots de la même ligue
        league_opponents = []
        for bot in all_active_bots:
            bot_league = LeagueManager.get_league_from_elo(bot.elo_rating)
            if bot_league == player_league:
                league_opponents.append(bot)
        
        # Trier par elo_rating croissant
        league_opponents.sort(key=lambda b: b.elo_rating)
        
        # Le Boss sera dans league_opponents, triés par league_elo avec les autres
        boss = BossSystem.get_boss_for_league(player_league)  # Pour logging
        
        # NOUVEAU SYSTÈME: Reset league_elo à 0 pour chaque nouvelle soumission
        # Le bot commence toujours avec league_elo=0 dans sa ligue actuelle
        player_bot.league_elo = 0
        db.session.commit()
        logging.getLogger(__name__).info(
            f"Bot {player_bot.name} starting fresh in {player_league.to_name()} with league_elo=0"
        )
        
        # ============================================================
        # SYSTÈME DE PLACEMENT SIMPLIFIÉ
        # ============================================================
        # Phase 1: Préparation (25 matchs contre bots normaux)
        # Phase 2: Challenge Boss (continue tant que ratio > 50%)
        # Doc: SIMPLIFIED_PLACEMENT.md
        # ============================================================
        
        PREPARATION_MATCHES = 25        # Phase préparation contre bots normaux
        MAX_BOSS_ATTEMPTS = 100         # Max absolu pour éviter boucle infinie
        MIN_BOSS_FIGHTS_CHECK = 10      # Vérifier ratio après 10 combats minimum
        MIN_WIN_RATE = 0.5              # 50% minimum pour continuer
        
        placement_results = []
        total_matches_played = 0
        boss_wins = 0
        boss_attempts = 0
        
        # ============================================================
        # PHASE 1: PRÉPARATION (25 matchs contre bots normaux)
        # ============================================================
        
        if league_opponents:
            # Séparer Boss et bots normaux
            normal_bots = [b for b in league_opponents if not b.is_boss]
            boss_bot = next((b for b in league_opponents if b.is_boss), None)
            
            logging.getLogger(__name__).info(
                f"🎯 Starting simplified placement: {len(normal_bots)} normal bots, "
                f"Boss: {boss_bot.name if boss_bot else 'None'} (ELO {boss_bot.elo_rating if boss_bot else 'N/A'})"
            )
            
            # Phase 1: Combattre des bots normaux pour gagner de l'ELO
            if normal_bots:
                logging.getLogger(__name__).info(
                    f"📚 PHASE 1: Preparation ({PREPARATION_MATCHES} matches against normal bots)"
                )
                
                for match_num in range(1, PREPARATION_MATCHES + 1):
                    # Sélection aléatoire parmi les bots normaux
                    opponent = random.choice(normal_bots)
                    
                    try:
                        game_id = str(uuid.uuid4())
                        match = arena_manager.create_match(bot_id, opponent.id, game_id)
                        if not match:
                            continue
                        
                        # Exécuter le match (avec skip_league_update pendant placement)
                        result = _execute_arena_match(game_id, bot_id, opponent.id, is_placement_match=True)
                        
                        # Recharger le bot pour avoir l'ELO à jour
                        db.session.refresh(player_bot)
                        
                        placement_results.append({
                            'opponent': opponent.name,
                            'opponent_elo': opponent.elo_rating,
                            'result': result.get('winner') if result else 'error',
                            'new_elo': player_bot.league_elo,  # Use league_elo
                            'phase': 'preparation',
                            'is_boss': False,
                            'match_number': match_num
                        })
                        
                        total_matches_played += 1
                        
                        logging.getLogger(__name__).info(
                            f"  Match {match_num}/{PREPARATION_MATCHES} vs {opponent.name} (League ELO {opponent.league_elo}): "
                            f"{result.get('winner')} → Bot League ELO now {player_bot.league_elo}"
                        )
                        
                    except Exception as e:
                        logging.getLogger(__name__).exception(f"Error in preparation match vs {opponent.name}")
                
                logging.getLogger(__name__).info(
                    f"✅ PHASE 1 Complete: Bot League ELO now {player_bot.league_elo} (after {PREPARATION_MATCHES} matches)"
                )
            
            # ============================================================
            # PHASE 2: CHALLENGE BOSS (continue tant que ratio > 50%)
            # ============================================================
            # Règles:
            # 1. Promotion si: League ELO bot > League ELO Boss ET victoire contre Boss
            # 2. Continue tant que: League ELO bot <= League ELO Boss OU ratio >= 50%
            # 3. Arrêt si: Après 10 combats minimum, ratio V/D < 50%
            # ============================================================
            
            if boss_bot:
                boss_losses = 0
                
                logging.getLogger(__name__).info(
                    f"👑 PHASE 2: Boss Challenge (continue while ratio > 50%)"
                )
                logging.getLogger(__name__).info(
                    f"  Boss: {boss_bot.name} (League ELO {boss_bot.league_elo})"
                )
                logging.getLogger(__name__).info(
                    f"  Rule 1: Promotion if Bot League ELO > Boss League ELO AND win against Boss"
                )
                logging.getLogger(__name__).info(
                    f"  Rule 2: Continue while Bot League ELO <= Boss League ELO OR win rate >= {MIN_WIN_RATE*100}%"
                )
                logging.getLogger(__name__).info(
                    f"  Rule 3: Stop if after {MIN_BOSS_FIGHTS_CHECK} fights, win rate < {MIN_WIN_RATE*100}%"
                )
                
                while boss_attempts < MAX_BOSS_ATTEMPTS:
                    try:
                        boss_attempts += 1
                        
                        game_id = str(uuid.uuid4())
                        match = arena_manager.create_match(bot_id, boss_bot.id, game_id)
                        if not match:
                            continue
                        
                        # Exécuter le match contre le Boss
                        result = _execute_arena_match(game_id, bot_id, boss_bot.id, is_placement_match=True)
                        
                        # Recharger le bot
                        db.session.refresh(player_bot)
                        
                        # Vérifier victoire
                        player_won = result.get('winner') == 'player' if result else False
                        if player_won:
                            boss_wins += 1
                        else:
                            boss_losses += 1
                        
                        # Calculer ratio V/D
                        win_rate = boss_wins / boss_attempts if boss_attempts > 0 else 0
                        
                        placement_results.append({
                            'opponent': boss_bot.name,
                            'opponent_elo': boss_bot.league_elo,  # Use league_elo
                            'result': result.get('winner') if result else 'error',
                            'new_elo': player_bot.league_elo,  # Use league_elo
                            'phase': 'boss_challenge',
                            'is_boss': True,
                            'match_number': boss_attempts,
                            'boss_wins': boss_wins,
                            'boss_losses': boss_losses,
                            'win_rate': win_rate
                        })
                        
                        total_matches_played += 1
                        
                        # Logs détaillés
                        if player_won:
                            logging.getLogger(__name__).info(
                                f"  🎉 Match {boss_attempts}: WIN! Bot League ELO {player_bot.league_elo} vs Boss {boss_bot.league_elo} "
                                f"(W/L: {boss_wins}/{boss_losses}, ratio: {win_rate*100:.1f}%)"
                            )
                        else:
                            logging.getLogger(__name__).info(
                                f"  ❌ Match {boss_attempts}: LOSE. Bot League ELO {player_bot.league_elo} vs Boss {boss_bot.league_elo} "
                                f"(W/L: {boss_wins}/{boss_losses}, ratio: {win_rate*100:.1f}%)"
                            )
                        
                        # ============================================================
                        # VÉRIFICATION DES CONDITIONS DE PROMOTION OU ARRÊT
                        # ============================================================
                        
                        # Condition 1: League ELO > Boss ET victoire → PROMOTION!
                        if player_bot.league_elo > boss_bot.league_elo and player_won:
                            logging.getLogger(__name__).info(
                                f"✅ PROMOTION CRITERIA MET!"
                            )
                            logging.getLogger(__name__).info(
                                f"   - Bot League ELO {player_bot.league_elo} > Boss League ELO {boss_bot.league_elo} ✓"
                            )
                            logging.getLogger(__name__).info(
                                f"   - Victory against Boss ✓"
                            )
                            break
                        
                        # Condition 2: League ELO > Boss mais défaite → Continue
                        if player_bot.league_elo > boss_bot.league_elo and not player_won:
                            logging.getLogger(__name__).info(
                                f"⚠️ Bot League ELO > Boss but lost. Need victory for promotion. Continuing..."
                            )
                            continue
                        
                        # Condition 3: League ELO <= Boss → Continue tant que ratio bon
                        if player_bot.league_elo <= boss_bot.league_elo:
                            logging.getLogger(__name__).info(
                                f"📈 Bot League ELO {player_bot.league_elo} <= Boss {boss_bot.league_elo}. Training continues..."
                            )
                            
                            # Vérification ratio après MIN_BOSS_FIGHTS_CHECK combats
                            if boss_attempts >= MIN_BOSS_FIGHTS_CHECK:
                                if win_rate < MIN_WIN_RATE:
                                    logging.getLogger(__name__).info(
                                        f"🛑 STOP: After {boss_attempts} fights, win rate {win_rate*100:.1f}% < {MIN_WIN_RATE*100}%"
                                    )
                                    logging.getLogger(__name__).info(
                                        f"   Bot too weak against Boss. Need more training!"
                                    )
                                    break
                                else:
                                    logging.getLogger(__name__).info(
                                        f"✓ Win rate {win_rate*100:.1f}% >= {MIN_WIN_RATE*100}%. Continuing training..."
                                    )
                                    # IMPORTANT: Continue même après MIN_BOSS_FIGHTS_CHECK si ratio bon!
                                    # Pas de break ici - on continue la boucle
                        
                    except Exception as e:
                        logging.getLogger(__name__).exception(f"Error in Boss challenge attempt {boss_attempts}")
                
                # Résumé Boss challenge
                final_win_rate = boss_wins / boss_attempts if boss_attempts > 0 else 0
                elo_surpassed = player_bot.league_elo > boss_bot.league_elo
                
                logging.getLogger(__name__).info(
                    f"\n🏆 PHASE 2 Complete:"
                )
                logging.getLogger(__name__).info(
                    f"  - Total fights: {boss_attempts}"
                )
                logging.getLogger(__name__).info(
                    f"  - Record: {boss_wins}W - {boss_losses}L (win rate: {final_win_rate*100:.1f}%)"
                )
                logging.getLogger(__name__).info(
                    f"  - Bot League ELO: {player_bot.league_elo} vs Boss: {boss_bot.league_elo} "
                    f"({'✓ SURPASSED' if elo_surpassed else '✗ BELOW'})"
                )
        
        # ============================================================
        # PHASE 3: PROMOTION (double condition)
        # ============================================================
        # Promotion si:
        #   1. Bot League ELO > Boss League ELO (dépassement du gardien)
        #   2. ET victoire contre Boss (preuve de compétence)
        # ============================================================
        
        # Résumé des résultats
        db.session.refresh(player_bot)
        total_matches = len(placement_results)
        wins = sum(1 for r in placement_results if r['result'] == 'player')
        losses = sum(1 for r in placement_results if r['result'] == 'opponent')
        
        # Récupérer le Boss de la ligue actuelle
        boss_in_league = BossSystem.get_boss_for_league(League.from_index(player_bot.league))
        
        promoted = False
        old_league = League.from_index(player_bot.league)
        new_league = old_league
        
        # Vérifier les conditions de promotion
        elo_condition = False
        win_condition = False
        
        if boss_in_league:
            elo_condition = player_bot.league_elo > boss_in_league.league_elo  # Use league_elo
            # Vérifier si la DERNIÈRE victoire était contre le Boss ET que League ELO > Boss à ce moment
            boss_results = [r for r in placement_results if r.get('is_boss')]
            if boss_results:
                last_boss_result = boss_results[-1]
                # Promotion si dernière tentative = victoire ET League ELO > Boss
                win_condition = (last_boss_result.get('result') == 'player' and 
                                last_boss_result.get('new_elo', 0) > boss_in_league.league_elo)
        
        if not player_bot.is_boss:
            if elo_condition and win_condition:
                # PROMOTION! Les deux conditions sont remplies
                new_league_value = min(player_bot.league + 1, int(League.GOLD))  # Cap à Gold
                if new_league_value > player_bot.league:
                    player_bot.league = new_league_value
                    new_league = League.from_index(new_league_value)
                    
                    # RESET league_elo à 0 pour la nouvelle ligue
                    player_bot.league_elo = 0
                    db.session.commit()
                    promoted = True
                    
                    logging.getLogger(__name__).info(
                        f"\n🎉 PROMOTION! Bot {player_bot.name}: {old_league.to_name()} → {new_league.to_name()}"
                    )
                    logging.getLogger(__name__).info(
                        f"   ✓ Bot League ELO {player_bot.league_elo} (reset to 0 in new league)"
                    )
                    logging.getLogger(__name__).info(
                        f"   ✓ Victory against Boss achieved"
                    )
                else:
                    logging.getLogger(__name__).info(
                        f"✅ Bot {player_bot.name} remains in {old_league.to_name()} (already at maximum league)"
                    )
            else:
                # Conditions non remplies
                logging.getLogger(__name__).info(
                    f"\n❌ No promotion: Criteria not met"
                )
                if not elo_condition:
                    logging.getLogger(__name__).info(
                        f"   ✗ Bot League ELO {player_bot.league_elo} <= Boss League ELO {boss_in_league.league_elo if boss_in_league else 'N/A'}"
                    )
                else:
                    logging.getLogger(__name__).info(
                        f"   ✓ Bot League ELO {player_bot.league_elo} > Boss League ELO {boss_in_league.league_elo if boss_in_league else 'N/A'}"
                    )
                
                if not win_condition:
                    logging.getLogger(__name__).info(
                        f"   ✗ No victory against Boss (or ELO not high enough at time of win)"
                    )
                else:
                    logging.getLogger(__name__).info(
                        f"   ✓ Victory against Boss achieved"
                    )
                
                logging.getLogger(__name__).info(
                    f"💪 Keep training: Improve ELO or defeat Boss!"
                )
        
        # Vérifier l'ELO floor (pour information seulement)
        elo_floor = BossSystem.get_elo_floor_for_league(player_bot.league)
        
        # Boss de la ligue actuelle (après promotion si applicable)
        current_boss = BossSystem.get_boss_for_league(League.from_index(player_bot.league))
        
        return jsonify({
            'version': version_info,
            'message': f"Bot submitted to Arena as version {version_info['version_name']}. Simplified placement completed.",
            'placement_summary': {
                'total_matches': total_matches,
                'preparation_matches': PREPARATION_MATCHES,
                'boss_attempts': boss_attempts,
                'boss_wins': boss_wins,
                'wins': wins,
                'losses': losses,
                'win_rate': round((wins / total_matches * 100), 1) if total_matches > 0 else 0,
                'starting_elo': league_opponents[0].elo_rating if league_opponents else player_bot.elo_rating,
                'final_elo': player_bot.elo_rating,
                'old_league': old_league.to_name(),
                'final_league': new_league.to_name(),
                'promoted': promoted,
                'elo_gain': player_bot.elo_rating - (league_opponents[0].elo_rating if league_opponents else player_bot.elo_rating),
                'elo_floor': elo_floor,
                'beat_boss': promoted,  # Promotion = double condition remplie
                'boss_name': current_boss.name if current_boss else None,
                'boss_elo': current_boss.elo_rating if current_boss else None
            },
            'results': placement_results
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        return jsonify({'error': 'Unauthorized'}), 403
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to submit bot to arena')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/<int:bot_id>', methods=['GET'])
@jwt_required()
def api_get_bot(bot_id):
    """Get a specific bot.
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Délégation au service - vérifie propriété pour inclure code
        bot_info = bot_service.get_bot_info(bot_id)
        
        if not bot_info:
            return jsonify({'error': 'Bot not found'}), 404
        
        # Masquer le code si l'utilisateur n'est pas propriétaire
        if bot_info['user_id'] != user.id:
            bot_info.pop('code', None)
        
        return jsonify({'bot': bot_info}), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get bot')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/<int:bot_id>/deactivate', methods=['POST'])
@jwt_required()
def api_deactivate_bot(bot_id):
    """Deactivate a bot.
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Délégation au service
        bot_info = bot_service.deactivate_bot(bot_id, user_id=user.id)
        
        return jsonify({
            'bot': bot_info, 
            'message': 'Bot deactivated'
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except PermissionError as e:
        return jsonify({'error': 'Unauthorized'}), 403
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to deactivate bot')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/<int:bot_id>/versions', methods=['GET'])
@jwt_required()
def api_get_bot_versions(bot_id):
    """Get all versions of a bot.
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Délégation au service avec vérification propriété
        versions = bot_service.get_bot_versions(bot_id, user_id=user.id)
        
        return jsonify({'versions': versions}), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except PermissionError as e:
        return jsonify({'error': 'Unauthorized'}), 403
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get bot versions')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/<int:bot_id>/versions/<int:version_number>', methods=['GET'])
@jwt_required()
def api_get_bot_version(bot_id, version_number):
    """Get a specific version of a bot.
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Délégation au service
        code = bot_service.get_bot_version_code(bot_id, version_number, user_id=user.id)
        
        return jsonify({
            'version': {
                'bot_id': bot_id,
                'version_number': version_number,
                'code': code
            }
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except PermissionError as e:
        return jsonify({'error': 'Unauthorized'}), 403
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get bot version')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/<int:bot_id>/rollback/<int:version_number>', methods=['POST'])
@jwt_required()
def api_rollback_bot_version(bot_id, version_number):
    """Rollback bot to a specific version.
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Délégation au service
        result = bot_service.rollback_to_version(bot_id, version_number, user_id=user.id)
        
        return jsonify({
            'message': f'Rolled back to version {version_number}',
            'version': result
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except PermissionError as e:
        return jsonify({'error': 'Unauthorized'}), 403
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to rollback bot')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/bots/<int:bot_id>/load-version/<int:version_number>', methods=['POST'])
@jwt_required()
def api_load_bot_version_to_playground(bot_id, version_number):
    """Load a specific version into Playground (updates bot.code without creating new version).
    
    API Layer: Validation et délégation au BotService (SOLID refactored).
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Délégation au service
        result = bot_service.load_version_to_draft(bot_id, version_number, user_id=user.id)
        
        return jsonify({
            'bot': result,
            'message': f'Version {version_number} loaded into Playground'
        }), 200
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except PermissionError as e:
        return jsonify({'error': 'Unauthorized'}), 403
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to load bot version')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/arena/challenge', methods=['POST'])
@jwt_required()
def api_challenge_bot():
    """Challenge another bot to a match."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    data = request.get_json()
    my_bot_id = data.get('my_bot_id')
    opponent_bot_id = data.get('opponent_bot_id')
    
    if not my_bot_id:
        return jsonify({'error': 'my_bot_id is required'}), 400
    
    # Get bots
    my_bot = Bot.query.get(my_bot_id)
    if not my_bot or my_bot.user_id != user.id:
        return jsonify({'error': 'Bot not found or you don\'t own it'}), 403
    
    # Find opponent if not specified
    if not opponent_bot_id:
        opponent_bot = arena_manager.find_opponent(my_bot_id)
        if not opponent_bot:
            return jsonify({'error': 'No suitable opponent found'}), 404
        opponent_bot_id = opponent_bot.id
    else:
        opponent_bot = Bot.query.get(opponent_bot_id)
        if not opponent_bot:
            return jsonify({'error': 'Opponent bot not found'}), 404
    
    # Create game using existing game creation logic
    game_id = str(uuid.uuid4())
    referee = PacmanRefereeV2()
    referee.init_game({})
    
    game_entry = {
        'game_id': game_id,
        'referee': 'pacman',
        'referee_obj': referee,
        'player_code': my_bot.code,
        'opponent_code': opponent_bot.code,
        'player_bot_id': my_bot_id,
        'opponent_bot_id': opponent_bot_id,
        'is_arena_match': True
    }
    GAMES[game_id] = game_entry
    
    # Create match record
    match = arena_manager.create_match(my_bot_id, opponent_bot_id, game_id)
    if not match:
        return jsonify({'error': 'Failed to create match'}), 500
    
    save_games_index_entry(game_id, {
        'referee': 'pacman',
        'player_bot_id': my_bot_id,
        'opponent_bot_id': opponent_bot_id,
        'match_id': match.id
    })
    
    return jsonify({
        'game_id': game_id,
        'match_id': match.id,
        'message': 'Match created successfully'
    }), 201


@app.route('/api/arena/leaderboard', methods=['GET'])
def api_get_arena_leaderboard():
    """Get the arena leaderboard (legacy endpoint, redirects to new leaderboard).
    
    This endpoint is kept for backward compatibility and redirects to /api/leaderboard
    which uses the bot-level league system.
    """
    # Rediriger vers le nouvel endpoint leaderboard
    from flask import redirect, request
    
    # Copier les query params
    league = request.args.get('league', '')
    limit = request.args.get('limit', '100')
    
    # Construire l'URL de redirection
    redirect_url = f'/api/leaderboard?league={league}&limit={limit}'
    
    return redirect(redirect_url, code=302)


@app.route('/api/arena/matches', methods=['GET'])
@jwt_required()
def api_get_match_history():
    """Get match history for the current user."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    limit = request.args.get('limit', 20, type=int)
    matches = arena_manager.get_match_history(user_id=user.id, limit=min(limit, 100))
    return jsonify({'matches': matches}), 200


@app.route('/api/arena/matches/<int:match_id>', methods=['GET'])
def api_get_match(match_id):
    """Get details of a specific match (public endpoint)."""
    match = Match.query.get(match_id)
    if not match:
        return jsonify({'error': 'Match not found'}), 404
    
    return jsonify({'match': match.to_dict()}), 200


@app.route('/api/arena/boss/info', methods=['GET'])
@jwt_required()
def api_get_boss_info():
    """Get information about the next Boss to challenge.
    
    Returns:
        - can_challenge: bool, si le joueur peut défier
        - message: str, explication
        - boss: dict, informations sur le Boss (si disponible)
        - required_elo: int, ELO requis pour défier
        - current_elo: int, ELO actuel du joueur (bot)
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Récupérer le bot actif de l'utilisateur
        user_bot = Bot.query.filter_by(
            user_id=user.id,
            is_active=True
        ).order_by(Bot.elo_rating.desc()).first()
        
        if not user_bot:
            return jsonify({'error': 'Vous devez avoir un bot actif'}), 400
        
        can_challenge, message, boss = BossSystem.can_challenge_boss(user)
        
        user_league = League.from_index(user_bot.league)
        league_info = LeagueManager.get_league_info(user_bot.elo_rating)
        
        response = {
            'can_challenge': can_challenge,
            'message': message,
            'current_elo': user_bot.elo_rating,
            'current_league': user_bot.league,
            'current_league_name': league_info['current_league']
        }
        
        if boss:
            boss_config = BossSystem.BOSS_CONFIG.get(user_league)
            response['boss'] = {
                'id': boss.id,
                'name': boss.name,
                'elo': boss.elo_rating,
                'description': boss_config['description'] if boss_config else '',
                'wins': boss.win_count,
                'matches': boss.match_count
            }
            response['required_elo'] = boss.elo_rating
        
        return jsonify(response), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get boss info')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/arena/boss/challenge', methods=['POST'])
@jwt_required()
def api_challenge_boss():
    """Challenge the Boss of current league.
    
    Creates a match against the Boss using league-specific rules.
    The match is executed immediately and the result determines promotion.
    
    Returns:
        - success: bool
        - promoted: bool, si promu après victoire
        - match_result: dict avec détails du match
        - message: str
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Vérifier si peut défier
        can_challenge, msg, boss = BossSystem.can_challenge_boss(user)
        if not can_challenge:
            return jsonify({'error': msg}), 400
        
        # Récupérer le bot du joueur (dernier soumis à l'arène)
        player_bot = Bot.query.filter_by(
            user_id=user.id,
            is_active=True
        ).order_by(Bot.latest_version_number.desc()).first()
        
        if not player_bot:
            return jsonify({'error': 'Vous devez avoir un bot actif pour défier le Boss'}), 400
        
        # Créer et exécuter le match contre le Boss
        game_id = str(uuid.uuid4())
        
        # Utiliser les règles spécifiques à la ligue
        from leagues import get_league_rules, League
        current_league = League.from_index(player_bot.league)
        league_rules = get_league_rules(current_league)
        
        logging.getLogger(__name__).info(
            f"🏆 User {user.username} (bot {player_bot.name}) challenges {boss.name} with league rules: {league_rules.to_dict()}"
        )
        
        # Exécuter le match (synchrone)
        result = _execute_arena_match(game_id, player_bot.id, boss.id)
        
        if 'error' in result:
            return jsonify({'error': result['error']}), 500
        
        # Vérifier si victoire
        beat_boss = result['winner'] == 'player'
        
        # Appliquer promotion si victoire (passer le bot du joueur)
        promoted, promo_msg = BossSystem.check_promotion_after_boss_match(user, player_bot, beat_boss)
        
        # Recharger le bot pour avoir les valeurs à jour
        db.session.refresh(player_bot)
        
        response = {
            'success': True,
            'beat_boss': beat_boss,
            'promoted': promoted,
            'match_result': result,
            'message': promo_msg if promoted else (
                "💪 Victoire contre le Boss ! Mais vous êtes déjà promu." if beat_boss 
                else "😔 Défaite... Continuez à vous entraîner et réessayez !"
            ),
            'new_league': player_bot.league,
            'new_elo': player_bot.elo_rating
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to challenge boss')
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/arena/boss/all', methods=['GET'])
def api_get_all_bosses():
    """Get information about all Bosses (public endpoint)."""
    try:
        from leagues import League
        
        bosses = []
        for league in [League.WOOD2, League.WOOD1, League.BRONZE, League.SILVER, League.GOLD]:
            boss = BossSystem.get_boss_for_league(league)
            config = BossSystem.BOSS_CONFIG.get(league)
            
            if boss and config:
                bosses.append({
                    'league': league.to_name(),
                    'league_index': int(league),
                    'name': boss.name,
                    'elo': boss.elo_rating,
                    'description': config['description'],
                    'wins': boss.win_count,
                    'matches': boss.match_count,
                    'win_rate': round(boss.win_count / boss.match_count * 100, 1) if boss.match_count > 0 else 0
                })
        
        return jsonify({'bosses': bosses}), 200
        
    except Exception as e:
        logging.getLogger(__name__).exception('Failed to get all bosses')
        return jsonify({'error': 'Internal server error'}), 500


# Modify the existing step endpoint to complete arena matches
_original_step = None

def _wrap_step_for_arena():
    """Wrap the step endpoint to detect and complete arena matches."""
    global _original_step
    
    # Find the step function
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'step_game':
            _original_step = app.view_functions[rule.endpoint]
            break
    
    if not _original_step:
        return
    
    def wrapped_step_game(game_id):
        # Call original step
        response = _original_step(game_id)
        
        # Check if this is an arena match and if it's finished
        game_entry = GAMES.get(game_id)
        if game_entry and game_entry.get('is_arena_match'):
            referee = game_entry.get('referee_obj')
            if referee and referee.is_finished():
                # Get match record
                idx = load_games_index()
                meta = idx.get(game_id, {})
                match_id = meta.get('match_id')
                
                if match_id:
                    state = referee.get_state()
                    winner = state.get('winner')
                    player_score = state.get('scores', {}).get('player', 0)
                    opponent_score = state.get('scores', {}).get('opponent', 0)
                    turns = state.get('turn', 0)
                    
                    arena_manager.complete_match(
                        match_id,
                        winner,
                        player_score,
                        opponent_score,
                        turns
                    )
        
        return response
    
    # Replace the endpoint
    for rule in app.url_map.iter_rules():
        if rule.endpoint == 'step_game':
            app.view_functions[rule.endpoint] = wrapped_step_game
            break

# Apply the wrapper after app initialization
_wrap_step_for_arena()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    app.run(host='0.0.0.0', port=5000, debug=True)
