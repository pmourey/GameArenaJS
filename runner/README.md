Runner folder notes

This README explains the Docker mount/fallback behavior for the runner and provides quick debug steps.

Background

- On macOS Docker Desktop, arbitrary host paths (like /tmp) are not always visible to the Docker VM unless explicitly shared in Docker Desktop Preferences → Resources → File Sharing.
- The project uses a Docker-based bot runner to execute user-submitted bots. Bind-mounting a host tmp dir into the container may fail to expose the bot file on some developer machines.

What we changed

- The Docker runner now forces a "create -> docker cp -> start -a -i" workflow by default. This creates a short-lived container, copies the generated `bot.py` into it, and starts the container attached. This avoids relying on host bind-mount visibility and works reliably on Docker Desktop macOS.

- Configuration / environment variables:
  - BOT_TMP_DIR: directory base used to create temporary bot dirs (default /tmp). Use this to point to a host path that is actually shared with Docker Desktop.
  - BOT_DOCKER_IMAGE: docker image used for bot execution (default python:3.11-slim).
  - ALLOW_DOCKER_CP_FALLBACK: (legacy) when set to 1/true/yes allowed older code paths to try docker-cp fallback.
  - BOT_RUNNER: 'auto'|'docker'|'subprocess' (default 'auto'). In 'auto' mode, the SDK prefers local subprocess when the referee's time budget is tiny (<=200ms) to avoid container startup latency.

How to test locally

1) Quick mount test (recommended):

```bash
# use a folder under your $HOME so Docker Desktop can share it easily
./runner/run_local_mount_test.sh "$HOME/gamearena-bot-test"
```

If the non-root run prints `MOVE 1 0`, mounts and permissions are OK for the non-root user used by the runner.

2) Test the app verify endpoint (executes a tiny bot through the runner):

```bash
# optionally force /tmp base
export BOT_TMP_DIR=/tmp
# start the Flask app
python3 app.py
# in another terminal
curl -sS http://127.0.0.1:3000/api/runner/verify | jq .
```

Look in the app console for DEBUG logs from `runner/docker_runner` (the app enables debug logging). Key lines to inspect:
- `run_bot_in_docker tmpdir=... bot_path=...`
- `tmpdir contents: ...`
- `forcing docker cp fallback (default)`
- `created container id: ...`
- `docker cp ... -> ...:/bot/bot.py`
- `docker start -a -i ...`

If verify returns rc 0 and stdout `PING\n` the runner works.

3) If bind-mounts are still desirable: open Docker Desktop -> Preferences -> Resources -> File Sharing and add the host path you mount (or use a folder under your $HOME).

Security note

- The `docker cp` fallback is convenient for development and CI in environments where volume mounts are unreliable. For production you should build a minimal runtime image and avoid copying user files at runtime or running as root.

Contact

If you still see problems after following the steps above, please paste the JSON output from `/api/runner/verify` and the DEBUG logs printed to the Flask console and I will investigate further.

