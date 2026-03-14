import json
import re

def _fix_and_parse_json(text: str):
    text = text.strip()
    if not text:
        return None
        
    # Generate common suffixes programmatically
    suffixes = ["", '"']
    for i in range(1, 5):
        suffixes.append("}" * i)
        suffixes.append('"' + "}" * i)
        suffixes.append("]" + "}" * i)
        suffixes.append('"]' + "}" * i)
        
    for suffix in suffixes:
        try:
            return json.loads(text + suffix)
        except json.JSONDecodeError:
            continue
    return None

text = """{"tool": "spawn_subagents", "params": {"task": "make a python exploit script", "agents": 3, "goal": "Create a fully functional exploit script with proper error handling"""
print(_fix_and_parse_json(text))
