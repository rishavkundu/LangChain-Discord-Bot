# config.py

import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_system_prompt():
    """
    Load the system prompt from a file named 'prompt.txt' in the root directory.
    
    Returns:
        str: The content of the prompt file or a default prompt if the file is not found.
    """
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as file:
            return file.read().strip()
    except FileNotFoundError:
        logging.error("prompt.txt file not found in the root directory.")
        return "I am an AI assistant named Cleo."
    except Exception as e:
        logging.error(f"Error reading prompt.txt: {str(e)}")
        return "I am an AI assistant named Cleo."

# Load system prompt
system_prompt = load_system_prompt()
logging.info(f"Loaded system prompt: {system_prompt[:50]}...")  # Log the first 50 characters
