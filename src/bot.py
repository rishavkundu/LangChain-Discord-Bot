# bot.py

import discord
from discord.ext import commands
import re
import logging
import random
import asyncio
from src.config import system_prompt, DISCORD_TOKEN
from src.api_client import (
    fetch_completion_with_hermes as api_fetch_completion, 
    conversation_cache, 
    ConversationManager,
    cache_lock
)
from src.flux import generate_image
from collections import defaultdict
from src.thought_chain import ThoughtChainManager
from src.emotional_state import EmotionalStateManager
import psutil
import platform
from datetime import datetime
import time
from src.utils.timing import log_timing
from src.utils.metrics import BotMetrics

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot setup with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # Enable member cache
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize managers
thought_chain_manager = ThoughtChainManager()
emotional_state_manager = EmotionalStateManager()

# Initialize database
async def setup_database():
    """Initialize the database for all conversation managers"""
    # Create default conversation manager for initialization
    default_manager = ConversationManager("setup")
    await default_manager.initialize()
    logger.info("Database initialized successfully")

def analyze_user_tone(message_content: str) -> str:
    """Analyzes the user's tone based on message content."""
    if any(word in message_content.lower() for word in ['?', 'how', 'why', 'what']):
        return 'inquisitive'
    elif any(word in message_content.lower() for word in ['!', 'amazing', 'fantastic', 'love']):
        return 'enthusiastic'
    elif any(word in message_content.lower() for word in [':(', 'sad', 'unfortunately']):
        return 'sympathetic'
    else:
        return 'neutral'

def adjust_tone(ai_response: str, user_tone: str) -> str:
    """Adjusts Cleo's response tone based on user's tone."""
    # Limit the number of interjections and emojis
    ai_response = re.sub(r'(You know,?|Haha,?|Well,?)', '', ai_response)
    emoji_count = len(re.findall(r'[^\w\s,]', ai_response))
    if emoji_count > 2:
        ai_response = re.sub(r'[^\w\s,]', '', ai_response)
    return ai_response.strip()

@log_timing("Hermes LLM Response")
async def process_llm_response(prompt: str, channel_id: str, user_id: str, max_tokens: int = 500):
    """Process and time LLM response."""
    try:
        logger.info("🔄 Queuing request to Hermes LLM...")
        response = await api_fetch_completion(prompt, channel_id, user_id, max_tokens)
        
        if not response:
            logger.error("Empty response from LLM")
            return "I'm thinking about how to respond to that..."
            
        # Clean up any stop sequences
        response = response.replace("<|end|>", "").strip()
        
        logger.info("✨ LLM response received successfully")
        return response
        
    except Exception as e:
        logger.error(f"Error in LLM processing: {str(e)}")
        return "I encountered an error processing that. Let me try again."

@log_timing("Message Processing")
async def process_and_send_response(message, ai_response):
    """Process and send AI response with chunking and typing simulation."""
    if not ai_response:
        return

    try:
        start_time = time.perf_counter()
        logger.info("🔄 Starting response processing...")
        
        # Clean up any existing mention format
        ai_response = re.sub(r'<@!?\d+>', '', ai_response)
        
        # Process the response
        user_tone = analyze_user_tone(message.content)
        ai_response = adjust_tone(ai_response, user_tone)
        ai_response = await handle_image_generation(ai_response, message.channel)
        
        # Use the new chunking method
        await chunk_and_send_messages(message, ai_response)
        
        logger.info(f"✨ Response processed and sent in {time.perf_counter() - start_time:.2f}ms")
        
        # Update conversation context
        await conversation_cache[str(message.channel.id)].add_message({
            "role": "assistant",
            "content": ai_response,
            "user_id": None
        })
        
    except Exception as e:
        logger.error(f"Error in process_and_send_response: {str(e)}", exc_info=True)

async def handle_image_generation(ai_response: str, channel):
    """Extract and handle image generation tags."""
    image_matches = re.finditer(r'<generate_image>(.*?)</generate_image>', ai_response)
    ai_response = re.sub(r'<generate_image>.*?</generate_image>', '', ai_response)

    for match in image_matches:
        prompt = match.group(1)
        async with channel.typing():
            image_data = await generate_image(prompt)
            if image_data:
                file = discord.File(fp=image_data, filename="generated_image.png")
                await channel.send(file=file)
            else:
                await channel.send("Oops! Something went wrong generating that image 😅")
    return ai_response

async def handle_thought_chain(message):
    """Handle the thought chain logic."""
    try:
        for _ in range(random.randint(1, 2)):  # 1-2 follow-up thoughts
            await asyncio.sleep(random.uniform(20, 30))

            follow_up_prompt = await thought_chain_manager.get_follow_up_prompt(str(message.channel.id))
            if not follow_up_prompt:
                logger.warning("Failed to generate follow-up prompt")
                break

            # Use metaprompting for follow-up thoughts
            ai_response = await process_llm_response(
                follow_up_prompt,
                str(message.channel.id),
                str(message.author.id),
                max_tokens=150
            )

            if not ai_response:
                logger.warning("Failed to generate follow-up response")
                break

            # Add Cleo's response to the context
            await conversation_cache[str(message.channel.id)].add_message({
                "role": "assistant",
                "content": ai_response,
                "user_id": None  # Assistant messages don't have user_id
            })

            # Process and send the response
            await process_and_send_response(message, ai_response)

            # Update the thought chain
            await thought_chain_manager.update_chain(str(message.channel.id), ai_response)

    except Exception as e:
        logger.error(f"Error in thought chain processing: {str(e)}", exc_info=True)

async def send_chunked_response(channel, response: str):
    """Send response in natural chunks/paragraphs."""
    # Split on double newlines or sentence endings followed by space
    chunks = re.split(r'\n\n|\. (?=[A-Z])', response)
    chunks = [chunk.strip() + ('.' if not chunk.endswith(('.', '!', '?')) else '') 
             for chunk in chunks if chunk.strip()]

    for chunk in chunks:
        if chunk:
            async with channel.typing():
                await asyncio.sleep(len(chunk) * 0.05)  # Natural typing delay
                await channel.send(chunk)
                await asyncio.sleep(0.5)  # Brief pause between messages

def segment_thoughts(response):
    """Segment response into appropriate message chunks."""
    # Split on thought boundaries (multiple newlines or clear thought transitions)
    thought_breaks = re.split(r'\n\s*\n|\.\s+(?=[A-Z])|(?<=[.!?])\s+(?=\w)', response)
    
    # Clean and filter chunks
    chunks = []
    for thought in thought_breaks:
        thought = thought.strip()
        if thought:
            # Split long thoughts if needed
            if len(thought) > 300:
                sentences = re.split(r'(?<=[.!?])\s+', thought)
                current_chunk = ''
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) + 1 <= 300:
                        current_chunk += (' ' if current_chunk else '') + sentence
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = sentence
                if current_chunk:
                    chunks.append(current_chunk.strip())
            else:
                chunks.append(thought)
    
    return chunks  # Remove the [:3] limit to allow natural thought flow


# Load extensions if any
async def load_extensions():
    """Load all cogs with proper error handling."""
    try:
        # Remove image_cog from loading list
        extensions = []  # Add any other cogs here if needed
        
        for extension in extensions:
            try:
                await bot.load_extension(extension)
                logger.info(f"✅ Loaded {extension}")
            except Exception as e:
                logger.error(f"Failed to load {extension}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error loading extensions: {str(e)}")

# Initialize metrics
metrics = BotMetrics()

@bot.event
async def on_ready():
    """Called when the bot is ready and connected"""
    logger.info("=== Cleo Bot Initialization ===")
    logger.info(f"Bot User: {bot.user}")
    logger.info(f"Bot ID: {bot.user.id}")
    logger.info(f"Discord.py Version: {discord.__version__}")
    logger.info(f"Python Version: {platform.python_version()}")
    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info("=== Initialization Complete ===")
    
    await setup_database()
    await load_extensions()
    await bot.tree.sync()

    # Start metrics logging
    bot.loop.create_task(log_metrics())

async def log_metrics():
    """Periodically log system metrics"""
    while True:
        try:
            metrics_data = metrics.get_system_metrics()
            logger.info("=== System Metrics ===")
            logger.info(f"Uptime: {metrics_data['uptime']}")
            logger.info(f"CPU Usage: {metrics_data['cpu_percent']}%")
            logger.info(f"Memory Usage: {metrics_data['memory_percent']}%")
            logger.info(f"Active Threads: {metrics_data['threads']}")
            logger.info(f"Messages Processed: {metrics_data['messages_processed']}")
            logger.info(f"Commands Processed: {metrics_data['commands_processed']}")
            logger.info(f"Error Count: {metrics_data['errors']}")
            logger.info("===================")
            
            await asyncio.sleep(300)  # Log every 5 minutes
        except Exception as e:
            logger.error(f"Error in metrics logging: {e}")
            await asyncio.sleep(60)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    try:
        if not should_respond_to_message(message):
            return
            
        channel_id = str(message.channel.id)
        
        # Initialize conversation cache if it doesn't exist
        async with cache_lock:  # Import cache_lock from api_client
            if channel_id not in conversation_cache:
                conversation_cache[channel_id] = await ConversationManager.create(channel_id)
        
        # Save user message to context
        await conversation_cache[channel_id].add_message({
            "role": "user",
            "content": process_message_content(message.content),
            "user_id": str(message.author.id),
            "timestamp": datetime.now().isoformat()
        })
        
        # Show typing indicator
        async with message.channel.typing():
            user_prompt = process_message_content(message.content)
            logger.info(f"🤔 Cleo is processing a response to: {user_prompt[:50]}...")
            
            # Generate response
            ai_response = await process_llm_response(
                user_prompt,
                str(message.channel.id),
                str(message.author.id)
            )
            
            if ai_response:
                # Process and send response with chunking
                await process_and_send_response(message, ai_response)
                logger.info("✨ Message sent successfully")

    except Exception as e:
        logger.error(f"Error in message processing: {str(e)}", exc_info=True)
        try:
            await message.channel.send("I encountered an error. Please try again.")
        except:
            pass

    await bot.process_commands(message)

@bot.command()
@commands.is_owner()
async def shutdown(ctx):
    """Shuts down the bot."""
    await ctx.send("Shutting down... Catch you on the flip side! 👋")
    await bot.close()

async def init_bot():
    """Initializes and starts the bot."""
    async with bot:
        await bot.start(DISCORD_TOKEN)

def run_bot():
    """Function to run the bot with the token."""
    asyncio.run(init_bot())

def should_respond_to_message(message: discord.Message) -> bool:
    """Determine if the bot should respond to this message."""
    # Don't respond to our own messages
    if message.author == bot.user:
        return False
        
    # Don't respond to other bots
    if message.author.bot:
        return False
        
    # Check if message mentions the bot
    if bot.user.mentioned_in(message):
        return True
        
    # Check if message is a direct message
    if isinstance(message.channel, discord.DMChannel):
        return True
        
    # Check if message starts with bot's name (case insensitive)
    if message.content.lower().startswith('cleo'):
        return True
        
    return False

def process_message_content(content: str) -> str:
    """Process and clean message content for LLM consumption."""
    # Remove bot mention
    content = re.sub(r'<@!?\d+>', '', content).strip()
    
    # Remove extra whitespace
    content = ' '.join(content.split())
    
    # Remove 'cleo' from start of message (case insensitive)
    content = re.sub(r'^cleo\s*', '', content, flags=re.IGNORECASE)
    
    return content.strip()

async def chunk_and_send_messages(message, content: str):
    """Unified message chunking and sending logic."""
    try:
        content = content.strip()
        if not content:
            return

        # Remove any stop sequences that might have leaked through
        content = content.replace("<|end|>", "").strip()
        
        # Split into semantic chunks using multiple delimiters
        chunk_delimiters = [
            r'\n\n+',                    # Multiple newlines
            r'(?<=[.!?])\s+(?=[A-Z])',   # Sentence boundaries
            r'(?<=\w)\s*[.!?]+\s+',      # Punctuation with space
            r'\s*[.!?]+\s*$'             # End of text
        ]
        
        split_pattern = f'({"|".join(chunk_delimiters)})'
        raw_chunks = re.split(split_pattern, content)
        
        # Combine chunks while respecting Discord's limit
        chunks = []
        current_chunk = ""
        
        for chunk in raw_chunks:
            if not chunk.strip():
                continue
                
            if len(current_chunk) + len(chunk) + 2 <= 1900:
                current_chunk += chunk
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = chunk
                
        if current_chunk:
            chunks.append(current_chunk.strip())

        # Send chunks with proper formatting and timing
        first_chunk = True
        for chunk in chunks:
            if not chunk.strip():
                continue
                
            async with message.channel.typing():
                if first_chunk:
                    chunk = f"{message.author.mention} {chunk}"
                    first_chunk = False
                
                # Natural typing simulation
                typing_delay = min(len(chunk) * 0.01, 1.5)  # Reduced max delay
                await asyncio.sleep(typing_delay)
                
                await message.channel.send(chunk)
                await asyncio.sleep(0.3)  # Reduced pause between messages

    except Exception as e:
        logger.error(f"Error in chunk_and_send_messages: {str(e)}")
