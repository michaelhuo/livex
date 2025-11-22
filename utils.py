from datetime import datetime, time as dt_time, timedelta
from pytz import timezone, utc
from dateutil import parser as dtparser
import logging
import streamlit as st

logger = logging.getLogger(__name__)
UTC = utc
MAX_DURATION_SECONDS = 31_536_000  # 1 year in seconds

def parse_to_utc_iso(time_str):
    """Parse a date/time string to UTC ISO 8601 (YYYY-MM-DDTHH:MM:SSZ).
    Raises ValueError if invalid or in the past."""
    try:
        now_utc = datetime.now(UTC)
        local_tz = timezone(st.session_state.timezone)
        if st.session_state.timezone.split('/')[0] in time_str.upper():
            dt = dtparser.parse(time_str).astimezone(local_tz)
            dt_utc = dt.astimezone(UTC)
        elif time_str.endswith("Z"):
            dt_utc = dtparser.parse(time_str).astimezone(UTC)
        else:
            dt_utc = dtparser.parse(time_str).replace(tzinfo=local_tz).astimezone(UTC)
        if dt_utc < now_utc:
            logger.warning(f"Parsed time {time_str} is in the past: {dt_utc}")
            raise ValueError("Time cannot be in the past")
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        logger.error(f"Failed to parse time {time_str}: {e}")
        raise ValueError(f"Invalid time format: {e}")

def validate_date(date_str, default_date):
    """Validate a YYYY-MM-DD date, return default if invalid or past."""
    local_tz = timezone(st.session_state.timezone)
    now_local = datetime.now(local_tz)
    today_str = now_local.strftime("%Y-%m-%d")
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        if date_str < today_str:
            logger.warning(f"Date {date_str} is in the past, using default: {default_date}")
            return default_date
        return date_str
    except ValueError:
        logger.warning(f"Invalid date {date_str}, using default: {default_date}")
        return default_date

def validate_duration_seconds(seconds):
    """Validate duration in seconds, return input if valid, else default to MAX_DURATION_SECONDS."""
    try:
        seconds = int(seconds)
        if seconds < 1:
            logger.warning(f"Invalid duration {seconds} seconds, using default: {MAX_DURATION_SECONDS}")
            return MAX_DURATION_SECONDS  # Default to one year
        if seconds > MAX_DURATION_SECONDS:
            logger.warning(f"Duration {seconds} seconds exceeds maximum {MAX_DURATION_SECONDS}, using maximum")
            return MAX_DURATION_SECONDS
        return seconds
    except (ValueError, TypeError):
        logger.warning(f"Invalid duration {seconds}, using default: {MAX_DURATION_SECONDS}")
        return MAX_DURATION_SECONDS

def calculate_end_date(start_date, duration_seconds):
    """Calculate end_date from start_date and duration in seconds."""
    try:
        local_tz = timezone(st.session_state.timezone)
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        start_datetime = local_tz.localize(datetime.combine(start_date_obj, dt_time(0, 0, 0)))
        end_datetime = start_datetime + timedelta(seconds=duration_seconds)
        return end_datetime.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        logger.error(f"Failed to calculate end_date from {start_date} + {duration_seconds} seconds: {e}")
        return start_date

def utc_to_local_display(utc_time_str):
    """Convert UTC ISO 8601 to local timezone display format with UTC in parentheses."""
    try:
        local_tz = timezone(st.session_state.timezone)
        utc_time = dtparser.parse(utc_time_str)
        local_time = utc_time.astimezone(local_tz)
        display = local_time.strftime("%m/%d/%Y %I:%M %p %Z")
        return f"{display} (UTC: {utc_time_str})"
    except ValueError as e:
        logger.error(f"Failed to convert {utc_time_str} to local timezone: {e}")
        return "N/A"
