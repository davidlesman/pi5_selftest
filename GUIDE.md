# **Raspberry Pi 5 Hardware Self-Test Guide**

Runs the Pi 5 through fourteen phases covering every major subsystem and reports each one as `PASS` / `FAIL` / `SKIP` / `INFO`. Most phases are automatic; a few pause to have you plug in a device or wire a jumper/PCB board. The process exits non-zero only if something returns as `FAIL`.

|  | Phase | Checks |
| ----- | ----- | ----- |
| automatic | `identify` | Pi 5 model, revision, RP1 gpiochip, `usb_max_current_enable` |
|  | `thermal` | SoC temp, throttle / under-voltage flags |
|  | `power` | PMIC rails; optional multimeter prompt for header pins |
|  | `i2c` | bus present, device scan |
|  | `pcie` | link speed, NVMe r/w stress (SHA-256, 3×1 GiB) |
|  | `ethernet` | carrier, negotiated speed, gateway ping |
|  | `rtc` | clock reads, skew vs system time |
|  | `fan` | idle RPM, then commanded spin-up |
| plug-in | `usb` | each of 4 ports: enumerate, speed, power budget, r/w |
|  | `mipi` | camera enumerate \+ still capture |
| wiring | `uart` | GPIO14→GPIO15 loopback @ 115200 |
|  | `spi` | GPIO10→GPIO9 loopback @ 1 MHz |
|  | `gpio` | all 28 header GPIOs, both directions, 14 pairs |
|  | `pulls` | internal pull-up / pull-down resistors |

## **Requirements**

* Pi 5 on Raspberry Pi OS, and a **5V/5A USB-C PD supply**. Underpowering is the most common source of failures, USB 3.0 especially.
* For wiring phases: female-to-female jumpers (PCB board). For hardware phases: USB flash drives (×4), NVMe HAT \+ M.2 SSD, MIPI camera, fan, I²C device.
* Optional: the PCB loopback board in `pi5_loopback/` hard-wires all GPIO/UART/SPI pairs onto one plug-on board, replacing the jumpers.

## **Setup**

```shell
git clone https://github.com/davidlesman/pi5_selftest.git
sudo apt install -y \
  python3-gpiozero python3-lgpio python3-serial python3-spidev \
  i2c-tools gpiod pciutils usbutils raspi-utils rpicam-apps \
  util-linux parted gdisk
sudo usermod -aG gpio,i2c,spi,dialout,video "$USER"   # re-login after
```

Enable the buses at boot:

```shell
sudo raspi-config nonint do_i2c 0
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_serial_hw 0      # UART hardware on
sudo raspi-config nonint do_serial_cons 1    # UART login console off
sudo reboot
```

`/boot/firmware/config.txt` must contain `dtparam=i2c_arm=on`, `dtparam=spi=on`, and `usb_max_current_enable=1`. `usb_max_current_enable` lifts the USB maximum current supply from 600 mA to 1600 mA; without it, USB 3.0 storage drawing \>600 mA (common, many want \~900 mA) browns out mid-enumeration and the `usb` phase fails.

## **Running**

This project runs as a module from the parent of the project directory, which must be named `pi5_selftest`:

```shell
# Everything, with interactive prompts (recommended for first run)
sudo python3 -m selftest.pi5_selftest full

# Automatic phases only - no wiring or hardware prompts
python3 -m selftest.pi5_selftest full --auto

# Skip specific phases
sudo python3 -m selftest.pi5_selftest full --skip usb,mipi

# Run only selected phases
sudo python3 -m selftest.pi5_selftest gpio uart spi

# Burn-in: repeat the full suite N times
sudo python3 -m selftest.pi5_selftest full --repeat 5

# Save a machine-readable JSON report
sudo python3 -m selftest.pi5_selftest full --json report.json

# Self-manage dtparam/dtoverlay (don't let the suite touch them)
sudo python3 -m selftest.pi5_selftest full --no-dt
```

At a prompt: **Enter** runs the step, **`s`\+Enter** or **Ctrl-C** skips the phase.

Root is required for the fan, PMIC, RTC, camera, NVMe, runtime bus enable, and mounting drives; without it those checks `SKIP` and the rest proceed.

The full wiring map prints before the `gpio` phase to facilitate the testing process.

## **Pin numbering**

Two schemes, and it is easy to trip up on them. The `gpio` and `pulls` configs use **BCM** numbers; `(2, 3)` is GPIO2↔GPIO3, i.e. physical pins 3 and 5, *not* physical pins 2–3. The header-voltage check uses **physical** pin numbers, since that's what you probe.

Results print as `BCM<n>/pin<p>`; use the `pin` half when locating a hole.

## **Design notes**

* **Phase order is fixed:** `uart` and `spi` run before `gpio`/`pulls`. The GPIO phase claims pins 9/10/11 and 14/15 as plain GPIO, so the bus loopbacks have to go first or they'd have nothing to test.
* **Pin-mux restore.** The suite snapshots each header pin's boot-time alt-function before any phase runs, and re-applies it at the end (releasing all line claims first, so the exit-time reset doesn't clobber it). This is the `bus pin mux restored` line, and it's why SPI/UART/I²C survive repeated runs without a reboot.
* **USB readiness.** The `usb` phase waits for the block device to report nonzero size before trusting it (a freshly inserted USB 3.0 stick reports size 0 for a beat while the link trains) and keys on the sysfs port path, so port identity is stable regardless of enumeration order.
* Any uncaught exception in a phase is trapped as `phase <name> crashed → FAIL` so one bad phase doesn't abort the run.

## Full test walkthrough

A complete run, from a powered-down board to reading the summary. Attach whatever optional
hardware you have; the phases for anything missing just SKIP.

### 1. Power down, then connect hardware

All wiring goes on with the Pi off.

**NVMe HAT + M.2 SSD (Elecrow).** Seat the SSD in the M.2 slot at an angle, press flat, screw
it to the standoff. Connect the PCIe FFC ribbon between the HAT and the Pi's PCIe connector;
lift the latch, insert contacts-down per the silkscreen, close the latch. Mount the HAT on its
standoffs. The HAT's power LED only proves the HAT has power, not that the data ribbon is
seated. A loose/reversed ribbon is the usual cause of `pcie` LINK DOWN.

**MIPI camera.** Lift the CAM0 (or CAM1) latch, insert the ribbon the correct way round for that
connector, close the latch. A loose or reversed ribbon is why `mipi` finds nothing or fails the
capture.

**Fan.** Into the 4-pin FAN header (not a GPIO fan pin). 0 RPM at idle is expected.

**Loopback: PCB or wires.** Either seat the `pi5_loopback` board on the 40-pin header, or wire
the 14 jumper pairs from the table above. Either way, leave the UART pair (pin8↔pin10) and SPI
pair (pin19↔pin21) in, `uart` and `spi` reuse them.


**USB drives** stay out for now. The `usb` phase is interactive and names each port one at a
time. **I²C device** (optional): SDA=pin3, SCL=pin5, 3V3=pin1,
GND=pin6.

### 2. Power up and SSH in

Power on, then from another machine:

    ssh <user>@<pi-hostname>.local      # or the IP

(If SSH isn't enabled: `sudo raspi-config` → Interface Options → SSH, or drop an empty `ssh`
file on the boot partition before first boot.) Interactive prompts work fine over SSH.


### 3. Start the run

From the parent of the cloned folder:

    sudo python3 -m pi5_selftest.pi5_selftest full

`sudo` so the root-only phases don't skip. Swap `full` for `full --auto` if you want only the
hands-off phases and no prompts.

### 4. Go through the phases

They run in fixed order. Automatic ones print and move on; the rest pause for you.

1. **identify, thermal, power** | automatic. `power` may offer a multimeter prompt for the
   header pins; press `s` to skip it if you're not probing.
2. **i2c** | automatic. Zero devices is fine if nothing's wired.
3. **pcie** | automatic, with one exception: if the SSD is *blank* it asks before creating a
   temp partition (wiped back after). A drive with a filesystem is tested with no prompt.
4. **ethernet, rtc, fan** | automatic. You'll hear the fan spin up.
5. **usb** | interactive. It names a port ("bottom-left, USB 3.0"); plug a drive in, it tests,
   then asks you to remove it. Repeats for all four ports. `s` skips any port.
6. **mipi** | interactive. Accept the prompt to capture a still.
7. **uart, spi** | interactive. Each confirms its jumper, then runs the loopback. (They run
   before `gpio` on purpose, see Design notes.)
8. **gpio** | prints the full wiring map, waits for you to confirm wiring, tests every pair
   both directions.
9. **pulls** | asks you to remove any jumpers tying the test pins to a rail, then checks the
   internal pulls.

### 5. Read the result

Lines print live; the end gives a pass/fail/skip tally with every FAIL listed, and the command
exits non-zero only if something failed. A SKIP next to hardware you didn't attach is expected.
Map any FAIL to a fix in the Failure reference below. Add `--json report.json` to capture a run,
or `--repeat N` to shake out an intermittent fault.

## **Failure reference (needs confirmation on some errors: I2C, ethernet, under-voltage tests)**

**`identify`**

* `Is a Raspberry Pi 5` → FAIL | wrong board; the pin maps assume a Pi 5, so nothing downstream is trustworthy.
* `USB Max Current Enable` → FAIL | capped at 600 mA. Set `usb_max_current_enable=1` and reboot. Fix this before chasing USB failures, ensure power supply can handle demand.

**`thermal`**

* `SoC temperature` → FAIL (≥80 °C) | cooling/airflow problem if it's hot at idle.
* `Throttle / under-voltage` → FAIL (active) | supply or cable. The PASS-but-"occurred since boot" variant is an early warning of the same.

**`power`**

* `PMIC read` → FAIL (no data) | run as root.
* A rail → FAIL | out-of-window rail; supply, PMIC, or a heavy load. Usually agrees with the thermal under-voltage flag.
* `Header pin N voltage` → FAIL | suspect probe placement before the board.

**`I2c`**

* `I2C bus` → SKIP | enable `dtparam=i2c_arm=on` \+ reboot.
* Zero devices when one is expected \-\> wire to SDA=pin3, SCL=pin5, 3V3=pin1, GND=pin6; on a still-empty rescan, check 3V3/GND, that SDA/SCL aren't swapped, and address-select pins. A `UU` entry is a present device already claimed by a driver, not a miss.

**`pcie`**

* `PCIe external link` → LINK DOWN | reseat the FPC ribbon (**orientation matters**) and reseat the SSD. A lit HAT power LED says nothing about the data ribbon. Confirm with `lspci` and `ls /dev/nvme*`.
* `NVMe read/write` → SKIP ("disk contains data or unknown signatures") | this is **not** the general “has a filesystem” case. A drive with a filesystem is tested either way: mounted-writable is used in place, unmounted is mounted by the suite. This skip is only reached when neither found a usable filesystem and the disk isn’t blank. Fix by exposing a writable mount, or blank the disk to get the auto-partition path (`wipefs -a <DISK>`, `sgdisk --zap-all <DISK>`, `partprobe <DISK>`, might need sudo)
* `NVMe … integrity` → FAIL | SHA-256 mismatch on readback; a real integrity fault. Reseat SSD/HAT/ribbon, suspect marginal power under load, and treat the SSD as suspect if it recurs.

**`ethernet`**

* `Ethernet interface` → FAIL | no `eth*`/`enx*`/`end*`; check `ip link` (or that a USB NIC enumerated).
* `<iface> link up` → FAIL | no carrier; cable/port/switch.
* `gateway ping` → FAIL | link up but gateway silent; DHCP lease, firewall, or gateway ICMP.

**`rtc`** | `RTC vs system clock` → INFO (large skew) is normal with no backup battery fitted or before NTP sync; not a fault.

**`fan`**

* `Fan spin-up test` → SKIP (needs root) | run with sudo.
* `Fan spin-up test` → FAIL | commanded to max but RPM didn't climb. Wrong header (must be the 4-pin FAN header), loose connector, or obstruction.

**`usb`** | failure messages name the cause; read them.

* "power issue … requests *N* mA … limit 600 mA" | exceeded the current cap and browned out. Power fix: `usb_max_current_enable=1` \+ 5V/5A supply. Most common failure here.
* `power budget` → FAIL | same fix; the line gives requested vs allowed mA.
* "SuperSpeed link didn't train" | blue port fell back to 480Mbps. Swap cable/drive, confirm the supply; a known-good drive training fine isolates it to the original cable/drive.
* "READ CAPACITY failed under uas" | UAS-incompatible enclosure. Force BOT with `usbcore.quirks=<VID:PID>:k` in `cmdline.txt` \+ reboot. Verify the port itself with a known-good drive first.
* "kernel logged nothing for this port" | dead port or drive never seated; test the drive elsewhere to isolate.
* `read/write` → SKIP (run with sudo) | needed to mount.

**`mipi`**

* `MIPI cameras` → INFO (none) | third-party modules need a `dtoverlay`; check ribbon orientation on both ends.
* `Camera 0 capture` → FAIL | listed but no usable JPEG; reseat the ribbon and run `rpicam-hello`/`rpicam-still` manually for the underlying error.

**`uart`**

* `UART loopback` → SKIP | add `dtoverlay=uart0-pi5` (or raspi-config: login shell off, hardware on) \+ reboot. Want `a4` on `pinctrl get 14-15`.
* `UART TXD->RXD` → FAIL | Reseat the jumper wire between Pin 8 and Pin 10, then reboot to clear the pin state and ensure the serial login console is turned off. Verify pins with: `pinctrl get 14-15` (Should show `a0` or `TXD0`/`RXD0`, not `ip`).

**`spi`**

* `SPI loopback` → SKIP | `dtparam=spi=on` \+ reboot for a reliable node.
* `SPI MOSI->MISO` → FAIL | The detail distinguishes the two cases: "NOT in SPI mode" \= an overlay/HAT grabbed the pins (check config.txt); "ARE in SPI mode … re-seat" \= config's fine, it's the jumper. Confirm with `pinctrl get 9-11` (want `a0` output).

**`gpio`**

* `gpiozero import` → FAIL | install `python3-gpiozero python3-lgpio`.
* A pair → FAIL ("drove 1, read 0") | jumper isn't contacting or is in the wrong holes; reseat the named `pin`.
* GPIO (7,8) → SKIP | expected with `spi=on` (SPI0 CE0/CE1; tested by the SPI phase).
* GPIO (0,1) → SKIP | expected with a HAT EEPROM holding the ID bus.
* Other "reserved by another driver" → run the suggested `gpioinfo | grep`; usually a boot-time overlay in config.txt.

**`pulls`** | a pin → FAIL ("tied to a fixed level") means a jumper still ties it to a rail. Remove all jumpers from the pull-test pins (BCM 4,5,6,13,16,17,19,20,21,22,26,27) and re-run; a failure with everything unwired points at a short on that pin.

## **Cross-cutting**

| Symptom | Fix |
| ----- | ----- |
| `ImportError: attempted relative import…` | Run as a module from the parent dir (`python3 -m pi5_selftest.pi5_selftest …`), not the file directly. |
| `not running as root` warning | Re-run with sudo, or accept that fan/PMIC/RTC/camera/NVMe/dt checks `SKIP`. |
| Bus pins stuck in `input` after a run | Only pre-dates the mux-restore; reboot once and subsequent runs self-correct. |
| Many `SKIP`s under `--auto` | Expected as `--auto` drops all interactive phases. |

