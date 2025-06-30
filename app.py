import discord
from discord.ext import commands
import asyncio
import os
import logging
from flask import Flask, request, jsonify
import threading
import time
import re
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Flask app for HTTP API
app = Flask(__name__)

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variables
tasks = {}
bot_ready = False
MIDJOURNEY_BOT_ID = 936929561302675456  # Official Midjourney bot ID

class MidjourneyTask:
    def __init__(self, task_id, prompt):
        self.task_id = task_id
        self.prompt = prompt
        self.status = "submitted"
        self.image_urls = []
        self.created_at = datetime.now()
        self.timeout = 900  # 15 minutes timeout

    def is_expired(self):
        return datetime.now() - self.created_at > timedelta(seconds=self.timeout)

@bot.event
async def on_ready():
    global bot_ready
    bot_ready = True
    logger.info(f'{bot.user} has connected to Discord!')
    
    # List servers the bot is in
    logger.info("Bot is in the following servers:")
    for guild in bot.guilds:
        logger.info(f"- {guild.name} (ID: {guild.id})")

@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Check if message is from Midjourney bot
    if message.author.id == MIDJOURNEY_BOT_ID:
        await handle_midjourney_response(message)
    
    await bot.process_commands(message)

async def handle_midjourney_response(message):
    """Handle responses from Midjourney bot"""
    try:
        # Look for completed images in message attachments
        if message.attachments:
            logger.info(f"Received Midjourney response with {len(message.attachments)} attachments")
            
            # Extract potential task info from message content
            # Midjourney often includes the original prompt in the response
            content = message.content.lower()
            
            # Find matching task by checking if prompt keywords match
            matching_task = None
            for task_id, task in tasks.items():
                if task.status == "processing":
                    # Check if key words from the task prompt appear in the message
                    task_words = set(task.prompt.lower().split())
                    content_words = set(content.split())
                    
                    # If at least 2 words match, consider it a match
                    if len(task_words.intersection(content_words)) >= 2:
                        matching_task = task
                        break
            
            if matching_task:
                # Extract image URLs
                image_urls = [attachment.url for attachment in message.attachments 
                             if attachment.url.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
                
                if image_urls:
                    matching_task.image_urls = image_urls
                    matching_task.status = "completed"
                    logger.info(f"Task {matching_task.task_id} completed with {len(image_urls)} images")
                else:
                    logger.warning("No valid image URLs found in Midjourney response")
            else:
                logger.info("Received Midjourney response but couldn't match to any pending task")
    
    except Exception as e:
        logger.error(f"Error handling Midjourney response: {e}")

async def send_midjourney_command(channel_id, prompt, task_id):
    """Send slash command to Midjourney"""
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel:
            logger.error(f"Channel {channel_id} not found")
            return False
        
        logger.info(f"Sending Midjourney command in channel: {channel.name}")
        
        # Method 1: Try to use application command (slash command)
        try:
            # Look for Midjourney bot in the guild
            guild = channel.guild
            midjourney_member = guild.get_member(MIDJOURNEY_BOT_ID)
            
            if midjourney_member:
                logger.info("Found Midjourney bot in server")
                
                # Send the /imagine command
                # Note: This requires the bot to have permission to use application commands
                await channel.send(f"/imagine prompt: {prompt}")
                
                # Update task status
                if task_id in tasks:
                    tasks[task_id].status = "processing"
                
                logger.info(f"Sent /imagine command: {prompt[:50]}...")
                return True
            else:
                logger.error("Midjourney bot not found in the server")
                return False
                
        except Exception as e:
            logger.error(f"Failed to send slash command: {e}")
            
            # Method 2: Fallback - send as regular message (less reliable)
            logger.info("Trying fallback method...")
            await channel.send(f"/imagine {prompt}")
            
            if task_id in tasks:
                tasks[task_id].status = "processing"
            
            return True
            
    except Exception as e:
        logger.error(f"Error sending Midjourney command: {e}")
        return False

# Flask routes
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "bot_ready": bot_ready,
        "bridge_ready": bot_ready,
        "pending_tasks": len([t for t in tasks.values() if t.status == "processing"]),
        "completed_tasks": len([t for t in tasks.values() if t.status == "completed"]),
        "deployment": "render"
    })

@app.route('/generate', methods=['POST'])
def generate_image():
    try:
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({"success": False, "error": "Missing prompt"}), 400
        
        prompt = data['prompt']
        task_id = data.get('task_id', f"task_{int(time.time())}")
        
        if not bot_ready:
            return jsonify({"success": False, "error": "Bot not ready"}), 503
        
        # Clean up expired tasks
        cleanup_expired_tasks()
        
        # Create new task
        tasks[task_id] = MidjourneyTask(task_id, prompt)
        
        # Get channel ID from environment
        channel_id = os.getenv('DISCORD_CHANNEL_ID')
        if not channel_id:
            return jsonify({"success": False, "error": "Discord channel not configured"}), 500
        
        # Send command asynchronously
        asyncio.create_task(send_midjourney_command(channel_id, prompt, task_id))
        
        logger.info(f"Created task {task_id} for prompt: {prompt[:50]}...")
        
        return jsonify({
            "success": True,
            "task_id": task_id,
            "status": "submitted"
        })
        
    except Exception as e:
        logger.error(f"Error in generate_image: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/status/<task_id>', methods=['GET'])
def get_status(task_id):
    try:
        if task_id not in tasks:
            return jsonify({"success": False, "error": "Task not found"}), 404
        
        task = tasks[task_id]
        
        # Check if task has expired
        if task.is_expired() and task.status == "processing":
            task.status = "timeout"
        
        return jsonify({
            "success": True,
            "task_id": task_id,
            "status": task.status,
            "image_urls": task.image_urls,
            "created_at": task.created_at.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error in get_status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def cleanup_expired_tasks():
    """Remove expired tasks to prevent memory buildup"""
    expired_tasks = [task_id for task_id, task in tasks.items() if task.is_expired()]
    for task_id in expired_tasks:
        del tasks[task_id]
    
    if expired_tasks:
        logger.info(f"Cleaned up {len(expired_tasks)} expired tasks")

def run_flask():
    """Run Flask app in a separate thread"""
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

async def main():
    """Main function to run both Flask and Discord bot"""
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Get Discord token
    discord_token = os.getenv('DISCORD_TOKEN')
    if not discord_token:
        logger.error("DISCORD_TOKEN environment variable not set!")
        raise ValueError("Discord token is required")
    
    # Get channel ID
    channel_id = os.getenv('DISCORD_CHANNEL_ID')
    if not channel_id:
        logger.error("DISCORD_CHANNEL_ID environment variable not set!")
        raise ValueError("Discord channel ID is required")
    
    logger.info(f"Starting bot with channel ID: {channel_id}")
    
    # Start Discord bot
    await bot.start(discord_token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
