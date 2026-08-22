"""Standalone hardware self-test: LED matrix, I2C sensors, WiFi/NTP.

Not imported by code.py -- this is a bench/field diagnostic, run manually.
CircuitPython has no shell or argparse, so there's no CLI: importing this
module runs the whole suite once, top to bottom, and prints a PASS/FAIL/SKIP
line per component plus a final summary.

How to run:
    1. Deploy it alongside the other modules (deploy.ps1 copies it).
    2. Open a serial console (Mu, tio, screen, PuTTY) to the board.
    3. Press Ctrl+C to stop the running code.py loop, dropping to the >>> REPL.
    4. Type: import hw_selftest
    5. Ctrl+D (or reset) afterward to resume normal code.py operation.

Reuses the same wrapper modules code.py does (rtc_manager, sensors,
wifi_manager, config, display_modes) rather than talking to the hardware
directly, so this stays correct if those modules' error handling changes.
"""
import time

import board
import displayio

import config
import display_modes
import rtc_manager
import sensors
import wifi_manager
from log import log

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_EXPECTED_I2C = {0x68: "DS3231", 0x38: "AHT20", 0x23: "BH1750"}
_MATRIX_COLORS = (
    ("Red", 0xFF0000),
    ("Green", 0x00FF00),
    ("Blue", 0x0000FF),
    ("White", 0xFFFFFF),
)
_MATRIX_COLOR_HOLD_S = 2.5

_results = []


def record(name, status, detail):
    _results.append((name, status, detail))
    log("[{}] {} - {}".format(status, name, detail))


def _run_test(name, fn, *args):
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001 -- one bad test must not abort the suite
        record(name, FAIL, "unexpected error: {}".format(e))


def _test_i2c_scan(i2c):
    while not i2c.try_lock():
        pass
    try:
        found = i2c.scan()
    finally:
        i2c.unlock()

    missing = [
        "{} (0x{:02X})".format(label, addr)
        for addr, label in _EXPECTED_I2C.items()
        if addr not in found
    ]
    found_hex = ["0x{:02X}".format(addr) for addr in found]
    if missing:
        record("i2c_scan", FAIL, "missing: {}; bus has: {}".format(", ".join(missing), found_hex))
    else:
        record("i2c_scan", PASS, "bus has: {}".format(found_hex))


def _test_rtc(i2c):
    rtc_mgr = rtc_manager.RTCManager(i2c)
    if not rtc_mgr.is_valid:
        if rtc_mgr.read_utc() is None:
            record("rtc", FAIL, "DS3231 not found on the bus")
        else:
            record("rtc", FAIL, "DS3231 present but invalid (lost power or year < 2020)")
        return
    utc = rtc_mgr.read_utc()
    chip_temp = rtc_mgr.read_chip_temperature()
    record(
        "rtc",
        PASS,
        "utc={:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z chip_temp_c={}".format(
            utc.tm_year, utc.tm_mon, utc.tm_mday, utc.tm_hour, utc.tm_min, utc.tm_sec, chip_temp
        ),
    )


def _test_indoor(i2c):
    hub = sensors.SensorHub(i2c)
    reading = hub.read_indoor()
    if reading is None:
        record("indoor_aht20", FAIL, "AHT20 not found or read failed")
        return
    temperature_c, humidity_pct = reading
    record(
        "indoor_aht20",
        PASS,
        "temperature_c={:.1f} humidity_pct={:.1f}".format(temperature_c, humidity_pct),
    )


def _test_lux(i2c):
    hub = sensors.SensorHub(i2c)
    lux = hub.read_lux()
    if lux is None:
        record("lux_bh1750", FAIL, "BH1750 not found or read failed")
        return
    record("lux_bh1750", PASS, "lux={:.1f}".format(lux))


def _test_wifi_and_ntp(cfg):
    if not cfg.wifi_configured:
        record("wifi", SKIP, "WIFI_SSID not set in settings.toml")
        record("ntp", SKIP, "wifi not configured")
        return

    with wifi_manager.session(cfg) as sess:
        if not sess.connected:
            record("wifi", FAIL, "could not associate to {}".format(cfg.wifi_ssid))
            record("ntp", SKIP, "wifi test failed")
            return
        record("wifi", PASS, "connected to {} rssi={}".format(cfg.wifi_ssid, sess.rssi()))

        utc = wifi_manager.ntp_sync(cfg)
        if utc is None:
            record("ntp", FAIL, "all configured NTP servers failed: {}".format(cfg.ntp_servers))
        else:
            record(
                "ntp",
                PASS,
                "synced {:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
                    utc.tm_year, utc.tm_mon, utc.tm_mday, utc.tm_hour, utc.tm_min, utc.tm_sec
                ),
            )


def _solid_group(color):
    bitmap = displayio.Bitmap(display_modes.WIDTH, display_modes.HEIGHT, 1)
    palette = displayio.Palette(1)
    palette[0] = color
    group = displayio.Group()
    group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
    return group


def _test_matrix():
    display = display_modes.init_display()
    display.brightness = 1.0

    for name, color in _MATRIX_COLORS:
        log("hw_selftest: matrix showing {}".format(name))
        display.root_group = _solid_group(color)
        time.sleep(_MATRIX_COLOR_HOLD_S)

    answer = input("All pixels lit evenly across all 4 colors, no dead/stuck pixels? [y/n] ")
    if answer.strip().lower().startswith("y"):
        record("matrix", PASS, "human-confirmed, no dead/stuck pixels")
    else:
        record("matrix", FAIL, "human-reported dead/stuck pixel(s) or uneven color")


def print_summary():
    counts = {PASS: 0, FAIL: 0, SKIP: 0}
    log("\n---- hw_selftest summary ----")
    for name, status, detail in _results:
        log("{:<6} {:<14} {}".format(status, name, detail))
        counts[status] += 1
    log(
        "Result: {} PASS, {} FAIL, {} SKIP".format(counts[PASS], counts[FAIL], counts[SKIP])
    )


def run():
    log("hw_selftest: ==== starting hardware self-test ====")
    i2c = board.I2C()
    cfg = config.load()

    _run_test("i2c_scan", _test_i2c_scan, i2c)
    _run_test("rtc", _test_rtc, i2c)
    _run_test("indoor_aht20", _test_indoor, i2c)
    _run_test("lux_bh1750", _test_lux, i2c)
    _run_test("wifi/ntp", _test_wifi_and_ntp, cfg)
    _run_test("matrix", _test_matrix)

    print_summary()


run()
