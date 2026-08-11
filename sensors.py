"""AHT20 (indoor temp/humidity) and BH1750 (ambient lux) wrappers.

Both read methods fail soft: they return None on any I2C error instead of
raising, so a disconnected/failed sensor degrades the affected display mode
or brightness control without crashing the main loop. Failures are logged to
serial only on the working<->failing transition, not on every loop
iteration, to avoid flooding the console while a sensor stays unplugged.
"""
import adafruit_ahtx0
import adafruit_bh1750


class SensorHub:
    def __init__(self, i2c):
        self._aht20 = adafruit_ahtx0.AHTx0(i2c)
        self._bh1750 = adafruit_bh1750.BH1750(i2c)
        self._indoor_ok = True
        self._lux_ok = True

    def read_indoor(self):
        """Returns (temperature_c, humidity_pct), or None on read failure."""
        try:
            reading = (self._aht20.temperature, self._aht20.relative_humidity)
            if not self._indoor_ok:
                print("sensors: AHT20 recovered")
                self._indoor_ok = True
            return reading
        except OSError as e:
            if self._indoor_ok:
                print("sensors: AHT20 read failed:", e)
                self._indoor_ok = False
            return None

    def read_lux(self):
        """Returns the current lux reading, or None on read failure."""
        try:
            lux = self._bh1750.lux
            if not self._lux_ok:
                print("sensors: BH1750 recovered")
                self._lux_ok = True
            return lux
        except OSError as e:
            if self._lux_ok:
                print("sensors: BH1750 read failed:", e)
                self._lux_ok = False
            return None
