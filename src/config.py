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


def _friendly_name(device_name):
    # str.capitalize() isn't implemented by CircuitPython's built-in str type.
    text = device_name.replace("_", " ").strip()
    return text[:1].upper() + text[1:].lower() if text else text


class Config:
    def __init__(self):
        # WiFi
        self.wifi_ssid = os.getenv("WIFI_SSID", "")
        self.wifi_password = os.getenv("WIFI_PASSWORD", "")

        # Home Assistant
        self.ha_host = os.getenv("HA_HOST", "")
        self.ha_token = os.getenv("HA_TOKEN", "")
        self.ha_report_interval = os.getenv("HA_REPORT_INTERVAL", 300)
        self.ha_fetch_interval = os.getenv("HA_FETCH_INTERVAL", 300)

        # Device identity
        self.device_name = os.getenv("DEVICE_NAME", "matrix_clock")
        self.friendly_device_name = _friendly_name(self.device_name)

        # Timezone
        self.timezone = os.getenv("TIMEZONE", "UTC0")

        # NTP
        self.ntp_servers = _split_csv(os.getenv("NTP_SERVERS", "pool.ntp.org"))

        # Display modes
        self.mode_order = _split_csv(os.getenv("MODE_ORDER", "clock"))
        self.mode_dwell = {
            "clock": os.getenv("MODE_DWELL_CLOCK", 30),
            "clock_date": os.getenv("MODE_DWELL_CLOCK_DATE", 15),
            "indoor": os.getenv("MODE_DWELL_INDOOR", 10),
            "outdoor": os.getenv("MODE_DWELL_OUTDOOR", 10),
            "scroll": os.getenv("MODE_DWELL_SCROLL", 2),
        }

        # Colors (parsed to ints once, here)
        self.color_time = _parse_hex_color(os.getenv("COLOR_TIME", "0xFFAA00"))
        self.color_date = _parse_hex_color(os.getenv("COLOR_DATE", "0x004488"))
        self.color_temp = _parse_hex_color(os.getenv("COLOR_TEMP", "0xFF4400"))
        self.color_humidity = _parse_hex_color(os.getenv("COLOR_HUMIDITY", "0x0088FF"))
        self.color_outdoor = _parse_hex_color(os.getenv("COLOR_OUTDOOR", "0x00FF88"))
        self.color_scroll = _parse_hex_color(os.getenv("COLOR_SCROLL", "0xFFFFFF"))

        # Adaptive brightness
        self.brightness_high_lux = os.getenv("BRIGHTNESS_HIGH_LUX", 200)
        self.brightness_low_lux = os.getenv("BRIGHTNESS_LOW_LUX", 10)
        self.brightness_max = os.getenv("BRIGHTNESS_MAX", 1.0)
        self.brightness_mid = os.getenv("BRIGHTNESS_MID", 0.4)
        self.brightness_min = os.getenv("BRIGHTNESS_MIN", 0.05)

        # Outdoor HA entities
        self.ha_outdoor_temp_entity = os.getenv(
            "HA_OUTDOOR_TEMP_ENTITY", "sensor.outdoor_temperature"
        )
        self.ha_outdoor_conditions_entity = os.getenv(
            "HA_OUTDOOR_CONDITIONS_ENTITY", "sensor.outdoor_conditions"
        )

        # Scroll (static message only -- no HA-pushed scroll message in this pass)
        self.scroll_message = os.getenv("SCROLL_MESSAGE", "Welcome!")

        # Derived availability flags -- missing config permanently disables the
        # subsystem rather than retrying forever (confirmed behavior).
        self.wifi_configured = bool(self.wifi_ssid)
        self.ha_configured = bool(self.ha_host) and bool(self.ha_token)


def load():
    return Config()
