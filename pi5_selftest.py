#!/usr/bin/env python3
"""
pi5_selftest.py - Comprehensive hardware self-test for the Raspberry Pi 5.

Runs as a sequence of PHASES. Some are fully automatic; others are interactive
(they ask you to wire a jumper or plug in a device, then press Enter).

  Automatic (no wiring, no hardware):
    identify  - board model / revision / RP1 gpiochip
    thermal   - SoC temperature + throttling/under-voltage flags
    power     - PMIC rail voltages/currents (incl. header 5V & 3.3V rails)
    i2c       - I2C bus present + scan
    pcie      - PCIe enumeration + link speed (+ NVMe FS r/w if mounted)
    ethernet  - interface up, negotiated speed, ping the gateway
    rtc       - onboard real-time clock
    fan       - read RPM, then actively spin it up and confirm it responds

  Interactive HARDWARE (need a device plugged in):
    usb       - test each of the 4 USB ports with a flash drive
    mipi      - enumerate CAM0/CAM1 cameras and capture a still

  Interactive WIRING (need jumper wires on the 40-pin header):
    gpio      - pin-pair loopback over all 26 user GPIOs (both directions)
    pulls     - internal pull-up / pull-down resistors
    uart      - GPIO14 TXD -> GPIO15 RXD loopback
    spi       - GPIO10 MOSI -> GPIO9 MISO loopback

Usage:
    sudo python3 pi5_selftest.py full            # everything, with prompts
    python3 pi5_selftest.py full --auto          # only automatic phases
    sudo python3 pi5_selftest.py full --skip usb,mipi   # run all but these
    sudo python3 pi5_selftest.py gpio uart        # just these phases
    sudo python3 pi5_selftest.py full --repeat 5  # run the suite 5x (burn-in)
    sudo python3 pi5_selftest.py full --json report.json

At any interactive prompt: press Enter to do the step, or type 's' + Enter
(or Ctrl-C) to skip the rest of that phase. So with nothing plugged in, the
USB and camera phases are one keystroke to move past.

Runtime interface management (needs sudo): the SPI, I2C and UART phases will
auto-enable their interface at runtime (dtparam/dtoverlay) if it isn't already
on, and the GPIO/pulls phases drop anything this run enabled so the pins are
free. This canNOT undo interfaces set in config.txt (those are baked in at
boot) -- for a fully clean GPIO sweep, remove spi/i2c/w1 from config.txt and
let this script enable them per-phase instead. Disable all of this with --no-dt.

Run with sudo: the fan, PMIC, camera, and auto-enable features need root.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict
from typing import Dict, List, Optional

from . import dt_manager
from .report import Report, FAIL, SKIP, INFO
from .utils import sh, have, is_root, _cfg, SkipPhase
from .dt_manager import DTManager

from .phase_identify import phase_identify
from .phase_thermal import phase_thermal
from .phase_power import phase_power
from .phase_i2c import phase_i2c
from .phase_pcie import phase_pcie
from .phase_ethernet import phase_ethernet
from .phase_rtc import phase_rtc
from .phase_fan import phase_fan
from .phase_usb import phase_usb
from .phase_mipi import phase_mipi
from .phase_gpio import phase_gpio
from .phase_pulls import phase_pulls
from .phase_uart import phase_uart
from .phase_spi import phase_spi

PHASES = {
    "identify": phase_identify,
    "thermal": phase_thermal,
    "power": phase_power,
    "i2c": phase_i2c,
    "pcie": phase_pcie,
    "ethernet": phase_ethernet,
    "rtc": phase_rtc,
    "fan": phase_fan,
    "usb": phase_usb,
    "mipi": phase_mipi,
    "gpio": phase_gpio,
    "pulls": phase_pulls,
    "uart": phase_uart,
    "spi": phase_spi,
}

# Within wiring, bus loopbacks (uart, spi) MUST come before bare-GPIO phases:
# the gpio phase claims GPIO9/10/11 (SPI) and 14/15 (UART) as plain GPIO,
# dropping them out of bus mode for the rest of the session.
FULL_ORDER = [
    "identify",
    "thermal",
    "power",
    "i2c",
    "pcie",
    "ethernet",
    "rtc",
    "fan",
    "usb",
    "mipi",
    "uart",
    "spi",
    "gpio",
    "pulls",
]

_BUS_MUX_SNAPSHOT: Dict[int, str] = {}


def _snapshot_bus_mux() -> None:
    """Record the boot-time alt-function of every header GPIO BEFORE any phase
    runs, so we can put bus pins (SPI/UART/I2C) back exactly as they were after
    the gpio phase claims them as plain GPIO. Only alt funcs (a0..a5) matter."""
    global _BUS_MUX_SNAPSHOT
    _BUS_MUX_SNAPSHOT = {}
    if not have("pinctrl"):
        return
    rc, out = sh(["pinctrl", "get", "0-27"])
    if rc != 0:
        return
    for line in out.splitlines():
        m = re.match(r"\s*(\d+):\s*(a[0-5])\b", line)
        if m:
            _BUS_MUX_SNAPSHOT[int(m.group(1))] = m.group(2)


def _restore_bus_mux(rep: Optional[Report] = None) -> None:
    """Put bus pins back into the alt mode they had at boot.

    CRITICAL ORDER: release gpiozero/lgpio line claims FIRST -- otherwise,
    when this process exits, lgpio frees those lines and the kernel resets them
    to input, clobbering the mux we set here. After releasing, the pinctrl set
    sticks because nothing holds the lines anymore."""
    if not (is_root() and have("pinctrl")):
        return
    try:
        from gpiozero import Device

        pf = Device.pin_factory
        if pf is not None:
            pf.close()
            Device.pin_factory = None  # force a fresh factory on the next run
    except Exception:  # noqa: BLE001
        pass
    restored = []
    for pin, func in _BUS_MUX_SNAPSHOT.items():
        rc, _ = sh(["pinctrl", "set", str(pin), func])
        if rc == 0:
            restored.append(pin)
    if rep is not None and restored:
        rep.add(
            "bus pin mux restored",
            INFO,
            f"re-applied boot functions to GPIO {sorted(restored)} so SPI/UART/"
            "I2C keep working on repeated runs without a reboot",
        )


def _run_once(order, skip) -> Report:
    rep = Report()
    dt_manager._DT = DTManager()
    _snapshot_bus_mux()
    if dt_manager._DT.active:
        print(
            "  Runtime interface management: ON (SPI/I2C/UART auto-enabled "
            "per phase, restored at end). Use --no-dt to disable."
        )
    try:
        for p in order:
            if p in skip:
                rep.phase(p)
                rep.add(f"phase {p}", SKIP, "skipped via --skip")
                continue
            try:
                PHASES[p](rep)
            except SkipPhase:
                rep.add(f"phase {p}", SKIP, "skipped by user")
            except KeyboardInterrupt:
                print("\n  (phase interrupted, moving on)")
            except Exception as e:  # noqa: BLE001
                rep.add(f"phase {p} crashed", FAIL, str(e))
    finally:
        if dt_manager._DT:
            dt_manager._DT.restore()
        _restore_bus_mux(rep)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Raspberry Pi 5 comprehensive hardware self-test.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "phases",
        nargs="*",
        default=["full"],
        help="'full', or any of: " + ", ".join(PHASES),
    )
    ap.add_argument(
        "--auto",
        action="store_true",
        help="skip all interactive (wiring / plug-in) steps",
    )
    ap.add_argument(
        "--skip",
        metavar="PHASES",
        default="",
        help="comma-separated phases to skip entirely, e.g. usb,mipi",
    )
    ap.add_argument(
        "--no-dt",
        action="store_true",
        help="do NOT auto enable/disable interfaces (SPI/I2C/UART) "
        "at runtime; you manage them yourself",
    )
    ap.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="run the whole suite N times in a row (burn-in). "
        "Pairs well with --auto for unattended runs.",
    )
    ap.add_argument("--json", metavar="PATH", help="write a JSON report")
    args = ap.parse_args()

    _cfg.auto = args.auto
    _cfg.dt_enabled = not args.no_dt
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    if "full" in args.phases:
        order = FULL_ORDER
    else:
        bad = [p for p in args.phases if p not in PHASES]
        if bad:
            ap.error(f"unknown phase(s): {bad}")
        order = args.phases

    print("=" * 66)
    print("  Raspberry Pi 5 Comprehensive Hardware Self-Test")
    if not is_root():
        print("  (note: not running as root -- fan/RTC/PMIC and auto-enable skip)")
    print("=" * 66)

    runs: List[Report] = []
    interactive = (not _cfg.auto) and sys.stdin.isatty()
    run_no = 0
    while True:
        run_no += 1
        if args.repeat > 1 or run_no > 1:
            print(f"\n\033[1m##### RUN {run_no} #####\033[0m")
        rep = _run_once(order, skip)
        rep.summary()
        runs.append(rep)
        if run_no < args.repeat:
            continue
        if not interactive:
            break
        try:
            again = input("\n  Run the whole suite again? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if again not in ("y", "yes"):
            break

    # Aggregate across runs
    total_fail = sum(sum(r.status == FAIL for r in rep.results) for rep in runs)
    if len(runs) > 1:
        print("\n" + "=" * 66)
        print(f"  OVERALL: {len(runs)} runs, {total_fail} failed check(s) total")
        failures = [
            f"    - run {idx} [{r.phase}] {r.name}: {r.detail}"
            for idx, rep in enumerate(runs, 1)
            for r in rep.results
            if r.status == FAIL
        ]
        if failures:
            print("  Failures across runs:")
            print("\n".join(failures))
        print("=" * 66)

    if args.json:
        with open(args.json, "w") as fh:
            json.dump([[asdict(r) for r in rep.results] for rep in runs], fh, indent=2)
        print(f"\n  Wrote JSON report ({len(runs)} run(s)) to {args.json}")

    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
