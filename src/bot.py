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
        return

    # Extract image generation tags first
    image_matches = re.finditer(r'<generate_image>(.*?)</generate_image>', ai_response)
    
    # Remove the tags from the response text
    cleaned_response = re.sub(r'<generate_image>.*?</generate_image>', '', ai_response)
    
    # Process and send the text response first
    thought_segments = []
    current_segment = ""
    
    # More intelligent thought segmentation
    breakpoints = ['. ', '! ', '? ', '... ', '…']
    continuation_markers = ['but', 'and', 'so', 'because', 'which', 'while']

    for char in cleaned_response:
        current_segment += char
        buffer = ""
        
        # Check for natural breakpoints
        for bp in breakpoints:
            if current_segment.endswith(bp):
                # Don't break if next word is a continuation
                next_word = cleaned_response[len(current_segment):].lstrip().split(' ')[0].lower()
                if next_word not in continuation_markers:
                    cleaned = current_segment.strip()
                    if len(cleaned) > 3 and not all(c in '.!?…' for c in cleaned):
                        thought_segments.append(cleaned)
                    current_segment = ""
                buffer = ""
                break

    # Add remaining text if meaningful
    if current_segment.strip() and len(current_segment.strip()) > 3:
        thought_segments.append(current_segment.strip())

    # Group related thoughts
    i = 0
    while i < len(thought_segments):
        current_group = [thought_segments[i]]
        while (i + 1 < len(thought_segments) and 
               should_group_thoughts(current_group[-1], thought_segments[i + 1])):
            current_group.append(thought_segments[i + 1])
            i += 1
        
        # Send grouped thoughts together
        grouped_message = ' '.join(current_group)
        typing_time = min(len(grouped_message) * random.uniform(0.02, 0.08), 4.0)
        
        async with message.channel.typing():
            await asyncio.sleep(typing_time)
        await message.channel.send(grouped_message)
        
        # Add natural pause between thought groups
        await asyncio.sleep(random.uniform(1.0, 2.5))
        i += 1

    # Extract and save any user notes
    cleaned_response, notes = UserNotesManager.extract_user_notes(ai_response)
    
    # Handle any image generations
    for match in image_matches:
        prompt = match.group(1)
        async with message.channel.typing():
            image_data = await generate_image(prompt)
            if image_data:
                # Create Discord file object from bytes
                file = discord.File(fp=image_data, filename="generated_image.png")
                await message.channel.send(file=file)
            else:
                await message.channel.send("oops! something went wrong generating that image 😅")

    for note in notes:
        notes_manager.add_note(str(message.author.id), note)

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
    
    # Split into sentences more reliably
    current_sentence = ""
    for char in response:
        current_sentence += char
        current_chunk += char
        
        # Check for sentence endings
        if char in '.!?' and not current_sentence.strip().endswith('...'):
            cleaned_chunk = current_chunk.strip()
            if len(cleaned_chunk) >= 4 and not all(c in '.!?…' for c in cleaned_chunk):
                if len(cleaned_chunk) >= 1500:
                    chunks.append(cleaned_chunk)
                    current_chunk = ""
            current_sentence = ""
    
    # Add remaining text if meaningful
    if current_chunk.strip() and len(current_chunk.strip()) > 3:
        chunks.append(current_chunk.strip())

    for chunk in chunks:
        if chunk.strip():
            typing_time = min(len(chunk) * 0.05, 5.0)
            async with channel.typing():
                await asyncio.sleep(typing_time)
            await channel.send(chunk)
            if len(chunks) > 1:
                await asyncio.sleep(random.uniform(0.5, 1.5))

def clean_response(response: str) -> str:
    # Remove irregular spacing patterns, but preserve intentional caps
    cleaned = re.sub(r'\s+', ' ', response)
    
    # Fix punctuation spacing only
    cleaned = re.sub(r'\s*([,.!?])\s*', r'\1 ', cleaned)
    
    return cleaned.strip()

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

def should_group_thoughts(prev_segment: str, next_segment: str) -> bool:
    # Check if thoughts are closely related
    related_markers = [
        (prev_segment.endswith('...') and not next_segment.startswith('...')),
        any(next_segment.lower().startswith(w) for w in ['and', 'but', 'so', 'because']),
        len(prev_segment) < 30 and not any(prev_segment.endswith(p) for p in ['!', '?']),
        bool(set(prev_segment.split()) & set(next_segment.split())) # shared words
    ]
    return sum(related_markers) >= 2