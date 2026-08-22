"""Loads settings.toml into a single typed config object.

This is the only module that touches os.getenv() / raw TOML values --
everything else reads already-typed fields off the Config instance.
"""
import os


def _split_csv(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_hex_color(value):
    if isinstance(value, int):
        return value
    return int(value, 16)


def _as_number(value, cast):
    """CircuitPython's settings.toml parser can leave a value as a str when
    the line has a trailing inline comment (a documented parser limitation)
    instead of stripping it -- coerce defensively so callers always get the
    numeric type they expect regardless of how the value was written."""
    return cast(value) if isinstance(value, str) else value


def _friendly_name(device_name):
    # str.capitalize() isn't implemented by CircuitPython's built-in str type.
    text = device_name.replace("_", " ").strip()
    return text[:1].upper() + text[1:].lower() if text else text


_SLUG_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_"


def _slugify(device_name):
    """HA's entity object_id must be lowercase alphanumeric/underscore --
    sanitize so a DEVICE_NAME like "Living Room Clock" still produces a
    valid entity_id instead of HA rejecting the POST with a 400.
    (Not str.isalnum(): CircuitPython's built-in str doesn't implement it.)"""
    chars = []
    for ch in device_name.strip().lower():
        chars.append(ch if ch in _SLUG_CHARS else "_")
    return "".join(chars)


class Config:
    def __init__(self):
        # WiFi
        self.wifi_ssid = os.getenv("WIFI_SSID", "")
        self.wifi_password = os.getenv("WIFI_PASSWORD", "")

        # Home Assistant
        self.ha_host = os.getenv("HA_HOST", "")
        self.ha_token = os.getenv("HA_TOKEN", "")
        self.ha_report_interval = _as_number(os.getenv("HA_REPORT_INTERVAL", 300), int)
        self.ha_fetch_interval = _as_number(os.getenv("HA_FETCH_INTERVAL", 300), int)

        # Device identity
        self.device_name = os.getenv("DEVICE_NAME", "matrix_clock")
        self.friendly_device_name = _friendly_name(self.device_name)
        self.device_name_slug = _slugify(self.device_name)

        # Timezone
        self.timezone = os.getenv("TIMEZONE", "UTC0")

        # NTP
        self.ntp_servers = _split_csv(os.getenv("NTP_SERVERS", "pool.ntp.org"))

        # Display modes
        self.mode_order = _split_csv(os.getenv("MODE_ORDER", "clock"))
        self.mode_dwell = {
            "clock": _as_number(os.getenv("MODE_DWELL_CLOCK", 30), int),
        }
        # Dwell for the clock's rotating bottom line (date / indoor / outdoor).
        self.bottom_dwell = {
            "date": _as_number(os.getenv("BOTTOM_DWELL_DATE", 15), int),
            "indoor": _as_number(os.getenv("BOTTOM_DWELL_INDOOR", 10), int),
            "outdoor": _as_number(os.getenv("BOTTOM_DWELL_OUTDOOR", 10), int),
        }

        # Colors (parsed to ints once, here)
        self.color_time = _parse_hex_color(os.getenv("COLOR_TIME", "0xFFAA00"))
        self.color_date = _parse_hex_color(os.getenv("COLOR_DATE", "0x004488"))
        self.color_temp = _parse_hex_color(os.getenv("COLOR_TEMP", "0xFF4400"))
        self.color_outdoor = _parse_hex_color(os.getenv("COLOR_OUTDOOR", "0x00FF88"))

        # Indoor temperature display unit -- AHT20 always reads Celsius in
        # hardware; this only controls the conversion applied at display time.
        self.temp_unit_f = os.getenv("TEMP_UNIT_F", True)
        if isinstance(self.temp_unit_f, str):
            self.temp_unit_f = self.temp_unit_f.strip().lower() in ("1", "true", "yes")

        # Adaptive brightness
        self.brightness_high_lux = _as_number(os.getenv("BRIGHTNESS_HIGH_LUX", 200), float)
        self.brightness_low_lux = _as_number(os.getenv("BRIGHTNESS_LOW_LUX", 10), float)
        self.brightness_hysteresis_lux = _as_number(os.getenv("BRIGHTNESS_HYSTERESIS_LUX", 20), float)
        self.brightness_max = _as_number(os.getenv("BRIGHTNESS_MAX", 1.0), float)
        self.brightness_mid = _as_number(os.getenv("BRIGHTNESS_MID", 0.4), float)
        self.brightness_min = _as_number(os.getenv("BRIGHTNESS_MIN", 0.05), float)

        # Outdoor HA entities
        self.ha_outdoor_temp_entity = os.getenv(
            "HA_OUTDOOR_TEMP_ENTITY", "sensor.outdoor_temperature"
        )
        self.ha_outdoor_conditions_entity = os.getenv(
            "HA_OUTDOOR_CONDITIONS_ENTITY", "sensor.outdoor_conditions"
        )

        # Derived availability flags -- missing config permanently disables the
        # subsystem rather than retrying forever (confirmed behavior).
        self.wifi_configured = bool(self.wifi_ssid)
        self.ha_configured = bool(self.ha_host) and bool(self.ha_token)


def load():
    return Config()
