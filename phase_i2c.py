import os
import re
import time
from typing import List, Optional, Tuple

from .report import Report, PASS, SKIP, INFO
from .utils import sh, have, prompt, SkipPhase
from . import dt_manager


def _i2c_scan_bus() -> Tuple[Optional[List[str]], int]:
    """Scan I2C bus 1. Returns (address_list, uu_count), or (None, 0) on error."""
    rc, out = sh(["i2cdetect", "-y", "1"])
    if rc != 0:
        return None, 0
    addrs, uu = [], 0
    for line in out.splitlines():
        if ":" not in line:
            continue
        cells = line.split(":", 1)[1]
        addrs += re.findall(r"\b[0-9a-f]{2}\b", cells)
        uu += len(re.findall(r"\bUU\b", cells))
    return addrs, uu


def _i2c_report_addrs(rep: Report, addrs: List[str], uu: int, label: str) -> bool:
    """Add a scan result to the report. Returns True if any devices were found."""
    shown = ", ".join("0x" + a for a in addrs)
    extra = f" (+{uu} in-use/UU)" if uu else ""
    if addrs or uu:
        rep.add(label, PASS, f"{len(addrs)} device(s): {shown}{extra}".strip())
        return True
    return False


def phase_i2c(rep: Report) -> None:
    rep.phase("i2c")
    _DT = dt_manager._DT
    buses = sorted(d for d in os.listdir("/dev") if d.startswith("i2c-"))
    if not buses and _DT and _DT.active:
        _DT.enable(rep, "i2c", "dtparam", "i2c_arm=on")
        for _ in range(20):
            buses = sorted(d for d in os.listdir("/dev") if d.startswith("i2c-"))
            if buses:
                break
            time.sleep(0.1)
    if not buses:
        rep.add("I2C bus", SKIP, "no /dev/i2c-* (enable dtparam=i2c_arm=on)")
        return
    rep.add("I2C controller present", PASS, f"/dev/{buses[-1]}")

    if not have("i2cdetect"):
        rep.add("I2C scan", SKIP, "i2cdetect not available (install i2c-tools)")
        return

    addrs, uu = _i2c_scan_bus()
    if addrs is None:
        rep.add("I2C scan", SKIP, "i2cdetect returned an error")
        return
    if _i2c_report_addrs(rep, addrs, uu, "I2C scan (bus 1)"):
        return

    rep.add(
        "I2C scan (bus 1)",
        INFO,
        "0 devices -- I2C can't self-loop like UART/SPI; it needs a real "
        "peripheral. Wire one to SDA=pin3, SCL=pin5, 3V3=pin1, GND=pin6.",
    )
    try:
        prompt(
            rep, "Connect any I2C device (RTC/OLED/sensor), then continue to rescan."
        )
    except SkipPhase:
        return
    addrs, uu = _i2c_scan_bus()
    if not _i2c_report_addrs(rep, addrs or [], uu, "I2C scan (rescan)"):
        rep.add(
            "I2C scan (rescan)",
            INFO,
            "still 0 -- check 3V3/GND, confirm SDA/SCL aren't swapped, and that "
            "the device needs no extra address pins tied",
        )
