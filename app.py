import os
import uuid
import json
import requests
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Environment variables (to be set in Render)
DISCORD_COOKIE = os.getenv("DISCORD_COOKIE")
DISCORD_USER_AGENT = os.getenv("DISCORD_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
DISCORD_SUPER_PROPERTIES = os.getenv("DISCORD_SUPER_PROPERTIES")
GUILD_ID = os.getenv("GUILD_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID", "1388899115647111304")  # Your channel ID
MAX_WAIT_MINUTES = int(os.getenv("MAX_WAIT_MINUTES", "15"))

# Midjourney Bot Application ID (official)
MIDJOURNEY_APP_ID = "936929561302675456"
IMAGINE_COMMAND_ID = "938956540159881230"
IMAGINE_COMMAND_VERSION = "1118961510123847772"

# Task storage
pending_tasks = {}
completed_tasks = {}

@app.route("/")
def home():
    return jsonify({
        "status": "✅ Midjourney Raw API Bridge is running",
        "version": "2.0",
        "method": "Raw Discord API calls",
        "endpoints": ["/generate", "/status/<task_id>", "/health"]
    })

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "configured": bool(DISCORD_COOKIE and GUILD_ID and CHANNEL_ID),
        "pending_tasks": len(pending_tasks),
        "completed_tasks": len(completed_tasks)
    })

@app.route("/generate", methods=["POST"])
def generate():
    """Generate image using raw Discord API to trigger Midjourney"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON data required"}), 400
            
        prompt = data.get("prompt", "").strip()
        task_id = data.get("task_id", f"task_{int(time.time() * 1000)}")
        
        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400
        
        # Validate required environment variables
        missing_vars = []
        if not DISCORD_COOKIE:
            missing_vars.append("DISCORD_COOKIE")
        if not GUILD_ID:
            missing_vars.append("GUILD_ID")
        if not CHANNEL_ID:
            missing_vars.append("CHANNEL_ID")
        if not DISCORD_SUPER_PROPERTIES:
            missing_vars.append("DISCORD_SUPER_PROPERTIES")
            
        if missing_vars:
            return jsonify({
                "error": f"Missing environment variables: {', '.join(missing_vars)}"
            }), 500
        
        logger.info(f"🚀 Submitting prompt to Midjourney: {prompt}")
        
        # Send the imagine command
        success, message = send_imagine_command(prompt, task_id)
        
        if success:
            return jsonify({
                "success": True,
                "task_id": task_id,
                "status": "submitted",
                "message": message,
                "prompt": prompt
            })
        else:
            return jsonify({
                "success": False,
                "task_id": task_id,
                "status": "failed",
                "error": message
            }), 400
            
    except Exception as e:
        logger.error(f"❌ Error in /generate: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/status/<task_id>", methods=["GET"])
def get_status(task_id):
    """Get status of a specific task"""
    if task_id in completed_tasks:
        return jsonify(completed_tasks[task_id])
    elif task_id in pending_tasks:
        task = pending_tasks[task_id]
        elapsed = (datetime.now() - task["created_at"]).total_seconds() / 60
        
        # Check if task has timed out
        if elapsed > MAX_WAIT_MINUTES:
            task["status"] = "timeout"
            task["message"] = f"Task timed out after {MAX_WAIT_MINUTES} minutes"
            
        return jsonify({
            "task_id": task_id,
            "status": task["status"],
            "prompt": task.get("prompt", ""),
            "elapsed_minutes": round(elapsed, 1),
            "message": task.get("message", "")
        })
    else:
        return jsonify({"error": "Task not found"}), 404

@app.route("/tasks", methods=["GET"])
def list_tasks():
    """List all tasks for debugging"""
    return jsonify({
        "pending": {k: {**v, "created_at": v["created_at"].isoformat()} for k, v in pending_tasks.items()},
        "completed": completed_tasks
    })

def send_imagine_command(prompt, task_id):
    """Send /imagine command using raw Discord API"""
    try:
        # Prepare headers
        headers = {
            "authority": "discord.com",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": "https://discord.com",
            "referer": f"https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}",
            "user-agent": DISCORD_USER_AGENT,
            "cookie": DISCORD_COOKIE,
            "x-super-properties": DISCORD_SUPER_PROPERTIES,
            "x-discord-locale": "en-US"
        }
        
        # Generate unique session ID
        session_id = str(uuid.uuid4())
        
        # Prepare payload for /imagine command
        payload = {
            "type": 2,  # APPLICATION_COMMAND
            "application_id": MIDJOURNEY_APP_ID,
            "guild_id": GUILD_ID,
            "channel_id": CHANNEL_ID,
            "session_id": session_id,
            "data": {
                "version": IMAGINE_COMMAND_VERSION,
                "id": IMAGINE_COMMAND_ID,
                "name": "imagine",
                "type": 1,
                "options": [
                    {
                        "type": 3,  # STRING
                        "name": "prompt",
                        "value": prompt[:2000]  # Discord limit
                    }
                ],
                "application_command": {
                    "id": IMAGINE_COMMAND_ID,
                    "application_id": MIDJOURNEY_APP_ID,
                    "version": IMAGINE_COMMAND_VERSION,
                    "default_member_permissions": None,
                    "type": 1,
                    "nsfw": False,
                    "name": "imagine",
                    "description": "Create images with Midjourney",
                    "dm_permission": True,
                    "options": [
                        {
                            "type": 3,
                            "name": "prompt",
                            "description": "A prompt to generate an image.",
                            "required": True
                        }
                    ]
                },
                "attachments": []
            }
        }
        
        logger.info(f"📤 Sending request to Discord API...")
        logger.info(f"🎯 Target: Guild {GUILD_ID}, Channel {CHANNEL_ID}")
        logger.info(f"💬 Prompt: {prompt}")
        
        # Send the request
        response = requests.post(
            "https://discord.com/api/v9/interactions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        logger.info(f"📬 Response status: {response.status_code}")
        
        if response.status_code == 204:
            # Success - command sent
            logger.info(f"✅ Successfully sent /imagine command")
            
            pending_tasks[task_id] = {
                "prompt": prompt,
                "status": "submitted",
                "created_at": datetime.now(),
                "session_id": session_id,
                "message": "Command sent successfully"
            }
            
            return True, "Command sent successfully to Midjourney"
            
        elif response.status_code == 401:
            error_msg = "Authentication failed - Discord cookie may be expired"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
            
        elif response.status_code == 403:
            error_msg = "Forbidden - Bot may not have permissions or user not in server"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
            
        elif response.status_code == 429:
            error_msg = "Rate limited - too many requests"
            logger.error(f"❌ {error_msg}")
            return False, error_msg
            
        else:
            # Other error
            error_text = response.text[:500] if response.text else "No response body"
            error_msg = f"Discord API error {response.status_code}: {error_text}"
            logger.error(f"❌ {error_msg}")
            
            pending_tasks[task_id] = {
                "prompt": prompt,
                "status": "failed",
                "created_at": datetime.now(),
                "error": error_msg
            }
            
            return False, error_msg
            
    except requests.exceptions.Timeout:
        error_msg = "Request timed out"
        logger.error(f"❌ {error_msg}")
        return False, error_msg
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

# Optional: Cleanup old tasks
def cleanup_old_tasks():
    """Remove tasks older than 24 hours"""
    cutoff = datetime.now() - timedelta(hours=24)
    
    # Clean pending tasks
    old_pending = [k for k, v in pending_tasks.items() if v["created_at"] < cutoff]
    for task_id in old_pending:
        del pending_tasks[task_id]
    
    # Clean completed tasks
    old_completed = [k for k, v in completed_tasks.items() 
                    if datetime.fromisoformat(v.get("completed_at", "1970-01-01")) < cutoff]
    for task_id in old_completed:
        del completed_tasks[task_id]
    
    if old_pending or old_completed:
        logger.info(f"🧹 Cleaned up {len(old_pending)} pending and {len(old_completed)} completed tasks")

if __name__ == "__main__":
    logger.info("🚀 Starting Midjourney Raw API Bridge...")
    logger.info(f"📍 Target Channel: {CHANNEL_ID}")
    logger.info(f"🏠 Target Guild: {GUILD_ID}")
    logger.info(f"🍪 Cookie configured: {'Yes' if DISCORD_COOKIE else 'No'}")
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
