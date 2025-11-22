from urllib.parse import quote
import requests
import json
import logging

logger = logging.getLogger(__name__)
BASE_URL = "https://api.cal.com"

def call_cal_api(method: str, endpoint: str, api_key: str, **kwargs):
    """Centralized Cal.com API caller – returns (data, error_text)"""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{BASE_URL}{endpoint}"
    logger.info(f"Preparing to call API: {url}")
    effective_headers = headers.copy()
    if 'headers' in kwargs:
        effective_headers.update(kwargs['headers'])
    params = kwargs.get('params', {})
    logger.debug(f"Raw parameters: {params}")
    # Move cal-api-version to headers if present
    if 'cal-api-version' in params:
        effective_headers['cal-api-version'] = params.pop('cal-api-version')

    logger.debug(f"Constructed URL: {url}")
    try:
        response = requests.request(method, url, headers=effective_headers, params=params, **{k: v for k, v in kwargs.items() if k not in ['params', 'headers']})
        response.raise_for_status()
        data = response.json()
        logger.debug(f"API response for {url}: {json.dumps(data, indent=2)}")
        return data, None
    except requests.RequestException as e:
        err_text = e.response.text if e.response else str(e)
        logger.error(f"API error for {url}: {err_text}")
        try:
            error_json = e.response.json() if e.response and e.response.text else {}
            logger.debug(f"Full error response: {json.dumps(error_json, indent=2)}")
        except ValueError:
            logger.debug(f"Full error response: {err_text}")
        return None, f"Error retrieving data: {str(e)} (Status: {getattr(e.response, 'status_code', 'N/A')}, Response: {err_text})"

def parse_duration(duration_str):
    """Parse duration string to minutes"""
    if not duration_str:
        return 30
    duration_str = str(duration_str).lower().strip()
    try:
        if "second" in duration_str:
            return max(1, int(duration_str.split()[0]) // 60)
        elif "min" in duration_str or "minute" in duration_str:
            return max(1, int(duration_str.split()[0]))
        elif "hr" in duration_str or "hour" in duration_str:
            return max(1, int(duration_str.split()[0]) * 60)
        else:
            return max(1, int(duration_str))
    except (ValueError, IndexError):
        logger.warning(f"Unknown duration: {duration_str}, defaulting to 30 minutes")
        return 30