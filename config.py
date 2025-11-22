import os
import streamlit as st
from importlib.metadata import version
from dotenv import load_dotenv
import logging
import requests
import json

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load .env file and verify
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(dotenv_path):
    logger.info(f"Found .env file at {dotenv_path}")
    load_dotenv(dotenv_path)
else:
    logger.error(f".env file not found at {dotenv_path}. Ensure it exists for local mode.")
    if os.getenv("STREAMLIT_ENV", "local") == "local":
        st.error(f".env file not found at {dotenv_path}. Please create it with required variables.")
        st.stop()

# Check Streamlit version compatibility
required_streamlit = "1.51.0"
installed_streamlit = version("streamlit")
if installed_streamlit < required_streamlit:
    st.error(f"Streamlit {installed_streamlit} detected. Please install {required_streamlit} or higher.")
    st.stop()

# Conditional import for Secret Manager (only for production)
secret_manager_available = False
if os.getenv("STREAMLIT_ENV", "local") != "local":
    try:
        from google.cloud import secretmanager
        secret_manager_available = True
    except ImportError:
        st.error("google-cloud-secretmanager is required for production. Install it with pip.")
        st.stop()

def get_secret(secret_id):
    if os.getenv("STREAMLIT_ENV", "local") == "local":
        # Map secret_id to .env variable name
        env_var_map = {
            "openai-key": "OPENAI_API_KEY",
            "cal-key": "CAL_API_KEY"
        }
        env_var = env_var_map.get(secret_id, secret_id.replace("-", "_").upper())
        value = os.getenv(env_var)
        logger.info(f"Local mode: Attempted to load {secret_id} (env var: {env_var}) = {value[:10] + '...' if value else 'None'}")
        if value is None:
            logger.error(f"Failed to load {secret_id} (env var: {env_var}) from .env. Ensure it is set correctly.")
        return value
    if not secret_manager_available:
        st.error("Secret Manager not available in production mode.")
        st.stop()
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/livex-app/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(name=name)
        value = response.payload.data.decode("UTF-8")
        logger.info(f"Production mode: Loaded {secret_id} = {value[:10] + '...' if value else 'None'}")
        return value
    except Exception as e:
        st.error(f"Failed to access secret {secret_id}: {e}")
        st.stop()

# Configuration (secrets for API keys, env vars for others)
OPENAI_API_KEY = get_secret("openai-key")
CAL_API_KEY = get_secret("cal-key")

# Load non-secret variables with explicit validation
USER_EMAIL_RAW = os.getenv("USER_EMAIL")
USERNAME_RAW = os.getenv("USERNAME")
EVENT_SLUG_RAW = os.getenv("EVENT_SLUG")
logger.debug(f"Raw .env values: USER_EMAIL={USER_EMAIL_RAW}, USERNAME={USERNAME_RAW}, EVENT_SLUG={EVENT_SLUG_RAW}")

USER_EMAIL = USER_EMAIL_RAW if USER_EMAIL_RAW and "@" in USER_EMAIL_RAW else "mhuo.live@gmail.com"
USERNAME = USERNAME_RAW if USERNAME_RAW and USERNAME_RAW.strip() else "michaelhuo"
EVENT_SLUG = EVENT_SLUG_RAW if EVENT_SLUG_RAW and EVENT_SLUG_RAW.strip() else "30min"

APP_HOST = os.getenv("APP_HOST", "127.0.0.1" if os.getenv("STREAMLIT_ENV", "local") == "local" else "0.0.0.0")
APP_PORT = os.getenv("APP_PORT", "5901" if os.getenv("STREAMLIT_ENV", "local") == "local" else os.getenv("PORT", "8080"))

# Debug logging for final values
logger.info(f"Loaded OPENAI_API_KEY: {'Yes' if OPENAI_API_KEY else 'No'}")
logger.info(f"Loaded CAL_API_KEY: {'Yes' if CAL_API_KEY else 'No'}")
logger.info(f"Loaded USER_EMAIL: {USER_EMAIL}")
logger.info(f"Loaded USERNAME: {USERNAME}")
logger.info(f"Loaded EVENT_SLUG: {EVENT_SLUG}")
logger.info(f"Loaded APP_HOST: {APP_HOST}")
logger.info(f"Loaded APP_PORT: {APP_PORT}")

# Validate required vars
required_vars = {
    'OPENAI_API_KEY': OPENAI_API_KEY,
    'CAL_API_KEY': CAL_API_KEY,
    'USER_EMAIL': USER_EMAIL,
    'USERNAME': USERNAME,
    'EVENT_SLUG': EVENT_SLUG
}
missing_vars = [var for var, value in required_vars.items() if not value or not value.strip()]
if missing_vars:
    st.error(f"Missing or invalid environment variables: {', '.join(missing_vars)}. Check .env file for local mode or Secret Manager for production.")
    st.stop()

IS_LOCAL = os.getenv("STREAMLIT_ENV", "local") == "local"
STATIC_BASE = "static/" if IS_LOCAL else "/app/static/"

tools = [
    {
        "type": "function",
        "function": {
            "name": "list_bookings",
            "description": "List the user's active scheduled events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of events to return", "default": 10}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Get available time slots for booking in a given date range. Parse user input (e.g., 'tomorrow', 'next Monday') and return start_date in YYYY-MM-DD format and duration (seconds) representing the range. Ensure start_date is today or in the future. If end_date is provided, verify it matches start_date + duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format (e.g., 2025-11-11), must be today or later"},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format (e.g., 2025-11-11), optional, defaults to start_date + duration"},
                    "duration": {"type": "integer", "description": "Length of the date range in seconds (e.g., 86400 for one day), defaults to 86400"},
                    "slot_minutes": {"type": "integer", "description": "Length of each slot in minutes", "default": 30},
                    "count": {"type": "integer", "description": "Number of slots to return", "default": 10}
                },
                "required": ["start_date"]  # end_date is now optional
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": "Create a new booking for an available slot. Expect start_time in UTC ISO 8601 format (e.g., '2025-11-11T18:00:00Z'). Convert local time inputs (e.g., '10:00 AM') using the user's timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_time": {"type": "string", "description": "Start time in UTC ISO 8601 format (e.g., '2025-11-11T18:00:00Z')"},
                    "title": {"type": "string", "description": "Title or reason for the meeting"},
                    "guests": {"type": "array", "items": {"type": "string"}, "description": "Optional guest emails"}
                },
                "required": ["start_time", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": "Cancel a specific booking by its UID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {"type": "string", "description": "The UID of the booking to cancel"},
                    "reason": {"type": "string", "description": "Optional reason for cancellation"}
                },
                "required": ["booking_uid"]
            }
        }
    }
]

def validate_cal_config():
    """Validate Cal.com configuration by checking event types."""
    try:
        headers = {"Authorization": f"Bearer {CAL_API_KEY}", "Content-Type": "application/json"}
        url = "https://api.cal.com/v2/event-types"
        params = {
            "username": USERNAME,
            "cal-api-version": "2024-08-13"
        }
        logger.info(f"Validating Cal.com config with URL: {url}")
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"API response for event types: {json.dumps(data, indent=2)}")
        event_types = data.get("data", {}).get("eventTypeGroups", [])
        for group in event_types:
            for event in group.get("eventTypes", []):
                if event.get("slug") == EVENT_SLUG and event.get("userIds", []) and not event.get("hidden"):
                    logger.info(f"Validated event slug {EVENT_SLUG} for username {USERNAME}")
                    return True
        logger.error(f"Event slug {EVENT_SLUG} or username {USERNAME} not found or hidden")
        return False
    except Exception as e:
        logger.error(f"Error validating Cal.com config: {str(e)}")
        return False

# Validate Cal.com configuration
if not validate_cal_config():
    st.error(f"Invalid Cal.com configuration: Event slug {EVENT_SLUG} or username {USERNAME} not found.")
    st.stop()
