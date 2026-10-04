"""Docker-based runner pour exécution isolée de bots.

Fonction principale:
- run_bot_in_docker(bot_code: str, input_str: str, timeout_ms: int = 50, memory_mb: int = 64, cpus: float = 0.5)

Comportement:
- Crée un répertoire temporaire contenant `bot.py` avec le code fourni.
- Lance `docker run` en lecture seule (mount), sans réseau, avec limites mémoire/CPU et options de sécurité.
- Communique l'entrée au process docker et capture stdout/stderr.
- Utilise un timeout côté hôte pour s'assurer que le container est tué après `timeout_ms`.
- Retourne (stdout, stderr, rc). En cas d'erreur (docker non disponible), retourne ('', 'docker-not-available: ...', -1) ou détails d'erreur.

Remarques de sécurité:
- Ce runner est un prototype éducatif. En production vous devriez builder une image minimale contenant uniquement les runtimes nécessaires et appliquer des politiques SELinux/AppArmor/seccomp supplémentaires.
"""
import tempfile
import os
import shutil
import subprocess
from typing import Tuple
import logging

# Module logger and runtime console tracing toggle. By default tracing can be enabled
# with the DOCKER_RUNNER_TRACE env var (values: '1','true','yes') or toggled at runtime
# via set_console_tracing(). When disabled, the logger level is raised to WARNING so
# debug messages from this module are suppressed in the Flask console.
logger = logging.getLogger(__name__)

def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')

_INITIAL_TRACE = _env_bool('DOCKER_RUNNER_TRACE', False)
# Debug snapshot container used across the module. Define it before any function that may set values.
LAST_RUN_DEBUG = {}
def set_console_tracing(enabled: bool):
    """Enable or disable debug tracing for the docker_runner module in the console.

    When enabled, the module logger level is set to DEBUG; when disabled it is set to WARNING.
    This affects what messages appear in the Flask console.
    """
    if enabled:
        logger.setLevel(logging.DEBUG)
    else:
        # Set INFO as the default visible level so INFO logs (like the image
        # name) appear in standard logs even when tracing is not enabled.
        logger.setLevel(logging.INFO)
    LAST_RUN_DEBUG['console_tracing'] = bool(enabled)

def is_console_tracing_enabled() -> bool:
    return logger.getEffectiveLevel() <= logging.DEBUG

# Apply initial setting from environment
set_console_tracing(_INITIAL_TRACE)

def get_last_run_debug() -> dict:
    return LAST_RUN_DEBUG.copy()


def _is_docker_unavailable(stderr: str) -> bool:
    if not stderr:
        return False
    s = stderr.lower()
    checks = [
        'cannot connect to the docker daemon',
        'permission denied',
        'error response from daemon',
        'docker daemon',
        'got permission denied while trying to connect to the docker daemon'
    ]
    return any(c in s for c in checks)


def _docker_cp_fallback(bot_path: str, image: str, input_str: str, timeout_ms: int, memory_mb: int, cpus: float, pids_limit: int, collect_debug: bool = False):
    """Create a container, copy bot.py into it, start attached and return (out,err,rc).
    Updates LAST_RUN_DEBUG with steps only if collect_debug is True and returns a tuple.
    """
    logger = logging.getLogger(__name__)
    cid = None
    try:
        create_cmd = [
            'docker', 'create', '--rm',
            '--network', 'none',
            '--memory', f'{memory_mb}m',
            '--cpus', str(cpus),
            '--pids-limit', str(pids_limit),
            '--security-opt', 'no-new-privileges',
            '--tmpfs', '/tmp:rw',
            '--entrypoint', 'python3',
            image,
            '/bot/bot.py'
        ]
        if collect_debug:
            LAST_RUN_DEBUG['fallback_create_cmd'] = ' '.join(create_cmd)
        logger.debug("create command (fallback): %s", ' '.join(create_cmd))
        cid = subprocess.check_output(create_cmd, stderr=subprocess.STDOUT, text=True).strip()
        if collect_debug:
            LAST_RUN_DEBUG['fallback_cid'] = cid
        logger.debug("created container id for fallback: %s", cid)

        cp_proc = subprocess.run(['docker', 'cp', bot_path, f'{cid}:/bot/bot.py'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if collect_debug:
            LAST_RUN_DEBUG['fallback_cp_rc'] = cp_proc.returncode
            LAST_RUN_DEBUG['fallback_cp_stdout'] = (cp_proc.stdout or '').strip()
            LAST_RUN_DEBUG['fallback_cp_stderr'] = (cp_proc.stderr or '').strip()
        if cp_proc.returncode != 0:
            logger.debug("docker cp failed: %s", (cp_proc.stderr or '').strip())
            raise subprocess.CalledProcessError(cp_proc.returncode, cp_proc.args, output=cp_proc.stdout, stderr=cp_proc.stderr)

        logger.debug("docker start -a -i %s", cid)
        start_proc = subprocess.Popen(['docker', 'start', '-a', '-i', cid], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = start_proc.communicate(input=input_str, timeout=timeout_ms/1000.0)
            rc = start_proc.returncode
        except subprocess.TimeoutExpired:
            try:
                start_proc.kill()
            except Exception:
                pass
            out, err, rc = '', 'timeout', -1
        if collect_debug:
            LAST_RUN_DEBUG['fallback_start_rc'] = rc
            LAST_RUN_DEBUG['fallback_start_stdout'] = (out or '').strip()
            LAST_RUN_DEBUG['fallback_start_stderr'] = (err or '').strip()
        return out, err, rc
    except subprocess.CalledProcessError as cpe:
        msg = (getattr(cpe, 'stderr', '') or str(cpe)).strip()
        if collect_debug:
            LAST_RUN_DEBUG['fallback_error'] = msg
        logger.debug("docker-cp fallback failed: %s", msg)
        return '', msg, -1
    except Exception as e:
        if collect_debug:
            LAST_RUN_DEBUG['fallback_error'] = str(e)
        logger.debug("docker-cp fallback failed: %s", e)
        return '', str(e), -1
    finally:
        if cid:
            try:
                subprocess.run(['docker', 'rm', '-f', cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass


def run_bot_in_docker(bot_code: str, input_str: str, timeout_ms: int = 50, memory_mb: int = 64, cpus: float = 0.5, pids_limit: int = 64, host_bot_dir: str = None) -> Tuple[str, str, int]:
    """Run bot in a Docker container using image from BOT_DOCKER_IMAGE or fallback.

    Returns (stdout, stderr, rc). If docker is not available returns rc -1 and stderr starting with 'docker-not-available'.
    """
    # Allow forcing the temporary directory base (useful for macOS Docker Desktop where
    # only certain host paths are shared with the VM). Default to /tmp which is typically
    # available to Docker Desktop.
    # Default to /tmp/gamearena-bot-test which can be shared in Docker Desktop on macOS.
    tmp_base = os.environ.get('BOT_TMP_DIR', '/Users/display/gamearena-bot-test')
    # Ensure the base dir exists (tempfile.mkdtemp will fail if dir doesn't exist)
    try:
        os.makedirs(tmp_base, exist_ok=True)
    except Exception:
        # If we can't create the requested base, fall back to system temp dir
        tmp_base = tempfile.gettempdir()
    # Create the base temporary directory
    # tmpdir = tempfile.mkdtemp(prefix='bot-run-', dir=tmp_base)
    # Determine whether to use a persistent host directory (provided by caller)
    persistent_dir = None
    if host_bot_dir:
        try:
            persistent_dir = os.path.abspath(host_bot_dir)
            os.makedirs(persistent_dir, exist_ok=True)
        except Exception:
            persistent_dir = None

    # If persistent_dir is set use it, otherwise create an ephemeral tmp dir under tmp_base
    if persistent_dir:
        used_tmpdir = persistent_dir
        created_tmp = False
    else:
        used_tmpdir = tempfile.mkdtemp(prefix='bot-run-', dir=tmp_base)
        created_tmp = True

    bot_path = os.path.join(used_tmpdir, 'bot.py')
    try:
        # Decide whether to collect per-run debug info and run checks. Disabled by default.
        # Can be enabled by setting DOCKER_RUNNER_PER_RUN_CHECKS=1 or if console tracing is enabled.
        per_run_checks = _env_bool('DOCKER_RUNNER_PER_RUN_CHECKS', False)
        collect_debug = per_run_checks or is_console_tracing_enabled()

        # Initialize debug info for this run only if requested
        if collect_debug:
            LAST_RUN_DEBUG.clear()
            LAST_RUN_DEBUG.update({'tmp_base': tmp_base, 'used_tmpdir': used_tmpdir})

        # Write the bot file and ensure it's flushed to disk so that the docker process
        # sees it when the host path is bind-mounted into the container.
        # If using a persistent host directory, we overwrite bot.py there so Docker
        # (when mounting the directory) will see the user's edited code. If using
        # an ephemeral temp dir we behave as before.
        with open(bot_path, 'w', encoding='utf-8') as f:
            f.write(bot_code)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                # If fsync is not available for some reason, continue; the flush helps.
                pass
        if collect_debug:
            LAST_RUN_DEBUG['bot_path'] = bot_path

        # Determine which image to use (allow customization)
        image = os.environ.get('BOT_DOCKER_IMAGE', 'python:3.11-slim')

        # Always record the image requested so callers can inspect it via
        # get_last_run_debug() even when per-run checks are not enabled.
        LAST_RUN_DEBUG['image'] = image

        # Also emit a debug log entry showing the image used for this run.
        # The message will be visible when console tracing is enabled.
        logger.debug("docker image for run_bot_in_docker: %s", image)

        # Emit an INFO-level log so the image is recorded in standard logs
        # even when debug tracing is not enabled. To see this message, ensure
        # your logging configuration allows INFO for this logger (or set
        # DOCKER_RUNNER_TRACE=1 to enable DEBUG output).
        logger.info("docker image for run_bot_in_docker: %s", image)

        # Check docker availability and pull image only if per-run checks are enabled.
        if collect_debug:
            try:
                subprocess.run(['docker', '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except Exception as e:
                # Include the image name in the returned status so callers know which
                # image we attempted to use when docker was not available.
                return '', f'docker-not-available (image={image}): {e}', -1

            # Try to pull the specified image to reduce first-run latency and surface pull errors
            try:
                subprocess.run(['docker', 'pull', image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except Exception:
                # If pull fails, continue; docker run may still work if the image is local
                LAST_RUN_DEBUG['pull_failed'] = True
                LAST_RUN_DEBUG['pull_image'] = image

        # Build docker run command using the chosen image
        # Use --entrypoint to ensure we run python3 with the script path reliably
        cmd = [
            'docker', 'run', '--rm', '-i',
            '--network', 'none',
            '--memory', f'{memory_mb}m',
            '--cpus', str(cpus),
            '--pids-limit', str(pids_limit),
            '--security-opt', 'no-new-privileges',
            '--read-only',
            '--tmpfs', '/tmp:rw',
            # Mount either the ephemeral temporary dir (fast path) or the provided
            # persistent host directory. We mount the directory as /bot in the container.
            '--volume', f'{used_tmpdir}:/bot:ro',
            '--user', '65534:65534',
            '--entrypoint', 'python3',
            image,
            '/bot/bot.py'
        ]

        logger = logging.getLogger(__name__)
        logger.debug("using BOT_TMP_DIR base: %s", tmp_base)
        logger.debug("run_bot_in_docker used_tmpdir=%s bot_path=%s", used_tmpdir, bot_path)
        try:
            logger.debug("used_tmpdir contents: %s", os.listdir(used_tmpdir))
        except Exception as e:
            logger.debug("failed listing used_tmpdir: %s", e)
        logger.debug("docker run cmd: %s", ' '.join(cmd))

        # Auto-detect whether the host bind-mount exposes bot.py inside the
        # container. Many macOS setups (Docker Desktop) require the host path to
        # be explicitly shared; if `bot.py` is visible we use the bind-mount
        # (faster). Otherwise we fall back to create->docker cp->start for
        # reliability. This check is optionally disabled to avoid doing docker
        # checks on every turn; enable with DOCKER_RUNNER_PER_RUN_CHECKS=1 or
        # by enabling console tracing.
        if collect_debug:
            try:
                list_cmd = [
                    'docker', 'run', '--rm', '--network', 'none',
                    '--volume', f'{used_tmpdir}:/bot:ro',
                    image, 'ls', '-la', '/bot'
                ]
                logger.debug("running bind-mount visibility check: %s", ' '.join(list_cmd))
                LAST_RUN_DEBUG['bind_check_cmd'] = ' '.join(list_cmd)
                list_proc = subprocess.run(list_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
                LAST_RUN_DEBUG['bind_check_rc'] = list_proc.returncode
                LAST_RUN_DEBUG['bind_check_stdout'] = (list_proc.stdout or '').strip()
                LAST_RUN_DEBUG['bind_check_stderr'] = (list_proc.stderr or '').strip()
                logger.debug("mount check rc=%s stdout=%s stderr=%s", list_proc.returncode, list_proc.stdout.strip(), (list_proc.stderr or '').strip())
                mount_shows_bot = 'bot.py' in (list_proc.stdout or '')
                LAST_RUN_DEBUG['mount_shows_bot'] = mount_shows_bot
            except Exception as e:
                logger.debug("bind-mount visibility check failed: %s", e)
                LAST_RUN_DEBUG['bind_check_error'] = str(e)
                mount_shows_bot = False
        else:
            # Assume bind-mount will be used (fast path). If it fails, the code
            # below will detect file-access errors and fallback to docker-cp.
            mount_shows_bot = True

        if mount_shows_bot:
            logger.debug("bind-mount exposes bot.py, using docker run with bind-mount")
            if collect_debug:
                LAST_RUN_DEBUG['docker_run_cmd'] = ' '.join(cmd)
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                out, err = proc.communicate(input=input_str, timeout=timeout_ms/1000.0)
                if collect_debug:
                    LAST_RUN_DEBUG['docker_run_rc'] = proc.returncode
                    LAST_RUN_DEBUG['docker_run_stdout'] = (out or '').strip()
                    LAST_RUN_DEBUG['docker_run_stderr'] = (err or '').strip()
                # If the run failed with common file-not-found/permission errors
                # try the docker-cp fallback automatically (useful when the
                # visibility check ran as root but the final container runs
                # as a non-root user and cannot access the bind-mounted file).
                if proc.returncode != 0:
                    lowered = (err or '').lower() + '\n' + (out or '').lower()
                    need_cp_fallback = any(s in lowered for s in ["can't open file '/bot/bot.py'", "cannot open file '/bot/bot.py'", "can't open file \"/bot/bot.py\"", 'no such file or directory', 'permission denied'])
                    if need_cp_fallback:
                        logger.debug("docker run failed with file-access error; attempting docker-cp fallback")
                        out_f, err_f, rc_f = _docker_cp_fallback(bot_path, image, input_str, timeout_ms, memory_mb, cpus, pids_limit, collect_debug=collect_debug)
                        return out_f, err_f, rc_f
                return out, err, proc.returncode
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                return '', 'timeout', -1
        else:
            logger.debug("bind-mount does not expose bot.py; using docker cp fallback")
            return _docker_cp_fallback(bot_path, image, input_str, timeout_ms, memory_mb, cpus, pids_limit, collect_debug=collect_debug)
    finally:
        # Cleanup: remove the temporary directory only if we created it here (i.e. not a persistent dir)
        try:
            if not persistent_dir and created_tmp:
                shutil.rmtree(used_tmpdir)
        except Exception:
            pass
