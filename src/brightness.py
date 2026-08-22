"""Maps BH1750 lux readings to a smoothed display brightness level.

Two pure functions, no state of their own -- the caller (code.py) owns the
"current brightness" value across loop iterations. Split this way so lux ->
target level and target -> smoothed step can each be reasoned about (and
tested) independently.
"""

_DEFAULT_MAX_STEP = 0.05  # largest brightness change applied per update cycle


def target_level(lux, cfg, current_zone="mid"):
    """Pure lux -> (target brightness, zone) mapping, per the configured
    thresholds -- with hysteresis so lux hovering right at a threshold
    doesn't flicker the target back and forth every sample. Once in the
    max/min zone, lux has to cross back past the threshold by
    `brightness_hysteresis_lux` before the zone releases, rather than
    re-crossing the same line it just crossed."""
    high = cfg.brightness_high_lux
    low = cfg.brightness_low_lux
    hyst = cfg.brightness_hysteresis_lux

    if current_zone == "max" and lux > high - hyst:
        return cfg.brightness_max, "max"
    if current_zone == "min" and lux < low + hyst:
        return cfg.brightness_min, "min"

    if lux > high:
        return cfg.brightness_max, "max"
    if lux < low:
        return cfg.brightness_min, "min"
    return cfg.brightness_mid, "mid"


def smooth(current, target, max_step=_DEFAULT_MAX_STEP):
    """Moves `current` toward `target` by at most `max_step` -- avoids the
    sudden jumps the spec calls out, instead of snapping straight to target."""
    if current < target:
        return min(target, current + max_step)
    if current > target:
        return max(target, current - max_step)
    return current
