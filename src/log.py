"""Timestamped debug logging -- a drop-in replacement for print().

Prefixes every line with seconds-since-boot. Monotonic time (not the RTC) is
the source: logging has to work identically before the RTC/WiFi are even
known-good, and modules that log here (sensors, wifi_manager, rtc_manager,
...) shouldn't need to depend on rtc_manager just to get a clock.
"""
import time


def log(*args, **kwargs):
    print("[{:10.3f}]".format(time.monotonic()), *args, **kwargs)
