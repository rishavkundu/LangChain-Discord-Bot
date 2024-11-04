# bot.py
import discord
from discord.ext import commands
import re
import logging
import random
from src.config import system_prompt, DISCORD_TOKEN
from src.api_client import fetch_completion_with_hermes
import asyncio
from src.flux import generate_image
from src.user_notes import UserNotesManager
from collections import defaultdict
from src.thought_chain import ThoughtChainManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize UserNotesManager
notes_manager = UserNotesManager()

# Add this near other global variables
message_history = defaultdict(list)

# Initialize at module level
thought_chain_manager = ThoughtChainManager()

async def manage_context(channel_id: str, message: dict, max_history: int = 10):
    """Manage message history for each channel"""
    message_history[channel_id].append(message)
    message_history[channel_id] = message_history[channel_id][-max_history:]
    return message_history[channel_id]

async def process_and_send_response(message, ai_response):
    """Process and send AI response with chunking and typing simulation"""
    if not ai_response:
        await message.channel.send(f"{message.author.mention} oops! my circuits are a bit fuzzy. could you try asking that again? 🤖💫")
        return

    # Check if response appears truncated
    if len(ai_response) >= 1500 and not any(ai_response.endswith(end) for end in ['.', '!', '?', '<end>']):
        # Response might be truncated, send a graceful fallback
        await message.channel.send(f"{message.author.mention} i had so much to say, but let me keep it brief instead! 😅 could you ask me to focus on a specific part?")
        return

    # Extract and save any user notes
    cleaned_response, notes = UserNotesManager.extract_user_notes(ai_response)
    
    # Extract image generation tags
    image_tags = re.findall(r'<generate_image>(.*?)</generate_image>', cleaned_response, re.DOTALL)
    cleaned_response = re.sub(r'<generate_image>.*?</generate_image>', '', cleaned_response, flags=re.DOTALL)
    
    # Process any image generation requests
    for image_prompt in image_tags:
        async with message.channel.typing():
            image_data = await generate_image(image_prompt)
            if image_data:
                await message.channel.send(file=discord.File(image_data, 'generated_image.png'))
            else:
                await message.channel.send("Sorry, I couldn't generate that image 😅")

    for note in notes:
        notes_manager.add_note(str(message.author.id), note)

    # Split response into chunks
    chunks = []
    current_chunk = ""
    sentences = re.split(r'(?<=[.!?])\s+', cleaned_response)
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < 1500:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    
    if current_chunk:
        chunks.append(current_chunk.strip())

    # Send chunks with typing simulation
    for chunk in chunks:
        if chunk.strip():
            # Simulate human-like typing patterns
            typing_multiplier = 0.05
            if any(trigger in cleaned_response.lower() for trigger in ['!', 'WAIT', 'OMG']):
                typing_multiplier = 0.03  # Type faster when excited
            elif '...' in cleaned_response:
                typing_multiplier = 0.07  # Type slower when thoughtful

            typing_time = min(len(chunk) * typing_multiplier, 5.0)
            async with message.channel.typing():
                await asyncio.sleep(typing_time)
            await message.channel.send(chunk)
            if len(chunks) > 1:
                await asyncio.sleep(random.uniform(0.5, 1.5))

    # Maybe start a thought chain
    if await thought_chain_manager.maybe_start_chain(str(message.channel.id), message.content, cleaned_response):
        try:
            for _ in range(random.randint(1, 2)):  # 1-2 follow-up thoughts
                # Wait for a natural pause
                await asyncio.sleep(random.uniform(20, 30))
                
                # Get follow-up prompt
                follow_up_prompt = await thought_chain_manager.get_follow_up_prompt(str(message.channel.id))
                if not follow_up_prompt:
                    logger.warning("Failed to generate follow-up prompt")
                    break
                
                # Get follow-up response
                follow_up_response = await fetch_completion_with_hermes(
                    follow_up_prompt,
                    str(message.channel.id),
                    str(message.author.id),
                    max_tokens=150  # Shorter follow-up responses
                )
                
                if not follow_up_response:
                    logger.warning("Failed to generate follow-up response")
                    break
                
                # Show typing indicator before follow-up
                async with message.channel.typing():
                    await asyncio.sleep(random.uniform(2, 4))
                
                # Process and send the follow-up response
                cleaned_follow_up, _ = UserNotesManager.extract_user_notes(follow_up_response)
                await send_chunked_response(message.channel, cleaned_follow_up)
                
                # Update the chain with the new response
                await thought_chain_manager.update_chain(
                    str(message.channel.id),
                    cleaned_follow_up
                )
                
        except Exception as e:
            logger.error(f"Error in thought chain processing: {str(e)}", exc_info=True)

    # Calculate base typing delay
    base_delay = random.uniform(1.5, 3.0)
    
    # Add thinking time for complex/poetic messages
    if any(trigger in message.content.lower() for trigger in 
           ['universe', 'dimension', 'ethereal', 'cosmic']):
        await asyncio.sleep(random.uniform(2.0, 4.0))
    
    # Occasionally show "thinking" indicator before responding
    if random.random() < 0.3:
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(1.0, 2.0))
            await message.channel.send("*thinking...*")
            await asyncio.sleep(1.0)

async def send_chunked_response(channel, response):
    chunks = []
    current_chunk = ""
    sentences = re.split(r'(?<=[.!?])\s+', response)
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < 1500:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    
    if current_chunk:
        chunks.append(current_chunk.strip())

    for chunk in chunks:
        if chunk.strip():
            typing_time = min(len(chunk) * 0.05, 5.0)
            async with channel.typing():
                await asyncio.sleep(typing_time)
            await channel.send(chunk)
            if len(chunks) > 1:
                await asyncio.sleep(random.uniform(0.5, 1.5))

@bot.event
async def on_ready():
    logger.info(f'Connected as {bot.user}')
    print(f"Connected as {bot.user}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    logger.info(f"Message received from {message.author.name}: {message.content}")
    
    # Store all messages for context, regardless of mention
    await manage_context(str(message.channel.id), {
        "role": "user",
        "content": f"{message.author.name}: {message.content}"
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
                    ai_response = f"{message.author.mention} {ai_response}"
                
                await process_and_send_response(message, ai_response)

        except Exception as e:
            logger.error(f"Error in on_message: {str(e)}", exc_info=True)
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error traceback:", exc_info=True)
            await message.channel.send(f"uh-oh! something went wrong, {message.author.name}. let's give it another shot later! 🛠️")

    await bot.process_commands(message)

@bot.command()
@commands.is_owner()
async def shutdown(ctx):
    await ctx.send("shutting down... catch you on the flip side! 👋")
    await bot.close()

def run_bot():
    """Function to run the bot with the token"""
    bot.run(DISCORD_TOKEN)