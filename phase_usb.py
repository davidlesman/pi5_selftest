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

# How long to let a freshly-detected device settle (SuperSpeed trains slower
# than the block node appears). Local so config.py needn't change; move it there
# if you prefer to keep all timeouts together.
USB_SETTLE_TIMEOUT = 5.0

# Optional sanity check that the operator used the right physical port. BOARD-
# SPECIFIC (these are the sysfs port ids seen on one Pi 5 -- a blue port's USB2
# fallback and other board revisions can differ). Empty = check disabled. Fill
# in from one careful labeled pass; mismatches are reported as INFO, never FAIL.
# Known from logs (Pi 5): bottom-left=2-1, top-left=4-1, bottom-right=3-2,
# top-right=1-2 (SuperSpeed view for the blue ports).
EXPECTED_PORTS: Dict[str, set] = {
    # "bottom-left": {"2-1", "1-1"},
    # "top-left": {"4-1", "3-1"},
    # "bottom-right": {"3-2"},
    # "top-right": {"1-2"},
}


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


def _block_ready(name: str) -> bool:
    """True once the kernel has read the device capacity (size > 0). Right after
    a USB3 stick is plugged, /dev/sdX exists but size is briefly 0 while the
    SuperSpeed link trains and READ CAPACITY completes -- that gap is the source
    of the flaky USB3 detections."""
    try:
        return int(read(f"/sys/block/{name}/size") or "0") > 0
    except (ValueError, TypeError):
        return False


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


def _usb_occupied_ports(ready_only: bool = False) -> Dict[str, str]:
    """Map physical-USB-port -> block name for USB storage devices present.
    With ready_only, only count devices the kernel has finished enumerating."""
    occ: Dict[str, str] = {}
    for name in _usb_disks():
        p = _usb_port_path(name)
        if not p:
            continue
        if ready_only and not _block_ready(name):
            continue
        occ[p] = name
    return occ


def _usb_new_port(
    before: Dict[str, str], ready_only: bool = True
) -> Optional[Tuple[str, str]]:
    """First USB port that appeared since `before`. Defaults to ready_only so a
    half-enumerated device isn't accepted until its capacity is readable."""
    now = _usb_occupied_ports(ready_only=ready_only)
    fresh = [p for p in now if p not in before]
    return (fresh[0], now[fresh[0]]) if fresh else None


def _settled_speed(name: str) -> str:
    """Read the negotiated speed, giving it a moment to populate (the speed
    attribute can lag the block node by a fraction of a second on USB3)."""
    spd = _usb_speed_for(name)
    if spd and spd.isdigit():
        return spd
    spd = _poll(
        lambda: (
            _usb_speed_for(name) if (_usb_speed_for(name) or "").isdigit() else None
        ),
        USB_SETTLE_TIMEOUT,
        interval=0.25,
    )
    return spd or _usb_speed_for(name) or "?"


def _dmesg_lines() -> List[str]:
    """Kernel ring buffer (needs root). Empty list if unavailable."""
    if not (is_root() and have("dmesg")):
        return []
    rc, out = sh(["dmesg"])
    return out.splitlines() if rc == 0 else []


def _usb_ids_from(devpath: str) -> Optional[str]:
    """Walk up a sysfs device path to the USB device node and read VID:PID."""
    d = devpath
    for _ in range(12):
        vid = read(os.path.join(d, "idVendor"))
        pid = read(os.path.join(d, "idProduct"))
        if vid and pid:
            return f"{vid}:{pid}"
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _usb_scsi_stuck() -> Optional[str]:
    """Find a USB-attached SCSI disk that enumerated but never produced a block
    device (READ CAPACITY failed/hung). Returns its sysfs path if found. This is
    the UAS-at-SuperSpeed failure: sg0 appears, sda never does."""
    base = "/sys/class/scsi_device"
    try:
        entries = os.listdir(base)
    except OSError:
        return None
    for entry in entries:
        real = os.path.realpath(os.path.join(base, entry, "device"))
        if "/usb" not in real:
            continue
        if not os.path.isdir(os.path.join(real, "block")):
            return real  # SCSI disk with no block child = stuck
    return None


def _usb_enum_diag(mark: int) -> str:
    """Describe why a USB port produced no usable drive."""
    stuck = _usb_scsi_stuck()
    if stuck:
        return " -- " + _ss_fail_msg(stuck)
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


USB_STORAGE_QUIRKS = "/sys/module/usb_storage/parameters/quirks"


def _driver_at(syspath: str) -> str:
    """Driver bound to the USB interface (…:1.0) within a sysfs path:
    'uas', 'usb-storage', or '?'. Works for a stuck device with no block node."""
    parts = syspath.split("/")
    for i in range(len(parts), 0, -1):
        if re.match(r"^\d+-[\d.]+:\d+\.\d+$", parts[i - 1]):
            return os.path.basename(os.path.realpath("/".join(parts[:i]) + "/driver"))
    return "?"


def _usb_transport(name: str) -> str:
    """Which transport a live block device is using."""
    return _driver_at(os.path.realpath(f"/sys/block/{name}"))


def _ss_fail_msg(stuck: str) -> str:
    """Honest description of an enumerated-but-no-block-device failure, naming
    the actual transport and link speed so UAS isn't blamed when it's not the
    cause (e.g. after blacklisting uas)."""
    port = next((p for p in stuck.split("/") if re.match(r"^\d+-[\d.]+$", p)), "?")
    ids = _usb_ids_from(stuck) or "VID:PID"
    tr = _driver_at(stuck)
    dev = _usb_devnode_from(stuck)
    spd = (read(os.path.join(dev, "speed")) if dev else None) or "?"
    return (
        f"device {ids} trained to {spd} Mbps on port {port} but READ CAPACITY failed "
        f"under {tr} -- a SuperSpeed/drive incompatibility, not a transport bug "
        f"({'BOT' if tr != 'uas' else 'UAS'} is in use and still fails). The port is "
        "likely fine: test it with a known-good USB3 drive. This drive works at USB2. "
        f"To try to rescue it at SuperSpeed: 'usbcore.quirks={ids}:k' (disable link "
        "power management) in /boot/firmware/cmdline.txt + reboot, then power-cycle the "
        "drive"
    )


def _usb_devnode_from(syspath: str) -> Optional[str]:
    """The /sys/bus/usb/devices/<portid> node for a device's sysfs path."""
    port = next((p for p in syspath.split("/") if re.match(r"^\d+-[\d.]+$", p)), None)
    if not port:
        return None
    node = f"/sys/bus/usb/devices/{port}"
    return node if os.path.exists(node) else None


def _set_ignore_uas_quirk(ids: str) -> bool:
    """Add VID:PID:u to usb-storage's runtime quirks so this device uses Bulk-
    Only Transport on its next connect. Session-only (resets on reboot); leaves
    UAS active for every other device."""
    if not os.path.exists(USB_STORAGE_QUIRKS):
        sh(["modprobe", "usb_storage"])
    if not os.path.exists(USB_STORAGE_QUIRKS):
        return False
    cur = read(USB_STORAGE_QUIRKS) or ""
    entries = [e for e in cur.split(",") if e]
    want = f"{ids}:u"
    if want not in entries:
        entries.append(want)
    try:
        with open(USB_STORAGE_QUIRKS, "w") as f:
            f.write(",".join(entries))
        return True
    except OSError:
        return False


def _reenumerate(devnode: str) -> bool:
    """Force a device to disconnect+reconnect (so a new quirk takes effect)
    without a physical replug, by toggling its 'authorized' attribute."""
    auth = os.path.join(devnode, "authorized")
    if not os.path.exists(auth):
        return False
    try:
        with open(auth, "w") as f:
            f.write("0")
        time.sleep(0.6)
        with open(auth, "w") as f:
            f.write("1")
        time.sleep(0.6)
        return True
    except OSError:
        return False


def _force_bot_and_retry(
    rep: Report, label: str, stuck_path: str
) -> Optional[Tuple[str, str]]:
    """UAS failed for this device. Set the ignore-UAS quirk, re-enumerate, and
    see if it now comes up under Bulk-Only Transport. Returns (port, name) on
    success. Runtime only -- no reboot, no cmdline change, UAS stays default."""
    if not is_root():
        return None
    ids = _usb_ids_from(stuck_path)
    if not ids:
        return None
    if not _set_ignore_uas_quirk(ids):
        rep.add(
            f"USB {label} BOT fallback",
            SKIP,
            f"could not set usb-storage quirk for {ids} (module not loaded?)",
        )
        return None
    devnode = _usb_devnode_from(stuck_path)
    baseline = _usb_occupied_ports(ready_only=True)
    if not (devnode and _reenumerate(devnode)):
        rep.add(
            f"USB {label} BOT fallback",
            SKIP,
            f"quirk {ids}:u set but couldn't auto re-enumerate; replug the drive, "
            "or bake usb-storage.quirks into cmdline.txt",
        )
        return None
    rep.add(
        f"USB {label} BOT fallback",
        INFO,
        f"UAS failed; forced {ids} onto Bulk-Only Transport and re-enumerated",
    )
    return _poll(lambda: _usb_new_port(baseline), USB_DETECT_TIMEOUT)


def _usb_rw(rep: Report, label: str, name: str) -> None:
    """Run the r/w test on a USB disk, mounting it ourselves if needed."""
    mp = _poll(lambda: _mountpoint_for([name]), USB_MOUNT_TIMEOUT)
    if mp:
        _fs_rw_test(rep, f"USB {label}", mp)
        return
    if not is_root():
        rep.add(f"USB {label} read/write", SKIP, "not mounted (run with sudo to mount)")
        return
    # Device is already confirmed ready before we get here, but the partition
    # table read can still lag a touch -- poll briefly before calling it blank.
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
        before = _usb_occupied_ports()  # everything present, ready or not
        dmesg_mark = len(_dmesg_lines())
        prompt(rep, f"Plug a USB flash drive into the {label} port.")

        # Only accept a NEW port whose device is actually ready (size > 0). This
        # is what makes USB3 reliable: we wait out the SuperSpeed-training gap
        # instead of latching onto a half-enumerated node.
        found = _poll(lambda: _usb_new_port(before), USB_DETECT_TIMEOUT)
        bot_note = ""
        if not found and is_root():
            # A USB SCSI disk that enumerated but produced no block device. Only
            # blame UAS (and try the BOT fallback) if it's actually on UAS. If it
            # already failed under BOT, that's a SuperSpeed-level problem and the
            # fallback is pointless -- report it honestly instead.
            stuck = _usb_scsi_stuck()
            if stuck:
                if _driver_at(stuck) == "uas":
                    rep.add(
                        f"USB {label} UAS",
                        FAIL,
                        "enumerated but no block device under UAS (READ CAPACITY failed)",
                    )
                    found = _force_bot_and_retry(rep, label, stuck)
                    if found:
                        bot_note = " via BOT fallback"
                    else:
                        rep.add(f"USB {label}", FAIL, _ss_fail_msg(stuck))
                        continue
                else:
                    rep.add(f"USB {label}", FAIL, _ss_fail_msg(stuck))
                    continue
        if not found:
            rep.add(
                f"USB {label}",
                FAIL,
                f"no new ready storage device within {USB_DETECT_TIMEOUT:.0f}s"
                + _usb_enum_diag(dmesg_mark),
            )
            continue
        port, name = found
        transport = _usb_transport(name)
        if transport == "uas":
            rep.add(f"USB {label} UAS", PASS, "block device came up under UAS")
        exp = EXPECTED_PORTS.get(label.split()[0])
        if exp and port not in exp:
            rep.add(
                f"USB {label} port check",
                INFO,
                f"drive enumerated on USB port {port}, expected {sorted(exp)} "
                "-- wrong physical port, a USB2 fallback on a blue port, or a "
                "board that differs from EXPECTED_PORTS",
            )
        spd_raw = _settled_speed(name)
        rep.add(
            f"USB {label} enumerate",
            PASS,
            f"/dev/{name} @ {spd_raw} Mbps (USB port {port}, {transport}){bot_note}",
        )
        try:
            spd = int(spd_raw)
            ok = spd >= want_speed * 0.9
            detail = f"{spd} Mbps (expected >= {want_speed})"
            if not ok and want_speed >= 5000 and spd <= 480:
                detail += " -- SuperSpeed link didn't train; suspect cable/drive/port"
            rep.add(f"USB {label} negotiated speed", PASS if ok else FAIL, detail)
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
