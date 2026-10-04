"""Minimal game SDK/referee patterns.
Defines a Referee base class and helpers for JSON state exchange between backend and frontend.
Also provides a BotRunner abstraction to execute bot code in different runners (docker/subprocess/auto).
"""
from typing import Any, Dict, List, Tuple, Optional
import os
import subprocess
from venv import logger
import ast
import types
import io
import sys
import threading
import contextlib


class Referee:
    """Base referee class. Subclass this to implement a new game/referee.

    Methods to implement:
    - init_game(init_params) -> None : initialize game state
    - get_protocol() -> dict : return protocol description (init inputs, per-turn inputs, outputs, constraints)
    - get_state() -> dict : return current state serializable to JSON
    - is_finished() -> bool
    - step(actions_by_bot: Dict[str,str]) -> Tuple[dict,str,str] : apply actions and advance one turn.
        returns: (state, stdout_log, stderr_log)
    - make_bot_input(bot_id) -> str : produce the string given to each bot on a turn
    - parse_bot_output(bot_id, output_str) -> str : parse bot output into an action string
    """
    def __init__(self):
        # common runtime fields used by many referees. Initializing here avoids static-analysis warnings
        self.history: List[Dict[str, Any]] = []
        self.turn: int = 0
        self.logs: List[str] = []

        # optional game-specific fields (referees may overwrite these)
        self.pacs: Dict[str, Tuple[int, int]] = {}
        self.pellets: set = set()
        self.scores: Dict[str, int] = {}
        self.max_turns: int = 0

    def init_game(self, init_params: Dict[str,Any]):
        raise NotImplementedError()

    def get_protocol(self) -> Dict[str,Any]:
        return {}

    def get_state(self) -> Dict[str,Any]:
        raise NotImplementedError()

    def is_finished(self) -> bool:
        raise NotImplementedError()

    def step(self, actions_by_bot: Dict[str,str]) -> Tuple[Dict[str,str], str, str]:
        raise NotImplementedError()

    def make_bot_input(self, bot_id: str) -> str:
        """Return the string sent to the bot for this turn."""
        return ""

    def parse_bot_output(self, bot_id: str, output_str: str) -> str:
        """Return an action identifier parsed from bot output."""
        return output_str.strip()

    def on_bot_timeout(self, bot_id: str, turn: int, reason: str = ''):
        """Called by the runner when a bot fails to provide output in time or terminates.

        By default this raises a TimeoutError including bot id, turn and an optional reason.
        Individual referees may override this to implement custom handling.
        """
        msg = f"Bot '{bot_id}' failed to provide output on turn {turn}"
        if reason:
            msg += f": {reason}"
        raise TimeoutError(msg)


# ------------------ Bot runner abstraction ------------------
class BotRunner:
    """Pluggable runner to execute bot code.

    Modes:
      - 'auto' : try docker first then fallback to subprocess
      - 'docker': always use docker
      - 'subprocess': always use local subprocess

    Configuration via env vars:
      - BOT_RUNNER: 'auto'|'docker'|'subprocess' (default 'auto')
      - BOT_DOCKER_IMAGE: docker image to use (default 'python:3.11-slim')
    """
    def __init__(self, mode: Optional[str]=None, docker_image: Optional[str]=None):
        self.mode = (mode or os.environ.get('BOT_RUNNER') or 'auto').lower()
        self.docker_image = docker_image or os.environ.get('BOT_DOCKER_IMAGE') or 'python:3.11-slim'

    def run(self, bot_code: str, input_str: str, timeout_ms: int = 50, memory_mb: int = 64, cpus: float = 0.5, host_bot_dir: str = None) -> Tuple[str, str, int, str]:
        """Execute bot_code with input_str. Returns (stdout, stderr, rc, runner_used).
        runner_used is one of: 'docker', 'subprocess', 'subprocess_fallback', 'docker-unavailable'.
        """
        # choose behavior based on mode
        if self.mode == 'docker':
            # When docker is explicitly requested, give the container a bit more
            # startup time than very small per-turn timeouts (which are intended
            # for fast bots). This avoids spurious timeouts on platforms where
            # container startup can be slow (macOS Docker Desktop, etc.). We don't
            # change 'auto' behavior here to preserve the fallback optimization.
            docker_min_startup_ms = 1000
            docker_timeout_ms = timeout_ms if timeout_ms >= docker_min_startup_ms else docker_min_startup_ms
            out, err, rc = self._run_docker(bot_code, input_str, docker_timeout_ms, memory_mb, cpus, host_bot_dir=host_bot_dir)
            used = 'docker' if rc != -1 else 'docker-unavailable'
            return out, err, rc, used
        elif self.mode == 'subprocess':
            out, err, rc = self._run_subprocess(bot_code, input_str, timeout_ms)
            return out, err, rc, 'subprocess'
        else:  # auto
            # For very small timeouts, prefer local subprocess to avoid Docker startup latency.
            # Docker containers typically take hundreds of milliseconds to start on many hosts
            # (especially on macOS). If a referee requests a tiny time budget (e.g. 50ms),
            # running the bot as a local subprocess is more likely to meet the constraint.
            # Default threshold for preferring subprocess when in 'auto' mode.
            # Make this configurable via env var BOT_DOCKER_AUTO_THRESHOLD_MS (milliseconds).
            # Lower the default to 100ms so typical referee budgets (e.g. 200ms) will still
            # allow trying Docker first.
            try:
                docker_startup_threshold_ms = int(os.environ.get('BOT_DOCKER_AUTO_THRESHOLD_MS', '100'))
            except Exception:
                docker_startup_threshold_ms = 100
            # Use local subprocess when timeout is <= threshold to avoid Docker startup latency
            if timeout_ms <= docker_startup_threshold_ms:
                out, err, rc = self._run_subprocess(bot_code, input_str, timeout_ms)
                return out, err, rc, 'subprocess'
            # try docker first
            # Give Docker a bit more time for container startup when auto-trying docker.
            try:
                docker_min_startup_ms = int(os.environ.get('BOT_DOCKER_STARTUP_MS', '1000'))
            except Exception:
                docker_min_startup_ms = 1000
            docker_timeout_ms = timeout_ms if timeout_ms >= docker_min_startup_ms else docker_min_startup_ms
            out, err, rc = self._run_docker(bot_code, input_str, docker_timeout_ms, memory_mb, cpus, host_bot_dir=host_bot_dir)
            # If docker failed due to availability or timeout, fallback to subprocess.
            if rc == -1:
                lowered = (err or '').lower()
                if 'docker-not-available' in lowered or lowered.strip() == 'timeout':
                    # transient failure: retry once with a larger timeout before falling back
                    try:
                        retry_timeout_ms = max(docker_min_startup_ms * 2, docker_timeout_ms * 2)
                    except Exception:
                        retry_timeout_ms = docker_timeout_ms * 2
                    out_r, err_r, rc_r = self._run_docker(bot_code, input_str, retry_timeout_ms, memory_mb, cpus, host_bot_dir=host_bot_dir)
                    if rc_r != -1:
                        return out_r, err_r, rc_r, 'docker'
                    # final fallback to subprocess
                    out, err, rc = self._run_subprocess(bot_code, input_str, timeout_ms)
                    return out, err, rc, 'subprocess_fallback'
            return out, err, rc, 'docker'

    def _run_subprocess(self, bot_code: str, input_str: str, timeout_ms: int = 50) -> Tuple[str, str, int]:
        # run python -c with the provided code
        # Use real subprocess with timeout
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

    def _run_docker(self, bot_code: str, input_str: str, timeout_ms: int = 50, memory_mb: int = 64, cpus: float = 0.5, host_bot_dir: str = None) -> Tuple[str, str, int]:
        # Lazy import to avoid requiring docker libs when not used
        try:
            from runner.docker_runner import run_bot_in_docker
        except Exception as e:
            return '', f'docker-not-available: {e}', -1
        try:
            # temporarily set BOT_DOCKER_IMAGE env var for the docker runner
            old_img = os.environ.get('BOT_DOCKER_IMAGE')
            os.environ['BOT_DOCKER_IMAGE'] = self.docker_image
            logger.debug(f'Using docker image: {self.docker_image}')
            out, err, rc = run_bot_in_docker(bot_code, input_str, timeout_ms=timeout_ms, memory_mb=memory_mb, cpus=cpus, host_bot_dir=host_bot_dir)
            # restore
            if old_img is None:
                del os.environ['BOT_DOCKER_IMAGE']
            else:
                os.environ['BOT_DOCKER_IMAGE'] = old_img
            return out, err, rc
        except Exception as e:
            return '', f'docker-not-available: {e}', -1


def make_bot_runner() -> BotRunner:
    return BotRunner()


def parse_bot_code(src: str):
    """Parse bot source and return a dict with compiled init and turn code and a fresh globals dict.

    Strategy: find the first top-level `while` statement (commonly `while True:`).
    Everything before that is the initialization code; the body of the while is the per-turn code.
    If no top-level while is found, entire source is considered initialization and per-turn body is empty.
    """
    try:
        mod = ast.parse(src)
    except Exception as e:
        raise
    init_nodes = []
    turn_nodes = []
    found = False
    for node in mod.body:
        if not found and isinstance(node, ast.While):
            # found the loop; take its body as turn nodes
            found = True
            turn_nodes.extend(node.body)
        elif not found:
            init_nodes.append(node)
        else:
            # code after the first while is ignored for turn execution
            pass
    # Compile AST nodes into code objects
    init_mod = ast.Module(body=init_nodes, type_ignores=[])
    ast.fix_missing_locations(init_mod)

    # Wrap turn_nodes in a single-iteration loop so that any top-level 'break' or 'continue'
    # statements extracted from the original `while True:` loop remain syntactically and semantically valid!
    if turn_nodes:
        wrapper = ast.parse('for _bot_turn_once_ in (True,): pass').body[0]
        wrapper.body = turn_nodes
        turn_mod = ast.Module(body=[wrapper], type_ignores=[])
    else:
        turn_mod = ast.Module(body=[], type_ignores=[])

    ast.fix_missing_locations(turn_mod)
    init_code = compile(init_mod, '<bot_init>', 'exec')
    turn_code = compile(turn_mod, '<bot_turn>', 'exec')
    return {'init_code': init_code, 'turn_code': turn_code, 'globals': {}}


def _exec_code_with_io(codeobj, globs, input_lines: list, timeout_ms: int = 2000):
    """Execute compiled codeobj in globs with input_lines (list of strings). Capture stdout/stderr. Timeout in ms."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()

    # prepare input iterator
    it = iter(input_lines or [])

    def input_func(prompt=None):
        try:
            return next(it)
        except StopIteration:
            # simulate EOF for input() calls when no more lines are available
            raise EOFError()

    # install input into globals so code calling input() will use our function
    globs['input'] = input_func

    exc = {}

    def target():
        try:
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                exec(codeobj, globs)
        except Exception as e:
            exc['err'] = e

    th = threading.Thread(target=target)
    th.start()
    th.join(timeout_ms/1000.0)
    if th.is_alive():
        # still running -> timed out
        return '', 'timeout', -1
    if 'err' in exc:
        return out_buf.getvalue(), str(exc['err']), -1
    return out_buf.getvalue(), err_buf.getvalue(), 0


def run_parsed_init(parsed, initial_input: str, timeout_ms: int = 2000):
    """Run the init part once with initial_input (string containing lines)."""
    lines = [l for l in initial_input.splitlines()]
    return _exec_code_with_io(parsed['init_code'], parsed['globals'], lines, timeout_ms=timeout_ms)


def run_parsed_turn(parsed, per_turn_input: str, timeout_ms: int = 2000):
    """Run the parsed turn code with per_turn_input; returns (stdout, stderr, rc)."""
    lines = [l for l in per_turn_input.splitlines()]
    return _exec_code_with_io(parsed['turn_code'], parsed['globals'], lines, timeout_ms=timeout_ms)
