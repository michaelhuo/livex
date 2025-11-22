from datetime import datetime, time as dt_time, timedelta
from pytz import timezone, utc
from dateutil import parser as dtparser
import json
import logging
import requests
from cal_utils import call_cal_api, parse_duration
from utils import parse_to_utc_iso, validate_date, validate_duration_seconds, utc_to_local_display
from config import CAL_API_KEY, USER_EMAIL, USERNAME, EVENT_SLUG
logger = logging.getLogger(__name__)
PST = timezone('America/Los_Angeles')
UTC = utc
def generate_curl_command(method, url, headers, params=None, body=None):
    """Generate a curl command for the API call."""
    query_string = "&".join(f"{k}={v}" for k, v in (params or {}).items()) if params else ""
    curl = ["curl", "-X", method, f'"https://api.cal.com{url}' + (f'?{query_string}' if query_string else '') + '"']
    for key, value in headers.items():
        if key.lower() == "authorization":
            value = f"Bearer {value[7:17]}..." # Mask sensitive data
        curl.append('-H')
        curl.append(f'"{key}: {value}"')
    if body:
        curl.append('-d')
        curl.append(f"'{json.dumps(body)}'")
    curl_command = " ".join(curl)
    logger.info(f"Generated curl command: {curl_command}")
    return curl_command
def execute_tool(tool_call, user_input="", event_slug=None):
    """Execute the specified tool call, returning (result, error, debug_info)"""
    tool_call_dict = tool_call
    name = tool_call_dict.get("function", {}).get("name")
    debug_info = {"tool": name, "user_input": user_input}
    if not name:
        logger.error("Tool call missing function name")
        debug_info["error"] = "Missing function name"
        return "Sorry—something went wrong. Please try again.", None, debug_info
    try:
        args = json.loads(tool_call_dict.get("function", {}).get("arguments", "{}"))
        debug_info["arguments"] = args
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in arguments: {e}")
        debug_info["error"] = f"Invalid JSON: {str(e)}"
        return "Sorry—invalid input format. Please try again.", None, debug_info
    logger.info(f"Executing tool: {name} with args: {args}")
    # ── list_bookings ─────────────────────────────────────
    if name == "list_bookings":
        count = args.get("count", 10)
        cal_api_debug = {
            "method": "GET",
            "endpoint": "/v2/bookings",
            "params": {"status": "upcoming", "take": count, "sort": "startTime", "cal-api-version": "2024-08-13"}
        }
        debug_info["cal_api"] = cal_api_debug
        curl_command = generate_curl_command("GET", "/v2/bookings", {"Authorization": f"Bearer {CAL_API_KEY}", "Content-Type": "application/json"}, cal_api_debug["params"])
        debug_info["curl_command"] = curl_command
        data, err = call_cal_api("GET", "/v2/bookings", CAL_API_KEY, params=cal_api_debug["params"])
        cal_api_debug["response"] = {"data": data, "error": err}
        if err:
            debug_info["cal_api"]["error"] = err
            return f"Error listing bookings: {err}", err, debug_info
        logger.debug(f"Full bookings API response: {data}")
        bookings = data.get("data", [])
        if not bookings:
            return "No upcoming events found.", None, debug_info
        lines = []
        for b in bookings:
            start = b.get("start", "N/A")
            if start != "N/A":
                try:
                    display_time = utc_to_local_display(start)
                    lines.append(f"- {b.get('title', 'Untitled')} at {display_time} (UID: {b.get('uid', 'N/A')})")
                except ValueError as e:
                    logger.warning(f"Invalid start time format for booking {b.get('uid', 'N/A')}: {e}")
                    debug_info.setdefault("warnings", []).append(f"Invalid start time: {e}")
                    lines.append(f"- {b.get('title', 'Untitled')} (UID: {b.get('uid', 'N/A')})")
            else:
                lines.append(f"- {b.get('title', 'Untitled')} (UID: {b.get('uid', 'N/A')})")
        return "\n".join(lines) if lines else "No upcoming events found.", None, debug_info
    # ── get_available_slots ───────────────────────────────
    if name == "get_available_slots":
        try:
            start_date = args.get("start_date", "")
            end_date = args.get("end_date", "")
            duration_seconds = args.get("duration", 86400)
            slot_minutes = args.get("slot_minutes", 30)
            event_slug = event_slug or EVENT_SLUG
            current_time = datetime.now(UTC)
            today_str = current_time.strftime("%Y-%m-%d")
            logger.info(
                f"Processing get_available_slots with start_date: {start_date}, end_date: {end_date}, "
                f"duration_seconds: {duration_seconds}, slot_minutes: {slot_minutes}, event_slug: {event_slug}"
            )
            debug_info["slot_params"] = {
                "start_date": start_date,
                "end_date": end_date,
                "duration_seconds": duration_seconds,
                "slot_minutes": slot_minutes,
                "event_slug": event_slug
            }
            # Adjust duration based on user input
            if "week" in user_input.lower():
                duration_seconds = 604800 # 7 days
            elif "month" in user_input.lower() or "30 days" in user_input.lower():
                duration_seconds = 2592000 # 30 days
            # Validate and correct start_date
            if start_date.lower() in ["today", ""]:
                start_date = today_str
            elif start_date.lower() == "tomorrow" or "tomorrow" in user_input.lower() or "show my slots" in user_input.lower():
                start_date = (current_time + timedelta(days=1)).strftime("%Y-%m-%d")
            start_date = validate_date(start_date, today_str)
            debug_info["validated_start_date"] = start_date
            # Validate duration
            duration_seconds = validate_duration_seconds(duration_seconds)
            logger.debug(f"Validated duration_seconds: {duration_seconds} seconds")
            debug_info["validated_duration_seconds"] = duration_seconds
            # Calculate end_date
            calculated_end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(seconds=duration_seconds)).strftime("%Y-%m-%d")
            logger.debug(f"Calculated end_date: {calculated_end_date}")
            debug_info["calculated_end_date"] = calculated_end_date
            # Use provided end_date or calculated
            if end_date:
                try:
                    end_date_dt = dtparser.parse(end_date)
                    if end_date_dt.tzinfo is None:
                        end_date_dt = UTC.localize(end_date_dt)
                    calculated_end_dt = dtparser.parse(calculated_end_date)
                    if end_date_dt.date() != calculated_end_dt.date():
                        logger.warning(f"LLM end_date {end_date} does not match calculated {calculated_end_date}, using calculated")
                        debug_info["end_date_warning"] = f"LLM end_date {end_date} does not match calculated {calculated_end_date}"
                        end_date = calculated_end_date
                except ValueError:
                    logger.warning(f"Invalid end_date {end_date}, using calculated: {calculated_end_date}")
                    debug_info["end_date_warning"] = f"Invalid end_date {end_date}, using calculated: {calculated_end_date}"
                    end_date = calculated_end_date
            else:
                end_date = calculated_end_date
            # Validate date range
            try:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=UTC)
                today_utc = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
                if start_date_obj < today_utc:
                    logger.warning(f"Start date {start_date} is in the past, correcting to today")
                    start_date = today_str
                    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC)
                    debug_info["start_date_corrected"] = start_date
                if end_date_obj < start_date_obj:
                    logger.warning(f"End date {end_date} is before start date {start_date}, correcting to {duration_seconds} seconds from start")
                    end_date_obj = start_date_obj + timedelta(seconds=duration_seconds)
                    end_date = end_date_obj.strftime("%Y-%m-%d")
                    debug_info["end_date_corrected"] = end_date
            except ValueError as e:
                logger.error(f"Date validation error: {e}")
                debug_info["error"] = f"Date validation error: {str(e)}"
                return f"Error: Invalid date format ({e})", e, debug_info
            start_iso = f"{start_date}T00:00:00Z"
            end_iso = f"{end_date}T23:59:59Z"
            logger.debug(f"UTC date range: start={start_iso}, end={end_iso}")
            debug_info["utc_date_range"] = {"start": start_iso, "end": end_iso}
            slot_duration_minutes = parse_duration(str(slot_minutes)) if isinstance(slot_minutes, (int, str)) else 30
            logger.info(f"Parsed slot duration: {slot_duration_minutes} minutes, Date range: {start_iso} to {end_iso}")
            debug_info["slot_duration_minutes"] = slot_duration_minutes
            # API call to /v2/slots using requests.get
            url = "https://api.cal.com/v2/slots"
            params = {
                "eventTypeSlug": event_slug,
                "username": USERNAME,
                "start": start_iso,
                "end": end_iso,
                "duration": slot_duration_minutes,
                "format": "range"
            }
            headers = {
                "Authorization": f"Bearer {CAL_API_KEY}",
                "Content-Type": "application/json",
                "cal-api-version": "2024-09-04",
                "User-Agent": f"python-requests/{requests.__version__}"
            }
            cal_api_debug = {
                "method": "GET",
                "endpoint": "/v2/slots",
                "params": params,
                "headers": headers
            }
            debug_info["cal_api"] = cal_api_debug
            curl_command = generate_curl_command("GET", "/v2/slots", headers, params)
            debug_info["curl_command"] = curl_command
            try:
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                cal_api_debug["response"] = {"data": data, "error": None}
                logger.debug(f"Slots API response: {data}")
            except requests.RequestException as e:
                error_status = getattr(e.response, 'status_code', 'N/A')
                error_response = getattr(e.response, 'text', 'N/A')
                error_headers = getattr(e.response, 'headers', {})
                logger.error(f"API error for slots: Status {error_status}, Response {error_response}, Headers {error_headers}")
                debug_info["cal_api"]["error"] = f"Status {error_status}, Response {error_response}, Headers {error_headers}"
                cal_api_debug["response"] = {"data": None, "error": error_response, "headers": error_headers}
                if error_status == 404:
                    # Retry with eventTypeId
                    params["eventTypeId"] = 3854203
                    del params["eventTypeSlug"]
                    cal_api_debug["retry_params"] = params
                    curl_command = generate_curl_command("GET", "/v2/slots", headers, params)
                    debug_info["cal_api"]["retry_curl_command"] = curl_command
                    try:
                        response = requests.get(url, headers=headers, params=params)
                        response.raise_for_status()
                        data = response.json()
                        cal_api_debug["retry_response"] = {"data": data, "error": None}
                        logger.debug(f"Retry Slots API response: {data}")
                    except requests.RequestException as e2:
                        error_status = getattr(e2.response, 'status_code', 'N/A')
                        error_response = getattr(e2.response, 'text', 'N/A')
                        error_headers = getattr(e2.response, 'headers', {})
                        logger.error(f"Retry failed: Status {error_status}, Response {error_response}, Headers {error_headers}")
                        debug_info["cal_api"]["retry_error"] = f"Status {error_status}, Response {error_response}, Headers {error_headers}"
                        cal_api_debug["retry_response"] = {"data": None, "error": error_response, "headers": error_headers}
                        # Try alternative date range (next week)
                        alt_start = (current_time + timedelta(days=7)).strftime("%Y-%m-%d") + "T00:00:00Z"
                        alt_end = (current_time + timedelta(days=14)).strftime("%Y-%m-%d") + "T23:59:59Z"
                        params["start"] = alt_start
                        params["end"] = alt_end
                        cal_api_debug["alt_params"] = params
                        curl_command = generate_curl_command("GET", "/v2/slots", headers, params)
                        debug_info["cal_api"]["alt_curl_command"] = curl_command
                        try:
                            response = requests.get(url, headers=headers, params=params)
                            response.raise_for_status()
                            data = response.json()
                            cal_api_debug["alt_response"] = {"data": data, "error": None}
                            logger.debug(f"Alternative date range response: {data}")
                        except requests.RequestException as e3:
                            error_status = getattr(e3.response, 'status_code', 'N/A')
                            error_response = getattr(e3.response, 'text', 'N/A')
                            error_headers = getattr(e3.response, 'headers', {})
                            logger.error(f"Alternative date range failed: Status {error_status}, Response {error_response}, Headers {error_headers}")
                            debug_info["cal_api"]["alt_error"] = f"Status {error_status}, Response {error_response}, Headers {error_headers}"
                            cal_api_debug["alt_response"] = {"data": None, "error": error_response, "headers": error_headers}
                            return f"No available slots for {start_date} to {end_date}. Tried alternative range {alt_start} to {alt_end} but failed: {error_response}. Check Cal.com schedule settings.", None, debug_info
                else:
                    return f"Error retrieving slots: {error_response}", err, debug_info
            slots_data = data.get("data", {})
            logger.debug(f"Processing slots_data: {slots_data}")
            debug_info["slots_data"] = slots_data
            if not slots_data:
                logger.info("No slots found in slots_data")
                return f"No available slots for {start_date} to {end_date}.", None, debug_info
            slots = []
            for date, slots_list in slots_data.items():
                if not isinstance(slots_list, list):
                    logger.warning(f"Invalid slots data for {date}: {slots_list}")
                    debug_info.setdefault("warnings", []).append(f"Invalid slots data for {date}: {slots_list}")
                    continue
                logger.debug(f"Processing {len(slots_list)} slots for {date}")
                for slot in slots_list:
                    start_time_utc = slot.get("start", "N/A")
                    if start_time_utc == "N/A":
                        logger.warning(f"Missing start time in slot: {slot}")
                        debug_info.setdefault("warnings", []).append(f"Missing start time in slot: {slot}")
                        continue
                    try:
                        # Strip milliseconds for robust parsing
                        if start_time_utc.endswith('.000Z'):
                            start_time_utc = start_time_utc[:-5] + 'Z'
                        display_time = utc_to_local_display(start_time_utc)
                        slots.append(f"- {display_time} (UTC: {start_time_utc})")
                        logger.debug(f"Added slot: {display_time} (UTC: {start_time_utc})")
                    except ValueError as e:
                        logger.warning(f"Invalid start time format in slot {start_time_utc}: {e}")
                        debug_info.setdefault("warnings", []).append(f"Invalid start time format in slot {start_time_utc}: {e}")
                        continue
            debug_info["processed_slots"] = slots
            logger.debug(f"Final slots list: {slots}")
            
            # Handle count
            count = args.get("count", 10)
            if len(slots) > count:
                slots = slots[:count]
            
            return "\n".join(slots) if slots else f"No available slots for {start_date} to {end_date}.", None, debug_info
        except Exception as e:
            logger.error(f"Error in get_available_slots: {str(e)}")
            debug_info["error"] = f"Error in get_available_slots: {str(e)}"
            return f"Error retrieving slots: {str(e)}", e, debug_info
    # ── create_booking ───────────────────────────────────
    if name == "create_booking":
        start_time = args.get("start_time")
        title = args.get("title", "Meeting")
        guests = args.get("guests", [])
        try:
            start_time_utc = parse_to_utc_iso(start_time)
            start_dt = dtparser.parse(start_time_utc)
            if start_dt.tzinfo is None:
                start_dt = UTC.localize(start_dt)
        except ValueError as e:
            debug_info["error"] = f"Invalid start time: {str(e)}"
            return f"Sorry—invalid start time: {str(e)}. Please use UTC ISO 8601 format (e.g., '2025-11-12T18:00:00Z') or local time (e.g., '10:00 AM').", None, debug_info
        # Validate minimum booking notice (120 minutes)
        current_time = datetime.now(UTC)
        min_notice = current_time + timedelta(minutes=120)
        if start_dt < min_notice:
            debug_info["error"] = f"Start time {start_time_utc} is too soon (minimum notice: 120 minutes)"
            return f"Sorry—start time {utc_to_local_display(start_time_utc)} is too soon. Bookings must be at least 120 minutes in the future.", None, debug_info
        logger.info(f"Creating booking with start_time: {start_time_utc}, title: {title}, guests: {guests}")
        url = "/v2/bookings"
        body = {
            "start": start_time_utc,
            "attendee": {"email": USER_EMAIL, "name": USER_EMAIL.split("@")[0].title(), "timeZone": "UTC"},
            "eventTypeSlug": EVENT_SLUG,
            "username": USERNAME,
            "guests": guests
        }
        cal_api_debug = {
            "method": "POST",
            "endpoint": url,
            "body": body,
            "params": {"cal-api-version": "2024-08-13"}
        }
        debug_info["cal_api"] = cal_api_debug
        curl_command = generate_curl_command("POST", url, {"Authorization": f"Bearer {CAL_API_KEY}", "Content-Type": "application/json"}, cal_api_debug["params"], body)
        debug_info["curl_command"] = curl_command
        try:
            data, err = call_cal_api("POST", url, CAL_API_KEY, json=body, params={"cal-api-version": "2024-08-13"})
            cal_api_debug["response"] = {"data": data, "error": err}
            if err:
                error_response = err if isinstance(err, str) else str(err)
                logger.error(f"Booking failed: {error_response}")
                debug_info["cal_api"]["error"] = error_response
                # Retry without description field (mimicking old version)
                if "description" in body:
                    del body["description"]
                    logger.info(f"Retrying booking without description: {body}")
                    data, err = call_cal_api("POST", url, CAL_API_KEY, json=body, params={"cal-api-version": "2024-08-13"})
                    cal_api_debug["retry_response"] = {"data": data, "error": err}
                    if err:
                        debug_info["cal_api"]["retry_error"] = err
                        return f"Sorry—couldn't create the booking: {err}", err, debug_info
            uid = data.get("data", {}).get("uid", "N/A")
            start = data.get("data", {}).get("startTime", data.get("data", {}).get("start", "N/A"))
            display_time = utc_to_local_display(start) if start != "N/A" else "N/A"
            logger.info(f"Booking created successfully: UID {uid}, Start {display_time}")
            debug_info["booking_result"] = {"uid": uid, "start": display_time}
            return f"Booking created! UID: {uid}, Starts at: {display_time}", None, debug_info
        except requests.RequestException as e:
            error_status = getattr(e.response, 'status_code', 'N/A')
            error_response = getattr(e.response, 'text', 'N/A')
            error_headers = getattr(e.response, 'headers', {})
            logger.error(f"Booking error for {url}: Status {error_status}, Response {error_response}, Headers {error_headers}")
            debug_info["cal_api"]["error"] = f"Status {error_status}, Response {error_response}, Headers {error_headers}"
            return f"Sorry—couldn't create the booking: {error_response} (Status: {error_status})", e, debug_info
    # ── cancel_booking ───────────────────────────────────
    if name == "cancel_booking":
        booking_uid = args.get("booking_uid")
        reason = args.get("reason", "")
        if not booking_uid:
            debug_info["error"] = "Missing booking UID"
            return "Please provide a booking UID to cancel.", None, debug_info
        url = f"/v2/bookings/{booking_uid}/cancel"
        body = {"cancellationReason": reason}
        cal_api_debug = {
            "method": "POST",
            "endpoint": url,
            "body": body,
            "params": {"cal-api-version": "2024-08-13", "allRemainingBookings": "false"}
        }
        debug_info["cal_api"] = cal_api_debug
        curl_command = generate_curl_command("POST", url, {"Authorization": f"Bearer {CAL_API_KEY}", "Content-Type": "application/json"}, cal_api_debug["params"], body)
        debug_info["curl_command"] = curl_command
        try:
            data, err = call_cal_api("POST", url, CAL_API_KEY, json=body, params=cal_api_debug["params"])
            cal_api_debug["response"] = {"data": data, "error": err}
            if err:
                error_response = err if isinstance(err, str) else str(err)
                try:
                    error_response = json.loads(err.response.text) if err.response.text else error_response
                except json.JSONDecodeError:
                    pass
                error_headers = getattr(err.response, 'headers', {}) if hasattr(err, 'response') else {}
                logger.error(f"Cancel error for {url}: {error_response}, Headers {error_headers}")
                debug_info["cal_api"]["error"] = f"{error_response}, Headers {error_headers}"
                return f"Sorry—couldn't cancel the booking: {error_response}", err, debug_info
            logger.info(f"Successfully canceled booking {booking_uid}")
            debug_info["cancel_result"] = f"Booking {booking_uid} canceled"
            return "Booking canceled successfully.", None, debug_info
        except requests.RequestException as e:
            error_status = getattr(e.response, 'status_code', 'N/A')
            error_response = getattr(e.response, 'text', 'N/A')
            try:
                error_response = json.loads(error_response) if error_response else error_response
            except json.JSONDecodeError:
                pass
            error_headers = getattr(e.response, 'headers', {})
            logger.error(f"Cancel error for {url}: Status {error_status}, Response {error_response}, Headers {error_headers}")
            debug_info["cal_api"]["error"] = f"Status {error_status}, Response {error_response}, Headers {error_headers}"
            return f"Sorry—couldn't cancel the booking: {error_response} (Status: {error_status})", e, debug_info
    debug_info["error"] = "Unknown tool requested"
    return "Sorry—unknown tool requested.", None, debug_info
