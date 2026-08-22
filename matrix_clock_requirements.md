# Matrix Portal RGB Clock — Requirements & Design

## Overview

A room-facing RGB LED matrix clock built on the Adafruit Matrix Portal M4,
driven by CircuitPython. Displays time, date, indoor and outdoor environment
data, and scrolling messages. Brightness adapts automatically to ambient light.
Integrates with Home Assistant for data exchange.

---

## Parts List

| Product ID | Item | Price | Role |
|---|---|---|---|
| 4745 | Adafruit Matrix Portal M4 | $24.95 | Brain + WiFi + display driver |
| 2279 | 64×32 RGB LED Matrix — 3mm pitch | $44.95 | Display panel |
| 1466 | 5V 4A Switching Power Supply | $14.95 | Main power |
| 4767 | 5V Power Cable for RGB Matrices | $2.50 | Panel power connection |
| 1328 | DC Barrel Jack to Alligator Clips | $2.95 | PSU barrel jack → Portal terminals |
| 5188 | DS3231 Precision RTC — STEMMA QT | $13.95 | Battery-backed accurate timekeeping |
| 4566 | AHT20 Temp/Humidity Sensor — STEMMA QT | $4.50 | Indoor temperature and humidity |
| 4681 | BH1750 Ambient Light Sensor — STEMMA QT | $4.50 | Adaptive display brightness |
| 4399 | STEMMA QT Cable 50mm (×3) | $2.85 | Daisy-chain sensors over I2C |
| **Total** | | **$116.10** | |

### I2C Sensor Chain
 
All three sensors share the same I2C bus via STEMMA QT daisy-chain.
No address conflicts:

```
Matrix Portal M4
    └── DS3231 RTC       (I2C address 0x68)
            └── AHT20    (I2C address 0x38)
                    └── BH1750  (I2C address 0x23)
```

---

## Language & Framework

- **CircuitPython** (latest stable release)
- Libraries: `adafruit_matrixportal`, `adafruit_ds3231`, `adafruit_ahtx0`,
  `adafruit_bh1750`, `adafruit_display_text`, `adafruit_requests`

---

## Hardware Requirements

- Matrix Portal M4 driving 64×32 RGB HUB75 panel at 3mm pitch
- DS3231 RTC via STEMMA QT — stores UTC, battery-backed, independent of WiFi
- AHT20 via STEMMA QT — indoor temperature and humidity
- BH1750 via STEMMA QT — ambient light level for adaptive brightness control
- 5V 4A supply connected via dedicated panel power cable and barrel jack adapter

---

## Timekeeping Requirements

- On boot: read time from DS3231
  - If DS3231 is valid (year ≥ 2020 and no lost-power flag): start displaying immediately
  - If DS3231 is invalid: connect WiFi, sync NTP, write UTC to DS3231, then display
- NTP sync once per day to correct DS3231 drift and pick up DST transitions automatically
- DS3231 always stores **UTC only** — local time conversion applied at display time
- Timezone and DST handled via POSIX timezone string — no manual clock changes ever needed
- NTP servers tried in order until one responds; hardcoded IPs used first to bypass DNS

---

## Connectivity Requirements

- WiFi connects **only** when needed: NTP sync, HA data fetch, HA data push
- WiFi disconnects after each operation to save power and reduce latency impact
- All credentials stored in `settings.toml` — never in source code
- If WiFi or HA is unavailable, degrade gracefully:
  - Clock and indoor sensors continue working
  - HA-dependent display modes are skipped silently

---

## Home Assistant Integration

### Data pulled from HA (on configurable interval)

| Data | HA Entity (configurable) |
|---|---|
| Outdoor temperature | `sensor.outdoor_temperature` |
| Outdoor weather conditions | `sensor.outdoor_conditions` |

### Data pushed to HA (on configurable interval)

| Data | HA Entity (auto-created) |
|---|---|
| AHT20 indoor temperature | `sensor.{device_name}_indoor_temperature` |
| AHT20 indoor humidity | `sensor.{device_name}_indoor_humidity` |
| BH1750 lux reading | `sensor.{device_name}_lux` |
| Last NTP sync timestamp | `sensor.{device_name}_last_ntp_sync` |

- Entities are created automatically on first POST — no HA YAML configuration needed
- Device name set in `settings.toml` so multiple clocks post to separate entities
- Friendly names derived from device name (e.g. `living_room_clock` → `Living room clock ...`)

---

## Adaptive Brightness Requirements

- BH1750 sampled on every display update cycle
- Display brightness mapped from lux to brightness level:

| Condition | Lux | Brightness |
|---|---|---|
| Bright room | > `BRIGHTNESS_HIGH_LUX` | `BRIGHTNESS_MAX` |
| Dim room | `BRIGHTNESS_LOW_LUX` – `BRIGHTNESS_HIGH_LUX` | `BRIGHTNESS_MID` |
| Dark room | < `BRIGHTNESS_LOW_LUX` | `BRIGHTNESS_MIN` |

- Brightness steps smoothly — no sudden jumps between levels
- Lux-to-zone mapping has hysteresis: once at MAX or MIN, lux must cross back
  past `BRIGHTNESS_HIGH_LUX`/`BRIGHTNESS_LOW_LUX` by `BRIGHTNESS_HYSTERESIS_LUX`
  before the zone releases back toward MID, so lux hovering right at a
  threshold doesn't flicker the brightness target every sample
- All thresholds and levels are configurable
- Minimum brightness still readable from across the room, not blinding in the dark

---

## Display Modes

There is a single top-level mode, Clock, that is always shown (`MODE_ORDER`
stays config-driven — see below — in case more top-level modes are added
later). The time is always visible; the bottom line internally rotates
through three items on its own configurable dwell time per item, skipping
any item whose backing data isn't currently available instead of stalling
on it.

### Mode: Clock
- **Content:** Time on top row, always visible; bottom row rotates through:
  - **Date** — date and day of week
  - **Indoor temperature** — from the local AHT20 sensor
  - **Outdoor temperature** — from a Home Assistant entity, skipped if
    unreachable
- **Layout:** 16px time, bottom row 8px for date / 16px for indoor and
  outdoor temperature
- **Color:** Time in primary color; date, indoor temp, and outdoor temp each
  in their own configurable color
- **Readable at:** 20ft+

---

## Configuration — `settings.toml`

All timing, credentials, entity IDs, brightness thresholds, and mode behavior
are controlled here. No values are hardcoded in source files.

```toml
# WiFi
WIFI_SSID = "your_ssid"
WIFI_PASSWORD = "your_password"

# Home Assistant
HA_HOST = "http://homeassistant.local:8123"
HA_TOKEN = "your_long_lived_access_token"
HA_REPORT_INTERVAL = 300          # seconds between HA push reports
HA_FETCH_INTERVAL = 300           # seconds between HA data pulls

# Device identity (used in HA entity IDs and friendly names)
DEVICE_NAME = "living_room_clock"

# Timezone (POSIX string — handles DST automatically)
# Eastern:  "EST5EDT,M3.2.0,M11.1.0"
# Central:  "CST6CDT,M3.2.0,M11.1.0"
# Mountain: "MST7MDT,M3.2.0,M11.1.0"
# Pacific:  "PST8PDT,M3.2.0,M11.1.0"
TIMEZONE = "EST5EDT,M3.2.0,M11.1.0"

# NTP (comma-separated, tried in order; IPs preferred over hostnames)
NTP_SERVERS = "216.239.35.0,216.239.35.4,129.6.15.28,pool.ntp.org"

# Display modes — top-level order/dwell (seconds). Only "clock" exists today.
MODE_ORDER = "clock"
MODE_DWELL_CLOCK = 30

# Dwell (seconds) for each item on the clock's rotating bottom line
BOTTOM_DWELL_DATE = 15
BOTTOM_DWELL_INDOOR = 10
BOTTOM_DWELL_OUTDOOR = 10

# Colors (RGB hex strings)
COLOR_TIME = "0xFFAA00"           # warm amber
COLOR_DATE = "0x004488"           # muted blue
COLOR_TEMP = "0xFF4400"           # warm orange
COLOR_OUTDOOR = "0x00FF88"        # green

# Adaptive brightness thresholds (lux)
BRIGHTNESS_HIGH_LUX = 200
BRIGHTNESS_LOW_LUX = 10
BRIGHTNESS_HYSTERESIS_LUX = 20    # zone-release margin, see Adaptive Brightness

# Brightness levels (0.0 – 1.0)
BRIGHTNESS_MAX = 1.0
BRIGHTNESS_MID = 0.4
BRIGHTNESS_MIN = 0.05

# Home Assistant entity IDs to pull outdoor data from
HA_OUTDOOR_TEMP_ENTITY = "sensor.outdoor_temperature"
HA_OUTDOOR_CONDITIONS_ENTITY = "sensor.outdoor_conditions"
```

---

## Graceful Degradation

| Failure | Behavior |
|---|---|
| WiFi unavailable on boot | Skip NTP; show `----` until DS3231 valid or WiFi recovers |
| DS3231 invalid + no WiFi | Display `----`; retry NTP every 60 seconds |
| HA unreachable | Skip outdoor mode; continue local sensor modes |
| AHT20 read failure | Skip indoor mode; log error to serial |
| BH1750 read failure | Hold last known brightness level |
| NTP sync failure | Retain DS3231 time; retry at next daily interval |

---

## Non-Requirements (Out of Scope)

- Hardware buttons (not needed at this time)
- Audio output
- Touch input
- OTA firmware updates
- Web configuration UI
- Multiple panels

---

## Future Considerations

- 3D printed enclosure (printer expected by end of year)
- MQTT discovery for cleaner Home Assistant device registration
- Additional display modes (sports scores, calendar events, energy usage)
- Second unit with different `DEVICE_NAME` for another room
