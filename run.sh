#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ -d .git ]; then
  git pull --ff-only || true
fi

. .venv/bin/activate

.venv/bin/python scheduler.py &
SCHEDULER_PID=$!
APP_PID=""

cleanup() {
  # Disable the signal traps while cleaning up so repeated signals cannot make
  # cleanup race with itself.
  trap - INT TERM

  kill "$SCHEDULER_PID" 2>/dev/null || true
  wait "$SCHEDULER_PID" 2>/dev/null || true

  if [ -n "$APP_PID" ]; then
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Keep the web server as run.sh's primary workload, while supervising both
# processes so a scheduler failure cannot go unnoticed.
.venv/bin/python app.py &
APP_PID=$!

set +e
wait -n "$SCHEDULER_PID" "$APP_PID"
STATUS=$?
set -e

if ! kill -0 "$SCHEDULER_PID" 2>/dev/null; then
  echo "scheduler.py stopped unexpectedly; stopping app.py" >&2
  if [ "$STATUS" -eq 0 ]; then
    STATUS=1
  fi
fi

exit "$STATUS"
