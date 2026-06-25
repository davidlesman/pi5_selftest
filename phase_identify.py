from .report import Report, PASS, FAIL, INFO
from .utils import sh


def phase_identify(rep: Report) -> bool:
    rep.phase("identify")
    from .utils import read

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
