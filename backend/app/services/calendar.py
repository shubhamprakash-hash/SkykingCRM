"""Working-hours clock. All inputs/outputs are naive UTC datetimes."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time, date
from zoneinfo import ZoneInfo


@dataclass
class Calendar:
    mode: str = "business"             # business | 24x7
    tz: str = "Asia/Kolkata"
    start: str = "09:00"
    end: str = "19:00"
    days: tuple = (0, 1, 2, 3, 4, 5)   # Mon=0 .. Sun=6  (Mon-Sat)
    holidays: tuple = ()               # ISO dates "2026-10-20"

    @classmethod
    def from_dict(cls, d: dict) -> "Calendar":
        d = dict(d or {})
        d["days"] = tuple(d.get("days", cls.days))
        d["holidays"] = tuple(d.get("holidays", ()))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _tz(cal): return ZoneInfo(cal.tz)
def _local(dt, cal): return dt.replace(tzinfo=timezone.utc).astimezone(_tz(cal))
def _utc(dt): return dt.astimezone(timezone.utc).replace(tzinfo=None)
def _hm(s): h, m = s.split(":"); return time(int(h), int(m))


def _is_workday(d: date, cal: Calendar) -> bool:
    return d.weekday() in cal.days and d.isoformat() not in cal.holidays


def _window(d: date, cal: Calendar):
    tz = _tz(cal)
    return (datetime.combine(d, _hm(cal.start), tzinfo=tz), datetime.combine(d, _hm(cal.end), tzinfo=tz))


def _next_midnight(cur):
    return datetime.combine(cur.date() + timedelta(days=1), time(0, 0), tzinfo=cur.tzinfo)


def add_working_minutes(start: datetime, minutes: float, cal: Calendar) -> datetime:
    if cal.mode == "24x7":
        return start + timedelta(minutes=minutes)
    cur, remaining = _local(start, cal), float(minutes)
    for _ in range(800):
        if not _is_workday(cur.date(), cal):
            cur = _next_midnight(cur); continue
        o, c = _window(cur.date(), cal)
        if cur < o:
            cur = o
        if cur >= c:
            cur = _next_midnight(cur); continue
        avail = (c - cur).total_seconds() / 60
        if remaining <= avail:
            return _utc(cur + timedelta(minutes=remaining))
        remaining -= avail
        cur = c
    raise RuntimeError("calendar has no working time")


def working_minutes_between(a: datetime, b: datetime, cal: Calendar) -> int:
    if b <= a:
        return 0
    if cal.mode == "24x7":
        return int((b - a).total_seconds() // 60)
    cur, end, total = _local(a, cal), _local(b, cal), 0.0
    for _ in range(2000):
        if cur >= end:
            break
        if not _is_workday(cur.date(), cal):
            cur = _next_midnight(cur); continue
        o, c = _window(cur.date(), cal)
        if cur < o:
            cur = o
        if cur >= c:
            cur = _next_midnight(cur); continue
        seg_end = min(c, end)
        if seg_end > cur:
            total += (seg_end - cur).total_seconds() / 60
        cur = max(seg_end, c) if seg_end == c else seg_end
        if cur >= end:
            break
    return int(total)
