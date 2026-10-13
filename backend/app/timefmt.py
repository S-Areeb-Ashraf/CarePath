"""Timezone-aware time formatting. The clinic timezone comes from settings
(CLINIC_TIMEZONE, default Asia/Riyadh). Every starts_at shown to a patient or
the LLM is formatted here so both the assistant and the frontend display the
same local time."""
from datetime import datetime, timezone

from .config import Settings


def format_local(settings: Settings, value: datetime) -> str:
    """Render a UTC datetime as clinic-local 'YYYY-MM-DD at HH:MM'."""
    local = _to_local(settings, value)
    return f'{local.date().isoformat()} at {local.strftime("%H:%M")}'


def to_local_iso(settings: Settings, value: datetime) -> str:
    """Render as clinic-local ISO 8601 with offset, e.g. 2026-10-06T09:00:00+03:00."""
    return _to_local(settings, value).isoformat()


def _to_local(settings: Settings, value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return value.astimezone(ZoneInfo(settings.clinic_timezone))
    except Exception:
        # Windows images without the tzdata package: fall back to a fixed offset.
        from datetime import timedelta
        return value.astimezone(timezone(timedelta(hours=settings.clinic_utc_offset_hours)))
