import os
import time

from .report import Report, PASS, FAIL, SKIP, INFO
from .utils import sh, have, read, is_root


def phase_rtc(rep: Report) -> None:
    rep.phase("rtc")
    rtc_sys = "/sys/class/rtc/rtc0"
    if not (os.path.exists("/dev/rtc0") or os.path.isdir(rtc_sys)):
        rep.add("Onboard RTC", INFO, "no rtc0 node")
        return
    name = read(f"{rtc_sys}/name")
    rep.add("Onboard RTC present", PASS, "/dev/rtc0" + (f" ({name})" if name else ""))
    epoch = read(f"{rtc_sys}/since_epoch")
    if epoch and epoch.isdigit():
        import datetime

        secs = int(epoch)
        rtc_dt = datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)
        rep.add("RTC read", PASS, f"{rtc_dt:%Y-%m-%d %H:%M:%S} UTC")
        skew = abs(secs - int(time.time()))
        rep.add(
            "RTC vs system clock",
            PASS if skew < 120 else INFO,
            f"{skew}s skew"
            + ("" if skew < 120 else " (RTC unset: no backup battery, or no NTP yet)"),
        )
    else:
        date, tm = read(f"{rtc_sys}/date"), read(f"{rtc_sys}/time")
        if date and tm:
            rep.add("RTC read", PASS, f"{date} {tm} UTC")
        elif have("hwclock") and is_root():
            rc, out = sh(["hwclock", "-r"])
            rep.add("RTC read", PASS if rc == 0 else FAIL, out[:60])
        else:
            rep.add("RTC read", SKIP, "no readable RTC time source in sysfs")
