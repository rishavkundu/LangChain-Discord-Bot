# api_client.py

import aiohttp
import logging
import json
from config import OPENAI_API_KEY, system_prompt

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
