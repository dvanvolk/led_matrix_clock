"""Maps BH1750 lux readings to a smoothed display brightness level.

Two pure functions, no state of their own -- the caller (code.py) owns the
"current brightness" value across loop iterations. Split this way so lux ->
target level and target -> smoothed step can each be reasoned about (and
tested) independently.
"""

_DEFAULT_MAX_STEP = 0.05  # largest brightness change applied per update cycle


def target_level(lux, cfg):
    """Pure lux -> target brightness mapping, per the configured thresholds."""
    if lux > cfg.brightness_high_lux:
        return cfg.brightness_max
    if lux < cfg.brightness_low_lux:
        return cfg.brightness_min
    return cfg.brightness_mid


def smooth(current, target, max_step=_DEFAULT_MAX_STEP):
    """Moves `current` toward `target` by at most `max_step` -- avoids the
    sudden jumps the spec calls out, instead of snapping straight to target."""
    if current < target:
        return min(target, current + max_step)
    if current > target:
        return max(target, current - max_step)
    return current
