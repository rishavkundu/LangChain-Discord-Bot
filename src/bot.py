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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
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


async def process_and_send_response(message, ai_response):
    """Process and send AI response with chunking and typing simulation."""
    if not ai_response:
        return

    # Analyze user's tone
    user_tone = analyze_user_tone(message.content)
    # Adjust Cleo's response tone
    ai_response = adjust_tone(ai_response, user_tone)

    # Handle any image generations
    ai_response = await handle_image_generation(ai_response, message.channel)

    # Incorporate self-interruptions and self-corrections
    ai_response = await thought_chain_manager.handle_thought_interruption(ai_response)

    # Segment and send the response
    await send_chunked_response(message.channel, ai_response)

    # Maybe start a thought chain
    if await thought_chain_manager.maybe_start_chain(str(message.channel.id), message.content, ai_response):
        await handle_thought_chain(message)

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

            # Extract and process the response
            await send_chunked_response(message.channel, ai_response)
            await thought_chain_manager.update_chain(str(message.channel.id), ai_response)

    except Exception as e:
        logger.error(f"Error in thought chain processing: {str(e)}", exc_info=True)

async def send_chunked_response(channel, response):
    """Send the response in chunks with natural pauses and typing simulation."""
    segments = segment_thoughts(response)

    for segment in segments:
        if segment.strip():
            typing_time = min(len(segment) * random.uniform(0.03, 0.06), 5.0)
            async with channel.typing():
                await asyncio.sleep(typing_time)
            await channel.send(segment)
            await asyncio.sleep(random.uniform(0.5, 1.5))

def segment_thoughts(response):
    """Segment response into appropriate message chunks."""
    # Split on sentence boundaries
    sentence_endings = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_endings.split(response)

    # Combine sentences into paragraphs
    max_chunk_length = 300  # Adjust as needed
    chunks = []
    current_chunk = ''
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_chunk_length:
            current_chunk += (' ' if current_chunk else '') + sentence
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks[:3]  # Limit to 3 messages max


# Load extensions if any
async def load_extensions():
    """Loads bot extensions."""
    try:
        bot.remove_command("create")  # Remove existing command if it exists
        await bot.load_extension("src.cogs.image_cog")
        logger.info("Successfully loaded image_cog")
    except Exception as e:
        logger.error(f"Failed to load image_cog: {e}")

@bot.event
async def on_ready():
    """Called when the bot is ready and connected"""
    await setup_database()
    logger.info(f'Connected as {bot.user}')
    print(f"Connected as {bot.user}")
    try:
        await load_extensions()
        await bot.tree.sync()
        logger.info("Successfully synced application commands")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message):
    """Event handler for incoming messages."""
    if message.author == bot.user:
        return

    logger.info(f"Message received from {message.author.name}: {message.content}")

    # Get or create conversation manager for this channel
    channel_id = str(message.channel.id)
    if channel_id not in conversation_cache:
        conversation_cache[channel_id] = ConversationManager(channel_id)
    
    # Store message in context
    await conversation_cache[channel_id].add_message({
        "role": "user",
        "content": f"{message.author.name}: {message.content}",
        "user_id": str(message.author.id)
    })

    # Only respond to mentions or when "cleo" is in the message
    if bot.user.mentioned_in(message) or re.search(r'\bcleo\b', message.content, re.IGNORECASE):
        user_prompt = re.sub(r'<@!?{}>'.format(bot.user.id), '', message.content)
        user_prompt = re.sub(r'\bcleo\b', '', user_prompt, flags=re.IGNORECASE)
        user_prompt = user_prompt.strip()

        try:
            async with message.channel.typing():
                max_tokens = random.randint(100, 250)
                ai_response = await fetch_completion_with_hermes(
                    user_prompt,
                    str(message.channel.id),
                    str(message.author.id),
                    max_tokens=max_tokens
                )

                if ai_response:
                    # Use proper Discord mention format with user ID
                    ai_response = f"<@{message.author.id}> {ai_response}"

                # Update emotional state
                await emotional_state_manager.analyze_message(
                    message.content, 
                    str(message.author.id), 
                    conversation_cache[str(message.channel.id)]
                )

                await process_and_send_response(message, ai_response)

        except Exception as e:
            logger.error(f"Error in on_message: {str(e)}", exc_info=True)
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
