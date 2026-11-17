"""Explicitly configured community event reminders with no network access.

Events are manually entered by administrators and never imply a verified
boss kill, castle capture, or live siege. GitHub cron is best effort.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .models import Event, Provenance, World, required

MAX_REMINDERS = 8
MAX_SCHEDULES = 100
REMINDER_GRACE_MINUTES = 20


@dataclass(frozen=True)
class ScheduledEvent:
    identifier: str
    world: World
    title: str
    body: str
    starts_at: datetime
    remind_before_minutes: tuple[int, ...] = (60,)
    clan: str | None = None
    enabled: bool = True

    def __post_init__(self):
        required(self.identifier, "scheduled event ID")
        required(self.title, "scheduled event title")
        if not isinstance(self.world, World):
            raise ValueError("scheduled event requires a valid world")
        if len(self.title) > 160 or not isinstance(self.body, str) or len(self.body) > 2000:
            raise ValueError("scheduled event text is too long")
        if not isinstance(self.starts_at, datetime) or self.starts_at.utcoffset() is None:
            raise ValueError("scheduled start time requires an explicit UTC offset")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        times = self.remind_before_minutes
        if not isinstance(times, tuple) or not 0 < len(times) <= MAX_REMINDERS:
            raise ValueError("scheduled reminders must contain 1-8 lead times")
        if len(times) != len(set(times)) or any(type(v) is not int or not 1 <= v <= 10080 for v in times):
            raise ValueError("reminder lead times must be unique integers 1-10080")
        if self.clan is not None:
            required(self.clan, "clan")


def due_reminders(
    schedules: Sequence[ScheduledEvent],
    now: datetime,
    grace_minutes: int = REMINDER_GRACE_MINUTES,
) -> list[Event]:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must include timezone")
    if type(grace_minutes) is not int or not 1 <= grace_minutes <= 60:
        raise ValueError("grace_minutes must be 1-60")
    result = []
    for item in schedules:
        if not item.enabled:
            continue
        for before in item.remind_before_minutes:
            trigger = item.starts_at - timedelta(minutes=before)
            # Do not send after event start or after the reminder window.
            if not trigger <= now < min(item.starts_at, trigger + timedelta(minutes=grace_minutes)):
                continue
            result.append(Event(
                world=item.world,
                source_id="manual_schedule",
                external_id=f"{item.identifier}:{item.starts_at.isoformat()}:lead-{before}",
                kind="event_reminder",
                title=f"{item.title} ({before} min reminder)",
                body=(
                    f"{item.body}\n"
                    f"Manually scheduled by a community administrator. "
                    f"Start: {item.starts_at.isoformat()}; reminder {before} minutes beforehand. "
                    f"This does not verify a boss kill, live siege or server event."
                ),
                source_url="https://github.com/",
                provenance=Provenance.MANUAL,
                observed_at=now,
                occurs_at=item.starts_at,
                clan=item.clan,
            ))
    return result
