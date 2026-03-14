"""
Pub-AI mascot — Blue Clawd with task-based animations.
Uses the authentic Clawd Unicode block character design.
"""

COLOR = "blue"

# ── Clawd States ──────────────────────────────────────────────────────

IDLE = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

THINKING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c  ?
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

HAPPY = """
\u2572\u2590\u259b\u2588\u2588\u2588\u259c\u258c\u2571
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

WORKING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c\u2571
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

HAMMERING = """
   \u250c\u2500\u2510
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

SEARCHING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c  O
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598 /
  \u2598\u2598 \u259d\u259d"""

CODING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d [>_]"""

ERROR = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c !!
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

DONE = """
\u2572\u2590\u259b\u2588\u2588\u2588\u259c\u258c\u2571
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598  \u259d\u259d"""

READING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d [=]"""

WRITING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c ...
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

BROWSING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c www
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

REMEMBERING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c *
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598 *
  \u2598\u2598 \u259d\u259d"""

DELEGATING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c\u2571 >> \u2590\u259b\u2588\u259c\u258c
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598    \u259c\u2588\u2588\u2588\u259b
  \u2598\u2598 \u259d\u259d      \u2598 \u259d"""

SCHEDULING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c @
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d"""

STARTING = """
\u2572\u2590\u259b\u2588\u2588\u2588\u259c\u258c\u2571
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598 \u259d\u259d  hi!"""

LOADING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598 ...
  \u2598\u2598 \u259d\u259d"""

DANCING = """
 \u2590\u259b\u2588\u2588\u2588\u259c\u258c\u2571
\u259d\u259c\u2588\u2588\u2588\u2588\u2588\u259b\u2598
  \u2598\u2598  \u259d\u259d"""

LARGE = """
 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588
\u2588\u2588\u2584\u2588\u2588\u2588\u2588\u2588\u2584\u2588\u2588
 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588
\u2588 \u2588   \u2588 \u2588"""

# ── Mappings ──────────────────────────────────────────────────────────

TOOL_MASCOTS: dict[str, tuple[str, str]] = {
    "code_execution":    ("Executing code",       CODING),
    "web_search":        ("Searching the web",    SEARCHING),
    "browser_agent":     ("Browsing",             BROWSING),
    "read_file":         ("Reading file",         READING),
    "write_file":        ("Writing file",         WRITING),
    "edit_file":         ("Editing file",         HAMMERING),
    "list_files":        ("Listing files",        SEARCHING),
    "memory_save":       ("Saving to memory",     REMEMBERING),
    "memory_load":       ("Recalling memory",     REMEMBERING),
    "memory_delete":     ("Cleaning memory",      WORKING),
    "call_subordinate":  ("Delegating task",      DELEGATING),
    "scheduler":         ("Scheduling",           SCHEDULING),
    "skills_tool":       ("Loading skill",        READING),
    "document_query":    ("Querying docs",        SEARCHING),
    "notify_user":       ("Notifying you",        HAPPY),
    "container_shell":   ("Running in sandbox",   CODING),
    "container_python":  ("Python in sandbox",    CODING),
    "container_install": ("Installing packages",  HAMMERING),
    "container_download":("Downloading file",     SEARCHING),
    "container_upload":  ("Copying files",        WORKING),
    "git_ops":           ("Git operation",        CODING),
    "vpn_proxy":         ("Managing VPN",         WORKING),
    "browser_screenshot":("Taking screenshot",    BROWSING),
    "browser_download":  ("Downloading",          BROWSING),
    "response":          ("Done!",                DONE),
}

EVENT_MASCOTS: dict[str, tuple[str, str]] = {
    "thinking":  ("Thinking...", THINKING),
    "response":  ("Done!",      DONE),
    "error":     ("Oops!",      ERROR),
    "done":      ("All done!",  HAPPY),
}


def get_mascot_for_tool(tool_name: str) -> tuple[str, str]:
    """Get (label, art) for a tool call."""
    return TOOL_MASCOTS.get(tool_name, ("Working...", WORKING))


def get_mascot_for_event(event_type: str) -> tuple[str, str]:
    """Get (label, art) for an event type."""
    return EVENT_MASCOTS.get(event_type, ("", IDLE))


def render_mascot(art: str, label: str = "", color: str = COLOR) -> str:
    """Build a Rich-formatted string for the mascot."""
    lines = [l for l in art.split('\n') if l.strip()]
    colored = [f"[bold {color}]{line}[/bold {color}]" for line in lines]
    if label:
        colored.append(f"[dim {color}]  {label}[/dim {color}]")
    return "\n".join(colored)
