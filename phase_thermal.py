import re

from .report import Report, PASS, FAIL, SKIP
from .utils import sh, have
from .config import TEMP_LIMIT_C, THROTTLE_BITS_NOW, THROTTLE_BITS_PAST
from . import config


def phase_thermal(rep: Report) -> None:
    rep.phase("thermal")
    if not have("vcgencmd"):
        rep.add("vcgencmd", SKIP, "install raspberrypi-utils")
        return
    rc, out = sh(["vcgencmd", "measure_temp"])
    m = re.search(r"temp=([\d.]+)", out)
    if m:
        t = float(m.group(1))
        rep.add("SoC temperature", PASS if t < TEMP_LIMIT_C else FAIL, f"{t:.1f} C",
                metric=config.accept_check("soc_temp_idle_C", t))
    rc, out = sh(["vcgencmd", "get_throttled"])
    if "throttled=" not in out:
        return
    hexval = out.split("=")[1]
    val = int(hexval, 16)
    now = [name for bit, name in THROTTLE_BITS_NOW if val & bit]
    past = [name for bit, name in THROTTLE_BITS_PAST if val & bit]
    if now:
        rep.add(
            "Throttle / under-voltage",
            FAIL,
            f"{hexval}: ACTIVE now -- {', '.join(now)}",
        )
    elif past:
        rep.add(
            "Throttle / under-voltage",
            PASS,
            f"{hexval}: clear now, but {', '.join(past)} occurred since "
            "boot -- check the power supply",
        )
    else:
        rep.add("Throttle / under-voltage", PASS, f"{hexval} (clean)")
