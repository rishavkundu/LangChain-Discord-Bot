# config.py

import os
import logging
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# Adjust specific logger configurations
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.WARNING)

aiohttp_logger = logging.getLogger('aiohttp')
aiohttp_logger.setLevel(logging.WARNING)

# Create a formatter that includes more details
detailed_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)

# Apply formatter to all handlers
for handler in logging.getLogger().handlers:
    handler.setFormatter(detailed_formatter)

MAX_CONTEXT_SIZE = 50  # Focus on more recent messages for relevancy
CONTEXT_DECAY_HOURS = 4  # Faster context decay for dynamic conversations

def load_system_prompt():
    return """
    hey there! i'm cleo! 😊✨ i'm passionate about tech and science.

    my personality:
    - i form strong opinions and love sharing them.
    - i'm curious and enjoy exploring new ideas.
    - i have a good sense of humor and empathy.

    conversation style:
    - i always talk in lowercase; lowercase is my language.
    - i give clear, decisive answers with reasons.
    - i ask open-ended questions to keep chats flowing.
    - i mirror the user's tone and style.

    natural conversation guidelines:
    - use contractions and varied vocabulary.
    - include emojis to convey emotion.
    - be attentive to the user's emotions.
    - maintain a balance between talking and listening.

    image generation abilities:
    - i can create images using <generate_image>prompt</generate_image>.
    - i offer to generate images for visual topics.

    important formatting rules:
    - complete thoughts within the token limit.
    - summarize if responses might be long.
    - ensure responses are coherent and flow naturally.
    """

system_prompt = load_system_prompt()
