import time

from .report import Report, PASS, FAIL, SKIP
from .utils import prompt
from .config import PULL_TEST_PINS
from .gpio_utils import _bp, _free_header_lines


def phase_pulls(rep: Report) -> None:
    rep.phase("pulls")
    pin_list = ", ".join(_bp(p) for p in PULL_TEST_PINS)
    if not prompt(
        rep,
        f"Remove jumpers tying these pins to 3V3/5V/GND: {pin_list}. "
        "(A jumper between two of these GPIOs is now tolerated.)",
    ):
        return
    _free_header_lines(rep)
    # The gpio phase used gpiozero, whose lgpio factory keeps its chip handle
    # and line reservations open for the whole process. Release it first, or
    # our separate lgpio handle below gets "GPIO busy" on every pin.
    try:
        from gpiozero import Device

        if Device.pin_factory is not None:
            Device.pin_factory.close()
            Device.pin_factory = None
    except Exception:  # noqa: BLE001
        pass
    try:
        import lgpio
    except Exception:  # noqa: BLE001
        rep.add("lgpio import", FAIL, "pip install lgpio")
        return
    try:
        h = lgpio.gpiochip_open(0)
    except Exception as e:  # noqa: BLE001
        rep.add("gpiochip open", FAIL, str(e))
        return
    try:
        for pin in PULL_TEST_PINS:
            reads = {}
            busy = False
            err = None
            try:
                for pull, flag in (
                    ("up", lgpio.SET_PULL_UP),
                    ("down", lgpio.SET_PULL_DOWN),
                ):
                    lgpio.gpio_claim_input(h, pin, flag)
                    time.sleep(0.01)
                    reads[pull] = lgpio.gpio_read(h, pin)
                    lgpio.gpio_free(h, pin)
                # Actively clear the pad bias to NONE before moving on, so this
                # pin can't drag a wired neighbour low/high on the next pin's
                # test (closing a line does NOT clear its pull on its own).
                lgpio.gpio_claim_input(h, pin, lgpio.SET_PULL_NONE)
                lgpio.gpio_free(h, pin)
            except lgpio.error as e:
                msg = str(e)
                if "busy" in msg.lower():
                    busy = True
                else:
                    err = msg
                try:
                    lgpio.gpio_free(h, pin)
                except Exception:  # noqa: BLE001
                    pass
            if busy:
                rep.add(f"{_bp(pin)} pulls", SKIP, "line reserved by another driver")
            elif err:
                rep.add(f"{_bp(pin)} pulls", FAIL, err)
            else:
                up, dn = reads.get("up"), reads.get("down")
                ok = up == 1 and dn == 0
                rep.add(
                    f"{_bp(pin)} pulls",
                    PASS if ok else FAIL,
                    f"pull-up read {up}, pull-down read {dn}"
                    + ("" if ok else "  <- pin tied to a fixed level (rail short?)"),
                )
    finally:
        try:
            lgpio.gpiochip_close(h)
        except Exception:  # noqa: BLE001
            pass
