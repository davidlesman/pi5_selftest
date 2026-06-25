import os
import time
from typing import Optional

from .report import Report, PASS, FAIL, SKIP
from .utils import _poll, prompt
from .config import UART_BAUD
from . import dt_manager


def _gpio_uart_device() -> Optional[str]:
    """Locate the GPIO UART device node."""
    if os.path.exists("/dev/ttyAMA0"):
        return "/dev/ttyAMA0"
    try:
        if os.path.realpath("/dev/serial0").endswith("ttyAMA0"):
            return "/dev/serial0"
    except OSError:
        pass
    return None


def phase_uart(rep: Report) -> None:
    rep.phase("uart")
    if not prompt(
        rep,
        "Jumper GPIO14 (pin 8, TXD) to GPIO15 (pin 10, RXD). "
        "Make sure the serial login console is DISABLED.",
    ):
        return
    try:
        import serial
    except Exception:  # noqa: BLE001
        rep.add("pyserial import", FAIL, "pip install pyserial")
        return

    _DT = dt_manager._DT
    dev = _gpio_uart_device()
    if dev is None and _DT and _DT.active:
        _DT.enable(rep, "uart", "dtoverlay", "uart0-pi5")
        dev = _poll(_gpio_uart_device, 3)
    if dev is None:
        rep.add(
            "UART loopback",
            SKIP,
            "GPIO14/15 UART (/dev/ttyAMA0) not available. Runtime enable is "
            "unreliable for UART on Pi 5 -- add 'dtoverlay=uart0-pi5' to "
            f"{dt_manager.boot_config_path() or 'config.txt'} (or raspi-config Serial "
            "Port: login shell NO, hardware YES) and reboot",
        )
        return
    s = None
    try:
        s = serial.Serial(dev, UART_BAUD, timeout=1)
        msg = b"PI5-UART-LOOPBACK-0123456789\n"
        s.reset_input_buffer()
        s.write(msg)
        s.flush()
        time.sleep(0.05)
        got = s.read(len(msg))
        rep.add(
            "UART TXD->RXD",
            PASS if got == msg else FAIL,
            f"via {dev}" if got == msg else f"sent {msg!r}, got {got!r}",
        )
    except Exception as e:  # noqa: BLE001
        rep.add("UART TXD->RXD", FAIL, str(e))
    finally:
        try:
            s and s.close()
        except Exception:  # noqa: BLE001
            pass
