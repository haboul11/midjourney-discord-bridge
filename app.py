# Full app.py using raw HTTP POST to send MidJourney slash command (no discord.py)
import os
import uuid
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# Load necessary environment variables
DISCORD_COOKIE = os.getenv("DISCORD_COOKIE")
DISCORD_USER_AGENT = os.getenv("DISCORD_USER_AGENT")
DISCORD_SUPER_PROPERTIES = os.getenv("DISCORD_SUPER_PROPERTIES")
GUILD_ID = os.getenv("GUILD_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
MAX_WAIT_MINUTES = 15

app = Flask(__name__)

# Task storage
pending_tasks = {}
completed_tasks = {}

@app.route("/")
def home():
    return "✅ MidJourney Flask Bridge is running"

@app.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.get_json()
        prompt = data.get("prompt")
        task_id = data.get("task_id", f"task_{int(datetime.now().timestamp())}")

        if not prompt:
            return jsonify({"error": "Prompt is required"}), 400

        if not all([DISCORD_COOKIE, DISCORD_USER_AGENT, DISCORD_SUPER_PROPERTIES, GUILD_ID, CHANNEL_ID]):
            return jsonify({"error": "Missing required headers or IDs"}), 500

        success = send_imagine_command(prompt, task_id)
        if success:
            return jsonify({
                "success": True,
                "task_id": task_id,
                "status": "submitted",
                "message": "Prompt submitted"
            })
        else:
            return jsonify({"success": False, "task_id": task_id, "status": "failed"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/status/<task_id>", methods=["GET"])
def status(task_id):
    if task_id in completed_tasks:
        return jsonify(completed_tasks[task_id])
    elif task_id in pending_tasks:
        task = pending_tasks[task_id]
        elapsed = (datetime.now() - task["created_at"]).total_seconds() / 60
        return jsonify({
            "task_id": task_id,
            "status": task["status"],
            "elapsed_minutes": round(elapsed, 1)
        })
    else:
        return jsonify({"status": "not_found"}), 404

def send_imagine_command(prompt, task_id):
    try:
        headers = {
            "authority": "discord.com",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": "https://discord.com",
            "referer": f"https://discord.com/channels/{GUILD_ID}/{CHANNEL_ID}",
            "user-agent": DISCORD_USER_AGENT,
            "cookie": DISCORD_COOKIE,
            "x-super-properties": DISCORD_SUPER_PROPERTIES
        }

        payload = {
            "type": 2,
            "application_id": "936929561302675456",
            "guild_id": GUILD_ID,
            "channel_id": CHANNEL_ID,
            "session_id": str(uuid.uuid4()),
            "data": {
                "version": "1118961510123847772",
                "id": "938956540159881230",
                "name": "imagine",
                "type": 1,
                "options": [
                    {
                        "type": 3,
                        "name": "prompt",
                        "value": prompt
                    }
                ]
            }
        }

        res = requests.post("https://discord.com/api/v9/interactions", headers=headers, json=payload)

        if res.status_code == 204:
            print(f"✅ Prompt submitted for task {task_id}: {prompt}")
            pending_tasks[task_id] = {
                "prompt": prompt,
                "status": "waiting_for_response",
                "created_at": datetime.now()
            }
            return True
        else:
            print(f"❌ Failed to submit prompt: {res.status_code} - {res.text}")
            pending_tasks[task_id] = {
                "prompt": prompt,
                "status": "failed",
                "created_at": datetime.now(),
                "error": res.text
            }
            return False

    except Exception as e:
        print(f"❌ Error in send_imagine_command: {e}")
        return False

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))

