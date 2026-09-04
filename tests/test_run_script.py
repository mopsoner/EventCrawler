import os
import subprocess
import time
from pathlib import Path


RUN_SCRIPT = Path(__file__).parents[1] / "run.sh"


def _fake_checkout(tmp_path: Path) -> tuple[Path, Path]:
    checkout = tmp_path / "checkout"
    python = checkout / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    (checkout / "run.sh").write_bytes(RUN_SCRIPT.read_bytes())
    (python.parent / "activate").write_text(":\n")
    python.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s %s\\n' \"$1\" \"$$\" >> \"$EVENTCRAWLER_TEST_LOG\"
if [ \"$1\" = scheduler.py ]; then
  if [ \"${EVENTCRAWLER_SCHEDULER_EXIT:-0}\" = 1 ]; then sleep 0.1; exit 0; fi
  trap 'printf stopped >> \"$EVENTCRAWLER_SCHEDULER_STOPPED\"; exit 0' TERM
  while :; do sleep 0.05; done
fi
while :; do sleep 0.05; done
"""
    )
    python.chmod(0o755)
    return checkout, python


def test_run_starts_both_processes_and_stops_scheduler_on_shutdown(tmp_path):
    checkout, _ = _fake_checkout(tmp_path)
    log = tmp_path / "commands.log"
    stopped = tmp_path / "scheduler.stopped"
    env = {
        **os.environ,
        "EVENTCRAWLER_TEST_LOG": str(log),
        "EVENTCRAWLER_SCHEDULER_STOPPED": str(stopped),
    }

    process = subprocess.Popen(["bash", "run.sh"], cwd=checkout, env=env)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if log.exists() and len(log.read_text().splitlines()) == 2:
            break
        time.sleep(0.05)
    else:
        process.kill()
        raise AssertionError("run.sh did not start both processes")

    process.terminate()
    assert process.wait(timeout=5) == 143
    assert {line.split()[0] for line in log.read_text().splitlines()} == {
        "scheduler.py",
        "app.py",
    }
    assert stopped.read_text() == "stopped"


def test_run_fails_and_stops_app_when_scheduler_exits_early(tmp_path):
    checkout, _ = _fake_checkout(tmp_path)
    log = tmp_path / "commands.log"
    env = {
        **os.environ,
        "EVENTCRAWLER_TEST_LOG": str(log),
        "EVENTCRAWLER_SCHEDULER_STOPPED": str(tmp_path / "unused"),
        "EVENTCRAWLER_SCHEDULER_EXIT": "1",
    }

    result = subprocess.run(
        ["bash", "run.sh"],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert "scheduler.py stopped unexpectedly" in result.stderr
    assert {line.split()[0] for line in log.read_text().splitlines()} == {
        "scheduler.py",
        "app.py",
    }
