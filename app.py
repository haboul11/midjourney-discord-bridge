#!/usr/bin/env python3
"""
Midjourney Discord Bridge - Render.com Deployment Version
Fixed asyncio event loop issues for production deployment
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
MAX_WAIT_MINUTES = 10
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
        """Send /imagine command to Discord"""
        try:
            if not self.ready or not self.channel:
                print("❌ Bot not ready or channel not found")
                return False
                
            print(f"🎨 Sending imagine command for task {task_id}")
            
            # Store task info
            pending_tasks[task_id] = {
                'prompt': prompt,
                'status': 'submitted',
                'created_at': datetime.now(),
                'command_message_id': None,
                'response_message_id': None,
                'image_urls': []
            }
            
            # Send the /imagine command
            command_text = f"/imagine {prompt}"
            message = await self.channel.send(command_text)
            
            pending_tasks[task_id]['command_message_id'] = message.id
            pending_tasks[task_id]['status'] = 'waiting_for_response'
            
            print(f"✅ Command sent! Message ID: {message.id}")
            return True
            
        except Exception as e:
            print(f"❌ Error sending command: {e}")
            if task_id in pending_tasks:
                pending_tasks[task_id]['status'] = 'error'
            return False

    async def wait_for_response(self, task_id):
        """Wait for Midjourney to respond"""
        try:
            if task_id not in pending_tasks:
                return None
                
            task_info = pending_tasks[task_id]
            prompt_words = task_info['prompt'].lower().split()[:5]
            
            print(f"🔍 Monitoring for response to task {task_id}")
            
            timeout = datetime.now() + timedelta(minutes=MAX_WAIT_MINUTES)
            check_interval = 5
            
            while datetime.now() < timeout:
                try:
                    messages = []
                    async for message in self.channel.history(limit=20, after=task_info['created_at']):
                        messages.append(message)
                    
                    for message in messages:
                        if message.author.id != MIDJOURNEY_USER_ID:
                            continue
                            
                        if not message.attachments:
                            continue
                            
                        message_content = message.content.lower()
                        matches = sum(1 for word in prompt_words if word in message_content)
                        
                        if matches >= 2:
                            print(f"🎯 Found matching message from Midjourney!")
                            
                            image_urls = []
                            for attachment in message.attachments:
                                if any(ext in attachment.filename.lower() for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                                    image_urls.append(attachment.url)
                            
                            if image_urls:
                                completed_tasks[task_id] = {
                                    'status': 'completed',
                                    'prompt': task_info['prompt'],
                                    'image_urls': image_urls,
                                    'discord_message_id': message.id,
                                    'completed_at': datetime.now()
                                }
                                
                                pending_tasks[task_id]['status'] = 'completed'
                                pending_tasks[task_id]['response_message_id'] = message.id
                                pending_tasks[task_id]['image_urls'] = image_urls
                                
                                print(f"✅ Task {task_id} completed! Found {len(image_urls)} images")
                                return image_urls
                    
                    await asyncio.sleep(check_interval)
                    
                except Exception as e:
                    print(f"❌ Error while monitoring: {e}")
                    await asyncio.sleep(check_interval)
            
            print(f"⏰ Timeout reached for task {task_id}")
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
        <p><strong>Debug Mode:</strong> {DEBUG_MODE}</p>
        
        <h3>API Endpoints</h3>
        <ul>
            <li><code>POST /generate</code> - Generate image</li>
            <li><code>GET /status/&lt;task_id&gt;</code> - Check task status</li>
            <li><code>GET /health</code> - Health check</li>
        </ul>
        
        <h3>Example Request</h3>
        <pre style="background: #f5f5f5; padding: 10px; border-radius: 5px;">
POST /generate
{{
    "prompt": "beautiful sunset over mountains",
    "task_id": "test123"
}}
        </pre>
        
        <h3>Recent Activity</h3>
        <ul>
    """
    
    # Show recent completed tasks
    recent_tasks = list(completed_tasks.items())[-5:]  # Last 5 tasks
    for task_id, task_info in recent_tasks:
        status_html += f"<li>{task_id}: {task_info['status']} - {len(task_info.get('image_urls', []))} images</li>"
    
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
            
        print(f"\n📥 NEW REQUEST")
        print(f"🆔 Task ID: {task_id}")
        print(f"📝 Prompt: {prompt}")
        
        # Process request using the Discord thread
        future = run_async_in_thread(process_generation_request(prompt, task_id))
        
        if future is None:
            return jsonify({'error': 'Could not process request - Discord loop not available'}), 503
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'status': 'submitted',
            'message': 'Generation request submitted to Discord'
        })
        
    except Exception as e:
        print(f"❌ Error in generate_image: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/status/<task_id>', methods=['GET'])
def check_status(task_id):
    """Check task status"""
    try:
        if task_id in completed_tasks:
            task_info = completed_tasks[task_id]
            return jsonify({
                'status': 'completed',
                'task_id': task_id,
                'image_urls': task_info['image_urls'],
                'discord_message_id': task_info.get('discord_message_id'),
                'completed_at': task_info['completed_at'].isoformat()
            })
        
        if task_id in pending_tasks:
            task_info = pending_tasks[task_id]
            return jsonify({
                'status': task_info['status'],
                'task_id': task_id,
                'created_at': task_info['created_at'].isoformat(),
                'message': f"Task is {task_info['status']}"
            })
        
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
        'deployment': 'render.com'
    })

async def process_generation_request(prompt, task_id):
    """Process generation request"""
    try:
        print(f"🔄 Processing generation request for {task_id}")
        
        success = await bridge.send_imagine_command(prompt, task_id)
        
        if success:
            print(f"✅ Command sent for {task_id}, waiting for response...")
            image_urls = await bridge.wait_for_response(task_id)
            
            if image_urls:
                print(f"✅ Generation successful for {task_id}")
            else:
                print(f"❌ No images received for {task_id}")
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
        
        success = await bridge.setup()
        
        if success:
            print(f"✅ Bridge ready on Render.com!")
            print(f"🔄 Event loop: {discord_loop}")
        else:
            print(f"❌ Bridge setup failed!")

    @bot.event
    async def on_message(message):
        """Handle incoming messages"""
        if DEBUG_MODE and message.author.id == MIDJOURNEY_USER_ID:
            print(f"📨 Midjourney message: {message.content[:50]}...")
            if message.attachments:
                print(f"   📎 {len(message.attachments)} attachments")
        
        await bot.process_commands(message)

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
    print("=" * 50)
    print("🚀 MIDJOURNEY BRIDGE - RENDER DEPLOYMENT")
    print("=" * 50)
    print(f"🔧 Discord Available: {DISCORD_AVAILABLE}")
    print(f"🔧 Token Set: {bool(DISCORD_TOKEN)}")
    print(f"🔧 Channel ID: {CHANNEL_ID}")
    
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
