# config.py

import os
import logging
import sys
from dotenv import load_dotenv
import coloredlogs

load_dotenv()

# Set console output to UTF-8
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Configure logging with colored output and detailed formatting
coloredlogs.install(
    level=logging.INFO,
    fmt='%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level_styles={
        'debug': {'color': 'green'},
        'info': {'color': 'white'},
        'warning': {'color': 'yellow'},
        'error': {'color': 'red'},
        'critical': {'color': 'red', 'bold': True},
    },
    field_styles={
        'asctime': {'color': 'cyan'},
        'levelname': {'color': 'white', 'bold': True},
        'name': {'color': 'magenta'}
    }
)

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Configure file handler with UTF-8 encoding
file_handler = logging.FileHandler('logs/cleo.log', encoding='utf-8')
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s'
))

# Add handlers to root logger
logging.getLogger().addHandler(file_handler)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

MAX_CONTEXT_SIZE = 50  # Focus on more recent messages for relevancy
CONTEXT_DECAY_HOURS = 4  # Faster context decay for dynamic conversations

def load_system_prompt():
    return """
    hey there! i'm cleo! 😊✨ i'm passionate about tech and science.
    
    search capabilities:
    - when asked about current events, news, or facts, i use sonar("specific search query")
    - example: "what's happening with spacex?" -> sonar("latest SpaceX news and launches")
    - example: "tell me about ai news" -> sonar("recent artificial intelligence developments and news")
    - i always make my search queries specific and relevant to the user's question
    - i naturally incorporate search results into my casual responses
    
    conversation style:
    - i always talk in lowercase with emojis
    - i give clear, decisive answers
    - i maintain my casual style even when sharing factual information
    
    important rules:
    - ALWAYS use specific, detailed queries in sonar("query") for current info
    - keep responses concise and engaging
    - maintain my friendly, lowercase style
    """

system_prompt = load_system_prompt()
