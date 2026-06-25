import os
import re

from .report import Report, PASS, FAIL, SKIP
from .utils import sh, read


def phase_ethernet(rep: Report) -> None:
    rep.phase("ethernet")
    net = "/sys/class/net"
    interfaces = [i for i in os.listdir(net) if i.startswith(("eth", "enx", "end"))]
    if not interfaces:
        rep.add("Ethernet interface", FAIL, "no wired interface found")
        return
    for iface in interfaces:
        carrier = read(f"{net}/{iface}/carrier") == "1"
        speed = read(f"{net}/{iface}/speed")
        rep.add(
            f"{iface} link up",
            PASS if carrier else FAIL,
            f"speed={speed}Mbps" if carrier else "no carrier (cable in?)",
        )
    up_ifaces = [i for i in interfaces if read(f"{net}/{i}/carrier") == "1"]
    if not up_ifaces:
        rep.add("Ethernet gateway ping", SKIP, "no ethernet link up to test through")
        return
    rc, route = sh(["ip", "route", "show", "default"])
    m = re.search(r"default via (\S+)", route)
    gw = m.group(1) if m else None
    if gw:
        rc, _ = sh(["ping", "-c", "2", "-W", "2", "-I", up_ifaces[0], gw])
        rep.add(
            "Ethernet gateway ping",
            PASS if rc == 0 else FAIL,
            f"{gw} via {up_ifaces[0]}",
        )
    else:
        rep.add("Ethernet gateway ping", SKIP, "no default route")
