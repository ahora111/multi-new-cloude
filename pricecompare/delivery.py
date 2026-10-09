"""Order windows & delivery estimates to Qazvin — independent per source, Asia/Tehran.

Each seller can declare (config/delivery.yaml):
  - one or more order windows per day (start, cut-off, ship time, arrival time in Qazvin, day offset)
  - active weekdays and holidays (non-working days)
  - whether the times are VERIFIED by the seller or only ESTIMATES
  - shipping cost / note (shipping is always quoted separately from the phone price)

All calculations run in Asia/Tehran. A source without config yields status="unknown"
(«زمان تحویل نامشخص») and never blocks the other sources. Estimated times are always
labelled as approximate — they are never presented as guaranteed.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_TZ_NAME = "Asia/Tehran"
TEHRAN = ZoneInfo(DEFAULT_TZ_NAME)

# python weekday(): Monday == 0 ... Sunday == 6
WEEKDAY_ALIASES = {
    "monday": 0, "mon": 0, "دوشنبه": 0,
    "tuesday": 1, "tue": 1, "tues": 1, "سه شنبه": 1, "سه‌شنبه": 1,
    "wednesday": 2, "wed": 2, "چهارشنبه": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "پنجشنبه": 3, "پنج شنبه": 3, "پنج‌شنبه": 3,
    "friday": 4, "fri": 4, "جمعه": 4,
    "saturday": 5, "sat": 5, "شنبه": 5,
    "sunday": 6, "sun": 6, "یکشنبه": 6, "يكشنبه": 6,
}
WEEKDAY_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]

UNKNOWN_LABEL = "زمان تحویل نامشخص"
SHIPPING_UNKNOWN_LABEL = "هزینه ارسال نیازمند استعلام"


class DeliveryConfigError(Exception):
    pass


@dataclass
class OrderWindow:
    start: time                      # earliest order time of this window
    end: time                        # cut-off: orders after this fall into the NEXT window
    ship_at: time                    # approximate dispatch time
    delivery_at: time                # approximate arrival time in Qazvin
    delivery_day_offset: int = 0     # 0 = same day, 1 = next day, ...
    note: str = ""


@dataclass
class SourceSchedule:
    name: str = ""
    windows: list = field(default_factory=list)          # [OrderWindow] sorted by start
    active_weekdays: set = field(default_factory=lambda: set(range(7)))   # default: every day
    holidays: set = field(default_factory=set)           # {date}
    verified: bool = False                               # True = times confirmed by the seller
    note: str = ""
    shipping_cost_toman: float | None = None
    shipping_note: str = ""


@dataclass
class DeliveryEstimate:
    source: str
    status: str = "unknown"          # ok | unknown
    order_deadline: datetime | None = None    # aware, Tehran
    ship_at: datetime | None = None           # aware, Tehran
    delivery_at: datetime | None = None       # aware, Tehran
    same_day: bool = False
    hours_from_now: float | None = None
    window_note: str = ""
    verified: bool = False
    schedule_note: str = ""
    shipping_cost_toman: float | None = None
    shipping_note: str = ""
    query_date: date | None = None        # the day the question was asked (Tehran)

    @property
    def label(self) -> str:
        return format_estimate(self)

    @property
    def shipping_label(self) -> str:
        if self.shipping_cost_toman is not None:
            return f"هزینه ارسال {self.shipping_cost_toman:,.0f} تومان (جدا از قیمت گوشی)"
        if self.shipping_note:
            return f"هزینه ارسال: {self.shipping_note}"
        return SHIPPING_UNKNOWN_LABEL

    def to_dict(self) -> dict:
        return {
            "status": self.status, "delivery_at": _iso(self.delivery_at),
            "order_deadline": _iso(self.order_deadline), "ship_at": _iso(self.ship_at),
            "same_day": self.same_day, "hours_from_now": (round(self.hours_from_now, 1)
                                                          if self.hours_from_now is not None else None),
            "label": self.label, "verified": self.verified, "note": self.schedule_note,
            "window_note": self.window_note, "shipping_cost_toman": self.shipping_cost_toman,
            "shipping_label": self.shipping_label}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_hhmm(value, where: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(value or ""))
    if not m:
        raise DeliveryConfigError(f"{where}: expected 'HH:MM', got {value!r}")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise DeliveryConfigError(f"{where}: time out of range: {value!r}")
    return time(h, mi)


def parse_weekday(value, where: str) -> int:
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    key = str(value or "").strip().lower()
    key = key.replace("‌", " ").replace("ي", "ی")
    aliases = {k.replace("‌", " "): v for k, v in WEEKDAY_ALIASES.items()}
    if key in aliases:
        return aliases[key]
    raise DeliveryConfigError(f"{where}: unknown weekday {value!r} "
                              f"(use monday..sunday / شنبه..جمعه / 0..6)")


def parse_date(value, where: str) -> date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        raise DeliveryConfigError(f"{where}: expected YYYY-MM-DD, got {value!r}")


def load_schedules(path, tz_name: str = DEFAULT_TZ_NAME) -> dict:
    """Load config/delivery.yaml -> {source_name: SourceSchedule}. A missing file is NOT an error
    (delivery is then 'unknown' everywhere); a malformed file IS an error so bad settings never
    pass silently."""
    p = Path(path)
    if not p.exists():
        return {}
    import yaml
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise DeliveryConfigError(f"{p}: invalid YAML ({exc})")
    if not isinstance(data, dict):
        raise DeliveryConfigError(f"{p}: top level must be a mapping")
    unknown = set(data) - {"sources", "timezone"}
    if unknown:
        raise DeliveryConfigError(f"{p}: unknown keys {sorted(unknown)}; allowed: ['sources', 'timezone']")
    tz_name = str(data.get("timezone") or tz_name)
    tz = _safe_zone(tz_name)
    out = {}
    for name, raw in (data.get("sources") or {}).items():
        out[str(name)] = _parse_schedule(str(name), raw or {}, where=f"{p}: sources.{name}", tz=tz)
    return out


def _safe_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        raise DeliveryConfigError(f"unknown timezone {name!r}")


def _parse_schedule(name: str, raw: dict, where: str, tz: ZoneInfo) -> SourceSchedule:
    unknown = set(raw) - {"order_windows", "active_weekdays", "holidays", "verified", "note",
                          "shipping_cost_toman", "shipping_note"}
    if unknown:
        raise DeliveryConfigError(f"{where}: unknown keys {sorted(unknown)}")
    windows_raw = raw.get("order_windows")
    if windows_raw is not None and not isinstance(windows_raw, list):
        raise DeliveryConfigError(f"{where}: order_windows must be a list")
    windows = []
    for i, w in enumerate(windows_raw or []):
        wwhere = f"{where}.order_windows[{i}]"
        if not isinstance(w, dict):
            raise DeliveryConfigError(f"{wwhere}: must be a mapping")
        bad = set(w) - {"start", "end", "ship_at", "delivery_at", "delivery_day_offset", "note"}
        if bad:
            raise DeliveryConfigError(f"{wwhere}: unknown keys {sorted(bad)}")
        for req in ("start", "end", "ship_at", "delivery_at"):
            if w.get(req) is None:
                raise DeliveryConfigError(f"{wwhere}: '{req}' is required")
        start, end = parse_hhmm(w["start"], wwhere + ".start"), parse_hhmm(w["end"], wwhere + ".end")
        ship, deliv = parse_hhmm(w["ship_at"], wwhere + ".ship_at"), parse_hhmm(w["delivery_at"], wwhere + ".delivery_at")
        offset = int(w.get("delivery_day_offset", 0) or 0)
        if offset < 0:
            raise DeliveryConfigError(f"{wwhere}: delivery_day_offset must be >= 0")
        if offset == 0 and deliv <= ship:
            raise DeliveryConfigError(f"{wwhere}: same-day delivery_at must be after ship_at")
        if start > end:
            raise DeliveryConfigError(f"{wwhere}: window start must be <= end (overnight windows are not supported)")
        windows.append(OrderWindow(start, end, ship, deliv, offset, str(w.get("note") or "")))
    windows.sort(key=lambda w: w.start)
    weekdays_raw = raw.get("active_weekdays")
    weekdays = ({parse_weekday(v, where + ".active_weekdays") for v in weekdays_raw}
                if weekdays_raw else set(range(7)))
    holidays = {parse_date(h, where + ".holidays") for h in (raw.get("holidays") or [])}
    cost = raw.get("shipping_cost_toman")
    if cost is not None:
        try:
            cost = float(cost)
        except (TypeError, ValueError):
            raise DeliveryConfigError(f"{where}: shipping_cost_toman must be a number")
        if cost < 0:
            raise DeliveryConfigError(f"{where}: shipping_cost_toman must be >= 0")
    return SourceSchedule(name=name, windows=windows, active_weekdays=weekdays, holidays=holidays,
                          verified=bool(raw.get("verified", False)), note=str(raw.get("note") or ""),
                          shipping_cost_toman=cost, shipping_note=str(raw.get("shipping_note") or ""))


def _is_working_day(day: date, sch: SourceSchedule) -> bool:
    return day.weekday() in sch.active_weekdays and day not in sch.holidays


def _next_working_day(day: date, sch: SourceSchedule) -> date:
    for _ in range(366):
        day += timedelta(days=1)
        if _is_working_day(day, sch):
            return day
    return day


def estimate(schedule: SourceSchedule | None, now: datetime, source: str = "") -> DeliveryEstimate:
    """Earliest realistic delivery to Qazvin for an order placed at `now` (aware UTC or None-ish)."""
    est = DeliveryEstimate(source=source or (schedule.name if schedule else ""))
    if schedule is None or not schedule.windows:
        est.schedule_note = "بدون تنظیمات سفارش/تحویل"
        return est
    est.verified = schedule.verified
    est.schedule_note = schedule.note
    est.shipping_cost_toman, est.shipping_note = schedule.shipping_cost_toman, schedule.shipping_note
    now_local = now.astimezone(TEHRAN)
    day = now_local.date()
    for _ in range(370):                                    # bounded search over holidays/weekends
        if not _is_working_day(day, schedule):
            day = _next_working_day(day, schedule)
            continue
        if day == now_local.date():                          # today: first window whose cut-off is not passed
            for w in schedule.windows:
                if now_local.time() <= w.end:                # exactly AT the cut-off is still accepted
                    return _build(est, schedule, w, now_local, day)
            day = _next_working_day(day, schedule)           # all cut-offs passed -> next working day
            continue
        return _build(est, schedule, schedule.windows[0], now_local, day)
    est.schedule_note = (est.schedule_note + " | " if est.schedule_note else "") + "هیچ روز کاری آینده یافت نشد"
    return est


def _build(est: DeliveryEstimate, sch: SourceSchedule, w: OrderWindow, now_local: datetime, day: date) -> DeliveryEstimate:
    ship_dt = datetime.combine(day, w.ship_at, tzinfo=TEHRAN)
    deliv_day = day + timedelta(days=w.delivery_day_offset)
    deliv_dt = datetime.combine(deliv_day, w.delivery_at, tzinfo=TEHRAN)
    if deliv_dt <= ship_dt:                                  # defensive: arrival can never precede dispatch
        deliv_dt = datetime.combine(deliv_day + timedelta(days=1), w.delivery_at, tzinfo=TEHRAN)
    est.status, est.order_deadline, est.ship_at, est.delivery_at = "ok", datetime.combine(day, w.end, tzinfo=TEHRAN), ship_dt, deliv_dt
    est.query_date = now_local.date()
    est.same_day = deliv_dt.date() == now_local.date()
    est.hours_from_now = (deliv_dt - now_local).total_seconds() / 3600.0
    est.window_note = w.note
    return est


def format_estimate(est: DeliveryEstimate) -> str:
    if est.status != "ok" or est.delivery_at is None:
        return UNKNOWN_LABEL
    d = est.delivery_at
    qd = est.query_date or d.date()
    if d.date() == qd:
        day_txt = "امروز"
    elif (d.date() - qd).days == 1:
        day_txt = "فردا"
    else:
        day_txt = WEEKDAY_FA[d.weekday()]
    tag = "" if est.verified else " (تقریبی)"
    base = f"{day_txt} {d.hour:02d}:{d.minute:02d}{tag}"
    if est.order_deadline:
        base += f" — سفارش تا {est.order_deadline.hour:02d}:{est.order_deadline.minute:02d}"
    return base


def estimates_for_sources(schedules: dict, now: datetime, sources) -> dict:
    """{source: DeliveryEstimate} for every requested source (missing config -> status unknown)."""
    return {s: estimate(schedules.get(s), now, s) for s in sources}
