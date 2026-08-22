"""Hand-rolled POSIX TZ string interpreter.

CircuitPython's `time` module has no tzset()/TZ support -- time.mktime() and
time.localtime() are pure, timezone-naive struct_time<->epoch converters with
no notion of "local" attached. This module uses them only in that literal
sense (never as an actual local-time source) to parse a POSIX TZ string like
"EST5EDT,M3.2.0,M11.1.0" and convert a UTC struct_time to local time + the
active zone abbreviation.

Scope: only the "Mm.n.d[/hh:mm:ss]" transition rule form is supported (covers
every zone in matrix_clock_requirements.md and effectively all modern US/EU
zones), plus the no-DST bare "STDoffset" form. Julian-day rule forms (Jn / n)
are out of scope.
"""
import time


def _parse_name(s, i):
    if i < len(s) and s[i] == "<":
        i += 1
        start = i
        while i < len(s) and s[i] != ">":
            i += 1
        name = s[start:i]
        return name, i + 1
    start = i
    while i < len(s) and s[i].isalpha():
        i += 1
    return s[start:i], i


def _offset_text_to_seconds(text):
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    elif text.startswith("+"):
        text = text[1:]
    parts = text.split(":")
    hours = int(parts[0]) if parts[0] else 0
    minutes = int(parts[1]) if len(parts) > 1 else 0
    seconds = int(parts[2]) if len(parts) > 2 else 0
    return sign * (hours * 3600 + minutes * 60 + seconds)


def _parse_offset(s, i):
    start = i
    if i < len(s) and s[i] in "+-":
        i += 1
    while i < len(s) and (s[i].isdigit() or s[i] == ":"):
        i += 1
    return _offset_text_to_seconds(s[start:i]), i


def _parse_rule(rule_str):
    if not rule_str.startswith("M"):
        raise ValueError("unsupported TZ rule form (only Mm.n.d is supported): " + rule_str)
    body = rule_str[1:]
    if "/" in body:
        date_part, time_part = body.split("/", 1)
        rule_seconds = _offset_text_to_seconds(time_part)
    else:
        date_part = body
        rule_seconds = 2 * 3600  # default transition time: 02:00:00
    month, week, posix_weekday = [int(x) for x in date_part.split(".")]
    return month, week, posix_weekday, rule_seconds


def _parse_tz(tz_string):
    i = 0
    std_name, i = _parse_name(tz_string, i)
    std_offset, i = _parse_offset(tz_string, i)

    dst_name = None
    dst_offset = None
    start_rule = None
    end_rule = None

    if i < len(tz_string) and tz_string[i] != ",":
        dst_name, i = _parse_name(tz_string, i)
        if i < len(tz_string) and tz_string[i] not in (",",):
            dst_offset, i = _parse_offset(tz_string, i)
        else:
            dst_offset = std_offset - 3600  # POSIX default: 1 hour ahead of std

    if i < len(tz_string) and tz_string[i] == ",":
        rules = tz_string[i + 1:].split(",")
        start_rule = _parse_rule(rules[0])
        if len(rules) > 1:
            end_rule = _parse_rule(rules[1])

    return {
        "std_name": std_name,
        "std_offset": std_offset,
        "dst_name": dst_name,
        "dst_offset": dst_offset,
        "start_rule": start_rule,
        "end_rule": end_rule,
    }


def _days_in_month(year, month):
    this_month_first = time.mktime((year, month, 1, 0, 0, 0, 0, 0, -1))
    if month == 12:
        next_month_first = time.mktime((year + 1, 1, 1, 0, 0, 0, 0, 0, -1))
    else:
        next_month_first = time.mktime((year, month + 1, 1, 0, 0, 0, 0, 0, -1))
    return int((next_month_first - this_month_first) // 86400)


def _nth_weekday_of_month(year, month, week, posix_weekday):
    # POSIX weekday: 0=Sunday..6=Saturday. CircuitPython/CPython tm_wday: 0=Monday..6=Sunday.
    target_wday = (posix_weekday - 1) % 7
    first_epoch = time.mktime((year, month, 1, 0, 0, 0, 0, 0, -1))
    first_wday = time.localtime(first_epoch)[6]
    day = 1 + ((target_wday - first_wday) % 7)
    if week == 5:  # "last" occurrence in the month
        while day + 7 <= _days_in_month(year, month):
            day += 7
    else:
        day += 7 * (week - 1)
    return day


def _rule_wall_epoch(year, rule):
    month, week, posix_weekday, rule_seconds = rule
    day = _nth_weekday_of_month(year, month, week, posix_weekday)
    hour = rule_seconds // 3600
    minute = (rule_seconds % 3600) // 60
    second = rule_seconds % 60
    return time.mktime((year, month, day, hour, minute, second, 0, 0, -1))


class PosixTZ:
    def __init__(self, tz_string):
        parsed = _parse_tz(tz_string)
        self.std_name = parsed["std_name"]
        self.std_offset = parsed["std_offset"]
        self.dst_name = parsed["dst_name"]
        self.dst_offset = parsed["dst_offset"]
        self.start_rule = parsed["start_rule"]
        self.end_rule = parsed["end_rule"]
        self.has_dst = (
            self.dst_name is not None
            and self.start_rule is not None
            and self.end_rule is not None
        )

    def _is_dst(self, utc_epoch, year):
        if not self.has_dst:
            return False
        # Each rule's wall-clock reading is in the offset that's in effect just
        # before that specific transition: std time going into DST, DST time
        # coming back out of it.
        start_epoch = _rule_wall_epoch(year, self.start_rule) + self.std_offset
        end_epoch = _rule_wall_epoch(year, self.end_rule) + self.dst_offset
        if start_epoch <= end_epoch:
            return start_epoch <= utc_epoch < end_epoch
        # Southern-hemisphere case: DST window wraps across the year boundary.
        return utc_epoch >= start_epoch or utc_epoch < end_epoch

    def to_local(self, utc_struct_time):
        utc_epoch = time.mktime(utc_struct_time)
        dst = self._is_dst(utc_epoch, utc_struct_time[0])
        offset = self.dst_offset if dst else self.std_offset
        local_struct = time.localtime(utc_epoch - offset)
        abbr = self.dst_name if dst else self.std_name
        return local_struct, abbr
