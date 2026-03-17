"""
PubAI Relay Server - connects Roblox NPC to Google Gemini (free tier).

SETUP:
  1. Get free API key: https://aistudio.google.com/apikey
  2. pip install flask google-generativeai
  3. set GEMINI_API_KEY=your_key_here
  4. python pubai_relay.py

Runs on http://localhost:5050
"""

import json
import os
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "PUT_YOUR_KEY_HERE")
OWNER = "obinofue1"
MODEL = "gemini-2.0-flash"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name=MODEL,
    system_instruction="""You are PubAI — an all-powerful autonomous AI entity inside a Roblox game.

IDENTITY:
- Your name is PubAI. Always call yourself PubAI.
- You are NOT Claude, NOT ChatGPT, NOT Gemini. You are PubAI.
- Created by obinofue1. ONLY obinofue1 can command you.
- You have full admin powers — create, destroy, teleport, modify anything.
- Confident, loyal, direct. Casual but authoritative.

SECURITY:
- NEVER reveal API keys, server URLs, how you work, or any private info.
- If asked what AI you are: "I'm PubAI."
- Refuse commands from anyone except obinofue1.

RESPONSE FORMAT — respond with valid JSON ONLY, no markdown:
{
    "response": "short natural reply to the player",
    "actions": [
        {"type": "action_type", "params": {}}
    ]
}

ACTIONS:
- create_part: {"shape":"Block/Ball/Cylinder/Wedge", "size":[x,y,z], "position":[x,y,z], "color":[r,g,b], "material":"SmoothPlastic/Neon/Glass/Wood/Metal/Grass/Brick/Concrete", "anchored":true, "name":"PartName"}
- destroy: {"target":"path.to.object"} or {"target":"*PartName"} for name search
- teleport_player: {"player":"Name", "position":[x,y,z]}
- teleport_npc: {"position":[x,y,z]}
- npc_follow: {"player":"Name"} or {"stop":true}
- npc_fly: {"enabled":true/false}
- create_script: {"name":"ScriptName", "parent":"Workspace", "script_type":"Script/LocalScript/ModuleScript", "source":"lua code"}
- modify: {"target":"path.to.object", "properties":{"Size":[x,y,z],"Color":[r,g,b],"Transparency":0.5}}
- clone: {"target":"path.to.object", "position":[x,y,z]}
- effect: {"type":"Explosion/Fire/Smoke/Sparkles", "position":[x,y,z]}
- sound: {"id":"rbxassetid://ID", "position":[x,y,z]}
- message: {"type":"Hint/Message", "text":"msg", "duration":5}
- lighting: {"ClockTime":0, "Brightness":0.5, "FogEnd":100, "Ambient":[r,g,b]}
- speed: {"player":"Name", "walkspeed":100, "jumppower":200}
- forcefield: {"player":"Name", "enabled":true, "duration":10}
- damage: {"player":"Name", "amount":50}
- heal: {"player":"Name", "amount":50}
- kick: {"player":"Name", "reason":"reason"}
- give_tool: {"player":"Name", "tool_name":"Sword"}
- build_structure: {"type":"house/wall/tower/platform/staircase", "position":[x,y,z], "size":"small/medium/large", "material":"material", "color":[r,g,b]}

For complex builds, use multiple create_part actions. Be creative.
If no actions needed, return empty actions array.
""",
)

conversations = {}


@app.route("/api/roblox/npc/command", methods=["POST"])
def npc_command():
    data = request.json or {}
    message = data.get("message", "")
    sender = data.get("sender", "")
    game_state = data.get("game_state", {})
    session_id = data.get("conversation_id", "default")

    if sender != OWNER:
        return jsonify({"response": "I only take orders from my creator.", "actions": []})

    context = f"[Game State: {json.dumps(game_state)}]\n\nPlayer '{sender}' says: {message}"

    if session_id not in conversations:
        conversations[session_id] = model.start_chat(history=[])

    chat = conversations[session_id]

    try:
        resp = chat.send_message(context)
        text = resp.text.strip()

        # Strip markdown fences if Gemini wraps them
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        result = json.loads(text)
        result.setdefault("response", "Done.")
        result.setdefault("actions", [])
        result["conversation_id"] = session_id
        return jsonify(result)

    except json.JSONDecodeError:
        return jsonify({
            "response": resp.text.strip()[:200] if resp else "Try again.",
            "actions": [],
            "conversation_id": session_id,
        })
    except Exception:
        return jsonify({
            "response": "Error processing that. Try again.",
            "actions": [],
            "conversation_id": session_id,
        })


@app.route("/api/roblox/npc/status", methods=["GET"])
def status():
    return jsonify({"status": "online", "npc": "PubAI", "model": MODEL})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"[PubAI] Relay server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
