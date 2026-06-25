import glob
import os
import re
import tempfile
from typing import List, Optional

from .report import Report, PASS, FAIL, SKIP, INFO
from .utils import sh, have, read, _poll, is_root, prompt, SkipPhase
from .fs_utils import _fs_rw_test
from .config import NVME_TEST_SIZE_MB, NVME_CHUNK_MB, NVME_PASSES


def _nvme_lsblk_rows() -> List[dict]:
    """Return lsblk rows (as dicts) for all NVMe devices."""
    rc, out = sh(["lsblk", "-Pno", "NAME,FSTYPE,MOUNTPOINT,TYPE"])
    rows = []
    for line in out.splitlines():
        d = dict(re.findall(r'(\w+)="([^"]*)"', line))
        if d.get("NAME", "").startswith("nvme"):
            rows.append(d)
    return rows


def _nvme_is_blank(dev: str) -> bool:
    """Conservative blank-disk detection."""
    rc, wipefs_out = sh(["wipefs", "-n", dev])
    rc2, lsblk_out = sh(["lsblk", "-nro", "NAME", dev])
    names = [x.strip() for x in lsblk_out.splitlines() if x.strip()]
    return rc == 0 and not wipefs_out.strip() and len(names) <= 1


def _create_nvme_test_partition(rep: Report, dev: str) -> Optional[str]:
    """Create a ~2 GiB ext4 test partition on a blank NVMe. Returns partition path or None."""
    rc, out = sh(["parted", "-s", dev, "mklabel", "gpt"])
    if rc != 0:
        rep.add("NVMe test partition", FAIL, out[:80])
        return None
    rc, out = sh(
        [
            "parted",
            "-s",
            dev,
            "mkpart",
            "pi5test",
            "ext4",
            "1MiB",
            f"{NVME_TEST_SIZE_MB + 1025}MiB",
        ]
    )
    if rc != 0:
        rep.add("NVMe test partition", FAIL, out[:80])
        return None
    part = dev + "p1"
    if not _poll(lambda: os.path.exists(part), 5):
        rep.add("NVMe test partition", FAIL, "partition node never appeared")
        return None
    rc, out = sh(["mkfs.ext4", "-F", part], timeout=120)
    if rc != 0:
        rep.add("NVMe format", FAIL, out[:80])
        return None
    rep.add("NVMe test partition", INFO, f"created temporary filesystem on {part}")
    return part


def _nvme_teardown(rep: Report, disk: str) -> None:
    """Remove the test partition and wipe signatures so the drive returns to blank."""
    part = disk + "p1"
    if have("wipefs"):
        sh(["wipefs", "-a", part])  # clear the ext4 signature on the partition
    if have("parted"):
        sh(["parted", "-s", disk, "rm", "1"])  # delete the partition
    if have("wipefs"):
        sh(["wipefs", "-a", disk])  # clear the GPT signature -> blank again
    rep.add(
        "NVMe cleanup", INFO, f"removed test partition and wiped {disk} back to blank"
    )


def _nvme_rw_test(rep: Report) -> None:
    """Write+read on the NVMe to exercise the PCIe link both ways.

    Priority: mounted FS -> unmounted FS -> blank SSD (prompt + create FS) ->
    refuse anything ambiguous."""
    parts = _nvme_lsblk_rows()
    created_disk = None

    # 1. Use a mounted writable filesystem if available.
    for row in parts:
        mp = row.get("MOUNTPOINT")
        if mp and os.path.ismount(mp) and os.access(mp, os.W_OK):
            _fs_rw_test(rep, "NVMe", mp, NVME_TEST_SIZE_MB, NVME_PASSES, NVME_CHUNK_MB)
            return

    # 2. Find an unmounted filesystem partition to mount ourselves.
    cand = next(
        (
            r
            for r in parts
            if r.get("FSTYPE") and not r.get("MOUNTPOINT") and r.get("TYPE") == "part"
        ),
        None,
    ) or next(
        (
            r
            for r in parts
            if r.get("FSTYPE") and not r.get("MOUNTPOINT") and r.get("TYPE") == "disk"
        ),
        None,
    )

    # 3. If no filesystem, try to initialise a blank disk (with user consent).
    if not cand:
        nvme_disk = next(
            ("/dev/" + r["NAME"] for r in parts if r.get("TYPE") == "disk"), None
        )
        if not nvme_disk:
            rep.add("NVMe read/write", SKIP, "no NVMe disk found")
            return
        if not is_root():
            rep.add("NVMe read/write", SKIP, "needs sudo to inspect a blank NVMe")
            return
        if not _nvme_is_blank(nvme_disk):
            rep.add(
                "NVMe read/write",
                SKIP,
                "disk contains data or unknown signatures; refusing to modify",
            )
            return
        try:
            prompt(
                rep,
                f"{nvme_disk} appears blank. Create a temporary ~2 GiB test "
                "partition and filesystem (it'll be wiped back to blank afterward)?",
            )
        except SkipPhase:
            rep.add("NVMe read/write", SKIP, "user declined blank-disk initialization")
            return
        part = _create_nvme_test_partition(rep, nvme_disk)
        if not part:
            return
        created_disk = nvme_disk
        cand = {
            "NAME": os.path.basename(part),
            "TYPE": "part",
            "FSTYPE": "ext4",
            "MOUNTPOINT": "",
        }

    if not is_root():
        rep.add("NVMe read/write", SKIP, "needs sudo to mount the NVMe")
        return

    dev = "/dev/" + cand["NAME"]
    mnt = tempfile.mkdtemp(prefix="pi5nvme_")
    mounted = False
    try:
        rc, out = sh(["mount", dev, mnt])
        if rc != 0:
            rep.add("NVMe read/write", FAIL, f"could not mount {dev}: {out[:80]}")
            return
        mounted = True
        _fs_rw_test(rep, "NVMe", mnt, NVME_TEST_SIZE_MB, NVME_PASSES, NVME_CHUNK_MB)
    finally:
        if mounted:
            sh(["umount", mnt])
        try:
            os.rmdir(mnt)
        except OSError:
            pass
        if created_disk:
            _nvme_teardown(rep, created_disk)


def phase_pcie(rep: Report) -> None:
    rep.phase("pcie")
    if not have("lspci"):
        rep.add("PCIe (lspci)", SKIP, "install pciutils")
        return
    rc, out = sh(["lspci"])
    lines = [line for line in out.splitlines() if line.strip()]
    rep.add("PCIe enumeration", PASS if lines else INFO, f"{len(lines)} devices")
    nvme = [line for line in lines if "Non-Volatile" in line or "NVMe" in line]
    if not nvme:
        downs = []
        if is_root() and have("dmesg"):
            _, dm = sh(["dmesg"])
            for line in dm.splitlines():
                m = re.search(r"(\w+)\.pcie:\s*link down", line)
                if m:
                    downs.append(m.group(1))
        if downs:
            rep.add(
                "PCIe external link",
                INFO,
                f"controller {', '.join(downs)} reports LINK DOWN -- no device "
                "negotiated. If your NVMe HAT is on this connector: reseat the "
                "FPC ribbon (orientation matters -- try it the other way up) and "
                "reseat/screw down the M.2 SSD. A lit HAT power LED does NOT mean "
                "the data ribbon is connected.",
            )
        else:
            rep.add("NVMe on PCIe", INFO, "no NVMe fitted")
        return
    rep.add("NVMe detected", PASS, nvme[0].split(": ", 1)[-1][:60])
    _GEN_LABELS = {
        "2.5 GT/s": "Gen1",
        "5.0 GT/s": "Gen2",
        "8.0 GT/s": "Gen3",
        "16.0 GT/s": "Gen4",
    }
    for d in glob.glob("/sys/bus/pci/devices/*"):
        cls = read(f"{d}/class") or ""
        if cls.startswith("0x0108"):
            spd = read(f"{d}/current_link_speed") or "?"
            wid = read(f"{d}/current_link_width") or "?"
            label = _GEN_LABELS.get(spd, "")
            rep.add(
                "NVMe PCIe link",
                INFO,
                f"{spd}, x{wid}" + (f" ({label} x{wid})" if label else ""),
            )
    _nvme_rw_test(rep)
