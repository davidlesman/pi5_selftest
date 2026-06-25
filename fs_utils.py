import os
import re
import time
from typing import List, Optional

from .report import Report, PASS, FAIL
from .utils import sh


def _fs_rw_test(
    rep: Report,
    label: str,
    mountpoint: str,
    size_mb: int = 64,
    passes: int = 1,
    chunk_mb: int = 4,
) -> None:
    """Write random data to a temp file, read it back, and verify by SHA-256.

    Defaults are light (64 MiB x1) for USB; the PCIe phase passes the heavier
    NVMe stress values."""
    import hashlib
    from .report import INFO

    path = os.path.join(mountpoint, f".pi5selftest_{os.getpid()}.bin")
    try:
        total_written = 0
        write_time = 0.0
        read_time = 0.0
        for pass_no in range(passes):
            if passes > 1:
                rep.add(
                    f"{label} stress pass {pass_no + 1}",
                    INFO,
                    f"{size_mb} MiB write/read",
                )
            sha_write = hashlib.sha256()
            t0 = time.time()
            with open(path, "wb") as fh:
                remaining = size_mb
                while remaining > 0:
                    block = os.urandom(chunk_mb * 1024 * 1024)
                    fh.write(block)
                    sha_write.update(block)
                    remaining -= chunk_mb
                fh.flush()
                os.fsync(fh.fileno())
            write_time += time.time() - t0
            expected = sha_write.hexdigest()
            sha_read = hashlib.sha256()
            t0 = time.time()
            with open(path, "rb") as fh:
                while True:
                    block = fh.read(chunk_mb * 1024 * 1024)
                    if not block:
                        break
                    sha_read.update(block)
            read_time += time.time() - t0
            if sha_read.hexdigest() != expected:
                rep.add(
                    f"{label} read/write integrity",
                    FAIL,
                    f"SHA256 mismatch on pass {pass_no + 1}",
                )
                return
            total_written += size_mb
        write_mbps = total_written / write_time if write_time else 0
        read_mbps = total_written / read_time if read_time else 0
        detail = (
            f"{total_written} MiB verified, "
            f"write ~{write_mbps:.0f} MB/s, read ~{read_mbps:.0f} MB/s"
        )
        if passes > 1:
            detail = f"{passes} passes, " + detail
        rep.add(f"{label} read/write integrity", PASS, detail)
    except OSError as e:
        rep.add(f"{label} read/write integrity", FAIL, str(e))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _mountpoint_for(block_names: List[str]) -> Optional[str]:
    rc, out = sh(["lsblk", "-rno", "NAME,MOUNTPOINT"])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("/"):
            base = re.sub(r"\d+$", "", parts[0])
            if base in block_names or parts[0] in block_names:
                if os.access(parts[1], os.W_OK):
                    return parts[1]
    return None


def _block_fs_partition(disk: str) -> Optional[str]:
    """Return the NAME of a filesystem-bearing partition under <disk>, or None."""
    rc, out = sh(["lsblk", "-Pno", "NAME,FSTYPE,TYPE", "/dev/" + disk])
    disk_fallback = None
    for line in out.splitlines():
        d = dict(re.findall(r'(\w+)="([^"]*)"', line))
        if d.get("FSTYPE"):
            if d.get("TYPE") == "part":
                return d["NAME"]
            if d.get("TYPE") == "disk":
                disk_fallback = d["NAME"]
    return disk_fallback
