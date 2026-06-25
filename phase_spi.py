import glob
import os

from .report import Report, PASS, FAIL, SKIP
from .utils import sh, have, _poll, prompt
from .config import SPI_BUS, SPI_DEV, SPI_HZ
from .gpio_utils import _pin_func_map
from . import dt_manager


def phase_spi(rep: Report) -> None:
    rep.phase("spi")
    if not prompt(rep, "Jumper GPIO10 (pin 19, MOSI) to GPIO9 (pin 21, MISO)."):
        return
    try:
        import spidev
    except Exception:  # noqa: BLE001
        rep.add("spidev import", FAIL, "pip install spidev")
        return

    _DT = dt_manager._DT
    node = f"/dev/spidev{SPI_BUS}.{SPI_DEV}"
    if not os.path.exists(node) and _DT and _DT.active:
        _DT.enable(rep, "spi", "dtparam", "spi=on")
        if have("modprobe"):
            sh(["modprobe", "spidev"])
        _poll(lambda: os.path.exists(node), 5)
    if not os.path.exists(node):
        bus_up = bool(glob.glob("/sys/bus/spi/devices/spi*"))
        hint = (
            "the SPI controller IS up (spi0.x present) but the spidev node "
            "did not bind at runtime -- this is not a wiring issue. "
            if bus_up
            else ""
        )
        rep.add(
            "SPI loopback",
            SKIP,
            f"{node} not created. {hint}Add 'dtparam=spi=on' to "
            f"{dt_manager.boot_config_path() or 'config.txt'} and reboot for a reliable node",
        )
        return
    spi = None
    try:
        spi = spidev.SpiDev()
        spi.open(SPI_BUS, SPI_DEV)
        spi.max_speed_hz = SPI_HZ
        spi.mode = 0
        tx = [0x00, 0x01, 0x55, 0xAA, 0xFF, 0x7E]
        rx = spi.xfer2(list(tx))
        if rx == tx:
            rep.add("SPI MOSI->MISO", PASS, "")
        else:
            funcs, raw = _pin_func_map("9-11")
            not_spi = [p for p in (9, 10, 11) if "SPI" not in funcs.get(p, "").upper()]
            if funcs and not_spi:
                why = (
                    f"GPIO{','.join(map(str, not_spi))} NOT in SPI mode -- an "
                    f"overlay/HAT claimed them. Check config.txt. [{raw.splitlines()}]"
                )
            elif funcs:
                why = (
                    "GPIO9/10/11 ARE in SPI mode, so the bus is configured "
                    "right -- this is the MOSI<->MISO jumper: re-seat pin19<->pin21"
                )
            else:
                why = "re-seat the MOSI<->MISO jumper (pin19<->pin21)"
            rep.add("SPI MOSI->MISO", FAIL, f"sent {tx}, got {rx}; {why}")
    except Exception as e:  # noqa: BLE001
        rep.add("SPI MOSI->MISO", FAIL, str(e))
    finally:
        try:
            spi and spi.close()
        except Exception:  # noqa: BLE001
            pass
