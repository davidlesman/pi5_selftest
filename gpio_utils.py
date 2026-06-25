from typing import Dict, Tuple

from .report import Report, INFO
from .utils import sh, have
from .config import GPIO_LOOPBACK_PAIRS
from . import dt_manager


BCM_TO_PIN = {
    0: 27,
    1: 28,
    2: 3,
    3: 5,
    4: 7,
    5: 29,
    6: 31,
    7: 26,
    8: 24,
    9: 21,
    10: 19,
    11: 23,
    12: 32,
    13: 33,
    14: 8,
    15: 10,
    16: 36,
    17: 11,
    18: 12,
    19: 35,
    20: 38,
    21: 40,
    22: 15,
    23: 16,
    24: 18,
    25: 22,
    26: 37,
    27: 13,
}


def _bp(bcm: int) -> str:
    """Format a BCM GPIO number as 'BCMn/pinp' for unambiguous output."""
    return f"BCM{bcm}/pin{BCM_TO_PIN.get(bcm, '?')}"


# Known alternate-function pins and the bus that owns them.
_BUS_PIN_ROLE = {
    2: "I2C1 SDA",
    3: "I2C1 SCL",
    7: "SPI0 CE1",
    8: "SPI0 CE0",
    9: "SPI0 MISO",
    10: "SPI0 MOSI",
    11: "SPI0 SCLK",
    14: "UART0 TXD",
    15: "UART0 RXD",
}


def _bus_skip_reason(src: int, dst: int) -> str:
    """Explain why a loopback pair is busy because of an active bus driver."""
    roles = [f"GPIO{p} = {_BUS_PIN_ROLE[p]}" for p in (src, dst) if p in _BUS_PIN_ROLE]
    if roles:
        bus = _BUS_PIN_ROLE[src if src in _BUS_PIN_ROLE else dst].split()[0]
        phase = {"SPI0": "SPI", "UART0": "UART", "I2C1": "I2C"}.get(bus, bus)
        return (
            f"held by the {bus} driver ({'; '.join(roles)}) while that bus is "
            f"enabled -- exercised by the {phase} phase instead, not as plain GPIO"
        )
    return (
        f"line reserved by another driver "
        f"(run: gpioinfo | grep -E 'GPIO{src}|GPIO{dst}')"
    )


def _pin_func_map(pins: str) -> Tuple[Dict[int, str], str]:
    raw = ""
    for tool in (["pinctrl", "get", pins], ["raspi-gpio", "get", pins]):
        if have(tool[0]):
            rc, out = sh(tool)
            if rc == 0 and out:
                raw = out
                break
    funcs: Dict[int, str] = {}
    for line in raw.splitlines():
        import re

        m = re.search(r"(?:GPIO\s*)?(\d+)\s*[:=]", line)
        if m:
            funcs[int(m.group(1))] = line.strip()
    return funcs, raw


def _import_gpiozero():
    """Import and return (DigitalOutputDevice, InputDevice), or None on failure."""
    try:
        # InputDevice (not DigitalInputDevice): we only ever read the level, and
        # DigitalInputDevice spins up an lgpio edge-detection callback thread per
        # pin whose late callbacks crash once the pin factory is closed.
        from gpiozero import DigitalOutputDevice, InputDevice

        return DigitalOutputDevice, InputDevice
    except Exception:  # noqa: BLE001
        return None


def _free_header_lines(rep: Report) -> None:
    """Release any interfaces this run enabled, and report boot-time interfaces
    that still hold header pins."""
    _DT = dt_manager._DT
    if _DT and _DT.active and _DT.added:
        _DT.restore()
        rep.add(
            "freed runtime overlays", INFO, "removed interfaces this run had enabled"
        )
    boot = dt_manager.boot_enabled_interfaces()
    if boot:
        cfg = dt_manager.boot_config_path()
        for key, line in boot.items():
            rep.add(
                f"boot-time interface: {key}",
                INFO,
                f"holds header pins; comment out in {cfg} + reboot to free",
            )


def _print_gpio_wiring() -> None:
    """Print the physical-pin jumper map so wiring is unambiguous."""
    print("      GPIO loopback wiring -- jumper these physical pin pairs:")
    for a, b in GPIO_LOOPBACK_PAIRS:
        if {a, b} == {14, 15}:
            tag = "   <- same as UART jumper (leave it in)"
        elif {a, b} == {9, 10}:
            tag = "   <- same as SPI jumper (leave it in)"
        elif {a, b} == {0, 1}:
            tag = "   (ID EEPROM pins; may SKIP if a HAT holds them)"
        else:
            tag = ""
        print(
            f"        pin{BCM_TO_PIN[a]:<2} <-> pin{BCM_TO_PIN[b]:<2}"
            f"   ({_bp(a)} <-> {_bp(b)}){tag}"
        )
    print("      NEVER wire to a 5V / 3.3V / GND pin.")
