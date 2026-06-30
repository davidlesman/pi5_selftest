from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Configuration -- edit to match physical wiring / tolerances
# ---------------------------------------------------------------------------
#
# TWO NUMBERING SCHEMES (this is the usual source of confusion):
#   * GPIO_LOOPBACK_PAIRS and PULL_TEST_PINS use BCM / GPIO numbers -- the
#     numbers gpiozero speaks (e.g. GPIO2, GPIO14). NOT physical pin positions.
#     So (2, 3) means GPIO2 <-> GPIO3, i.e. physical pins 3 and 5 -- it does
#     NOT mean physical pins 2 and 3 (physical pin 2 is 5V!).
#   * HEADER_POWER_PINS uses PHYSICAL pin numbers (1..40) -- because you probe
#     those positions with a multimeter.
# Output lines print both as "BCM<n>/pin<p>" so there's no ambiguity.

# GPIO loopback: jumper each pair. BCM numbers. Covers all 28 header GPIOs
# (BCM 0..27). Two pairs match the UART and SPI jumpers so you don't rewire
# them: (14,15) == the UART jumper, (9,10) == the SPI jumper.
GPIO_LOOPBACK_PAIRS: List[Tuple[int, int]] = [
    (2, 3),
    (4, 17),
    (27, 22),
    (5, 6),
    (13, 19),
    (26, 21),
    (20, 16),
    (12, 25),  # both free GPIO -- testable (was 12<->7 / 8<->25, which hit SPI CE)
    (7, 8),  # SPI0 CE1/CE0; SKIP together when SPI is on (claimed by spi0)
    (24, 23),
    (18, 11),
    (14, 15),  # == UART jumper (pin8 <-> pin10)
    (9, 10),  # == SPI jumper  (pin21 <-> pin19)
    (0, 1),  # ID_SD/ID_SC (pin27 <-> pin28); may SKIP if a HAT EEPROM holds them
]

# Pull-resistor test: BCM numbers, pins that must have NOTHING wired to them.
PULL_TEST_PINS: List[int] = [4, 17, 27, 22, 5, 6, 13, 19, 26, 21, 20, 16]

# Header power pins to verify by multimeter -- PHYSICAL pin -> nominal volts.
HEADER_POWER_PINS: Dict[int, float] = {
    1: 3.3,
    17: 3.3,  # 3.3V pins
    2: 5.0,
    4: 5.0,  # 5V pins
}
VOLT_TOLERANCE = 0.25  # +/- volts allowed on a header power pin

# PMIC rail acceptance windows (volts): (min, max)
PMIC_LIMITS: Dict[str, Tuple[float, float]] = {
    "EXT5V_V": (4.75, 5.25),  # 5V input == header 5V pins
    "3V3_SYS_V": (3.20, 3.40),  # 3.3V rail == header 3.3V pins
    "1V8_SYS_V": (1.70, 1.90),
    "VDD_CORE_V": (0.60, 1.05),
}

# Human-readable labels for PMIC rails shown in the report (others use the key as-is).
PMIC_LABELS: Dict[str, str] = {
    "EXT5V_V": "5V input / header 5V rail",
    "3V3_SYS_V": "3.3V rail / header 3.3V",
}

UART_DEVICE = "/dev/serial0"
UART_BAUD = 115200
SPI_BUS, SPI_DEV, SPI_HZ = 0, 0, 1_000_000
TEMP_LIMIT_C = 80.0

# NVMe stress test (PCIe phase only -- NOT used for USB).
NVME_TEST_SIZE_MB = 1024  # 1 GiB per pass
NVME_CHUNK_MB = 4
NVME_PASSES = 3  # 3 * 1 GiB in and out

# USB phase: upper bounds for polling, not fixed sleeps.
USB_DETECT_TIMEOUT = 20.0  # wait this long for a plugged drive to enumerate
USB_REMOVE_TIMEOUT = 15.0  # wait this long for a pulled drive to disappear
USB_MOUNT_TIMEOUT = 6.0  # wait this long for automount before the r/w test
USB_FS_TIMEOUT = 10.0  # wait this long for the kernel to read the partition table
USB_SETTLE_TIMEOUT = 5.0

# Throttle / under-voltage bit masks from `vcgencmd get_throttled`.
THROTTLE_BITS_NOW: List[Tuple[int, str]] = [
    (0x00001, "under-voltage"),
    (0x00002, "arm freq capped"),
    (0x00004, "throttled"),
    (0x00008, "soft temp limit"),
]
THROTTLE_BITS_PAST: List[Tuple[int, str]] = [
    (0x10000, "under-voltage"),
    (0x20000, "arm freq capped"),
    (0x40000, "throttled"),
    (0x80000, "soft temp limit"),
]


# ===========================================================================
# ACCEPTANCE SPEC  --  production incoming-inspection thresholds & policy.
# Edit the numbers here; report.py reads them to compute the verdict. Floors
# seeded from 3 known-good runs (with margin): nvme_write 144-145,
# nvme_read 1099-1103, usb3_write 110-117, usb2_write ~28,
# fan_spinup 3876-6587, soc_temp idle 45-47.
# ===========================================================================
ACCEPT_THRESHOLDS: Dict[str, dict] = {
    "nvme_write_MBps": {"min": 120, "unit": "MB/s"},
    "nvme_read_MBps": {"min": 900, "unit": "MB/s"},
    "usb3_write_MBps": {"min": 80, "unit": "MB/s"},
    "usb2_write_MBps": {"min": 18, "unit": "MB/s"},
    "usb3_link_Mbps": {"min": 5000, "unit": "Mbps"},
    "usb2_link_Mbps": {"min": 480, "unit": "Mbps"},
    "fan_spinup_rpm": {"min": 3000, "unit": "RPM"},
    "soc_temp_idle_C": {"max": 75, "unit": "C"},
    # USB READ throughput is deliberately ABSENT: a 64 MiB read-back is served
    # from page cache and swings 739-1078, so a floor would fail good units.
}

# Non-PASS checks acceptable on THIS station's config (no cable / no device /
# manual step / pins held by a bus driver). Matched on phase + (name OR detail).
ACCEPT_NONPASS: List[Tuple[str, str]] = [
    ("ethernet", "link up"),
    ("ethernet", "gateway ping"),
    ("i2c", "scan"),
    ("power", "phase power"),
    ("mipi", "DSI display"),
    ("gpio", "held by the SPI0 driver"),  # GPIO7/8 are SPI0 CE lines
]

# Fallback parsers: pull a number out of a phase's detail string when the phase
# has not (yet) attached a structured metric. (phase, contains[], key, regex).
# These let the grader work today; as phases start passing metric=check(...),
# the structured value wins and the parser is ignored.
ACCEPT_PARSERS: List[dict] = [
    {
        "phase": "pcie",
        "contains": ["read/write integrity"],
        "key": "nvme_write_MBps",
        "regex": r"write ~(\d+)",
    },
    {
        "phase": "pcie",
        "contains": ["read/write integrity"],
        "key": "nvme_read_MBps",
        "regex": r"read ~(\d+)",
    },
    {
        "phase": "usb",
        "contains": ["USB 3.0", "read/write integrity"],
        "key": "usb3_write_MBps",
        "regex": r"write ~(\d+)",
    },
    {
        "phase": "usb",
        "contains": ["USB 2.0", "read/write integrity"],
        "key": "usb2_write_MBps",
        "regex": r"write ~(\d+)",
    },
    {
        "phase": "usb",
        "contains": ["USB 3.0", "negotiated speed"],
        "key": "usb3_link_Mbps",
        "regex": r"(\d+)\s*Mbps",
    },
    {
        "phase": "usb",
        "contains": ["USB 2.0", "negotiated speed"],
        "key": "usb2_link_Mbps",
        "regex": r"(\d+)\s*Mbps",
    },
    {
        "phase": "fan",
        "contains": ["spin-up"],
        "key": "fan_spinup_rpm",
        "regex": r"->\s*(\d+)\s*RPM",
    },
    {
        "phase": "thermal",
        "contains": ["SoC temperature"],
        "key": "soc_temp_idle_C",
        "regex": r"([\d.]+)\s*C",
    },
]


def accept_check(key, value) -> dict:
    """Grade one measured value against ACCEPT_THRESHOLDS -> structured metric.
    Phases call this: rep.add(..., metric=config.accept_check('nvme_write_MBps', v))."""
    spec = ACCEPT_THRESHOLDS.get(key, {})
    lo, hi = spec.get("min"), spec.get("max")
    ok = (
        value is not None
        and (lo is None or value >= lo)
        and (hi is None or value <= hi)
    )
    return {
        "key": key,
        "value": value,
        "unit": spec.get("unit", ""),
        "min": lo,
        "max": hi,
        "pass": bool(ok),
    }


def accept_nonpass(phase, name, detail="") -> bool:
    """True if a FAIL/SKIP is an expected exception for this station's config."""
    return any(
        p == phase and (s.lower() in name.lower() or s.lower() in detail.lower())
        for p, s in ACCEPT_NONPASS
    )
