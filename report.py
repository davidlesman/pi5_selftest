from dataclasses import dataclass, field
from typing import List

PASS, FAIL, SKIP, INFO = "PASS", "FAIL", "SKIP", "INFO"
_COLOR = {PASS: "\033[92m", FAIL: "\033[91m", SKIP: "\033[93m", INFO: "\033[96m"}
_RST = "\033[0m"


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""
    phase: str = ""


@dataclass
class Report:
    results: List[Result] = field(default_factory=list)
    _phase: str = ""

    def phase(self, name: str) -> None:
        self._phase = name
        print(f"\n\033[1m=== PHASE: {name} ===\033[0m")

    def add(self, name: str, status: str, detail: str = "") -> Result:
        r = Result(name, status, detail, self._phase)
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
