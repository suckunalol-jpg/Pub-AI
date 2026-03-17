"""Extended language registry for per-agent Docker container execution.

Re-exports the base LANGUAGE_CONFIG and LANGUAGE_ALIASES from sandbox.py,
then layers on security DSLs, data tools, and web languages that are only
available inside the provisioned Kali workspace containers.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from executor.sandbox import LANGUAGE_ALIASES, LANGUAGE_CONFIG

# ──────────────────────────────────────────────────────────────
# Container-only language definitions
# ──────────────────────────────────────────────────────────────

CONTAINER_EXTRA_LANGUAGES: Dict[str, dict] = {
    # ── Security DSLs ─────────────────────────────────────────
    "yara":       {"ext": ".yar",   "cmd": ["yara", "-r", "{src}", "/workspace/"], "category": "security-rules"},
    "sigma":      {"ext": ".yml",   "cmd": ["sigma", "convert", "-t", "splunk", "{src}"], "category": "security-rules"},
    "snort":      {"ext": ".rules", "cmd": ["snort", "-T", "-c", "{src}"], "category": "security-rules"},
    "suricata":   {"ext": ".rules", "cmd": ["suricata", "-T", "-c", "{src}"], "category": "security-rules"},
    "zeek":       {"ext": ".zeek",  "cmd": ["zeek", "{src}"], "category": "security-rules"},
    "oval":       {"ext": ".xml",   "cmd": ["oscap", "oval", "eval", "{src}"], "category": "security-rules"},

    # ── Security tools (Python wrapper scripts) ──────────────
    "stix":       {"ext": ".json",  "type": "stix",    "category": "security-tools"},
    "cypher":     {"ext": ".cypher","type": "cypher",   "category": "security-tools"},
    "metasploit": {"ext": ".rc",    "cmd": ["msfconsole", "-q", "-r", "{src}"], "category": "security-tools"},
    "nse":        {"ext": ".nse",   "cmd": ["nmap", "--script={src}", "localhost"], "category": "security-tools"},

    # ── Data ──────────────────────────────────────────────────
    "sql":        {"ext": ".sql",   "type": "sql",     "category": "data"},

    # ── Web ───────────────────────────────────────────────────
    "html":       {"ext": ".html",  "type": "static",  "category": "web"},
    "css":        {"ext": ".css",   "type": "static",  "category": "web"},

    # ── Scientific ────────────────────────────────────────────
    "octave":     {"ext": ".m",     "cmd": ["octave", "--no-gui", "{src}"], "category": "scientific"},
}

CONTAINER_EXTRA_ALIASES: Dict[str, str] = {
    "msfconsole":      "metasploit",
    "nmap-script":     "nse",
    "sqlite":          "sql",
    "psql":            "sql",
    "mysql":           "sql",
    "suricata-rules":  "suricata",
    "snort-rules":     "snort",
    "yar":             "yara",
    "zeek-script":     "zeek",
}

# ──────────────────────────────────────────────────────────────
# Combined registries for container execution
# ──────────────────────────────────────────────────────────────

CONTAINER_LANGUAGES: Dict[str, dict] = {**LANGUAGE_CONFIG, **CONTAINER_EXTRA_LANGUAGES}
CONTAINER_ALIASES: Dict[str, str] = {**LANGUAGE_ALIASES, **CONTAINER_EXTRA_ALIASES}


def resolve_container_language(language: str) -> Optional[Tuple[str, dict]]:
    """Resolve a language name (including aliases) to its container config.

    Returns (canonical_key, config_dict) or None if unrecognised.
    """
    key = language.lower().strip()
    key = CONTAINER_ALIASES.get(key, key)
    config = CONTAINER_LANGUAGES.get(key)
    return (key, config) if config else None


# ──────────────────────────────────────────────────────────────
# Flat list for the /api/execute endpoint discovery
# ──────────────────────────────────────────────────────────────

CONTAINER_SUPPORTED_LANGUAGES: List[dict] = sorted(
    [
        {
            "name": name,
            "ext": cfg.get("ext", ""),
            "category": cfg.get("category", "general"),
        }
        for name, cfg in CONTAINER_LANGUAGES.items()
    ],
    key=lambda entry: (entry["category"], entry["name"]),
)
