# flux.py

import aiohttp
import io
import json
import base64
import logging

async def generate_image(prompt):
    url = "https://api.hyperbolic.xyz/v1/image/generation"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJyaXNoYXZrdW5kdUBnbWFpbC5jb20ifQ.R0S-YeFaORhiibbHjyPZFgce_2iFqe00rP1a8aI-MWY"
    }
    data = {
        "model_name": "FLUX.1-dev",
        "prompt": prompt,
        "height": 1024,
        "width": 1024,
        "steps": 50,
        "backend": "auto"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                logging.info(f"Image generation API response status: {response.status}")
                if response.status == 200:
                    response_json = await response.json()
                    logging.info(f"Image generation API response: {json.dumps(response_json, indent=2)}")
                    if 'images' in response_json and len(response_json['images']) > 0:
                        image_base64 = response_json['images'][0]['image']
                        image_data = base64.b64decode(image_base64)
                        return io.BytesIO(image_data)
                    else:
                        logging.warning("No images in the response JSON")
                else:
                    logging.error(f"Unexpected status code: {response.status}")
    except Exception as e:
        logging.error(f"Error in generate_image: {str(e)}")
    
    logging.error("Failed to generate image")
    return None