#!/usr/bin/env python3
"""
Midjourney Discord Bridge - Render.com Deployment Version
Fixed asyncio event loop issues and proper Midjourney command format
"""

import os
import sys
import asyncio
import json
import time
import re
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# Handle discord.py import with fallback
try:
    import discord
    from discord.ext import commands
    DISCORD_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Discord import failed: {e}")
    DISCORD_AVAILABLE = False

# Configuration from environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
FLASK_HOST = "0.0.0.0"
FLASK_PORT = int(os.getenv('PORT', '5000'))
MIDJOURNEY_USER_ID = 936929561302675456
MAX_WAIT_MINUTES = 15  # Increased wait time
DEBUG_MODE = os.getenv('DEBUG_MODE', 'True').lower() == 'true'

# Flask app
app = Flask(__name__)

# Discord bot setup
if DISCORD_AVAILABLE:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    bot = commands.Bot(command_prefix='!', intents=intents)
else:
    bot = None

# Storage for tasks
pending_tasks = {}
completed_tasks = {}

# Global event loop for async operations
discord_loop = None

class MidjourneyBridge:
    def __init__(self):
        self.channel = None
        self.ready = False
        
    async def setup(self):
        """Initialize the bot and get the channel"""
        try:
            if not DISCORD_AVAILABLE or not bot:
                print("❌ Discord not available")
                return False
                
            await bot.wait_until_ready()
            self.channel = bot.get_channel(CHANNEL_ID)
            
            if not self.channel:
                print(f"❌ Could not find channel with ID: {CHANNEL_ID}")
                return False
                
            print(f"✅ Connected to channel: {self.channel.name}")
            print(f"🏢 Server: {self.channel.guild.name}")
            self.ready = True
            return True
            
        except Exception as e:
            print(f"❌ Setup error: {e}")
            return False

    async def send_imagine_command(self, prompt, task_id):
        """Send /imagine command to Discord with proper format"""
        try:
            if not self.ready or not self.channel:
                print("❌ Bot not ready or channel not found")
                return False
                
            print(f"🎨 Sending imagine command for task {task_id}")
            print(f"📝 Prompt: {prompt}")
            
            # Store task info
            pending_tasks[task_id] = {
                'prompt': prompt,
                'status': 'submitted',
                'created_at': datetime.now(),
                'command_message_id': None,
                'response_message_id': None,
                'image_urls': []
            }
            
            # Try multiple command formats for better Midjourney compatibility
            command_formats = [
                f"/imagine prompt: {prompt}",  # Correct Midjourney format
                f"/imagine {prompt}",          # Alternative format
                f"<@{MIDJOURNEY_USER_ID}> /imagine prompt: {prompt}",  # With mention
            ]
            
            message = None
            successful_format = None
            
            for i, command_text in enumerate(command_formats):
                try:
                    print(f"🔄 Trying format {i+1}: {command_text[:50]}...")
                    message = await self.channel.send(command_text)
                    successful_format = command_text
                    print(f"✅ Successfully sent format {i+1}")
                    break
                except Exception as e:
                    print(f"❌ Format {i+1} failed: {e}")
                    # Wait a bit before trying next format
                    await asyncio.sleep(1)
                    continue
            
            if message:
                pending_tasks[task_id]['command_message_id'] = message.id
                pending_tasks[task_id]['status'] = 'waiting_for_response'
                pending_tasks[task_id]['command_used'] = successful_format
                
                print(f"✅ Command sent successfully!")
                print(f"📨 Message ID: {message.id}")
                print(f"📝 Format used: {successful_format}")
                return True
            else:
                print("❌ All command formats failed")
                pending_tasks[task_id]['status'] = 'failed'
                return False
                
        except Exception as e:
            print(f"❌ Error sending command: {e}")
            if task_id in pending_tasks:
                pending_tasks[task_id]['status'] = 'error'
            return False

    async def wait_for_response(self, task_id):
        """Wait for Midjourney to respond with improved detection"""
        try:
            if task_id not in pending_tasks:
                print(f"❌ Task {task_id} not found in pending tasks")
                return None
                
            task_info = pending_tasks[task_id]
            prompt_words = task_info['prompt'].lower().split()
            
            # Use more specific keywords for matching
            key_words = []
            for word in prompt_words[:8]:  # Use first 8 words
                if len(word) > 3:  # Only words longer than 3 characters
                    key_words.append(word)
            
            print(f"🔍 Monitoring for response to task {task_id}")
            print(f"🔍 Looking for keywords: {key_words}")
            
            timeout = datetime.now() + timedelta(minutes=MAX_WAIT_MINUTES)
            check_interval = 8  # Check every 8 seconds
            
            while datetime.now() < timeout:
                try:
                    # Get recent messages since task creation
                    messages = []
                    async for message in self.channel.history(limit=30, after=task_info['created_at']):
                        messages.append(message)
                    
                    # Look for Midjourney responses
                    for message in messages:
                        # Check if message is from Midjourney
                        if message.author.id != MIDJOURNEY_USER_ID:
                            continue
                        
                        # Check if message has attachments (images)
                        if not message.attachments:
                            continue
                            
                        message_content = message.content.lower()
                        
                        # Check for keyword matches
                        matches = 0
                        for keyword in key_words:
                            if keyword in message_content:
                                matches += 1
                        
                        # If we have enough matches, this is likely our response
                        if matches >= 2 or len(key_words) <= 2:
                            print(f"🎯 Found potential matching message from Midjourney!")
                            print(f"📨 Message content: {message.content[:100]}...")
                            print(f"🔍 Keyword matches: {matches}/{len(key_words)}")
                            
                            # Extract image URLs from attachments
                            image_urls = []
                            for attachment in message.attachments:
                                if any(ext in attachment.filename.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                                    image_urls.append(attachment.url)
                            
                            if image_urls:
                                # Task completed successfully!
                                completed_tasks[task_id] = {
                                    'status': 'completed',
                                    'prompt': task_info['prompt'],
                                    'image_urls': image_urls,
                                    'discord_message_id': message.id,
                                    'completed_at': datetime.now(),
                                    'keyword_matches': matches
                                }
                                
                                # Update pending task
                                pending_tasks[task_id]['status'] = 'completed'
                                pending_tasks[task_id]['response_message_id'] = message.id
                                pending_tasks[task_id]['image_urls'] = image_urls
                                
                                print(f"✅ Task {task_id} completed successfully!")
                                print(f"🖼️ Found {len(image_urls)} images:")
                                for i, url in enumerate(image_urls):
                                    print(f"   {i+1}. {url}")
                                
                                return image_urls
                    
                    # No matching message found yet, wait and check again
                    print(f"⏳ Still waiting... {datetime.now().strftime('%H:%M:%S')}")
                    await asyncio.sleep(check_interval)
                    
                except Exception as e:
                    print(f"❌ Error while monitoring: {e}")
                    await asyncio.sleep(check_interval)
            
            # Timeout reached
            print(f"⏰ Timeout reached for task {task_id} after {MAX_WAIT_MINUTES} minutes")
            if task_id in pending_tasks:
                pending_tasks[task_id]['status'] = 'timeout'
            
            return None
            
        except Exception as e:
            print(f"❌ Error in wait_for_response: {e}")
            return None

# Initialize bridge
bridge = MidjourneyBridge()

def run_async_in_thread(coro):
    """Run async function in the Discord thread"""
    global discord_loop
    if discord_loop and not discord_loop.is_closed():
        future = asyncio.run_coroutine_threadsafe(coro, discord_loop)
        return future
    else:
        print("❌ Discord loop not available")
        return None

# Flask routes
@app.route('/', methods=['GET'])
def home():
    """Home page with status"""
    status_html = f"""
    <html>
    <head><title>Midjourney Bridge - Render Deployment</title></head>
    <body style="font-family: Arial, sans-serif; margin: 40px;">
        <h1>🤖 Midjourney Discord Bridge</h1>
        <h2>🌐 Deployed on Render.com</h2>
        
        <h3>Status</h3>
        <p><strong>Bot Ready:</strong> {'✅ Yes' if bridge.ready else '❌ No'}</p>
        <p><strong>Discord Connected:</strong> {'✅ Yes' if bot and bot.is_ready() else '❌ No'}</p>
        <p><strong>Discord Available:</strong> {'✅ Yes' if DISCORD_AVAILABLE else '❌ No'}</p>
        <p><strong>Event Loop:</strong> {'✅ Active' if discord_loop and not discord_loop.is_closed() else '❌ Not Active'}</p>
        <p><strong>Pending Tasks:</strong> {len(pending_tasks)}</p>
        <p><strong>Completed Tasks:</strong> {len(completed_tasks)}</p>
        
        <h3>Configuration</h3>
        <p><strong>Channel ID:</strong> {CHANNEL_ID}</p>
        <p><strong>Max Wait Time:</strong> {MAX_WAIT_MINUTES} minutes</p>
        <p><strong>Debug Mode:</strong> {DEBUG_MODE}</p>
        
        <h3>API Endpoints</h3>
        <ul>
            <li><code>POST /generate</code> - Generate image</li>
            <li><code>GET /status/&lt;task_id&gt;</code> - Check task status</li>
            <li><code>GET /health</code> - Health check</li>
        </ul>
        
        <h3>Command Formats Supported</h3>
        <ul>
            <li><code>/imagine prompt: [description]</code> (Primary)</li>
            <li><code>/imagine [description]</code> (Fallback)</li>
            <li><code>@Midjourney /imagine prompt: [description]</code> (With mention)</li>
        </ul>
        
        <h3>Recent Activity</h3>
        <ul>
    """
    
    # Show recent completed tasks
    recent_tasks = list(completed_tasks.items())[-5:]  # Last 5 tasks
    for task_id, task_info in recent_tasks:
        status_html += f"<li><strong>{task_id}:</strong> {task_info['status']} - {len(task_info.get('image_urls', []))} images</li>"
    
    status_html += """
        </ul>
        
        <h3>Pending Tasks</h3>
        <ul>
    """
    
    # Show current pending tasks
    for task_id, task_info in pending_tasks.items():
        status_html += f"<li><strong>{task_id}:</strong> {task_info['status']} (Created: {task_info['created_at'].strftime('%H:%M:%S')})</li>"
    
    status_html += """
        </ul>
    </body>
    </html>
    """
    return status_html

@app.route('/generate', methods=['POST'])
def generate_image():
    """Generate image endpoint"""
    try:
        data = request.get_json()
        prompt = data.get('prompt')
        task_id = data.get('task_id', f"task_{int(time.time())}")
        
        if not prompt:
            return jsonify({'error': 'Prompt is required'}), 400
            
        if not bridge.ready:
            return jsonify({'error': 'Discord bot not ready'}), 503
        
        if not DISCORD_AVAILABLE:
            return jsonify({'error': 'Discord not available'}), 503
            
        print(f"\n📥 NEW GENERATION REQUEST")
        print(f"🆔 Task ID: {task_id}")
        print(f"📝 Prompt: {prompt}")
        print(f"⏰ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Process request using the Discord thread
        future = run_async_in_thread(process_generation_request(prompt, task_id))
        
        if future is None:
            return jsonify({'error': 'Could not process request - Discord loop not available'}), 503
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': 'submitted',
            'message': 'Generation request submitted to Discord',
            'max_wait_minutes': MAX_WAIT_MINUTES
        })
        
    except Exception as e:
        print(f"❌ Error in generate_image: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/status/<task_id>', methods=['GET'])
def check_status(task_id):
    """Check task status"""
    try:
        # Check completed tasks first
        if task_id in completed_tasks:
            task_info = completed_tasks[task_id]
            return jsonify({
                'status': 'completed',
                'task_id': task_id,
                'image_urls': task_info['image_urls'],
                'discord_message_id': task_info.get('discord_message_id'),
                'completed_at': task_info['completed_at'].isoformat(),
                'total_images': len(task_info['image_urls']),
                'keyword_matches': task_info.get('keyword_matches', 0)
            })
        
        # Check pending tasks
        if task_id in pending_tasks:
            task_info = pending_tasks[task_id]
            elapsed_minutes = (datetime.now() - task_info['created_at']).total_seconds() / 60
            return jsonify({
                'status': task_info['status'],
                'task_id': task_id,
                'created_at': task_info['created_at'].isoformat(),
                'elapsed_minutes': round(elapsed_minutes, 1),
                'max_wait_minutes': MAX_WAIT_MINUTES,
                'message': f"Task is {task_info['status']} ({elapsed_minutes:.1f}/{MAX_WAIT_MINUTES} min)"
            })
        
        # Task not found
        return jsonify({
            'status': 'not_found',
            'task_id': task_id,
            'message': 'Task not found'
        }), 404
        
    except Exception as e:
        print(f"❌ Error in check_status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'bot_ready': bot.is_ready() if bot else False,
        'bridge_ready': bridge.ready,
        'discord_available': DISCORD_AVAILABLE,
        'event_loop_active': discord_loop is not None and not discord_loop.is_closed() if discord_loop else False,
        'pending_tasks': len(pending_tasks),
        'completed_tasks': len(completed_tasks),
        'max_wait_minutes': MAX_WAIT_MINUTES,
        'midjourney_user_id': MIDJOURNEY_USER_ID,
        'deployment': 'render.com'
    })

async def process_generation_request(prompt, task_id):
    """Process generation request"""
    try:
        print(f"🔄 Processing generation request for {task_id}")
        
        # Send the imagine command
        success = await bridge.send_imagine_command(prompt, task_id)
        
        if success:
            print(f"✅ Command sent for {task_id}, waiting for Midjourney response...")
            
            # Wait for Midjourney to respond
            image_urls = await bridge.wait_for_response(task_id)
            
            if image_urls:
                print(f"✅ Generation successful for {task_id}!")
                print(f"🖼️ Received {len(image_urls)} images")
            else:
                print(f"❌ No images received for {task_id}")
                print("💡 This could mean:")
                print("   - Midjourney didn't respond (check Discord)")
                print("   - Command format wasn't recognized")
                print("   - Prompt was rejected by Midjourney")
                print("   - Response detection failed")
        else:
            print(f"❌ Failed to send command for {task_id}")
            
    except Exception as e:
        print(f"❌ Error processing {task_id}: {e}")

# Discord bot events
if DISCORD_AVAILABLE and bot:
    @bot.event
    async def on_ready():
        """Bot ready event"""
        global discord_loop
        discord_loop = asyncio.get_event_loop()
        
        print(f'\n🤖 Discord bot logged in as {bot.user}')
        print(f"🆔 Bot ID: {bot.user.id}")
        print(f"🏢 Connected to {len(bot.guilds)} server(s)")
        
        # List all servers for debugging
        for guild in bot.guilds:
            print(f"   - {guild.name} (ID: {guild.id})")
        
        success = await bridge.setup()
        
        if success:
            print(f"✅ Bridge ready on Render.com!")
            print(f"🔄 Event loop: {discord_loop}")
            print(f"⏰ Max wait time: {MAX_WAIT_MINUTES} minutes")
            print(f"🎯 Target Midjourney User ID: {MIDJOURNEY_USER_ID}")
        else:
            print(f"❌ Bridge setup failed!")

    @bot.event
    async def on_message(message):
        """Handle incoming messages with enhanced logging"""
        if DEBUG_MODE and message.author.id == MIDJOURNEY_USER_ID:
            print(f"📨 Midjourney message detected:")
            print(f"   Content: {message.content[:100]}...")
            print(f"   Attachments: {len(message.attachments)}")
            if message.attachments:
                for i, att in enumerate(message.attachments):
                    print(f"      {i+1}. {att.filename} ({att.url})")
        
        await bot.process_commands(message)

    @bot.event
    async def on_error(event, *args, **kwargs):
        """Handle Discord errors"""
        print(f"❌ Discord error in {event}: {args}")

def run_flask():
    """Run Flask server"""
    print(f"🌐 Starting Flask server on {FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False)

def run_bot():
    """Run Discord bot"""
    if not DISCORD_AVAILABLE:
        print("❌ Discord not available - running Flask only")
        return
        
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN environment variable not set")
        return
    
    if not CHANNEL_ID:
        print("❌ CHANNEL_ID environment variable not set")
        return
    
    print("🤖 Starting Discord bot...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"❌ Failed to start Discord bot: {e}")

def main():
    """Main function for Render deployment"""
    print("=" * 60)
    print("🚀 MIDJOURNEY BRIDGE - RENDER DEPLOYMENT v2.0")
    print("=" * 60)
    print(f"🔧 Discord Available: {DISCORD_AVAILABLE}")
    print(f"🔧 Token Set: {bool(DISCORD_TOKEN)}")
    print(f"🔧 Channel ID: {CHANNEL_ID}")
    print(f"🔧 Max Wait Time: {MAX_WAIT_MINUTES} minutes")
    print(f"🔧 Debug Mode: {DEBUG_MODE}")
    
    if not DISCORD_AVAILABLE:
        print("⚠️ Running in Flask-only mode")
        run_flask()
        return
    
    # Start Flask in separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run Discord bot (this blocks)
    run_bot()

if __name__ == "__main__":
    main()
