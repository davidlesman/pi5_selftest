import os
import re
import tempfile
import time
from typing import Dict, List, Optional, Tuple

from .report import Report, PASS, FAIL, SKIP, INFO
from .utils import sh, have, read, _poll, is_root, prompt
from .fs_utils import _fs_rw_test, _mountpoint_for, _block_fs_partition
from .config import (
    USB_DETECT_TIMEOUT,
    USB_REMOVE_TIMEOUT,
    USB_MOUNT_TIMEOUT,
    USB_FS_TIMEOUT,
)


def _usb_speed_for(block: str) -> Optional[str]:
    try:
        d = os.path.realpath(f"/sys/block/{block}")
    except OSError:
        return None
    for _ in range(12):
        v = read(os.path.join(d, "speed"))
        if v:
            return v
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _usb_disks() -> Dict[str, str]:
    rc, out = sh(["lsblk", "-Sno", "NAME,TRAN"])
    disks: Dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "usb":
            disks[parts[0]] = _usb_speed_for(parts[0]) or "?"
    return disks


def _usb_port_path(name: str) -> Optional[str]:
    """Physical USB port a block device is on (e.g. '2-1' or '4-1.2').

    Taken from the sysfs path, so stable per physical port and independent of
    the /dev/sdX name -- re-plugging into a different port is always detected."""
    real = os.path.realpath(f"/sys/block/{name}")
    toks = [p for p in real.split("/") if re.match(r"^\d+-[\d.]+$", p)]
    return toks[-1] if toks else None


def _usb_occupied_ports() -> Dict[str, str]:
    """Map physical-USB-port -> block name for every USB storage device present."""
    occ: Dict[str, str] = {}
    for name in _usb_disks():
        p = _usb_port_path(name)
        if p:
            occ[p] = name
    return occ


def _usb_new_port(before: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """Return (port, block_name) for the first USB port that appeared since `before`."""
    now = _usb_occupied_ports()
    fresh = [p for p in now if p not in before]
    return (fresh[0], now[fresh[0]]) if fresh else None


def _dmesg_lines() -> List[str]:
    """Kernel ring buffer (needs root). Empty list if unavailable."""
    if not (is_root() and have("dmesg")):
        return []
    rc, out = sh(["dmesg"])
    return out.splitlines() if rc == 0 else []


def _usb_enum_diag(mark: int) -> str:
    """Describe what the kernel logged for a USB port since line <mark>."""
    new = _dmesg_lines()[mark:]
    kw = ("usb", "xhci", "over-current", "overcurrent")
    hits = [ln for ln in new if any(k in ln.lower() for k in kw)]
    if not hits:
        return " -- kernel logged nothing for this port (dead port, or the drive never seated)"
    errish = [
        ln
        for ln in hits
        if any(
            e in ln.lower()
            for e in ("error", "fail", "over-current", "overcurrent", "unable", "reset")
        )
    ]
    tail = (errish or hits)[-1].split("] ", 1)[-1]
    return f" -- the port saw activity: {tail[:120]}"


def _usb_raw_read_test(rep: Report, label: str, name: str, size_mb: int = 64) -> None:
    """Read-only raw test for drives with no filesystem (blank/unformatted).
    Never writes to an unknown raw disk."""
    sectors = read(f"/sys/block/{name}/size") or "0"
    try:
        dev_mib = int(sectors) * 512 / (1 << 20)
    except ValueError:
        dev_mib = 0
    if dev_mib < 1:
        rep.add(
            f"USB {label} read/write",
            SKIP,
            "no filesystem and the block device reports 0 size (not ready yet)",
        )
        return
    count = max(1, min(size_mb, int(dev_mib)))
    dev = "/dev/" + name
    cmd = ["dd", f"if={dev}", "of=/dev/null", "bs=1M", f"count={count}"]
    t0 = time.monotonic()
    rc, out = sh(cmd + ["iflag=direct"], timeout=60)
    dt = time.monotonic() - t0
    if rc != 0:  # some paths reject O_DIRECT; retry buffered
        t0 = time.monotonic()
        rc, out = sh(cmd, timeout=60)
        dt = time.monotonic() - t0
    m = re.search(r"(\d+)\s*bytes", out)
    nbytes = int(m.group(1)) if m else 0
    if rc != 0 or nbytes == 0:
        rep.add(
            f"USB {label} read/write",
            SKIP,
            f"no filesystem; raw read returned {nbytes} bytes (drive not ready)",
        )
        return
    mib = nbytes / (1 << 20)
    mbps = mib / dt if dt > 0 else 0
    rep.add(
        f"USB {label} raw read",
        PASS,
        f"blank drive: {mib:.0f} MiB read-only @ ~{mbps:.0f} MB/s "
        "(unformatted, so no write test)",
    )


def _usb_rw(rep: Report, label: str, name: str) -> None:
    """Run the r/w test on a USB disk, mounting it ourselves if needed."""
    mp = _poll(lambda: _mountpoint_for([name]), USB_MOUNT_TIMEOUT)
    if mp:
        _fs_rw_test(rep, f"USB {label}", mp)
        return
    if not is_root():
        rep.add(f"USB {label} read/write", SKIP, "not mounted (run with sudo to mount)")
        return
    # Poll for the partition table: right after enumeration the kernel may not
    # have read it yet, so a single check can spuriously report "no filesystem"
    # for a drive that actually has one (the intermittent SKIP you saw).
    part = _poll(lambda: _block_fs_partition(name), USB_FS_TIMEOUT)
    if not part:
        _usb_raw_read_test(rep, label, name)
        return
    mnt = tempfile.mkdtemp(prefix="pi5usb_")
    mounted = False
    try:
        rc, out = sh(["mount", "/dev/" + part, mnt])
        if rc != 0:
            rep.add(f"USB {label} read/write", SKIP, f"could not mount /dev/{part}")
            return
        mounted = True
        _fs_rw_test(rep, f"USB {label}", mnt)
    finally:
        if mounted:
            sh(["umount", mnt])
        try:
            os.rmdir(mnt)
        except OSError:
            pass


def phase_usb(rep: Report) -> None:
    rep.phase("usb")
    if not have("lsblk"):
        rep.add("USB tests", SKIP, "lsblk not available (install util-linux)")
        return
    ports = [
        ("bottom-left (USB 3.0, blue)", 5000),
        ("top-left (USB 3.0, blue)", 5000),
        ("bottom-right (USB 2.0, black)", 480),
        ("top-right (USB 2.0, black)", 480),
    ]
    for label, want_speed in ports:
        before = _usb_occupied_ports()
        dmesg_mark = len(_dmesg_lines())
        prompt(rep, f"Plug a USB flash drive into the {label} port.")

        found = _poll(lambda: _usb_new_port(before), USB_DETECT_TIMEOUT)
        if not found:
            rep.add(
                f"USB {label}",
                FAIL,
                f"no new storage device within {USB_DETECT_TIMEOUT:.0f}s"
                + _usb_enum_diag(dmesg_mark),
            )
            continue
        port, name = found
        spd_raw = _usb_speed_for(name) or "?"
        rep.add(
            f"USB {label} enumerate",
            PASS,
            f"/dev/{name} @ {spd_raw} Mbps (USB port {port})",
        )
        try:
            spd = int(spd_raw)
            ok = spd >= want_speed * 0.9
            rep.add(
                f"USB {label} negotiated speed",
                PASS if ok else FAIL,
                f"{spd} Mbps (expected >= {want_speed})",
            )
        except ValueError:
            rep.add(f"USB {label} negotiated speed", SKIP, "speed unknown")

        _usb_rw(rep, label, name)

        prompt(rep, f"Remove the drive from the {label} port.")
        if not _poll(lambda: port not in _usb_occupied_ports(), USB_REMOVE_TIMEOUT):
            rep.add(
                f"USB {label} removed",
                INFO,
                f"USB port {port} still occupied after {USB_REMOVE_TIMEOUT:.0f}s "
                "(detection keys on port now, so the next port is unaffected)",
            )
