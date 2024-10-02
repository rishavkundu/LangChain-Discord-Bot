import discord
from discord.ext import commands
import os
import aiohttp
from dotenv import load_dotenv
import logging
import json
import re

# Load environment variables from .env file
load_dotenv()

# Retrieve sensitive information from environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize bot with all necessary intents
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
bot = commands.Bot(command_prefix="!", intents=intents)

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

async def fetch_completion_with_hermes(user_prompt):
    """
    Fetch a completion from the OpenRouter API using the Hermes model.
    
    Args:
        user_prompt (str): The user's input prompt.
    
    Returns:
        str: The AI model's response or an error message.
    """
    try:
        api_url = "https://openrouter.ai/api/v1/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        full_prompt = f"{system_prompt}\n\n{user_prompt}\n"
        data = {
            "model": "nousresearch/hermes-3-llama-3.1-405b:free",
            "prompt": full_prompt,
            "max_tokens": 150,
            "temperature": 0.6,
            "top_p": 1,
            "stop": ["\nHuman:", "\n\nHuman:", "Assistant:"]  # Add stop sequences
        }

        logging.info(f"Sending request to OpenRouter: {json.dumps(data, indent=2)}")

        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=data) as response:
                logging.info(f"Received response status: {response.status}")
                if response.status == 200:
                    result = await response.json()
                    logging.info(f"API Response: {json.dumps(result, indent=2)}")
                    return result['choices'][0]['text'].strip()
                else:
                    error_text = await response.text()
                    logging.error(f"API Error {response.status}: {error_text}")
                    return f"API Error: {response.status}"
    except Exception as e:
        logging.error(f"Exception in API call: {str(e)}")
        return f"Error: {str(e)}"

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

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)