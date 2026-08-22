"""WiFi connect/disconnect discipline and NTP sync.

The Matrix Portal M4 (SAMD51) has no native network hardware -- WiFi goes
through the onboard ESP32 "AirLift" co-processor over SPI, driven via
adafruit_esp32spi. adafruit_connection_manager abstracts that co-processor
radio behind the same socketpool/ssl-context interface CircuitPython's
native `wifi`/`socketpool` modules provide on boards that do have a native
radio, so the rest of this module (and adafruit_requests/adafruit_ntp) don't
need to know which kind of radio they're talking to.

WiFi connects only for NTP sync / HA fetch / HA push, then disconnects
immediately after -- every network operation goes through session(), a
context manager that guarantees disconnect happens even if the operation
raises. A class-based context manager is used instead of
@contextlib.contextmanager since contextlib isn't reliably present on
CircuitPython builds.
"""
import gc
import time

import board
from digitalio import DigitalInOut

import adafruit_connection_manager
import adafruit_ntp
import adafruit_requests
from adafruit_esp32spi import adafruit_esp32spi

from log import log

_esp = None
_pool = None
_ssl_context = None

# Brief settle time after association, before the first socket/NTP call.
# esp.connect_AP() already blocks until the co-processor reports it has
# joined the network, but a sibling ESP8266 clock project (which this
# NTP_SERVERS list and retry pattern are carried over from) found NTP
# requests sent immediately after connecting would silently go unanswered --
# the radio/stack needs a moment to settle before it reliably passes
# traffic. Cheap to keep even though the blocking connect call makes it less
# likely to matter here.
_CONNECT_SETTLE_S = 0.5


def _get_esp():
    global _esp
    if _esp is None:
        esp32_cs = DigitalInOut(board.ESP_CS)
        esp32_ready = DigitalInOut(board.ESP_BUSY)
        esp32_reset = DigitalInOut(board.ESP_RESET)
        spi = board.SPI()
        _esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)
    return _esp


def _get_pool():
    global _pool, _ssl_context
    if _pool is None:
        esp = _get_esp()
        _pool = adafruit_connection_manager.get_radio_socketpool(esp)
        _ssl_context = adafruit_connection_manager.get_radio_ssl_context(esp)
    return _pool


def connect(cfg):
    if not cfg.wifi_configured:
        return False
    esp = _get_esp()
    try:
        esp.connect_AP(cfg.wifi_ssid, cfg.wifi_password)
        time.sleep(_CONNECT_SETTLE_S)
        log("wifi: connected to {}, ip={}".format(cfg.wifi_ssid, esp.pretty_ip(esp.ip_address)))
        return True
    except (ConnectionError, OSError, RuntimeError) as e:
        log("wifi: connect failed: {}".format(e))
        return False


def disconnect():
    try:
        _get_esp().disconnect()
        log("wifi: disconnected")
    except (OSError, RuntimeError):
        pass
    gc.collect()


class _Session:
    """Yielded by session(): .connected is True if WiFi came up; .requests is
    an adafruit_requests.Session when connected, else None."""

    def __init__(self, cfg):
        self._cfg = cfg
        self.connected = False
        self.requests = None

    def __enter__(self):
        self.connected = connect(self._cfg)
        if self.connected:
            _get_pool()
            self.requests = adafruit_requests.Session(_pool, _ssl_context)
        return self

    def __exit__(self, exc_type, exc, tb):
        disconnect()
        return False

    def rssi(self):
        """WiFi signal strength -- only readable while still connected."""
        try:
            return _get_esp().rssi
        except (OSError, RuntimeError, AttributeError) as e:
            log("wifi: rssi read failed: {}".format(e))
            return None


def session(cfg):
    return _Session(cfg)


def ntp_sync(cfg):
    """Tries each configured NTP server in order (IPs before hostnames, per
    NTP_SERVERS). Returns a UTC time.struct_time on success, or None if every
    server failed -- callers should leave the RTC untouched on None."""
    pool = _get_pool()
    for host in cfg.ntp_servers:
        try:
            ntp = adafruit_ntp.NTP(pool, server=host, tz_offset=0)
            datetime = ntp.datetime
            log("wifi: NTP sync ok from {}".format(host))
            return datetime
        except (OSError, ValueError) as e:
            log("wifi: NTP server {} failed: {}".format(host, e))
    return None
