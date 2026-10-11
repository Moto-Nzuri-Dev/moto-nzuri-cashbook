"""One place for 'now' and 'today' so every date is in Nairobi time, wherever the server runs."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)


def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()
