# Matrix Portal RGB Clock

A room-facing RGB LED matrix clock built on the Adafruit Matrix Portal M4,
running CircuitPython. Displays time, date, indoor and outdoor environment
data, and scrolling messages; brightness adapts automatically to ambient
light; reports status to and pulls outdoor weather from Home Assistant.

Full behavioral spec: [`matrix_clock_requirements.md`](matrix_clock_requirements.md).
Guidance for AI coding assistants working in this repo: [`CLAUDE.md`](CLAUDE.md).

## Hardware

| Product ID | Item | Role |
|---|---|---|
| 4745 | Adafruit Matrix Portal M4 | Brain + WiFi + display driver |
| 2279 | 64×32 RGB LED Matrix — 3mm pitch | Display panel |
| 1466 | 5V 4A Switching Power Supply | Main power |
| 4767 | 5V Power Cable for RGB Matrices | Panel power connection |
| 1328 | DC Barrel Jack to Alligator Clips | PSU barrel jack → Portal terminals |
| 5188 | DS3231 Precision RTC — STEMMA QT | Battery-backed accurate timekeeping |
| 4566 | AHT20 Temp/Humidity Sensor — STEMMA QT | Indoor temperature and humidity |
| 4681 | BH1750 Ambient Light Sensor — STEMMA QT | Adaptive display brightness |
| 4399 | STEMMA QT Cable 50mm (×3) | Daisy-chain sensors over I2C |

All three sensors daisy-chain off the Portal's STEMMA QT connector on one I2C
bus — no address conflicts (DS3231 `0x68`, AHT20 `0x38`, BH1750 `0x23`).

## Features

- DS3231 RTC keeps time when WiFi is unavailable — clock starts immediately
  on boot if the RTC holds a valid time; no network round-trip needed
- DS3231 always stores **UTC only** — local time (and DST) is computed at
  display time from a POSIX timezone string, so there's never a manual clock
  change
- NTP sync once per day corrects RTC drift; multiple NTP servers are tried
  in order, with IP addresses ahead of hostnames so DNS issues don't block a
  sync (see [NTP notes](#ntp-notes) below)
- WiFi connects only when needed — NTP sync, HA fetch, HA push — and
  disconnects immediately after each operation
- Adaptive brightness from a BH1750 ambient light sensor, stepped smoothly
  rather than snapping between levels
- Five cycling display modes: Clock, Clock + Date, Indoor Environment,
  Outdoor Weather (from Home Assistant), and a scrolling message
- Reports to Home Assistant on a configurable interval: DS3231 chip
  temperature, BH1750 lux, last NTP sync time, WiFi RSSI, current display
  mode — entities are auto-created on first POST, no HA YAML needed
- Every failure mode (no WiFi, no HA, a dead sensor, a failed NTP sync)
  degrades gracefully instead of hanging or blanking the panel — see the
  degradation table in the requirements doc

## Setup

### 1. Install CircuitPython

Flash the latest stable CircuitPython release for the Matrix Portal M4. The
board will mount as a `CIRCUITPY` USB drive.

### 2. Vendor the required libraries

Download the [Adafruit CircuitPython bundle](https://circuitpython.org/libraries)
matching your CircuitPython version and copy these into a `lib/` folder on
`CIRCUITPY`:

- `adafruit_matrixportal`
- `adafruit_ds3231`
- `adafruit_ahtx0`
- `adafruit_bh1750`
- `adafruit_display_text`
- `adafruit_requests`
- `adafruit_connection_manager`
- `adafruit_ntp`

### 3. Configure `settings.toml`

Edit the `settings.toml` in this repo directly — it's read by CircuitPython
at boot via `os.getenv`, so no separate secrets file is needed. At minimum,
set `WIFI_SSID` / `WIFI_PASSWORD`, `HA_HOST` / `HA_TOKEN` (a long-lived
access token from your HA profile), `DEVICE_NAME`, and `TIMEZONE`:

```toml
# Eastern:  "EST5EDT,M3.2.0,M11.1.0"
# Central:  "CST6CDT,M3.2.0,M11.1.0"
# Mountain: "MST7MDT,M3.2.0,M11.1.0"
# Pacific:  "PST8PDT,M3.2.0,M11.1.0"
TIMEZONE = "EST5EDT,M3.2.0,M11.1.0"
```

`settings.toml` holds real credentials once filled in — don't commit it with
production values. Leaving `WIFI_SSID` or `HA_HOST`/`HA_TOKEN` blank disables
that subsystem permanently (logged once at boot) rather than retrying forever,
so a clock-only, fully offline deployment is a supported configuration.

Every other tunable (mode order/dwell times, colors, brightness thresholds,
report intervals) lives in the same file — see the file's comments or the
requirements doc for the full schema.

### 4. Deploy

Copy `code.py` and every `.py` module in this repo (`config.py`, `tz.py`,
`rtc_manager.py`, `sensors.py`, `brightness.py`, `display_modes.py`,
`wifi_manager.py`, `ha_client.py`) plus `settings.toml` and `lib/` onto the
`CIRCUITPY` drive. The board auto-reloads on save. Watch the serial console
(e.g. `screen`, Mu, or `tio`) for boot and runtime log output.

## NTP notes

Multiple CircuitPython/ESP8266 clock projects (including a sibling ESP8266 +
DS3231 clock this project's `NTP_SERVERS` list and retry order were carried
over from) ran into NTP requests going unanswered under two specific
conditions, both addressed here:

- **DNS-dependent hostnames as the first server tried.** If DNS isn't
  immediately usable right after associating, a hostname-only NTP server list
  can stall or fail before ever reaching a server. `NTP_SERVERS` in
  `settings.toml` lists IP addresses first (Google's and NIST's NTP servers)
  and falls back to `pool.ntp.org` last, so a sync doesn't depend on DNS
  working at all unless every IP attempt already failed.
- **Sending the first network request too soon after connecting.**
  `wifi_manager.connect()` adds a brief settle delay after
  `wifi.radio.connect()` returns, before any socket traffic is sent — see the
  comment in `wifi_manager.py` for the specific failure mode this guards
  against.

`wifi_manager.ntp_sync()` tries every configured server in order and returns
`None` (leaving the RTC untouched) only if all of them fail — the boot
sequence then retries the whole list every 60 seconds, and the main loop
retries the whole list on the next daily cycle.

## Known deviations / limitations

- **Clock mode uses 16px text, not the spec's literal 32px.** The built-in
  `terminalio.FONT` is a fixed 6px-wide monospace glyph; at the scale needed
  to hit 32px tall, even a 3-character string overflows the 64px-wide panel.
  Scale 2 (16px) is the largest that fits a full "H:MM" string without
  clipping. A custom narrow-glyph bitmap font would be needed to hit 32px for
  real — noted as a deferred option in `display_modes.py`.
- **Scroll mode shows only the static `SCROLL_MESSAGE`** from `settings.toml`
  in this pass — there's no HA-pushed scroll message mechanism yet.
- **POSIX TZ parsing supports only the `Mm.n.d` transition rule form**
  (covers all standard US/EU zones, including all four examples in
  `settings.toml`), not the legacy Julian-day (`Jn`/`n`) forms.
