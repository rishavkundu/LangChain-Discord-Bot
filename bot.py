# bot.py
import discord
from discord.ext import commands
import re
import logging
import random
from config import system_prompt, DISCORD_TOKEN
from api_client import fetch_completion_with_hermes
import asyncio
from user_notes import UserNotesManager

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

async def process_and_send_response(message, ai_response):
    """Process and send AI response with chunking and typing simulation"""
    if not ai_response:
        await message.channel.send(f"{message.author.mention} oops! my circuits are a bit fuzzy. could you try asking that again? 🤖💫")
        return

    # Extract and save any user notes
    cleaned_response, notes = UserNotesManager.extract_user_notes(ai_response)
    
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
            typing_time = min(len(chunk) * 0.05, 5.0)  # Cap at 5 seconds
            async with message.channel.typing():
                await asyncio.sleep(typing_time)
            await message.channel.send(chunk)
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

    if bot.user.mentioned_in(message) or re.search(r'\bcleo\b', message.content, re.IGNORECASE):
        user_prompt = re.sub(r'<@!?{}>'.format(bot.user.id), '', message.content)
        user_prompt = re.sub(r'\bcleo\b', '', user_prompt, flags=re.IGNORECASE)
        user_prompt = user_prompt.strip()

        user_prompt = f"{message.author.name}: {user_prompt}"

        try:
            async with message.channel.typing():
                max_tokens = random.randint(100, 250)
                ai_response = await fetch_completion_with_hermes(
                    user_prompt, 
                    str(message.channel.id),
                    str(message.author.id),  # Add user ID
                    max_tokens=max_tokens
                )
                
                if ai_response:
                    ai_response = f"{message.author.mention} {ai_response}"
                
                await process_and_send_response(message, ai_response)

        except Exception as e:
            logger.error(f"Error in on_message: {str(e)}")
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