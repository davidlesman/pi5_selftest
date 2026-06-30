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
# Spec lives here; report.py reads it. Verdict rule (in report.py) is a single
# honest line: the unit FAILs if ANY check FAILs or ANY measurement is out of
# spec. SKIP = "not tested" and never counts. There is deliberately no
# forgive-list -- things this station does not test simply are not run / are
# SKIPped at the source (e.g. ethernet with no cable).
#
# ACCEPT_THRESHOLDS order == the order rows appear in the report's MEASUREMENTS
# table. Floors seeded from known-good runs, with margin.
# ===========================================================================
ACCEPT_THRESHOLDS: Dict[str, dict] = {
    "nvme_write_MBps": {"min": 120, "unit": "MB/s"},
    "nvme_read_MBps": {"min": 900, "unit": "MB/s"},
    "usb3_write_MBps": {"min": 80, "unit": "MB/s"},
    "usb2_write_MBps": {"min": 18, "unit": "MB/s"},
    "usb3_link_Mbps": {"min": 5000, "unit": "Mbps"},
    "usb2_link_Mbps": {"min": 480, "unit": "Mbps"},
    "usb_power_limit_mA": {
        "min": 1600,
        "unit": "mA",
    },  # guards the 600mA-cap regression
    "pcie_link_GTs": {"min": 5.0, "unit": "GT/s"},
    "fan_spinup_rpm": {"min": 3000, "unit": "RPM"},
    "soc_temp_idle_C": {"max": 75, "unit": "C"},
    "rail_5V_V": {"min": 4.75, "max": 5.25, "unit": "V"},
    "rail_3V3_V": {"min": 3.20, "max": 3.40, "unit": "V"},
    "rail_1V8_V": {"min": 1.70, "max": 1.90, "unit": "V"},
    "rail_VDDCORE_V": {"min": 0.60, "max": 1.05, "unit": "V"},
    # USB READ throughput is deliberately absent (cache-inflated, ~739-1078).
}

# Human labels for the MEASUREMENTS table (key -> left-column text).
ACCEPT_LABELS: Dict[str, str] = {
    "nvme_write_MBps": "NVMe write",
    "nvme_read_MBps": "NVMe read",
    "usb3_write_MBps": "USB 3.0 write (slowest port)",
    "usb2_write_MBps": "USB 2.0 write (slowest port)",
    "usb3_link_Mbps": "USB 3.0 link speed",
    "usb2_link_Mbps": "USB 2.0 link speed",
    "usb_power_limit_mA": "USB power pool",
    "pcie_link_GTs": "PCIe link",
    "fan_spinup_rpm": "Fan spin-up",
    "soc_temp_idle_C": "SoC temperature (idle)",
    "rail_5V_V": "5V rail",
    "rail_3V3_V": "3V3 rail",
    "rail_1V8_V": "1V8 rail",
    "rail_VDDCORE_V": "VDD_CORE",
}

# Fallback parsers: pull a number out of a phase's detail string when the phase
# has not attached a structured metric. (phase, contains[], key, regex).
# Structured metric (rep.add(..., metric=accept_check(...))) always wins.
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
        "phase": "pcie",
        "contains": ["PCIe link"],
        "key": "pcie_link_GTs",
        "regex": r"([\d.]+)\s*GT/s",
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
        "phase": "usb",
        "contains": ["power budget"],
        "key": "usb_power_limit_mA",
        "regex": r"system limit is (\d+)\s*mA",
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
    {
        "phase": "power",
        "contains": ["5V input"],
        "key": "rail_5V_V",
        "regex": r"([\d.]+)\s*V",
    },
    {
        "phase": "power",
        "contains": ["3.3V rail"],
        "key": "rail_3V3_V",
        "regex": r"([\d.]+)\s*V",
    },
    {
        "phase": "power",
        "contains": ["1V8_SYS_V"],
        "key": "rail_1V8_V",
        "regex": r"([\d.]+)\s*V",
    },
    {
        "phase": "power",
        "contains": ["VDD_CORE_V"],
        "key": "rail_VDDCORE_V",
        "regex": r"([\d.]+)\s*V",
    },
]


def accept_check(key, value) -> dict:
    """Grade one measured value against ACCEPT_THRESHOLDS -> structured metric.
    Rounds per unit so the report never shows raw floats. Phases may call this:
    rep.add(..., metric=config.accept_check('nvme_write_MBps', v))."""
    spec = ACCEPT_THRESHOLDS.get(key, {})
    lo, hi = spec.get("min"), spec.get("max")
    unit = spec.get("unit", "")
    if value is not None:
        if unit in ("RPM", "Mbps", "mA"):
            value = int(round(value))
        elif unit == "V":
            value = round(value, 2)
        else:
            value = round(value, 1)
    ok = (
        value is not None
        and (lo is None or value >= lo)
        and (hi is None or value <= hi)
    )
    return {
        "key": key,
        "value": value,
        "unit": unit,
        "min": lo,
        "max": hi,
        "pass": bool(ok),
    }
