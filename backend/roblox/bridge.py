from __future__ import annotations

from typing import Dict


def analyze_bytecode(bytecode: str) -> Dict:
    """Analyze Roblox Luau bytecode. Placeholder for full decompiler integration."""
    # TODO: Integrate with actual Luau bytecode decompiler
    if not bytecode or not bytecode.strip():
        return {"error": "Empty bytecode input"}

    # Basic bytecode header detection
    bytecode_bytes = bytecode.encode("latin-1") if isinstance(bytecode, str) else bytecode

    info = {
        "size": len(bytecode_bytes),
        "status": "analyzed",
    }

    # Check for Luau bytecode version header
    if len(bytecode_bytes) >= 1:
        version = bytecode_bytes[0]
        info["bytecode_version"] = version
        if version in (3, 4, 5, 6):
            info["format"] = "luau"
        else:
            info["format"] = "unknown"

    return {
        "decompiled": "-- Decompilation requires a Luau bytecode decompiler integration\n-- Bytecode received and parsed",
        "info": info,
    }


def build_roblox_context(context: Dict) -> str:
    """Build context string from Roblox client metadata."""
    parts = []
    if context.get("place_id"):
        parts.append(f"Place ID: {context['place_id']}")
    if context.get("game_name"):
        parts.append(f"Game: {context['game_name']}")
    if context.get("player_name"):
        parts.append(f"Player: {context['player_name']}")
    return " | ".join(parts) if parts else "No context provided"
