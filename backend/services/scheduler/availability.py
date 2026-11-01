# Pure free-slot finder: working hours, buffers, weekends, per-day and total limits (no LLM)
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo

from services.scheduler import config
from services.scheduler.models import TimeSlot


@dataclass(frozen=True)
class SlotConstraints:
    """Optional candidate preferences. weekdays uses 0=Mon..6=Sun; latest bounds the slot end."""

    dates_from: date | None = None
    dates_to: date | None = None
    weekdays: frozenset[int] | None = None
    earliest: time | None = None
    latest: time | None = None
    exclude_dates: frozenset[date] = field(default_factory=frozenset)
    exclude_starts: frozenset[datetime] = field(default_factory=frozenset)  # slots already shown

    def single_date(self) -> bool:
        return self.dates_from is not None and self.dates_from == self.dates_to

    def allows_day(self, day: date) -> bool:
        if self.dates_from and day < self.dates_from:
            return False
        if self.dates_to and day > self.dates_to:
            return False
        if self.weekdays is not None and day.weekday() not in self.weekdays:
            return False
        return day not in self.exclude_dates


def stable_slot_id(start: datetime) -> str:
    return "s_" + hashlib.sha1(start.isoformat().encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def find_free_slots(
    busy: list[TimeSlot],
    from_dt: datetime,
    tz: tzinfo,
    *,
    work_start: time = config.WORK_START,
    work_end: time = config.WORK_END,
    slot_minutes: int = config.SLOT_MINUTES,
    buffer_minutes: int = config.BUFFER_MINUTES,
    step_minutes: int = config.STEP_MINUTES,
    days: int = config.DAYS,
    max_slots: int = config.MAX_SLOTS,
    per_day: int = config.PER_DAY,
    constraints: SlotConstraints | None = None,
) -> list[TimeSlot]:
    """Earliest free slots over the next `days` working days, at most `per_day` per day.

    With constraints restricted to a single date, up to `max_slots` may fall on that day.
    """
    if from_dt.tzinfo is None or from_dt.utcoffset() is None:
        raise ValueError("from_dt must be timezone-aware")
    constraints = constraints or SlotConstraints()
    if constraints.single_date():
        per_day = max_slots
    day_start = max(work_start, constraints.earliest) if constraints.earliest else work_start
    day_end = min(work_end, constraints.latest) if constraints.latest else work_end

    duration = timedelta(minutes=slot_minutes)
    buffer = timedelta(minutes=buffer_minutes)
    step = timedelta(minutes=step_minutes)

    slots: list[TimeSlot] = []
    day = from_dt.astimezone(tz).date()
    working_days_seen = 0
    while working_days_seen < days and len(slots) < max_slots:
        if day.weekday() < 5:
            working_days_seen += 1
            if constraints.allows_day(day):
                limit = min(per_day, max_slots - len(slots))
                slots.extend(_slots_for_day(
                    day, busy, from_dt, tz, work_start, day_start, day_end, duration, buffer, step, limit,
                    constraints.exclude_starts,
                ))
        day += timedelta(days=1)
    return slots


def _slots_for_day(
    day: date,
    busy: list[TimeSlot],
    from_dt: datetime,
    tz: tzinfo,
    grid_start: time,
    earliest: time,
    latest: time,
    duration: timedelta,
    buffer: timedelta,
    step: timedelta,
    limit: int,
    exclude_starts: frozenset[datetime] = frozenset(),
) -> list[TimeSlot]:
    found: list[TimeSlot] = []
    start = datetime.combine(day, grid_start, tzinfo=tz)
    lower = datetime.combine(day, earliest, tzinfo=tz)
    day_end = datetime.combine(day, latest, tzinfo=tz)
    while start < lower:  # keep slots on the same step grid as the working day
        start += step
    while start + duration <= day_end and len(found) < limit:
        end = start + duration
        # Slots already proposed today count as busy, so same-day proposals never overlap.
        clashes = any(start < b.end + buffer and b.start - buffer < end for b in [*busy, *found])
        if start >= from_dt and not clashes and start not in exclude_starts:
            found.append(TimeSlot(start=start, end=end))
        start += step
    return found
