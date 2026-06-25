import glob
import os
import re

from .report import Report, PASS, FAIL, SKIP, INFO
from .utils import sh, have, prompt


def phase_mipi(rep: Report) -> None:
    rep.phase("mipi")
    cam_tool = (
        "rpicam-hello"
        if have("rpicam-hello")
        else ("libcamera-hello" if have("libcamera-hello") else None)
    )
    if not cam_tool:
        rep.add("Camera tooling", SKIP, "install rpicam-apps")
    else:
        rc, out = sh([cam_tool, "--list-cameras"], timeout=20)
        cams = re.findall(
            r"^\s*(\d+)\s*:\s*(\S+).*?(\(/base.*?\))?$", out, re.MULTILINE
        )
        found = [(idx, sensor) for idx, sensor, _ in cams]
        if not found:
            rep.add(
                "MIPI cameras",
                INFO,
                "none detected (3rd-party modules need a dtoverlay)",
            )
        else:
            for idx, sensor in found:
                rep.add(f"Camera port {idx}", PASS, sensor)
            still = (
                "rpicam-still"
                if have("rpicam-still")
                else ("libcamera-still" if have("libcamera-still") else None)
            )
            if still and prompt(rep, "Point camera 0 at something with light."):
                tmp = f"/tmp/pi5cam_{os.getpid()}.jpg"
                rc, o = sh(
                    [still, "--camera", "0", "-n", "--immediate", "-o", tmp], timeout=30
                )
                ok = os.path.exists(tmp) and os.path.getsize(tmp) > 10_000
                if ok:
                    with open(tmp, "rb") as fh:
                        ok = fh.read(2) == b"\xff\xd8"
                rep.add(
                    "Camera 0 capture",
                    PASS if ok else FAIL,
                    f"{os.path.getsize(tmp)} bytes" if os.path.exists(tmp) else o[:60],
                )
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    dsi = glob.glob("/sys/class/drm/*DSI*")
    if dsi:
        for c in dsi:
            from .utils import read

            st = read(f"{c}/status")
            rep.add(f"DSI {os.path.basename(c)}", INFO, st or "unknown")
    else:
        rep.add("DSI display connectors", INFO, "none reported")
