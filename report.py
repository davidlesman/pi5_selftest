import re
import subprocess
import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional

PASS, FAIL, SKIP, INFO = "PASS", "FAIL", "SKIP", "INFO"
_COLOR = {PASS: "\033[92m", FAIL: "\033[91m", SKIP: "\033[93m", INFO: "\033[96m"}
_RST = "\033[0m"


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""
    phase: str = ""
    metric: Optional[dict] = None  # structured {key,value,unit,min,max,pass}


@dataclass
class Report:
    results: List[Result] = field(default_factory=list)
    _phase: str = ""

    def phase(self, name: str) -> None:
        self._phase = name
        print(f"\n\033[1m=== PHASE: {name} ===\033[0m")

    def add(
        self, name: str, status: str, detail: str = "", metric: Optional[dict] = None
    ) -> Result:
        r = Result(name, status, detail, self._phase, metric)
        self.results.append(r)
        print(
            f"  [{_COLOR.get(status, '')}{status:^4}{_RST}] {name}"
            + (f"  -  {detail}" if detail else "")
        )
        return r

    def summary(self) -> int:
        passed = sum(r.status == PASS for r in self.results)
        failed = sum(r.status == FAIL for r in self.results)
        skipped = sum(r.status == SKIP for r in self.results)
        print("\n" + "=" * 66)
        print(
            f"  SUMMARY: {passed} passed, {failed} failed, {skipped} skipped, "
            f"{len(self.results)} checks"
        )
        print("=" * 66)
        if failed:
            print("  Failures:")
            for r in self.results:
                if r.status == FAIL:
                    print(f"    - [{r.phase}] {r.name}: {r.detail}")
        return 1 if failed else 0


# ---------------------------------------------------------------------------
# Acceptance grading: turn one or more runs into a pass/fail record + sheet.
# Spec lives in config.py (ACCEPT_THRESHOLDS / ACCEPT_NONPASS / ACCEPT_PARSERS).
# ---------------------------------------------------------------------------
def _sh(cmd):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=8
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def board_identity(runs) -> dict:
    """Board identity, read live from the Pi when possible, else from the report."""
    ident = {
        "serial": "unknown",
        "model": "unknown",
        "revision": "unknown",
        "firmware": "unknown",
        "eeprom": "unknown",
        "kernel": "unknown",
    }
    cpu = ""
    try:
        cpu = open("/proc/cpuinfo").read()
    except OSError:
        pass
    for key, pat in (
        ("serial", r"Serial\s*:\s*([0-9a-fA-F]+)"),
        ("revision", r"Revision\s*:\s*(\w+)"),
        ("model", r"Model\s*:\s*(.+)"),
    ):
        m = re.search(pat, cpu)
        if m:
            ident[key] = m.group(1).strip()
    ident["kernel"] = _sh(["uname", "-r"]) or ident["kernel"]
    fw = _sh(["vcgencmd", "version"])
    if fw:
        ident["firmware"] = fw.splitlines()[-1].strip()
    eep = _sh(["vcgencmd", "bootloader_version"])
    if eep:
        ident["eeprom"] = eep.splitlines()[0].strip()
    for rep in runs:  # fall back to report INFO lines
        for r in rep.results:
            if (
                r.phase == "identify"
                and r.name == "Board model"
                and ident["model"] == "unknown"
            ):
                ident["model"] = r.detail
            if (
                r.phase == "identify"
                and r.name == "Board revision"
                and ident["revision"] == "unknown"
            ):
                ident["revision"] = r.detail
    return ident


def _measured(runs) -> dict:
    """Collect measured values per metric key across all runs: structured
    metric wins; otherwise parse the detail per config.ACCEPT_PARSERS. Returns
    {key: [values]}."""
    from . import config

    vals: dict = {}
    for rep in runs:
        for r in rep.results:
            if r.metric and r.metric.get("key"):
                vals.setdefault(r.metric["key"], []).append(r.metric.get("value"))
                continue
            for p in config.ACCEPT_PARSERS:
                if r.phase != p["phase"]:
                    continue
                if not all(c.lower() in r.name.lower() for c in p["contains"]):
                    continue
                m = re.search(p["regex"], r.detail)
                if m:
                    vals.setdefault(p["key"], []).append(float(m.group(1)))
    return vals


def acceptance_record(runs) -> dict:
    """Grade runs into an acceptance record (worst-case across runs).

    Verdict rule, single and honest: FAIL if ANY check FAILed or ANY measured
    value is out of spec. SKIP ('not tested') and INFO never count. No
    forgive-list.
    """
    from . import config

    counts = {PASS: 0, FAIL: 0, SKIP: 0, INFO: 0}
    fails = []
    for rep in runs:
        for r in rep.results:
            counts[r.status] = counts.get(r.status, 0) + 1
            if r.status == FAIL:
                fails.append(f"{r.phase}/{r.name}: {r.detail}")

    measured = _measured(runs)
    metrics, metric_fails = {}, []
    in_spec = graded = 0
    for key, spec in config.ACCEPT_THRESHOLDS.items():
        nums = [v for v in measured.get(key, []) if isinstance(v, (int, float))]
        if not nums:
            metrics[key] = {
                "key": key,
                "value": None,
                "unit": spec.get("unit", ""),
                "min": spec.get("min"),
                "max": spec.get("max"),
                "pass": None,
            }
            continue
        worst = (
            max(nums) if spec.get("max") is not None else min(nums)
        )  # ceiling vs floor
        graded += 1
        m = config.accept_check(key, worst)
        metrics[key] = m
        if m["pass"]:
            in_spec += 1
        else:
            bound = (
                f">= {spec['min']}"
                if spec.get("min") is not None
                else f"<= {spec['max']}"
            )
            metric_fails.append(
                f"{config.ACCEPT_LABELS.get(key, key)} "
                f"{m['value']} {m['unit']} out of spec ({bound})"
            )

    verdict = "PASS" if not fails and not metric_fails else "FAIL"

    return {
        "schema": 2,
        "tool": "pi5_selftest",
        "graded_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs_graded": len(runs),
        "identity": board_identity(runs),
        "verdict": verdict,
        "counts": counts,
        "metrics_in_spec": in_spec,
        "metrics_graded": graded,
        "functional_failures": fails,
        "metric_failures": metric_fails,
        "metrics": metrics,
        "runs": [[asdict(r) for r in rep.results] for rep in runs],
    }


# --- plain-text report (reads well under `cat`; no markdown) ----------------
_W = 70  # report width
_TAG = {PASS: "ok", FAIL: "FAIL", SKIP: "n/t", INFO: "info"}


def fmt_metric(v, unit) -> str:
    if v is None:
        return "n/a"
    if unit in ("RPM", "Mbps", "mA"):
        return f"{int(round(v))} {unit}"
    if unit == "V":
        return f"{v:.2f} {unit}"
    if unit == "GT/s":
        return f"{v:.1f} {unit}"
    return f"{v:g} {unit}"


def _spec_str(m) -> str:
    if m["min"] is not None and m["max"] is not None:
        return f"{m['min']} - {m['max']}"
    if m["min"] is not None:
        return f">= {m['min']}"
    if m["max"] is not None:
        return f"<= {m['max']}"
    return ""


def render_report(rec: dict) -> str:
    from . import config

    i, v = rec["identity"], rec["verdict"]
    bar = "=" * _W
    dash = "-" * _W
    L = [
        bar,
        f"  RASPBERRY PI 5  \u2014  ACCEPTANCE REPORT{v:>{_W - 39}}",
        bar,
        f"  Serial     {i['serial']}",
        f"  Model      {i['model']}",
        f"  Firmware   {i['firmware']:<26}EEPROM  {i['eeprom']}",
        f"  Kernel     {i['kernel']}",
        f"  Tested     {rec['graded_at']}",
        f"  Result     {rec['counts'].get(PASS, 0)} pass \u00b7 "
        f"{rec['counts'].get(FAIL, 0)} fail \u00b7 "
        f"{rec['counts'].get(SKIP, 0)} not tested \u00b7 "
        f"measurements {rec['metrics_in_spec']}/{rec['metrics_graded']} in spec",
    ]

    if v == "FAIL":
        L += ["", "  WHY IT FAILED"]
        for x in rec["metric_failures"]:
            L.append(f"    - {x}")
        for x in rec["functional_failures"]:
            L.append(f"    - {x}")

    # MEASUREMENTS table
    L += [
        "",
        dash,
        f"  {'MEASUREMENTS':<30}{'measured':>11}   {'spec':<13} {'result':>6}",
        dash,
    ]
    for key, m in rec["metrics"].items():
        label = config.ACCEPT_LABELS.get(key, key)
        meas = fmt_metric(m["value"], m["unit"])
        res = {True: "ok", False: "FAIL", None: "n/a"}[m["pass"]]
        L.append(f"  {label:<30}{meas:>11}   {_spec_str(m):<13} {res:>6}")

    # DETAIL BY PHASE, in run order, with per-phase tallies
    L += ["", dash, "  DETAIL BY PHASE", dash]
    run = rec["runs"][0] if rec["runs"] else []
    if len(rec["runs"]) > 1:
        L.append(f"  (showing run 1 of {len(rec['runs'])}; all runs are in the JSON)")
    # group consecutive checks by phase, preserving order
    order = []
    for c in run:
        if not order or order[-1][0] != c["phase"]:
            order.append((c["phase"], []))
        order[-1][1].append(c)
    for phase, checks in order:
        tally = {}
        for c in checks:
            tally[c["status"]] = tally.get(c["status"], 0) + 1
        parts = []
        for st, word in (
            (PASS, "pass"),
            (FAIL, "fail"),
            (SKIP, "not tested"),
            (INFO, "info"),
        ):
            if tally.get(st):
                parts.append(f"{tally[st]} {word}")
        dots = "." * max(2, 18 - len(phase))
        L += ["", f"  {phase} {dots} {', '.join(parts)}"]
        for c in checks:
            tag = _TAG.get(c["status"], c["status"])
            line = f"    {tag:<5} {c['name']}"
            if c.get("detail"):
                line += f"   {c['detail']}"
            L.append(line)
    L += [bar]
    return "\n".join(L) + "\n"
