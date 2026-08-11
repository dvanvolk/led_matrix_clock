"""WiFi connect/disconnect discipline and NTP sync.

WiFi connects only for NTP sync / HA fetch / HA push, then disconnects
immediately after -- every network operation goes through session(), a
context manager that guarantees disconnect happens even if the operation
raises. A class-based context manager is used instead of
@contextlib.contextmanager since contextlib isn't reliably present on
CircuitPython builds.
"""
import gc
import time

import adafruit_ntp
import adafruit_requests
import socketpool
import ssl
import wifi

_pool = None

# Brief settle time after association, before the first socket/NTP call.
# wifi.radio.connect() already blocks until DHCP completes, but a sibling
# ESP8266 clock project (which this NTP_SERVERS list and retry pattern are
# carried over from) found NTP requests sent immediately after connecting
# would silently go unanswered -- the radio/stack needs a moment to settle
# before it reliably passes traffic. Cheap to keep even though CircuitPython's
# blocking connect() call makes it less likely to matter here.
_CONNECT_SETTLE_S = 0.5


def _get_pool():
    global _pool
    if _pool is None:
        _pool = socketpool.SocketPool(wifi.radio)
    return _pool


def connect(cfg):
    if not cfg.wifi_configured:
        return False
    try:
        wifi.radio.connect(cfg.wifi_ssid, cfg.wifi_password)
        time.sleep(_CONNECT_SETTLE_S)
        return True
    except (ConnectionError, OSError) as e:
        print("wifi: connect failed:", e)
        return False


def disconnect():
    try:
        wifi.radio.stop_station()
    except OSError:
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
            self.requests = adafruit_requests.Session(_get_pool(), ssl.create_default_context())
        return self

    def __exit__(self, exc_type, exc, tb):
        disconnect()
        return False

    def rssi(self):
        """WiFi signal strength -- only readable while still connected."""
        try:
            return wifi.radio.ap_info.rssi
        except (OSError, AttributeError):
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
            return ntp.datetime
        except (OSError, ValueError) as e:
            print("wifi: NTP server {} failed: {}".format(host, e))
    return None
