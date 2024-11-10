import discord
from discord import app_commands
from discord.ext import commands
import logging
from src.flux import generate_image

logger = logging.getLogger(__name__)

class ImageCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if "create" not in self.bot.tree.get_commands():
            self.bot.tree.add_command(self.create)

    @app_commands.command(name="create", description="Generate an image based on your prompt")
    async def create(self, interaction: discord.Interaction, prompt: str):
        """Generate an image using the provided prompt"""
        try:
            await interaction.response.defer()
            
            async with interaction.channel.typing():
                image_data = await generate_image(prompt)
                
                if image_data:
                    with open(image_data, 'rb') as fp:
                        file = discord.File(fp=fp, filename="generated_image.png")
                        await interaction.followup.send(file=file)
                else:
                    await interaction.followup.send("Oops! Something went wrong generating that image 😅")
                    
        except Exception as e:
            logger.error(f"Error in create command: {str(e)}", exc_info=True)
            await interaction.followup.send("An unexpected error occurred. Please try again later.")

async def setup(bot):
    await bot.add_cog(ImageCog(bot)) 