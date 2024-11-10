# prompt_templates.py

METAPROMPT_TEMPLATES = [
    """
Reflect on your last message: "{cleo_last_response}"

Provide additional insights or explore new angles on the topic without repeating previous points. Aim for depth and originality in your response.

Share your thought process and craft a response that is both coherent and captivating.
""",
    """
Consider your previous reply: "{cleo_last_response}"

How can you expand upon this in a way that showcases your unique perspective? Think carefully about the connections you can make and present them thoughtfully to the user.

Let your response flow naturally from your reasoning.
""",
    # Additional templates can be added here
]

REPROMPT_TEMPLATES = [
    """
Your previous thought was: "{last_response}"

Take a moment to delve deeper into this idea. What further insights can you offer? How does this relate to broader concepts or personal experiences?

Compose a response that continues the conversation meaningfully.
""",
    """
Building upon what you just shared, explore any interesting implications or questions that arise.

Provide a thoughtful continuation that encourages the user to engage further.
""",
    # Additional templates can be added here
]
