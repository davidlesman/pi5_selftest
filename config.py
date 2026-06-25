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
