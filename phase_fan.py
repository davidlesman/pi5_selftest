import glob
import os
import time
from typing import Optional

from .report import Report, PASS, FAIL, SKIP, INFO
from .utils import read, is_root


def _fan_rpm() -> Optional[int]:
    for p in glob.glob("/sys/class/hwmon/hwmon*/fan1_input") + glob.glob(
        "/sys/devices/platform/cooling_fan/hwmon/*/fan1_input"
    ):
        v = read(p)
        if v is not None:
            try:
                return int(v)
            except ValueError:
                pass
    return None


def phase_fan(rep: Report) -> None:
    rep.phase("fan")
    rpm = _fan_rpm()
    if rpm is None:
        rep.add("Cooling fan", INFO, "no fan tachometer (none fitted?)")
        return
    rep.add("Fan tachometer", PASS, f"{rpm} RPM at rest")
    cdev = None
    for d in glob.glob("/sys/class/thermal/cooling_device*"):
        if "fan" in (read(f"{d}/type") or "").lower() or os.path.exists(
            f"{d}/cur_state"
        ):
            cdev = d
            break
    if not cdev:
        rep.add("Fan spin-up test", SKIP, "no cooling_device control node")
        return
    if not is_root():
        rep.add("Fan spin-up test", SKIP, "needs sudo to drive the fan")
        return
    maxs = read(f"{cdev}/max_state") or "3"
    prev = read(f"{cdev}/cur_state") or "0"
    try:
        with open(f"{cdev}/cur_state", "w") as fh:
            fh.write(str(maxs))
        time.sleep(0.7)
        hi = _fan_rpm() or 0
        ok = hi > rpm + 200
        rep.add(
            "Fan spin-up test",
            PASS if ok else FAIL,
            f"{rpm} -> {hi} RPM when commanded to level {maxs}",
        )
    except PermissionError:
        rep.add("Fan spin-up test", SKIP, "permission denied")
    finally:
        try:
            with open(f"{cdev}/cur_state", "w") as fh:
                fh.write(prev)
        except OSError:
            pass
