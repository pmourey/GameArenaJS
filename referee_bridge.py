"""Referee Bridge for GameArena - Connects Node.js Express server to Python game referees and bots.
Supports interactive JSON-lines via stdin/stdout or single-shot execution.
"""
import sys
import os
import json
import pickle
import traceback
from typing import Dict, Any, Optional

# Ensure project root is in python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from referees.pacman_referee_v2 import PacmanRefereeV2
from leagues import League, LeagueRules
from game_sdk import parse_bot_code, run_parsed_init, run_parsed_turn

SESSIONS_DIR = "/tmp/gamearena_sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

BOSS_FILES = {
    'wood2': 'bots/boss_codes/wood_boss.py',
    'wood1': 'bots/boss_codes/wood_boss.py',
    'bronze': 'bots/boss_codes/bronze_boss.py',
    'silver': 'bots/boss_codes/silver_boss.py',
    'gold': 'bots/boss_codes/gold_boss.py',
    'default': 'bots/Boss.py'
}

def resolve_boss_code(boss_name: str, league_index: int = 1) -> str:
    """Resolve boss code based on name or league index."""
    name_norm = (boss_name or '').lower().replace(' ', '').replace('_', '')
    target_path = None
    if 'gold' in name_norm or league_index == 5:
        target_path = os.path.join(ROOT_DIR, 'bots/boss_codes/gold_boss.py')
    elif 'silver' in name_norm or league_index == 4:
        target_path = os.path.join(ROOT_DIR, 'bots/boss_codes/silver_boss.py')
    elif 'bronze' in name_norm or league_index == 3:
        target_path = os.path.join(ROOT_DIR, 'bots/boss_codes/bronze_boss.py')
    elif 'wood' in name_norm or league_index in (1, 2):
        target_path = os.path.join(ROOT_DIR, 'bots/boss_codes/wood_boss.py')
    
    if target_path and os.path.exists(target_path):
        with open(target_path, 'r', encoding='utf-8') as f:
            return f.read()

    default_path = os.path.join(ROOT_DIR, 'bots/Boss.py')
    if os.path.exists(default_path):
        with open(default_path, 'r', encoding='utf-8') as f:
            return f.read()
    return 'print("MOVE 0 1 1")'


class SessionState:
    def __init__(self, session_id: str, referee: PacmanRefereeV2, 
                 player_code: str, opponent_code: str,
                 player_parsed: Any = None, opponent_parsed: Any = None):
        self.session_id = session_id
        self.ref = referee
        self.player_code = player_code
        self.opponent_code = opponent_code
        self.player_parsed = player_parsed
        self.opponent_parsed = opponent_parsed
        self.finished = False

    def ensure_parsed(self):
        if not self.player_parsed or not self.opponent_parsed:
            width = self.ref.width
            height = self.ref.height
            rows = [''.join(self.ref.grid[y]) for y in range(height)]
            initial_map_block = f"{width} {height}\n" + '\n'.join(rows) + '\n'

            self.player_parsed = parse_bot_code(self.player_code)
            run_parsed_init(self.player_parsed, initial_map_block, timeout_ms=2000)

            self.opponent_parsed = parse_bot_code(self.opponent_code)
            run_parsed_init(self.opponent_parsed, initial_map_block, timeout_ms=2000)

active_sessions: Dict[str, SessionState] = {}


def save_session(session: SessionState):
    active_sessions[session.session_id] = session
    path = os.path.join(SESSIONS_DIR, f"{session.session_id}.pkl")
    try:
        data = {
            'session_id': session.session_id,
            'ref': session.ref,
            'player_code': session.player_code,
            'opponent_code': session.opponent_code,
            'finished': session.finished
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
    except Exception as e:
        sys.stderr.write(f"Save session failed: {e}\n")


def load_session(session_id: str) -> Optional[SessionState]:
    if session_id in active_sessions:
        s = active_sessions[session_id]
        s.ensure_parsed()
        return s
    path = os.path.join(SESSIONS_DIR, f"{session_id}.pkl")
    if os.path.exists(path):
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
                session = SessionState(
                    session_id=data['session_id'],
                    referee=data['ref'],
                    player_code=data['player_code'],
                    opponent_code=data['opponent_code']
                )
                session.finished = data.get('finished', False)
                session.ensure_parsed()
                active_sessions[session_id] = session
                return session
        except Exception as e:
            sys.stderr.write(f"Load session failed: {e}\n")
    return None


def handle_create(params: Dict[str, Any]) -> Dict[str, Any]:
    session_id = str(params.get('session_id') or os.urandom(8).hex())
    league_idx = int(params.get('league_index') or 1)
    player_code = params.get('player_code') or ''
    opponent_spec = params.get('opponent') or 'Boss'

    # Fallback player code to template
    if not player_code or not player_code.strip():
        tpl_path = os.path.join(ROOT_DIR, 'bots/player_template.py')
        if os.path.exists(tpl_path):
            with open(tpl_path, 'r', encoding='utf-8') as f:
                player_code = f.read()
        else:
            player_code = 'print("MOVE 0 1 1")'

    # Resolve opponent code
    if os.path.exists(opponent_spec):
        with open(opponent_spec, 'r', encoding='utf-8') as f:
            opponent_code = f.read()
    elif len(opponent_spec.split('\n')) > 3:
        opponent_code = opponent_spec
    else:
        opponent_code = resolve_boss_code(opponent_spec, league_idx)

    # Initialize referee
    ref = PacmanRefereeV2()
    rules = LeagueRules(League.from_index(league_idx))
    init_params = rules.get_init_params()
    ref.init_game(init_params)

    # Setup map string
    width = ref.width
    height = ref.height
    rows = [''.join(ref.grid[y]) for y in range(height)]
    initial_map_block = f"{width} {height}\n" + '\n'.join(rows) + '\n'

    # Parse bot codes
    p_player = parse_bot_code(player_code)
    run_parsed_init(p_player, initial_map_block, timeout_ms=2000)

    p_opp = parse_bot_code(opponent_code)
    run_parsed_init(p_opp, initial_map_block, timeout_ms=2000)

    session = SessionState(session_id, ref, player_code, opponent_code, p_player, p_opp)
    save_session(session)

    return {
        'ok': True,
        'session_id': session_id,
        'state': ref.get_state(),
        'scores': ref.scores
    }


def handle_step(params: Dict[str, Any]) -> Dict[str, Any]:
    session_id = params.get('session_id')
    session = load_session(session_id)
    if not session:
        return {'ok': False, 'error': f'Session {session_id} not found'}

    ref = session.ref
    if ref.is_finished():
        session.finished = True
        save_session(session)
        return {
            'ok': True,
            'finished': True,
            'state': ref.get_state(),
            'scores': ref.scores,
            'history': ref.history
        }

    p_in = ref.make_bot_input('player')
    o_in = ref.make_bot_input('opponent')

    out_p, err_p, rc_p = run_parsed_turn(session.player_parsed, p_in, timeout_ms=2000)
    out_o, err_o, rc_o = run_parsed_turn(session.opponent_parsed, o_in, timeout_ms=2000)

    action_p = out_p.strip() if out_p else 'STAY'
    action_o = out_o.strip() if out_o else 'STAY'

    player_log = {'stdout': out_p or '', 'stderr': err_p or '', 'rc': rc_p, 'runner': 'parsed'}
    opponent_log = {'stdout': out_o or '', 'stderr': err_o or '', 'rc': rc_o, 'runner': 'parsed'}

    state, stdout, stderr = ref.step({'player': action_p, 'opponent': action_o})
    entry = ref.history[-1] if ref.history else {}
    entry['bot_logs'] = {'player': player_log, 'opponent': opponent_log}
    entry['__global_stdout'] = stdout
    entry['__global_stderr'] = stderr

    is_fin = ref.is_finished()
    session.finished = is_fin
    save_session(session)

    return {
        'ok': True,
        'finished': is_fin,
        'state': state,
        'history_entry': entry,
        'scores': ref.scores,
        'history': ref.history if is_fin else None
    }


def handle_run_all(params: Dict[str, Any]) -> Dict[str, Any]:
    session_id = params.get('session_id')
    session = load_session(session_id)
    if not session:
        # Create on the fly if needed
        res = handle_create(params)
        session_id = res['session_id']
        session = load_session(session_id)

    ref = session.ref
    max_turns = int(params.get('max_turns') or 200)

    while not ref.is_finished() and ref.turn < max_turns:
        p_in = ref.make_bot_input('player')
        o_in = ref.make_bot_input('opponent')

        out_p, err_p, rc_p = run_parsed_turn(session.player_parsed, p_in, timeout_ms=2000)
        out_o, err_o, rc_o = run_parsed_turn(session.opponent_parsed, o_in, timeout_ms=2000)

        action_p = out_p.strip() if out_p else 'STAY'
        action_o = out_o.strip() if out_o else 'STAY'

        state, stdout, stderr = ref.step({'player': action_p, 'opponent': action_o})
        entry = ref.history[-1]
        entry['bot_logs'] = {
            'player': {'stdout': out_p or '', 'stderr': err_p or '', 'rc': rc_p},
            'opponent': {'stdout': out_o or '', 'stderr': err_o or '', 'rc': rc_o}
        }
        entry['__global_stdout'] = stdout
        entry['__global_stderr'] = stderr

    session.finished = True
    save_session(session)

    p_score = ref.scores.get('player', 0)
    o_score = ref.scores.get('opponent', 0)
    winner = 'player' if p_score > o_score else ('opponent' if o_score > p_score else 'draw')

    return {
        'ok': True,
        'finished': True,
        'scores': ref.scores,
        'winner': winner,
        'turns': ref.turn,
        'history': ref.history
    }


def handle_history(params: Dict[str, Any]) -> Dict[str, Any]:
    session_id = params.get('session_id')
    session = load_session(session_id)
    if not session:
        return {'ok': False, 'error': f'Session {session_id} not found'}
    return {
        'ok': True,
        'history': session.ref.history,
        'finished': session.ref.is_finished(),
        'scores': session.ref.scores
    }


def process_command(line: str) -> str:
    try:
        data = json.loads(line)
        cmd = data.get('cmd')
        if cmd == 'create':
            res = handle_create(data)
        elif cmd == 'step':
            res = handle_step(data)
        elif cmd == 'run':
            res = handle_run_all(data)
        elif cmd == 'history':
            res = handle_history(data)
        elif cmd == 'ping':
            res = {'ok': True, 'pong': True}
        else:
            res = {'ok': False, 'error': f'Unknown cmd: {cmd}'}
        return json.dumps(res)
    except Exception as e:
        return json.dumps({'ok': False, 'error': str(e), 'traceback': traceback.format_exc()})


if __name__ == '__main__':
    # CLI or Server mode
    if len(sys.argv) > 1 and sys.argv[1] != 'server':
        # Single command passed via CLI argument or json arg
        arg = ' '.join(sys.argv[1:])
        print(process_command(arg))
    else:
        # Long-lived persistent stdio server
        sys.stderr.write("GameArena Referee Bridge started (stdio JSON-RPC)\n")
        sys.stderr.flush()
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                resp = process_command(line)
                print(resp, flush=True)
            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as e:
                err_resp = json.dumps({'ok': False, 'error': str(e)})
                print(err_resp, flush=True)
