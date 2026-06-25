import re
from typing import Dict

from .report import Report, PASS, FAIL, SKIP
from .utils import sh, have, prompt
from .config import PMIC_LIMITS, PMIC_LABELS, HEADER_POWER_PINS, VOLT_TOLERANCE


def _read_pmic_rails() -> Dict[str, float]:
    rc, out = sh(["vcgencmd", "pmic_read_adc"])
    vals: Dict[str, float] = {}
    if rc != 0:
        return vals
    for line in out.splitlines():
        m = re.match(r"(\S+)\s+\w+\(\d+\)=([\d.]+)([AV])", line.strip())
        if m:
            vals[m.group(1)] = float(m.group(2))
    return vals


def phase_power(rep: Report) -> None:
    rep.phase("power")
    if not have("vcgencmd"):
        rep.add("PMIC read", SKIP, "vcgencmd not available")
    else:
        rails = _read_pmic_rails()
        if not rails:
            rep.add("PMIC read", FAIL, "no data (try sudo)")
        for rail, (lo, hi) in PMIC_LIMITS.items():
            if rail in rails:
                v = rails[rail]
                label = PMIC_LABELS.get(rail, rail)
                rep.add(
                    f"PMIC {label}",
                    PASS if lo <= v <= hi else FAIL,
                    f"{v:.3f} V (want {lo}-{hi})",
                )

    if prompt(
        rep,
        "Put a multimeter between each header power pin and a GND pin. "
        "You'll be asked to type each reading.",
    ):
        for pin, nominal in HEADER_POWER_PINS.items():
            try:
                raw = input(
                    f"      Reading on physical pin {pin} (nominal {nominal}V): "
                ).strip()
                v = float(raw)
                ok = abs(v - nominal) <= VOLT_TOLERANCE
                rep.add(
                    f"Header pin {pin} voltage",
                    PASS if ok else FAIL,
                    f"{v:.2f} V (nominal {nominal} +/- {VOLT_TOLERANCE})",
                )
            except (ValueError, EOFError, KeyboardInterrupt):
                rep.add(f"Header pin {pin} voltage", SKIP, "no reading entered")
