# bot.py

import discord
from discord.ext import commands
import re
import logging
from config import system_prompt, DISCORD_TOKEN
from api_client import fetch_completion_with_hermes

# Initialize bot with all necessary intents
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    """
    Event handler that runs when the bot successfully connects to Discord.
    """
    logging.info(f'Connected as {bot.user}')
    print(f"Connected as {bot.user}")

@bot.event
async def on_message(message):
    """
    Event handler for processing incoming messages.
    
    This function handles bot mentions, messages containing the bot's name,
    commands starting with '!', and passes other messages to the command processor.
    """
    if message.author == bot.user:
        return  # Skip messages sent by the bot itself

    logging.info(f"Message received: {message.content}")
    print(f"Message received: {message.content}")

    # Check if the bot is mentioned or if "Cleo" is in the message (case-insensitive)
    if bot.user.mentioned_in(message) or re.search(r'\bcleo\b', message.content, re.IGNORECASE):
        # Remove the bot mention and "Cleo" from the message
        user_prompt = re.sub(r'<@!?{}>'.format(bot.user.id), '', message.content)
        user_prompt = re.sub(r'\bcleo\b', '', user_prompt, flags=re.IGNORECASE)
        user_prompt = user_prompt.strip()

        # If the message is not empty after removing mentions and "Cleo"
        if user_prompt:
            ai_response = await fetch_completion_with_hermes(user_prompt)
            await message.channel.send(ai_response)
        else:
            # If the message is empty, provide a default response
            await message.channel.send("Hello! How can I assist you today?")
        return

    if message.content.startswith("!"):
        user_prompt = message.content[1:]  # Strip the '!' prefix
        ai_response = await fetch_completion_with_hermes(user_prompt)
        await message.channel.send(ai_response)

    await bot.process_commands(message)

@bot.command()
@commands.is_owner()
async def shutdown(ctx):
    """
    Command to shut down the bot. Can only be used by the bot owner.
    
    Usage: !shutdown
    """
    await ctx.send("Shutting down...")
    await ctx.bot.close()

