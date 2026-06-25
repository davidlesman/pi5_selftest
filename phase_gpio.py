import time

from .report import Report, PASS, FAIL, SKIP
from .utils import prompt
from .config import GPIO_LOOPBACK_PAIRS
from .gpio_utils import (
    _bp,
    _bus_skip_reason,
    _import_gpiozero,
    _free_header_lines,
    _print_gpio_wiring,
)


def phase_gpio(rep: Report) -> None:
    rep.phase("gpio")
    _print_gpio_wiring()
    if not prompt(
        rep, f"Wire the {len(GPIO_LOOPBACK_PAIRS)} GPIO loopback pairs listed above."
    ):
        return
    _free_header_lines(rep)
    gpiozero_devices = _import_gpiozero()
    if not gpiozero_devices:
        rep.add("gpiozero import", FAIL, "pip install gpiozero lgpio")
        return
    DOut, DIn = gpiozero_devices
    for a, b in GPIO_LOOPBACK_PAIRS:
        for src, dst in ((a, b), (b, a)):
            o = i = None
            try:
                o = DOut(src)
                i = DIn(dst, pull_up=None, active_state=True)
                ok, detail = True, ""
                for lvl in (1, 0, 1, 0):
                    o.value = lvl
                    time.sleep(0.002)
                    if int(i.value) != lvl:
                        ok = False
                        detail = (
                            f"drove {lvl} on BCM{src}, read {int(i.value)} on BCM{dst}"
                        )
                        break
                rep.add(f"GPIO {_bp(src)} -> {_bp(dst)}", PASS if ok else FAIL, detail)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "busy" in msg.lower():
                    rep.add(
                        f"GPIO {_bp(src)} -> {_bp(dst)}",
                        SKIP,
                        _bus_skip_reason(src, dst),
                    )
                else:
                    rep.add(f"GPIO {_bp(src)} -> {_bp(dst)}", FAIL, msg)
            finally:
                for dev in (o, i):
                    try:
                        dev and dev.close()
                    except Exception:  # noqa: BLE001
                        pass
