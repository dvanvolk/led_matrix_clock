"""DS3231 RTC wrapper.

The DS3231 always stores UTC only -- this module never applies a timezone.
It is the sole time source for the main loop; CircuitPython's software
rtc.RTC() is deliberately not used, since the M4 has no battery backup for it
and it drifts on the board's own oscillator between assignments.
"""
import adafruit_ds3231

from log import log

_MIN_VALID_YEAR = 2020


class RTCManager:
    def __init__(self, i2c):
        self.io_error = False
        try:
            self._ds3231 = adafruit_ds3231.DS3231(i2c)
        except (OSError, ValueError) as e:
            log("rtc_manager: DS3231 not found, running without RTC:", e)
            self._ds3231 = None

    def rebind(self, i2c):
        """Re-probes the DS3231 against a freshly recovered I2C bus (see
        i2c_recovery.recover) -- reruns the same probe as __init__."""
        self.__init__(i2c)

    @property
    def is_valid(self):
        """No DS3231 present is treated the same as an invalid/lost-power
        one -- the boot/main-loop retry-via-NTP paths already handle that."""
        if self._ds3231 is None:
            return False
        try:
            return (
                self._ds3231.datetime.tm_year >= _MIN_VALID_YEAR
                and not self._ds3231.lost_power
            )
        except OSError:
            return False

    def read_utc(self):
        """Returns the current UTC time as a time.struct_time, or None if the
        DS3231 is missing or an I2C read glitches -- callers should hold the
        last known time rather than let this take down the main loop."""
        if self._ds3231 is None:
            self.io_error = False
            return None
        try:
            utc = self._ds3231.datetime
            self.io_error = False
            return utc
        except OSError as e:
            if not self.io_error:
                log("rtc_manager: DS3231 read failed:", e)
            self.io_error = True
            return None

    def write_utc(self, utc_struct_time):
        """Writes a UTC time.struct_time to the RTC (e.g. after an NTP sync).
        No-op if the DS3231 isn't present."""
        if self._ds3231 is None:
            return
        self._ds3231.datetime = utc_struct_time

    def read_chip_temperature(self):
        """Returns the DS3231's onboard temperature sensor reading in Celsius,
        or None on an I2C read failure or missing RTC."""
        if self._ds3231 is None:
            return None
        try:
            return self._ds3231.temperature
        except OSError:
            return None
