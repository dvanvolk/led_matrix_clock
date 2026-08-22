"""Recovers a wedged shared I2C bus.

DS3231, AHT20, and BH1750 daisy-chain off one STEMMA QT bus. A single bad
transaction (e.g. a device caught mid-clock-stretch by the HUB75 refresh
interrupt) can leave that device holding SDA low, which then fails every
future transaction for every device on the bus, not just the one that
glitched -- matching the observed pattern of DS3231/AHT20 reads failing
right after a BH1750 hiccup. Toggling SCL is the standard I2C bus-recovery
sequence: it clocks a wedged slave through whatever bit it was stuck on
until it releases SDA.
"""
import board
import busio
import digitalio


def recover(i2c):
    """Deinits `i2c`, bit-bangs the SCL-toggle recovery sequence, and
    returns a fresh busio.I2C bound to the same pins."""
    i2c.deinit()

    scl = digitalio.DigitalInOut(board.SCL)
    sda = digitalio.DigitalInOut(board.SDA)
    scl.switch_to_output(value=True)
    sda.switch_to_input()
    for _ in range(9):
        if sda.value:
            break
        scl.value = False
        scl.value = True
    scl.deinit()
    sda.deinit()

    return busio.I2C(board.SCL, board.SDA)
