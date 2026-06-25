import os
import re
from .report import Report, PASS, FAIL, INFO
from .utils import sh, have, read


def phase_identify(rep: Report) -> bool:
    rep.phase("identify")

    model = (
        (read("/sys/firmware/devicetree/base/model") or "").replace("\x00", "").strip()
    )
    rep.add("Board model", INFO, model or "unknown")

    for line in (read("/proc/cpuinfo") or "").splitlines():
        if line.lower().startswith("revision"):
            rep.add("Board revision", INFO, line.split(":")[-1].strip())

    is_pi5 = "Raspberry Pi 5" in model
    rep.add(
        "Is a Raspberry Pi 5",
        PASS if is_pi5 else FAIL,
        "" if is_pi5 else "pin maps below assume a Pi 5",
    )

    max_current_enabled = False

    if have("vcgencmd"):
        v_rc, v_out = sh(["vcgencmd", "get_config", "usb_max_current_enable"])
        if v_rc == 0 and "1" in v_out.split("=")[-1]:
            max_current_enabled = True

    if not max_current_enabled:
        for config_path in ["/boot/firmware/config.txt", "/boot/config.txt"]:
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        for line in f:
                            if re.match(r"^\s*usb_max_current_enable\s*=\s*1", line):
                                max_current_enabled = True
                                break
                except OSError:
                    pass
            if max_current_enabled:
                break

    rep.add(
        "USB Max Current Enable",
        PASS if max_current_enabled else FAIL,
        "usb_max_current_enable=1 (1600mA high-power pool active)"
        if max_current_enabled
        else "usb_max_current_enable=0 (Restricted to 600mA, high-draw USB3 storage will brown out)",
    )

    rc, out = sh(["gpiodetect"])
    if rc == 0:
        chip = next(
            (
                line.split()[0]
                for line in out.splitlines()
                if "rp1" in line.lower() or "pinctrl" in line.lower()
            ),
            "?",
        )
        rep.add(
            "RP1 header gpiochip",
            PASS if chip != "?" else INFO,
            f"{chip}  ({out.replace(chr(10), ' | ')})",
        )

    return is_pi5
