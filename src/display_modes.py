"""Panel init, per-mode Groups/Labels, mode-cycling state, and rendering.

Groups/Labels are built once at startup; mode switches just reassign
display.root_group and rendering only mutates existing Label.text/.color
when a value actually changed, avoiding repeated Label/bitmap allocation on
a long-running, RAM-constrained device.

Font note: terminalio.FONT is a fixed 6x8px monospace glyph, scaled by an
integer factor. On this 64px-wide panel that caps how large text can go
before a realistic "H:MM" string (up to 5 chars) no longer fits: scale=4
(24px/char) would overflow at just 3 characters, so the time is shown at
scale=2 (16px) rather than the spec's literal "32px" target -- the largest
scale a stock monospace font can hit without clipping off the panel edge.
Hitting 32px for real would need a custom narrow-glyph bitmap font (a
documented, deferred alternative -- see CLAUDE.md/requirements doc
discussion of font choice) rather than the built-in font this pass uses to
avoid vendoring an extra asset.
"""
import displayio
import terminalio
from adafruit_display_text.label import Label
from adafruit_matrixportal.matrix import Matrix

WIDTH = 64
HEIGHT = 32

_GLYPH_WIDTH = 6  # terminalio.FONT glyph width in px, before scaling
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_BOTTOM_ITEMS = ("date", "indoor", "outdoor")


def _fmt_time(local_time):
    hour = local_time.tm_hour % 12
    if hour == 0:
        hour = 12
    return "{:d}:{:02d}".format(hour, local_time.tm_min)


def _fmt_date(local_time):
    return "{} {:d}/{:d}".format(
        _WEEKDAYS[local_time.tm_wday], local_time.tm_mon, local_time.tm_mday
    )


def _fmt_indoor_temp(temperature_c, unit_f):
    if unit_f:
        return "{:.1f}F".format(temperature_c * 9.0 / 5.0 + 32.0)
    return "{:.1f}C".format(temperature_c)


def init_display(bit_depth=4):
    matrix = Matrix(width=WIDTH, height=HEIGHT, bit_depth=bit_depth)
    return matrix.display


class ModeManager:
    """Tracks which top-level mode is active and how long it's dwelled.
    MODE_ORDER is a single "clock" mode today, but this stays config-driven
    so another top-level mode can be added later without new machinery."""

    def __init__(self, cfg):
        self._modes = list(cfg.mode_order)
        self._dwell = cfg.mode_dwell
        self._index = 0
        self._mode_start = None

    def current_mode(self):
        return self._modes[self._index]

    def tick(self, now):
        """Call once per loop iteration, before rendering. Advances the mode
        if its dwell time has elapsed."""
        if self._mode_start is None:
            self._mode_start = now

        mode = self.current_mode()
        due = (now - self._mode_start) >= self._dwell.get(mode, 10)
        if due:
            self._advance(now)

    def _advance(self, now):
        self._index = (self._index + 1) % len(self._modes)
        self._mode_start = now
        print("display_modes: switched to mode:", self.current_mode())


class BottomRotator:
    """Tracks which item -- date, indoor temp, outdoor temp -- is currently
    shown on the clock's bottom line, and skips items whose backing data
    isn't currently available (indoor sensor down, HA outdoor data
    unreachable) instead of waiting out their dwell timer. "date" never
    reports unavailable, so this can never get stuck skipping forever."""

    def __init__(self, cfg):
        self._items = _BOTTOM_ITEMS
        self._dwell = cfg.bottom_dwell
        self._index = 0
        self._item_start = None
        self.indoor_available = True
        self.outdoor_available = True

    def update_availability(self, indoor_available, outdoor_available):
        self.indoor_available = indoor_available
        self.outdoor_available = outdoor_available

    def _data_available(self, item):
        if item == "indoor":
            return self.indoor_available
        if item == "outdoor":
            return self.outdoor_available
        return True

    def current_item(self):
        return self._items[self._index]

    def tick(self, now):
        """Call once per loop iteration, before rendering. Advances the item
        if its dwell time has elapsed, or immediately if its data isn't
        currently available."""
        if self._item_start is None:
            self._item_start = now

        if not self._data_available(self.current_item()):
            self._advance(now)
            return

        due = (now - self._item_start) >= self._dwell.get(self.current_item(), 10)
        if due:
            self._advance(now)

    def _advance(self, now):
        for _ in range(len(self._items)):
            self._index = (self._index + 1) % len(self._items)
            if self._data_available(self.current_item()):
                break
        self._item_start = now


class Renderer:
    def __init__(self, display, cfg):
        self._display = display
        self._cfg = cfg
        self._active_mode = None
        self._active_bottom_item = None

        # Time: always shown, top half of the panel. See module docstring
        # re: scale=2 (not the spec's literal 32px) being the largest that
        # fits H:MM at this panel width with the stock monospace font.
        self.time_label = Label(
            terminalio.FONT, text="--:--", scale=2, color=cfg.color_time
        )
        self.time_label.anchor_point = (0.5, 0.0)
        self.time_label.anchored_position = (WIDTH // 2, 0)

        # Bottom line: one shared Label, reconfigured (scale/anchor/color)
        # whenever the rotating item changes -- see _configure_bottom_label.
        self.bottom_label = Label(
            terminalio.FONT, text="", scale=1, color=cfg.color_date
        )
        self.bottom_label.anchor_point = (0.5, 1.0)
        self.bottom_label.anchored_position = (WIDTH // 2, HEIGHT)

        self.clock_group = displayio.Group()
        self.clock_group.append(self.time_label)
        self.clock_group.append(self.bottom_label)

        # Boot-time / RTC-invalid placeholder.
        self.placeholder_label = Label(
            terminalio.FONT, text="----", scale=2, color=cfg.color_time
        )
        self.placeholder_label.anchor_point = (0.5, 0.5)
        self.placeholder_label.anchored_position = (WIDTH // 2, HEIGHT // 2)
        self.placeholder_group = displayio.Group()
        self.placeholder_group.append(self.placeholder_label)

        self._groups = {"clock": self.clock_group}

    def show_placeholder(self, text="----"):
        self._set_text(self.placeholder_label, text)
        if self._active_mode != "__placeholder__":
            self._display.root_group = self.placeholder_group
            self._active_mode = "__placeholder__"

    def _configure_bottom_label(self, item):
        # All three items share the date's 8px size and centered position --
        # 16px (scale=2) was tall enough to visually overlap the time label
        # above it.
        self.bottom_label.scale = 1
        self.bottom_label.anchor_point = (0.5, 1.0)
        self.bottom_label.anchored_position = (WIDTH // 2, HEIGHT)
        if item == "date":
            self.bottom_label.color = self._cfg.color_date
        elif item == "indoor":
            self.bottom_label.color = self._cfg.color_temp
        elif item == "outdoor":
            self.bottom_label.color = self._cfg.color_outdoor

    def render(self, mode, bottom_item, local_time, indoor, outdoor):
        if self._active_mode != mode:
            self._display.root_group = self._groups[mode]
            self._active_mode = mode

        self._set_text(self.time_label, _fmt_time(local_time))

        if self._active_bottom_item != bottom_item:
            self._configure_bottom_label(bottom_item)
            self._active_bottom_item = bottom_item

        if bottom_item == "date":
            self._set_text(self.bottom_label, _fmt_date(local_time))
        elif bottom_item == "indoor":
            if indoor is not None:
                temperature_c, _humidity_pct = indoor
                self._set_text(
                    self.bottom_label,
                    _fmt_indoor_temp(temperature_c, self._cfg.temp_unit_f),
                )
        elif bottom_item == "outdoor":
            outdoor = outdoor or {}
            temp = outdoor.get("temperature")
            self._set_text(self.bottom_label, temp if temp is not None else "--")

    def _set_text(self, label, text):
        if label.text != text:
            label.text = text
