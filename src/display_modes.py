"""Panel init, per-mode Groups/Labels, mode-cycling state, and rendering.

Groups/Labels are built once at startup; mode switches just reassign
display.root_group and rendering only mutates existing Label.text/.color
when a value actually changed, avoiding repeated Label/bitmap allocation on
a long-running, RAM-constrained device.

Font note: terminalio.FONT is a fixed 6x8px monospace glyph, scaled by an
integer factor. On this 64px-wide panel that caps how large text can go
before a realistic "H:MM" string (up to 5 chars) no longer fits: scale=4
(24px/char) would overflow at just 3 characters, so Clock mode uses scale=2
(16px) rather than the spec's literal "32px" target -- the largest scale a
stock monospace font can hit without clipping off the panel edge. Hitting
32px for real would need a custom narrow-glyph bitmap font (a documented,
deferred alternative -- see CLAUDE.md/requirements doc discussion of font
choice) rather than the built-in font this pass uses to avoid vendoring an
extra asset.
"""
import displayio
import terminalio
from adafruit_display_text.label import Label
from adafruit_matrixportal.matrix import Matrix

WIDTH = 64
HEIGHT = 32

_GLYPH_WIDTH = 6  # terminalio.FONT glyph width in px, before scaling
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _fmt_time(local_time):
    hour = local_time.tm_hour % 12
    if hour == 0:
        hour = 12
    return "{:d}:{:02d}".format(hour, local_time.tm_min)


def _fmt_date(local_time):
    return "{} {:d}/{:d}".format(
        _WEEKDAYS[local_time.tm_wday], local_time.tm_mon, local_time.tm_mday
    )


def init_display(bit_depth=4):
    matrix = Matrix(width=WIDTH, height=HEIGHT, bit_depth=bit_depth)
    return matrix.display


class ModeManager:
    """Tracks which mode is active, how long it's dwelled, and skips modes
    whose backing data isn't currently available (indoor sensor down, HA
    outdoor data unreachable) instead of waiting out their dwell timer."""

    def __init__(self, cfg):
        self._modes = list(cfg.mode_order)
        self._dwell = cfg.mode_dwell
        self._index = 0
        self._mode_start = None
        self._scroll_passes = 0
        self.indoor_available = True
        self.outdoor_available = True

    def update_availability(self, indoor_available, outdoor_available):
        self.indoor_available = indoor_available
        self.outdoor_available = outdoor_available

    def _data_available(self, mode):
        if mode == "indoor":
            return self.indoor_available
        if mode == "outdoor":
            return self.outdoor_available
        return True

    def current_mode(self):
        return self._modes[self._index]

    def note_scroll_pass(self):
        self._scroll_passes += 1

    def tick(self, now):
        """Call once per loop iteration, before rendering. Advances the mode
        if its dwell time (or scroll pass count) has elapsed, or immediately
        if its data isn't currently available."""
        if self._mode_start is None:
            self._mode_start = now

        if not self._data_available(self.current_mode()):
            self._advance(now)
            return

        mode = self.current_mode()
        if mode == "scroll":
            due = self._scroll_passes >= self._dwell.get("scroll", 2)
        else:
            due = (now - self._mode_start) >= self._dwell.get(mode, 10)
        if due:
            self._advance(now)

    def _advance(self, now):
        for _ in range(len(self._modes)):
            self._index = (self._index + 1) % len(self._modes)
            if self._data_available(self.current_mode()):
                break
        self._mode_start = now
        self._scroll_passes = 0
        print("display_modes: switched to mode:", self.current_mode())

    def tick_interval(self):
        return 0.05 if self.current_mode() == "scroll" else 0.5


class Renderer:
    def __init__(self, display, cfg):
        self._display = display
        self._cfg = cfg
        self._active_mode = None

        # Clock: single large centered label. See module docstring re: scale=2
        # (not the spec's literal 32px) being the largest that fits H:MM at
        # this panel width with the stock monospace font.
        self.clock_label = Label(
            terminalio.FONT, text="--:--", scale=2, color=cfg.color_time
        )
        self.clock_label.anchor_point = (0.5, 0.5)
        self.clock_label.anchored_position = (WIDTH // 2, HEIGHT // 2)
        self.clock_group = displayio.Group()
        self.clock_group.append(self.clock_label)

        # Clock + Date: 16px time on top, 8px date on bottom.
        self.cd_time_label = Label(
            terminalio.FONT, text="--:--", scale=2, color=cfg.color_time
        )
        self.cd_time_label.anchor_point = (0.5, 0.0)
        self.cd_time_label.anchored_position = (WIDTH // 2, 0)
        self.cd_date_label = Label(
            terminalio.FONT, text="--- -/-", scale=1, color=cfg.color_date
        )
        self.cd_date_label.anchor_point = (0.5, 1.0)
        self.cd_date_label.anchored_position = (WIDTH // 2, HEIGHT)
        self.clock_date_group = displayio.Group()
        self.clock_date_group.append(self.cd_time_label)
        self.clock_date_group.append(self.cd_date_label)

        # Indoor: temp on top row, humidity on bottom row, 16px each.
        # Left-aligned (not centered) since these values' text length varies.
        self.indoor_temp_label = Label(
            terminalio.FONT, text="--", scale=2, color=cfg.color_temp
        )
        self.indoor_temp_label.anchor_point = (0.0, 0.0)
        self.indoor_temp_label.anchored_position = (0, 0)
        self.indoor_humidity_label = Label(
            terminalio.FONT, text="--", scale=2, color=cfg.color_humidity
        )
        self.indoor_humidity_label.anchor_point = (0.0, 0.0)
        self.indoor_humidity_label.anchored_position = (0, HEIGHT // 2)
        self.indoor_group = displayio.Group()
        self.indoor_group.append(self.indoor_temp_label)
        self.indoor_group.append(self.indoor_humidity_label)

        # Outdoor: temp on top row, conditions on bottom row, 16px each.
        self.outdoor_temp_label = Label(
            terminalio.FONT, text="--", scale=2, color=cfg.color_outdoor
        )
        self.outdoor_temp_label.anchor_point = (0.0, 0.0)
        self.outdoor_temp_label.anchored_position = (0, 0)
        self.outdoor_conditions_label = Label(
            terminalio.FONT, text="--", scale=2, color=cfg.color_outdoor
        )
        self.outdoor_conditions_label.anchor_point = (0.0, 0.0)
        self.outdoor_conditions_label.anchored_position = (0, HEIGHT // 2)
        self.outdoor_group = displayio.Group()
        self.outdoor_group.append(self.outdoor_temp_label)
        self.outdoor_group.append(self.outdoor_conditions_label)

        # Scroll: single line, manually animated left across the full width.
        self.scroll_label = Label(
            terminalio.FONT, text=cfg.scroll_message, scale=1, color=cfg.color_scroll
        )
        self.scroll_label.anchor_point = (0.0, 0.5)
        self.scroll_label.anchored_position = (WIDTH, HEIGHT // 2)
        self.scroll_group = displayio.Group()
        self.scroll_group.append(self.scroll_label)

        # Boot-time / RTC-invalid placeholder.
        self.placeholder_label = Label(
            terminalio.FONT, text="----", scale=2, color=cfg.color_time
        )
        self.placeholder_label.anchor_point = (0.5, 0.5)
        self.placeholder_label.anchored_position = (WIDTH // 2, HEIGHT // 2)
        self.placeholder_group = displayio.Group()
        self.placeholder_group.append(self.placeholder_label)

        self._groups = {
            "clock": self.clock_group,
            "clock_date": self.clock_date_group,
            "indoor": self.indoor_group,
            "outdoor": self.outdoor_group,
            "scroll": self.scroll_group,
        }

    def show_placeholder(self, text="----"):
        self._set_text(self.placeholder_label, text)
        if self._active_mode != "__placeholder__":
            self._display.root_group = self.placeholder_group
            self._active_mode = "__placeholder__"

    def render(self, mode, local_time, indoor, outdoor):
        if self._active_mode != mode:
            self._display.root_group = self._groups[mode]
            self._active_mode = mode

        if mode == "clock":
            self._set_text(self.clock_label, _fmt_time(local_time))
        elif mode == "clock_date":
            self._set_text(self.cd_time_label, _fmt_time(local_time))
            self._set_text(self.cd_date_label, _fmt_date(local_time))
        elif mode == "indoor":
            if indoor is not None:
                temperature_c, humidity_pct = indoor
                self._set_text(self.indoor_temp_label, "{:.1f}C".format(temperature_c))
                self._set_text(self.indoor_humidity_label, "{:.0f}%".format(humidity_pct))
        elif mode == "outdoor":
            outdoor = outdoor or {}
            temp = outdoor.get("temperature")
            conditions = outdoor.get("conditions")
            self._set_text(self.outdoor_temp_label, temp if temp is not None else "--")
            self._set_text(
                self.outdoor_conditions_label, conditions if conditions is not None else "--"
            )
        elif mode == "scroll":
            pass  # advanced via tick_scroll(), not on every render call

    def tick_scroll(self):
        """Advances the scroll label one frame. Returns True if a full pass
        (fully off the left edge) just completed."""
        label = self.scroll_label
        label.x -= 1
        text_width = len(label.text) * _GLYPH_WIDTH * label.scale
        if label.x < -text_width:
            label.x = WIDTH
            return True
        return False

    def _set_text(self, label, text):
        if label.text != text:
            label.text = text
