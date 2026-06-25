import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from .report import Report


@dataclass
class _RunConfig:
    auto: bool = False  # when True, interactive prompts auto-skip (--auto)
    dt_enabled: bool = True  # when False, skip runtime dtparam/dtoverlay (--no-dt)


_cfg = _RunConfig()


class SkipPhase(Exception):
    """Raised from prompt() to abandon the current phase cleanly."""


def sh(cmd, timeout=15) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: timed out"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def read(path: str) -> Optional[str]:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def _poll(fn, timeout, interval=0.4):
    """Call fn() until it returns something truthy or `timeout` seconds elapse."""
    deadline = time.time() + timeout
    val = fn()
    while not val and time.time() < deadline:
        time.sleep(interval)
        val = fn()
    return val


def is_root() -> bool:
    return os.geteuid() == 0


def prompt(rep: Report, msg: str) -> bool:
    """Ask the user to do something physical, then continue."""
    if _cfg.auto:
        raise SkipPhase
    try:
        resp = (
            input(
                f"\n  >>> {msg}\n"
                f"      [Enter] do it   |   [s] + Enter skip this phase   |   "
                f"Ctrl-C skip phase\n      > "
            )
            .strip()
            .lower()
        )
    except (KeyboardInterrupt, EOFError):
        print()
        raise SkipPhase
    if resp in ("s", "skip", "n", "no", "q"):
        raise SkipPhase
    return True
