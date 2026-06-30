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
    """Grade runs into an acceptance record (worst-case across runs)."""
    from . import config

    # functional failures: a FAIL/SKIP not on the accepted-exception list
    fails = set()
    for rep in runs:
        for r in rep.results:
            if r.status in (FAIL, SKIP) and not config.accept_nonpass(
                r.phase, r.name, r.detail
            ):
                tag = "" if r.status == FAIL else "SKIPPED "
                fails.add(f"{tag}{r.phase}/{r.name}: {r.detail[:70]}")

    measured = _measured(runs)
    metrics, metric_fails = {}, []
    for key, spec in config.ACCEPT_THRESHOLDS.items():
        nums = [v for v in measured.get(key, []) if isinstance(v, (int, float))]
        if not nums:
            metrics[key] = {
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
        graded = config.accept_check(key, worst)
        metrics[key] = graded
        if not graded["pass"]:
            bound = (
                f">={spec['min']}"
                if spec.get("min") is not None
                else f"<={spec['max']}"
            )
            metric_fails.append(f"{key}={worst}{spec.get('unit', '')} (need {bound})")

    verdict = "PASS" if not fails and not metric_fails else "FAIL"
    return {
        "schema": 1,
        "tool": "pi5_selftest",
        "graded_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "runs_graded": len(runs),
        "identity": board_identity(runs),
        "verdict": verdict,
        "functional_failures": sorted(fails),
        "metric_failures": metric_fails,
        "metrics": metrics,
        "runs": [[asdict(r) for r in rep.results] for rep in runs],
    }


def render_report(rec: dict) -> str:
    i, v = rec["identity"], rec["verdict"]
    L = [f"# Pi 5 acceptance report — {v}", "",
         f"**Verdict: {v}**  ·  serial `{i['serial']}`  ·  {rec['graded_at']}", "",
         "| field | value |", "|---|---|",
         f"| Model / rev | {i['model']} / {i['revision']} |",
         f"| Firmware | {i['firmware']} |",
         f"| EEPROM | {i['eeprom']} |",
         f"| Kernel | {i['kernel']} |",
         f"| Runs graded | {rec['runs_graded']} (worst-case) |", "",
         "## Graded metrics", "",
         "| metric | measured | spec | result |", "|---|---|---|---|"]
    for k, m in rec["metrics"].items():
        bound = (f">= {m['min']}" if m["min"] is not None else f"<= {m['max']}") + f" {m['unit']}"
        res = {True: "ok", False: "**FAIL**", None: "n/a"}[m["pass"]]
        val = "n/a" if m["value"] is None else f"{m['value']} {m['unit']}"
        L.append(f"| {k} | {val} | {bound} | {res} |")
    if rec["functional_failures"] or rec["metric_failures"]:
        L += ["", "## Why it failed"]
        L += [f"- out of spec: {x}" for x in rec["metric_failures"]]
        L += [f"- {x}" for x in rec["functional_failures"]]
    MARK = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "skip", "INFO": "info"}
    multi = len(rec["runs"]) > 1
    for ri, run in enumerate(rec["runs"], 1):
        L += ["", f"## Run {ri} — all checks" if multi else "## All checks"]
        phase = None
        for c in run:
            if c["phase"] != phase:
                phase = c["phase"]; L += ["", f"### {phase}"]
            line = f"- `{MARK.get(c['status'], c['status'])}` **{c['name']}**"
            if c.get("detail"):
                line += f" — {c['detail']}"
            mt = c.get("metric")
            if mt and mt.get("key") and mt.get("value") is not None:
                bound = (f">={mt['min']}" if mt["min"] is not None else f"<={mt['max']}") + f" {mt['unit']}"
                grade = "ok" if mt["pass"] else "**FAIL**"
                line += f" _(graded: {mt['value']} {mt['unit']}, need {bound} → {grade})_"
            L.append(line)
    return "\n".join(L) + "\n"


render_markdown = render_report  # back-compat alias
