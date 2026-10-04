"""Command-line runner to pit two bots against each other using PacmanReferee.

Usage:
    python3 run_referee.py player_bot.py opponent_bot.py

Each bot is started as a persistent process (python3 <script>) and is expected to
implement the typical CodinGame input/output pattern:
  - initial setup lines (width height and map rows)
  - game loop: the referee sends per-turn inputs; the bot must read stdin and
    print a single action line each turn

This runner will:
- start both bot processes
- send initial map information
- for each turn, write the per-turn input to each bot's stdin and read one output
  line (with timeout)
- apply actions via the referee and print the turn summary to stdout

This is a minimal prototype for local CLI matches (no Docker support here).
"""
import sys
import subprocess
import threading
import queue
import time
from referees.pacman_referee import PacmanReferee
from typing import Tuple

READ_LINE_TIMEOUT_S = 0.5  # default per-bot io timeout (seconds)


def _readline_with_timeout(proc, timeout_s: float) -> Tuple[str, bool]:
    """Read a single line from proc.stdout with timeout. Returns (line, timed_out).
    If proc has terminated, returns ('', False).
    """
    q = queue.Queue()

    def reader():
        try:
            line = proc.stdout.readline()
            q.put(line)
        except Exception:
            q.put('')

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        line = q.get(timeout=timeout_s)
        return line, False
    except queue.Empty:
        return '', True


def send_initial_map(proc, ref: PacmanReferee):
    # Send: "width height" and then height rows (map)
    width = ref.width
    height = ref.height
    # represent grid rows as strings (space for floor, '#' for wall)
    rows = []
    for y in range(height):
        row = ''.join(ref.grid[y])
        rows.append(row)
    initial = f"{width} {height}\n" + '\n'.join(rows) + '\n'
    try:
        proc.stdin.write(initial)
        proc.stdin.flush()
    except Exception:
        pass


def make_per_turn_input(ref: PacmanReferee, bot_id: str) -> str:
    # Compose inputs in the codinGame style used in the example
    # Line 1: my_score opponent_score
    player_score = ref.scores.get('player', 0)
    opp_score = ref.scores.get('opponent', 0)
    # For simplicity assign pac ids 0 (player) and 1 (opponent)
    my_score_line = f"{player_score} {opp_score}\n"
    # Visible pacs: include both and mark the 'mine' field correctly for the receiving bot
    pacs = []
    px, py = ref.pacs['player']
    ox, oy = ref.pacs['opponent']
    # Format: pac_id mine x y type_id speed_turns_left ability_cooldown
    owner0 = ref.owner_map.get(0)
    owner1 = ref.owner_map.get(1)
    mine0 = '1' if owner0 == bot_id else '0'
    mine1 = '1' if owner1 == bot_id else '0'
    pacs.append(f"0 {mine0} {px} {py} 0 0 0")
    pacs.append(f"1 {mine1} {ox} {oy} 0 0 0")
    visible_pac_count = len(pacs)
    pacs_block = f"{visible_pac_count}\n" + '\n'.join(pacs) + '\n'
    # Pellets
    pellets = list(ref.pellets)
    visible_pellet_count = len(pellets)
    pellets_lines = [f"{x} {y} 1" for x, y in pellets]
    pellets_block = f"{visible_pellet_count}\n" + ('\n'.join(pellets_lines) + '\n' if pellets_lines else '')
    # Compose final
    data = my_score_line + pacs_block + pellets_block
    return data


def run_match(player_bot_path: str, opponent_bot_path: str, max_turns: int = 200):
    ref = PacmanReferee()
    ref.init_game({})

    # Start bot processes
    player_proc = subprocess.Popen([sys.executable, player_bot_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    opponent_proc = subprocess.Popen([sys.executable, opponent_bot_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Send initial map to both bots
    send_initial_map(player_proc, ref)
    send_initial_map(opponent_proc, ref)

    # Optional: start threads to drain stderr asynchronously to avoid blocking
    def drain_stream(stream, name):
        for line in stream:
            if line:
                sys.stderr.write(f"[{name} stderr] {line}")
    threading.Thread(target=drain_stream, args=(player_proc.stderr, 'player'), daemon=True).start()
    threading.Thread(target=drain_stream, args=(opponent_proc.stderr, 'opponent'), daemon=True).start()

    turn = 0
    while not ref.is_finished() and turn < max_turns:
        turn += 1
        # prepare inputs
        p_input = make_per_turn_input(ref, 'player')
        o_input = make_per_turn_input(ref, 'opponent')

        # send to player
        try:
            player_proc.stdin.write(p_input)
            player_proc.stdin.flush()
        except Exception:
            pass
        # send to opponent
        try:
            opponent_proc.stdin.write(o_input)
            opponent_proc.stdin.flush()
        except Exception:
            pass

        # read player output and raise via referee if missing
        out_p, to_p = _readline_with_timeout(player_proc, READ_LINE_TIMEOUT_S)
        if to_p:
            # no data in time -> notify referee which should raise
            try:
                ref.on_bot_timeout('player', turn, 'timeout')
            except Exception:
                # ensure procs are killed then re-raise to surface the exception
                try:
                    player_proc.kill()
                except Exception:
                    pass
                try:
                    opponent_proc.kill()
                except Exception:
                    pass
                raise
        # if process terminated with no output
        if out_p == '' and player_proc.poll() is not None:
            try:
                ref.on_bot_timeout('player', turn, 'process terminated')
            except Exception:
                try:
                    player_proc.kill()
                except Exception:
                    pass
                try:
                    opponent_proc.kill()
                except Exception:
                    pass
                raise
        action_p = out_p.strip()

        out_o, to_o = _readline_with_timeout(opponent_proc, READ_LINE_TIMEOUT_S)
        if to_o:
            try:
                ref.on_bot_timeout('opponent', turn, 'timeout')
            except Exception:
                try:
                    player_proc.kill()
                except Exception:
                    pass
                try:
                    opponent_proc.kill()
                except Exception:
                    pass
                raise
        if out_o == '' and opponent_proc.poll() is not None:
            try:
                ref.on_bot_timeout('opponent', turn, 'process terminated')
            except Exception:
                try:
                    player_proc.kill()
                except Exception:
                    pass
                try:
                    opponent_proc.kill()
                except Exception:
                    pass
                raise
        action_o = out_o.strip()

        actions = {'player': action_p, 'opponent': action_o}
        state, stdout_log, stderr_log = ref.step(actions)

        # Print turn summary
        print(f"Turn {turn}: player -> {action_p} | opponent -> {action_o}")
        print(stdout_log)
        sys.stdout.flush()
        time.sleep(0.01)

    # Cleanup
    try:
        player_proc.kill()
    except Exception:
        pass
    try:
        opponent_proc.kill()
    except Exception:
        pass

    print("Match finished")
    print(f"Final scores: {ref.scores}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python3 run_referee.py player_bot.py opponent_bot.py', file=sys.stderr)
        sys.exit(2)
    player = sys.argv[1]
    opponent = sys.argv[2]
    run_match(player, opponent, max_turns=200)
