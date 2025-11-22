import streamlit as st
import json
from datetime import datetime
import logging
import os
from dotenv import load_dotenv
import importlib
from api import execute_tool
from packaging.version import Version
from config import tools, STATIC_BASE, APP_HOST, APP_PORT, USER_EMAIL, USERNAME
from openai_utils import initialize_openai_client, call_openai_api
import time

# Load environment variables
load_dotenv()

# Define EVENT_SLUG
EVENT_SLUG = os.getenv("EVENT_SLUG")

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize session state for timezone, style, and show_thinking
if "timezone" not in st.session_state:
    st.session_state.timezone = "America/Los_Angeles"  # Default to PT
if "style" not in st.session_state:
    st.session_state.style = "3"  # Default to Blue & White Minimal
if "show_thinking" not in st.session_state:
    st.session_state.show_thinking = False  # Default to not showing debug info

# Sidebar for configuration
with st.sidebar:
    st.header("Settings")
    timezone_options = {
        "PT (Pacific Time)": "America/Los_Angeles",
        "MT (Mountain Time)": "America/Denver",
        "CT (Central Time)": "America/Chicago",
        "ET (Eastern Time)": "America/New_York",
        "AKT (Alaska Time)": "America/Anchorage",
        "HAT (Hawaii-Aleutian Time)": "Pacific/Honolulu",
        "Chamorro Time (Guam)": "Pacific/Guam",
        "Atlantic Time (Puerto Rico)": "America/Puerto_Rico"
    }
    selected_timezone = st.selectbox(
        "Select Timezone",
        options=list(timezone_options.keys()),
        index=0,  # Default to PT
        key="timezone_select"
    )
    st.session_state.timezone = timezone_options[selected_timezone]

    style_options = {
        "1 - Coral & Dark Gray": "1",
        "2 - Orange & Gray": "2",
        "3 - Blue & White Minimal": "3",
        "4 - Green & Light Gray": "4",
        "5 - Purple & Neutral": "5",
        "6 - Yellow & Blue": "6",
        "7 - Teal & White": "7",
        "8 - Pink & Gray": "8",
        "9 - Navy & Cream": "9",
        "10 - Mint & Charcoal": "10"
    }
    selected_style = st.selectbox(
        "Select Style",
        options=list(style_options.keys()),
        index=2,  # Default to Blue & White Minimal
        key="style_select"
    )
    st.session_state.style = style_options[selected_style]

    st.checkbox("Show Thinking", value=st.session_state.show_thinking, key="show_thinking")

# Load CSS based on selected style
css_path = os.path.join(STATIC_BASE, f"style{st.session_state.style}.css")
if os.path.exists(css_path):
    with open(css_path, "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
else:
    st.warning(f"Thinking: CSS file not found at {css_path}. Proceeding without custom styling.")

# Cache OpenAI client initialization
@st.cache_resource
def get_openai_client():
    return initialize_openai_client()

client = get_openai_client()
if not client:
    st.warning("Thinking: Please set the OPENAI_API_KEY environment variable in a .env file.")
    st.stop()

# Initialize conversation history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Check Streamlit version compatibility
required_streamlit = "1.51.0"
installed_streamlit = importlib.metadata.version("streamlit")
if Version(installed_streamlit) < Version(required_streamlit):
    st.error(f"Thinking: Streamlit {installed_streamlit} detected. Please install {required_streamlit} or higher.")
    st.stop()

# UI setup
st.set_page_config(page_title="Book Michael's Calendar", page_icon=os.path.join(STATIC_BASE, "favicon.ico"))
st.title("Book Michael's Calendar")

# Center-aligned logo
logo_path = os.path.join(STATIC_BASE, 'logo.png')
assistant_profile_path = os.path.join(STATIC_BASE, 'assistant_profile.png')
user_profile_path = os.path.join(STATIC_BASE, 'user_profile.png')
if os.path.exists(logo_path):
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image(logo_path, caption="LiveX Logo", width=150)
else:
    st.warning("Thinking: Logo image missing. Please ensure logo.png is in the static directory.")

# Display welcome message
st.markdown(f"""
    <div class='welcome-message'>
        <p>Welcome, {USER_EMAIL.split('@')[0].title()}! Manage your schedule with ease.</p>
        <p>Username: {USERNAME}, Email: {USER_EMAIL}, Event Type: {EVENT_SLUG}</p>
    </div>
""", unsafe_allow_html=True)

# Display chat history
for message in st.session_state.chat_history:
    avatar = user_profile_path if message["role"] == "user" else assistant_profile_path
    with st.chat_message(message["role"], avatar=avatar if os.path.exists(avatar) else None):
        st.markdown(message["content"], unsafe_allow_html=True)

# Chat input and processing
if prompt := st.chat_input("How may I assist? (e.g., 'Book a meeting', 'Show my events')"):
    with st.chat_message("user", avatar=user_profile_path if os.path.exists(user_profile_path) else None):
        st.markdown(prompt)
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    
    with st.chat_message("assistant", avatar=assistant_profile_path if os.path.exists(assistant_profile_path) else None):
        with st.spinner("Processing..."):
            thinking_placeholder = st.empty()
            thinking_placeholder.info("Thinking...")
            user_input = prompt.strip()
            logger.info(f"Calling OpenAI API with input: {user_input}")
            
            chat_history = st.session_state.chat_history[:-1]
            system_prompt = {
                "role": "system",
                "content": f"You are a helpful assistant managing the user's Cal.com schedule. Parse user inputs (e.g., 'tomorrow', 'next Monday', '10:00 AM', 'first 5 slots') and return: - Dates in YYYY-MM-DD format, ensuring they are today ({datetime.now().strftime('%Y-%m-%d')}) or in the future. - Times in UTC ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ), using {st.session_state.timezone} for local time conversions. - A 'count' of items if the user specifies a number (e.g., '5 events', 'first 3 slots'). - For get_available_slots, provide a duration (in seconds) for the requested date range (e.g., 86400 for one day, 604800 for one week, 2592000 for 30 days). Use tools to list events, check availability, book meetings, and cancel events. For get_available_slots, if the user says 'tomorrow' or 'show my slots', set start_date to tomorrow's date with duration=86400 seconds. If the user specifies a longer period (e.g., 'whole week' or '7 days'), set duration=604800 seconds. If the user specifies 'X days' (e.g., 'coming 30 days'), set duration=X*86400 seconds. For create_booking, expect start_time in UTC ISO 8601 format (e.g., '2025-11-11T18:00:00Z') and convert any local time inputs (e.g., '10:00 AM') using the user's timezone. Return a single tool call per request unless explicitly required otherwise."
            }
            messages = [system_prompt] + chat_history + [{"role": "user", "content": user_input}]
            
            try:
                openai_request = {
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto"
                }
                response = call_openai_api(client, messages, tools)
                response_message = response.choices[0].message
                openai_response = {
                    "content": response_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                        } for tc in getattr(response_message, "tool_calls", [])
                    ],
                    "usage": getattr(response, "usage", None)
                }
                assistant_record = {"role": "assistant", "content": response_message.content}
                if getattr(response_message, "tool_calls", None):
                    assistant_record["tool_calls"] = [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in response_message.tool_calls
                    ]
                chat_history.append(assistant_record)
                st.session_state.chat_history = chat_history

                if response_message.tool_calls:
                    tool_results = []
                    for tool_call in response_message.tool_calls[:1]:  # Process only the first tool call
                        logger.info(f"Processing tool call: {tool_call.function.name}")
                        try:
                            function_name = tool_call.function.name
                            arguments = tool_call.function.arguments
                            args = json.loads(arguments)
                            event_slug = args.get("event_slug", "30min")
                            tool_result, error_response, cal_api_debug = execute_tool(
                                {"id": tool_call.id, "function": {"name": function_name, "arguments": arguments}, "type": "function"},
                                user_input,
                                event_slug=event_slug
                            )
                            tool_results.append({"content": tool_result, "error": error_response, "tool_call_id": tool_call.id, "cal_api_debug": cal_api_debug})
                            chat_history.append({
                                "role": "tool",
                                "content": tool_result if not error_response else error_response,
                                "tool_call_id": tool_call.id
                            })
                            st.session_state.chat_history = chat_history
                        except Exception as e:
                            logger.error(f"Error executing tool {function_name}: {e}")
                            tool_result = f"Thinking: Error executing tool: {str(e)}"
                            tool_results.append({"content": tool_result, "error": True, "tool_call_id": tool_call.id, "cal_api_debug": None})
                            chat_history.append({
                                "role": "tool",
                                "content": tool_result,
                                "tool_call_id": tool_call.id
                            })
                            st.session_state.chat_history = chat_history
                    for result in tool_results:
                        if result["error"]:
                            chat_history.append({
                                "role": "assistant",
                                "content": f"<div class='thinking-output error'>{result['content']}</div>"
                            })
                            st.session_state.chat_history = chat_history
                        else:
                            st.success(result["content"])
                        # Display debug info if "Show Thinking" is enabled
                        if st.session_state.show_thinking:
                            st.write("**Thinking: OpenAI API Debug Info**")
                            st.write({
                                "Request": openai_request,
                                "Response": openai_response
                            })
                            if result["cal_api_debug"]:
                                st.write("**Thinking: Cal.com API Debug Info**")
                                st.write(result["cal_api_debug"])
                else:
                    st.info(f"Thinking: {response_message.content or 'No response from LLM.'}")
                    if st.session_state.show_thinking:
                        st.write("**Thinking: OpenAI API Debug Info**")
                        st.write({
                            "Request": openai_request,
                            "Response": openai_response
                        })
            except Exception as e:
                logger.error(f"Error in API call: {str(e)}")
                chat_history.append({
                    "role": "assistant",
                    "content": f"<div class='thinking-output error'>Thinking: Error: {str(e)}</div>"
                })
                st.session_state.chat_history = chat_history
            finally:
                # Clear thinking bar
                thinking_placeholder.empty()
