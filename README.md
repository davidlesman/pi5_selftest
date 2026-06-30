# Raspberry Pi 5 Hardware Self-Test

Comprehensive hardware self-test for Pi 5 boards. Runs a sequence of automated and
interactive phases covering every major subsystem: power rails, GPIO, SPI, UART, I2C,
USB, PCIe/NVMe, Ethernet, RTC, fan, MIPI camera, and internal pull resistors.

---

## Requirements

### Hardware
- Raspberry Pi 5
- 5V/5A USB-C PD supply (official 27W recommended — USB 3.0 storage needs up to 1.6A)
- Jumper wires for GPIO loopback and UART/SPI loopback tests
- Optional: Elecrow NVMe HAT + M.2 SSD, USB flash drives (×4), MIPI camera, fan

### System packages
```bash
sudo apt update
sudo apt install -y \
  python3-gpiozero python3-lgpio python3-serial python3-spidev \
  i2c-tools gpiod pciutils usbutils raspi-utils rpicam-apps \
  util-linux parted gdisk
sudo usermod -aG gpio,i2c,spi,dialout,video "$USER"   # log out/in after
```

### Python packages
Covered by the apt install above. If running in a venv, use `requirements.txt`:
```bash
pip install -r requirements.txt
```

---

## Setup

### 1. Enable buses

SPI and UART must be boot-enabled — runtime enable is unreliable on Pi 5:
```bash
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_serial_hw 0      # enable UART hardware
sudo raspi-config nonint do_serial_cons 1    # disable login console on UART
sudo reboot
```

`/boot/firmware/config.txt` must contain:
```
dtparam=i2c_arm=on
dtparam=spi=on
usb_max_current_enable=1
```

`usb_max_current_enable=1` raises the USB port pool from 600 mA to 1600 mA.
Without it, the `identify` phase reports FAIL and USB 3.0 storage will brown out
on drives requesting more than 600 mA (e.g. Lexar USB 3.0 wants 896 mA).

Verify SPI pins are in bus mode before running:
```bash
pinctrl get 9-11    # want a0 ... SPI0_MISO / SPI0_MOSI / SPI0_SCLK  (NOT "input")
```

### 2. Wire the header

The suite prints the full physical-pin wiring list before the GPIO phase each run.

| Pair | BCM A → BCM B | Physical | Notes |
|------|--------------|----------|-------|
| 1 | GPIO2 → GPIO3 | pin3 ↔ pin5 | |
| 2 | GPIO4 → GPIO17 | pin7 ↔ pin11 | also pull-test pins |
| 3 | GPIO27 → GPIO22 | pin13 ↔ pin15 | also pull-test pins |
| 4 | GPIO5 → GPIO6 | pin29 ↔ pin31 | also pull-test pins |
| 5 | GPIO13 → GPIO19 | pin33 ↔ pin35 | also pull-test pins |
| 6 | GPIO26 → GPIO21 | pin37 ↔ pin40 | also pull-test pins |
| 7 | GPIO20 → GPIO16 | pin38 ↔ pin36 | also pull-test pins |
| 8 | GPIO12 → GPIO25 | pin32 ↔ pin22 | |
| 9 | GPIO7 → GPIO8 | pin26 ↔ pin24 | SPI0 CE1/CE0 — **SKIPS** while `spi=on` |
| 10 | GPIO24 → GPIO23 | pin18 ↔ pin16 | |
| 11 | GPIO18 → GPIO11 | pin12 ↔ pin23 | |
| 12 | GPIO14 → GPIO15 | pin8 ↔ pin10 | **UART jumper** — leave in for uart+gpio phases |
| 13 | GPIO9 → GPIO10 | pin21 ↔ pin19 | **SPI jumper** (MISO↔MOSI) — leave in for spi+gpio phases |
| 14 | GPIO0 → GPIO1 | pin27 ↔ pin28 | ID_SD/ID_SC — **SKIPS** if HAT EEPROM holds them |

**Pulls phase**: Jumpers can stay in, if any jumpers are on the 3.3V/5V/GND pins, remove them.

**Fan**: plug into the 4-pin FAN header. 0 RPM at idle is normal; the phase commands
a spin-up to confirm it responds.

---

## Running

The suite uses relative imports — run as a module from the `code/` parent directory:

```bash
# Everything, with interactive prompts (recommended for first run)
sudo python3 -m selftest.pi5_selftest full

# Automatic phases only — no wiring or hardware prompts
python3 -m selftest.pi5_selftest full --auto

# Skip specific phases
sudo python3 -m selftest.pi5_selftest full --skip usb,mipi

# Run only selected phases
sudo python3 -m selftest.pi5_selftest gpio uart spi

# Burn-in: repeat the full suite N times
sudo python3 -m selftest.pi5_selftest full --repeat 5

# Write report files to a specific directory (default: current dir)
sudo python3 -m selftest.pi5_selftest full --out-dir /tmp/reports

# Manage dtparam/dtoverlay yourself (don't let the suite touch them)
sudo python3 -m selftest.pi5_selftest full --no-dt
```

At any interactive prompt: **Enter** = do the step, `s`+Enter or **Ctrl-C** = skip the phase.

`sudo` is required for: fan/PMIC/RTC reads, raw NVMe access, runtime dtparam enable,
and mounting USB drives. Without it those checks are skipped.

---

## Phases

| Phase | Auto? | What it tests |
|-------|-------|---------------|
| `identify` | ✓ | Board model, revision, RP1 gpiochip, `usb_max_current_enable` |
| `thermal` | ✓ | SoC temperature, throttle/under-voltage flags (`vcgencmd get_throttled`) |
| `power` | ✓ | PMIC ADC rails (5V, 3.3V, 1.8V, VDD_CORE); optional multimeter prompt for header pins |
| `i2c` | ✓ | I2C bus present + device scan (`i2cdetect`) |
| `pcie` | ✓ | PCIe enumeration, link speed; NVMe r/w stress test if a drive is present |
| `ethernet` | ✓ | Interface up, negotiated speed, gateway ping |
| `rtc` | ✓ | Onboard RTC chip present, time read, skew vs system clock |
| `fan` | ✓ | Tachometer read at idle, then commanded spin-up to confirm response |
| `usb` | hardware | Each of the 4 USB ports: enumerate, negotiated speed, power budget, r/w test |
| `mipi` | hardware | Camera enumeration via `rpicam-hello`, still capture |
| `uart` | wiring | GPIO14 TXD → GPIO15 RXD loopback at 115200 baud |
| `spi` | wiring | GPIO10 MOSI → GPIO9 MISO loopback at 1 MHz |
| `gpio` | wiring | All 28 header GPIOs via 14 loopback pairs, both drive directions |
| `pulls` | wiring | Internal pull-up/pull-down resistors on 12 GPIOs (jumpers removed) |

**Phase order matters**: `uart` and `spi` run before `gpio`/`pulls` because the gpio
phase claims those pins as plain GPIO and drops them from bus mode. The suite
re-applies the boot pin mux at the end of every run (`bus pin mux restored` line), so
SPI/UART/I2C work across repeated runs without a reboot.

---

## Device-dependent tests

- **I2C** — needs a real device on the bus (SDA=pin3, SCL=pin5, 3V3=pin1, GND=pin6).
  Cannot loopback I2C; the phase will enumerate the bus and SKIP if nothing responds.
- **PCIe/NVMe** — Elecrow NVMe HAT + M.2 SSD. A blank SSD is auto-partitioned (~1 GiB
  ext4, 3 passes) and wiped back to blank afterward. Verify hardware is present first:
  ```bash
  lspci ; ls /dev/nvme*
  ```
- **USB** — USB flash drive plugged into each port in sequence. Blue ports = USB 3.0
  (5000 Mbps expected); black ports = USB 2.0 (480 Mbps expected).
- **MIPI** — camera attached to CAM0 or CAM1 (`rpicam-hello --list-cameras`).
- **PoE** — not tested; requires Pi 5 PoE HAT + 802.3af/at switch or injector.
- **UART debug port** — the 3-pin connector next to the micro-HDMIs (`/dev/ttyAMA10`)
  is a separate UART from the header UART (`/dev/ttyAMA0`, GPIO14/15). Test with a
  Raspberry Pi Debug Probe or 3.3V USB-TTL adapter at 115200.

---

## NVMe / SSD cleanup

The suite wipes the test partition it created. To do it by hand:
```bash
sudo wipefs -a /dev/nvme0n1
sudo sgdisk --zap-all /dev/nvme0n1
sudo partprobe /dev/nvme0n1
```

---

## Troubleshooting

**`identify` FAIL: `usb_max_current_enable=0`**
Add `usb_max_current_enable=1` to `/boot/firmware/config.txt` and reboot. Without it
USB 3.0 storage that requests >600 mA will brown out mid-enumeration.

**USB FAIL: power budget exceeded / over-current**
Same fix. The phase checks `bMaxPower` from sysfs against the active system limit and
reports exactly which drive and how many mA it requested.

**USB FAIL: SuperSpeed link didn't train (5000 Mbps expected, got 480)**
Likely a cable, drive, or power issue. Try a different cable; confirm the supply is
5V/5A. The phase logs the USB transport (UAS vs BOT) and port path.

**USB FAIL: `READ CAPACITY` failed / no block device**
The drive enumerated at the USB level but the SCSI layer didn't produce `/dev/sdX`.
The phase checks dmesg for over-current and suggests a `usbcore.quirks` fix if the
drive has a known UAS issue.

**SPI or UART phase SKIP/FAIL even with jumpers in place**
Check pin mux:
```bash
pinctrl get 9-11    # SPI: want a0 for pins 9, 10, 11
pinctrl get 14-15   # UART: want a4 for pins 14, 15
```
If any show `ip` (input), the bus was dropped from alt mode. Reboot once to restore,
then the suite's end-of-run mux restore will keep them correct afterward.

**GPIO (7,8) SKIP**
Expected — GPIO7/GPIO8 are SPI0 CE0/CE1, held by the SPI driver when `spi=on`. They
are tested via the SPI phase instead.

**GPIO (0,1) SKIP**
Expected if a HAT EEPROM is attached — GPIO0/GPIO1 are the ID EEPROM bus and the
kernel holds them.

**Pulls phase fails or crashes**
Remove ALL loopback jumpers from the pull-test pins (GPIO 4, 5, 6, 13, 16, 17, 19, 20,
21, 22, 26, 27) before this phase. Jumpers override the weak internal pull and cause the
test to read the wrong level.

**`not running as root` warning**
Fan, PMIC, RTC, camera enumeration, and runtime dtparam management all need root.
Run with `sudo` for a complete test.

**Bus pins stuck in `input` mode after a previous run**
Reboot once. This only happens if the suite was run before the bus-mux restore existed.
After that, every run restores the boot alt-functions at the end automatically.

**`ImportError: attempted relative import with no known parent package`**
Run from the `code/` parent directory as a module:
```bash
sudo python3 -m selftest.pi5_selftest full
```
Not `python3 pi5_selftest.py full` from inside the `selftest/` directory.
