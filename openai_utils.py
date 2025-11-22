import openai
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def initialize_openai_client():
    """Initialize and return the OpenAI client."""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set in .env file")
        return None
    try:
        client = openai.OpenAI(api_key=api_key)
        logger.info("OpenAI client initialized successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")
        return None

def call_openai_api(client, messages, tools, model="gpt-4o-mini", timeout=30):
    """Call OpenAI chat completion API with the provided messages and tools."""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            timeout=timeout
        )
        logger.info("OpenAI API call successful")
        return response
    except Exception as e:
        logger.error(f"Error in OpenAI API call: {str(e)}")
        raise