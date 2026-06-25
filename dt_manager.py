import os
import re
from typing import Dict, List, Optional

from .report import Report, INFO, SKIP
from .utils import sh, have, is_root, _cfg


class DTManager:
    def __init__(self) -> None:
        self.active = _cfg.dt_enabled and is_root() and have("dtoverlay")
        self.base = self._count() if self.active else 0
        self.added: List[str] = []

    def _count(self) -> int:
        rc, out = sh(["dtoverlay", "-l"])
        return len(re.findall(r"^\s*\d+:", out, re.M)) if rc == 0 else 0

    def enable(self, rep: Report, what: str, *cmd: str) -> bool:
        if not self.active:
            return False
        before = self._count()
        rc, out = sh(list(cmd))
        if rc != 0:
            rep.add(f"auto-enable {what}", SKIP, f"{' '.join(cmd)}: {out[:50]}")
            return False
        if self._count() > before:
            self.added.append(what)
        rep.add(f"auto-enable {what}", INFO, f"runtime: {' '.join(cmd)}")
        return True

    def restore(self) -> None:
        if not self.active:
            return
        while self._count() > self.base:
            sh(["dtoverlay", "-r"])
        self.added.clear()


_DT: Optional[DTManager] = None


def boot_config_path() -> Optional[str]:
    for p in ("/boot/firmware/config.txt", "/boot/config.txt"):
        if os.path.exists(p):
            return p
    return None


def boot_enabled_interfaces() -> Dict[str, str]:
    from .utils import read

    path = boot_config_path()
    found: Dict[str, str] = {}
    if not path:
        return found
    for raw in (read(path) or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        for key in (
            "spi=on",
            "i2c=on",
            "i2c_arm=on",
            "w1-gpio",
            "spi0",
            "uart0",
            "enable_uart=1",
        ):
            if key in low:
                found[key] = line
    return found
