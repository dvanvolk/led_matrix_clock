# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

The implementation is written and lives under `src/`: `code.py` (orchestrator) plus `config.py`, `tz.py`, `rtc_manager.py`, `sensors.py`, `brightness.py`, `display_modes.py`, `wifi_manager.py`, and `ha_client.py`, along with `settings.toml`. `src/matrix_clock_requirements.md` remains the spec of record — read it in full before changing behavior, since it defines things that would otherwise require guessing (exact failure-mode handling, HA entity naming, brightness curve, etc). Keep it authoritative: update it if requirements change during further work, and check new code against it rather than re-deriving behavior from scratch. `README.md` documents known deviations from the spec (e.g. clock-mode text size) — check there too before "fixing" something that's actually a deliberate, documented tradeoff.

## What this project is

A room-facing RGB LED matrix clock running CircuitPython on an Adafruit Matrix Portal M4, driving a 64×32 HUB75 RGB panel. It shows time/date, indoor and outdoor environment data, and scrolling messages, with brightness that adapts to ambient light, and it exchanges data with Home Assistant.

## Hardware architecture

- **Matrix Portal M4** — runs CircuitPython, drives the panel, has WiFi.
- **DS3231 RTC** (I2C `0x68`) — battery-backed, authoritative timekeeping source, always stores **UTC only**.
- **AHT20** (I2C `0x38`) — indoor temperature/humidity.
- **BH1750** (I2C `0x23`) — ambient light for adaptive brightness.
- All three sensors daisy-chain off the Portal on one I2C bus via STEMMA QT — no address conflicts, so no bus-switching logic is needed.

Libraries: `adafruit_matrixportal`, `adafruit_ds3231`, `adafruit_ahtx0`, `adafruit_bh1750`, `adafruit_display_text`, `adafruit_requests`.

## Development workflow (CircuitPython, not a normal build)

There is no compiler and no package/build step. CircuitPython executes `code.py` (or `main.py`) directly off the board's `CIRCUITPY` USB mass-storage drive — deploying is copying files to that drive, and the board auto-reloads on save. There is no unit test framework in this ecosystem; validation is done on-device (serial console for logs/errors). When adding library dependencies, they get vendored into a `lib/` folder on the CIRCUITPY drive (from the Adafruit CircuitPython bundle), not installed via pip.

Secrets and all tunable configuration live in `src/settings.toml` (see schema in the requirements doc) and are read via CircuitPython's `os.getenv`. **Never hardcode WiFi credentials, HA tokens, or tunables in source — they belong in `settings.toml`.**

`src/settings.toml` is gitignored (it holds real WiFi/HA credentials once filled in) and must never be committed. `settings.toml.example` (repo root) is the checked-in placeholder template — keep it in sync whenever the schema changes (new keys, renamed keys), but never fill it with real values.

## Core architectural rules from the spec

These are easy to get subtly wrong by "helpfully" simplifying, so they're called out explicitly:

- **Time is UTC end-to-end.** DS3231 always stores UTC; local time is derived only at display time via the POSIX `TIMEZONE` string from `settings.toml`. Never write local time to the RTC.
- **Boot sequence matters:** read DS3231 first. If it's valid (year ≥ 2020, no lost-power flag), display immediately without touching WiFi. Only bring up WiFi to NTP-sync if the RTC is invalid. This keeps the clock usable offline and avoids unnecessary radio use.
- **WiFi is opportunistic, not persistent.** Connect only for NTP sync / HA fetch / HA push, then disconnect. Don't leave the radio associated between operations.
- **NTP servers are tried in order, IPs before hostnames** (to bypass DNS latency/failures first) — see `NTP_SERVERS` in `settings.toml`.
- **Every failure mode degrades gracefully and locally** rather than blocking the clock: no WiFi/HA → HA-dependent modes are silently skipped, core clock and indoor-sensor modes keep working. See the Graceful Degradation table in the requirements doc for the specific behavior per failure (WiFi down, RTC invalid, HA unreachable, AHT20/BH1750 read failure, NTP failure).
- **Brightness is a smoothed function of lux**, not a hard threshold switch — steps between `BRIGHTNESS_MIN`/`MID`/`MAX` should not jump abruptly. Sample BH1750 every display update cycle; on a read failure, hold the last known brightness rather than erroring.
- **Display modes are config-driven**, not hardcoded: `MODE_ORDER` and per-mode dwell times in `settings.toml` control what cycles and for how long. Adding/reordering modes should be a config change where possible, not a code change.
- **HA entities are auto-created on first POST** — no HA-side YAML needed. Entity IDs incorporate `DEVICE_NAME` so multiple clock units on the same HA instance don't collide.

## Out of scope (per requirements doc)

Hardware buttons, audio, touch input, OTA updates, a web config UI, and multi-panel support are explicitly not planned — don't add scaffolding for these speculatively.
