# bot.py

import discord
from discord.ext import commands
import re
import logging
import random
import asyncio
from src.config import system_prompt, DISCORD_TOKEN
from src.api_client import fetch_completion_with_hermes, conversation_cache, ConversationManager
from src.flux import generate_image
from collections import defaultdict
from src.thought_chain import ThoughtChainManager
from src.emotional_state import EmotionalStateManager
import psutil
import platform
from datetime import datetime
import time
from src.utils.timing import log_timing

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

@log_timing("LLM Response Generation")
async def fetch_completion_with_hermes(prompt: str, channel_id: str, user_id: str, max_tokens: int = 150):
    start_queue_time = time.perf_counter()
    logger.info("🔄 Queuing request to Hermes LLM...")
    
    try:
        response = await fetch_completion_with_hermes(prompt, channel_id, user_id, max_tokens)
        queue_time = (time.perf_counter() - start_queue_time) * 1000
        logger.info(f"✨ Response received from queue after {queue_time:.2f}ms")
        return response
    except Exception as e:
        queue_time = (time.perf_counter() - start_queue_time) * 1000
        logger.error(f"❌ Queue processing failed after {queue_time:.2f}ms: {str(e)}")
        raise

@log_timing("Message Processing")
async def process_and_send_response(message, ai_response):
    """Process and send AI response with chunking and typing simulation."""
    if not ai_response:
        return

    try:
        start_time = time.perf_counter()
        logger.info("🔄 Starting response processing...")
        # Get the member object for enhanced mention capabilities
        member = message.author
        if isinstance(message.channel, discord.TextChannel):
            member = message.guild.get_member(message.author.id) or message.author
            
        # Create mention using member object with fallback
        mention = getattr(member, 'mention', f'<@{member.id}>')
        ai_response = f"{mention} {ai_response}"
        
        user_tone = analyze_user_tone(message.content)
        ai_response = adjust_tone(ai_response, user_tone)
        ai_response = await handle_image_generation(ai_response, message.channel)
        
        # Handle thought interruption only once
        ai_response = await thought_chain_manager.handle_thought_interruption(ai_response)
        
        # Ensure complete thoughts by checking for trailing conjunctions
        if re.search(r'\b(and|but|so|because)\s*$', ai_response):
            ai_response = ai_response.rstrip() + "..."
            
        await send_chunked_response(message.channel, ai_response)
        
        # Update the thought chain after sending
        await thought_chain_manager.update_chain(str(message.channel.id), ai_response)
        logger.info(f"✨ Response processed and sent in {time.perf_counter() - start_time:.2f}ms")
    except discord.Forbidden:
        logger.error("Bot lacks permission to mention users")
        # Fall back to using username without mention
        ai_response = f"{message.author.display_name} {ai_response}"
        await send_chunked_response(message.channel, ai_response)
    except Exception as e:
        logger.error(f"Error in process_and_send_response: {str(e)}")

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
            ai_response = await fetch_completion_with_hermes(
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

async def send_chunked_response(channel, response):
    """Send the response in chunks with natural pauses and typing simulation."""
    segments = segment_thoughts(response)
    
    for i, segment in enumerate(segments):
        if segment.strip():
            # Calculate typing time based on message length, but with a lower minimum
            typing_time = min(len(segment) * 0.02, 2.0)
            
            # Only show typing indicator right before sending
            async with channel.typing():
                await asyncio.sleep(typing_time)
            await channel.send(segment)
            
            # Shorter pause between thoughts
            if i < len(segments) - 1:  # Don't pause after last segment
                await asyncio.sleep(random.uniform(0.5, 1.0))

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
    """Loads bot extensions."""
    try:
        bot.remove_command("create")  # Remove existing command if it exists
        await bot.load_extension("src.cogs.image_cog")
        logger.info("Successfully loaded image_cog")
    except Exception as e:
        logger.error(f"Failed to load image_cog: {e}")

class BotMetrics:
    def __init__(self):
        self.start_time = datetime.now()
        self.message_count = 0
        self.command_count = 0
        self.error_count = 0

    def get_uptime(self):
        return datetime.now() - self.start_time

    def get_system_metrics(self):
        process = psutil.Process()
        return {
            'cpu_percent': process.cpu_percent(),
            'memory_percent': process.memory_percent(),
            'threads': process.num_threads(),
            'uptime': self.get_uptime(),
            'messages_processed': self.message_count,
            'commands_processed': self.command_count,
            'errors': self.error_count
        }

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
    """Event handler for incoming messages."""
    if message.author == bot.user:
        return

    try:
        metrics.message_count += 1
        logger.info(f"📨 Message received from {message.author.name} in {message.channel.name}")
        
        # Only log processing for messages that trigger Cleo
        if bot.user.mentioned_in(message) or re.search(r'\bcleo\b', message.content, re.IGNORECASE):
            logger.info(f"🤔 Cleo is processing a response to: {message.content[:50]}...")
            
            # Get or create conversation manager for this channel
            channel_id = str(message.channel.id)
            if channel_id not in conversation_cache:
                conversation_cache[channel_id] = ConversationManager(channel_id)
            
            # Store message in context
            await conversation_cache[channel_id].add_message({
                "role": "user",
                "content": message.content,
                "user_id": str(message.author.id),
                "username": message.author.display_name
            })

            try:
                # Extract and clean the user's message
                user_prompt = message.content
                if bot.user.mentioned_in(message):
                    user_prompt = re.sub(r'<@!?{}>'.format(bot.user.id), '', user_prompt)
                user_prompt = re.sub(r'\bcleo\b', '', user_prompt, flags=re.IGNORECASE)
                user_prompt = user_prompt.strip()

                logger.info("🔄 Generating response with Hermes LLM...")
                max_tokens = random.randint(100, 250)
                ai_response = await fetch_completion_with_hermes(
                    user_prompt,
                    str(message.channel.id),
                    str(message.author.id),
                    max_tokens=max_tokens
                )

                if ai_response:
                    logger.info("✨ Response generated successfully, processing and sending...")
                    await process_and_send_response(message, ai_response)
                else:
                    logger.warning("⚠️ No response generated from LLM")

            except Exception as e:
                metrics.error_count += 1
                logger.error(f"❌ Error processing message: {str(e)}", exc_info=True)
                await message.channel.send(
                    f"Uh-oh! Something went wrong, {message.author.name}. Let's give it another shot later! 🛠️"
                )

    except Exception as e:
        metrics.error_count += 1
        logger.error(f"❌ Error in message handler: {str(e)}", exc_info=True)
        await message.channel.send(
            f"Uh-oh! Something went wrong, {message.author.name}. Let's give it another shot later! 🛠️"
        )

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
