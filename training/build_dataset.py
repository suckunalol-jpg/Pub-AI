"""
Pub AI — Unified Training Dataset Builder

Downloads 3 HuggingFace reasoning datasets, normalizes them into a single
coherent ChatML format, deduplicates, and exports for fine-tuning.

Sources:
  1. nohurry/Opus-4.6-Reasoning-3000x-filtered  (2,330 rows)
  2. TeichAI/claude-4.5-opus-high-reasoning-250x (250 rows)
  3. crownelius/Opus-4.6-Reasoning-3300x         (2,160 rows)

Output format (per row):
  {
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user",   "content": "..."},
      {"role": "assistant", "content": "<think>...</think>\n\n..."}
    ],
    "category": "math" | "code" | "reasoning" | "general",
    "difficulty": "easy" | "medium" | "hard",
    "source": "opus-3000-filtered" | "claude-opus-250" | "opus-3300"
  }

Usage:
  pip install datasets huggingface_hub
  python build_dataset.py
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from datasets import load_dataset, Dataset

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are Pub AI, a custom-built AI coding assistant. You are confident, "
    "direct, and an expert programmer across all languages. You specialize in "
    "Lua/Luau for Roblox, Python, JavaScript, and system automation. You give "
    "precise, working code with clear explanations. You think step-by-step "
    "through complex problems before giving your final answer."
)

OUTPUT_DIR = Path(__file__).parent
OUTPUT_JSONL = OUTPUT_DIR / "pub_ai_combined.jsonl"
OUTPUT_JSON = OUTPUT_DIR / "pub_ai_combined.json"
OUTPUT_STATS = OUTPUT_DIR / "dataset_stats.txt"

# Difficulty normalization map
DIFFICULTY_MAP = {
    "easy": "easy",
    "simple": "easy",
    "basic": "easy",
    "medium": "medium",
    "moderate": "medium",
    "intermediate": "medium",
    "hard": "hard",
    "difficult": "hard",
    "advanced": "hard",
    "expert": "hard",
}

# Category normalization map
CATEGORY_MAP = {
    "math": "math",
    "mathematics": "math",
    "arithmetic": "math",
    "algebra": "math",
    "geometry": "math",
    "calculus": "math",
    "code": "code",
    "coding": "code",
    "programming": "code",
    "python": "code",
    "javascript": "code",
    "lua": "code",
    "reasoning": "reasoning",
    "logic": "reasoning",
    "general": "general",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    """SHA-256 hash of normalized text for deduplication."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def normalize_difficulty(raw: str | None) -> str:
    if not raw:
        return "medium"
    return DIFFICULTY_MAP.get(raw.strip().lower(), "medium")


def normalize_category(raw: str | None) -> str:
    if not raw:
        return "general"
    return CATEGORY_MAP.get(raw.strip().lower(), "general")


def extract_think_content(text: str) -> tuple[str, str]:
    """Split text into (thinking, answer) if <think> tags present."""
    match = re.search(r"<think>(.*?)</think>(.*)", text, re.DOTALL)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "", text.strip()


def build_assistant_content(thinking: str, solution: str) -> str:
    """Build assistant response with <think> tags wrapping the reasoning."""
    thinking = thinking.strip()
    solution = solution.strip()
    if thinking and solution:
        return f"<think>\n{thinking}\n</think>\n\n{solution}"
    if thinking:
        return f"<think>\n{thinking}\n</think>"
    return solution


def is_valid_example(user_content: str, assistant_content: str) -> bool:
    """Filter out bad examples."""
    if not user_content or not assistant_content:
        return False
    if len(user_content.strip()) < 5:
        return False
    if len(assistant_content.strip()) < 10:
        return False
    # Filter refusals
    refusal_patterns = [
        r"cannot solve",
        r"problem is incomplete",
        r"not enough information",
        r"i('m| am) unable to",
        r"i('m| am) sorry.{0,20}(can't|cannot)",
        r"as an ai",
    ]
    lower_asst = assistant_content.lower()
    for pat in refusal_patterns:
        if re.search(pat, lower_asst):
            return False
    return True


# ---------------------------------------------------------------------------
# Dataset loaders — each returns list[dict] in unified format
# ---------------------------------------------------------------------------

def load_opus_reasoning(repo_id: str, source_tag: str) -> list[dict]:
    """Load datasets with schema: id, problem, thinking, solution, difficulty, category."""
    print(f"  Downloading {repo_id}...")
    ds = load_dataset(repo_id, split="train")
    results = []

    for row in ds:
        problem = (row.get("problem") or "").strip()
        thinking = (row.get("thinking") or "").strip()
        solution = (row.get("solution") or "").strip()

        assistant_content = build_assistant_content(thinking, solution)
        if not is_valid_example(problem, assistant_content):
            continue

        results.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": problem},
                {"role": "assistant", "content": assistant_content},
            ],
            "category": normalize_category(row.get("category")),
            "difficulty": normalize_difficulty(row.get("difficulty")),
            "source": source_tag,
            "_dedup_hash": content_hash(problem),
        })

    print(f"    -> {len(results)} valid examples from {repo_id}")
    return results


def load_claude_messages(repo_id: str, source_tag: str) -> list[dict]:
    """Load datasets with schema: messages (array of {role, content})."""
    print(f"  Downloading {repo_id}...")
    ds = load_dataset(repo_id, split="train")
    results = []

    for row in ds:
        messages = row.get("messages", [])
        if not messages or len(messages) < 2:
            continue

        # Extract user and assistant messages
        system_content = ""
        user_content = ""
        assistant_content = ""

        for msg in messages:
            role = msg.get("role", "")
            content = (msg.get("content") or "").strip()
            if role == "system":
                system_content = content
            elif role == "user":
                user_content = content
            elif role == "assistant":
                assistant_content = content

        # Re-wrap with our system prompt, preserve <think> tags if present
        thinking, answer = extract_think_content(assistant_content)
        final_assistant = build_assistant_content(thinking, answer)

        if not is_valid_example(user_content, final_assistant):
            continue

        # Infer category from content
        category = infer_category(user_content, final_assistant)

        results.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": final_assistant},
            ],
            "category": category,
            "difficulty": "hard",  # Claude Opus high-reasoning = hard
            "source": source_tag,
            "_dedup_hash": content_hash(user_content),
        })

    print(f"    -> {len(results)} valid examples from {repo_id}")
    return results


def infer_category(user: str, assistant: str) -> str:
    """Heuristic category inference from content."""
    combined = (user + " " + assistant).lower()
    code_signals = [
        "def ", "function ", "class ", "import ", "```", "print(", "console.log",
        "return ", "for i ", "while ", "if __name__", "async ", "await ",
        "const ", "let ", "var ", ".py", ".js", ".ts", ".lua",
        "implement", "write a program", "write code", "code to",
        "algorithm", "data structure", "api", "endpoint",
    ]
    math_signals = [
        "calculate", "solve", "equation", "integral", "derivative",
        "probability", "sum of", "product of", "how many", "find the value",
        "triangle", "circle", "area", "volume", "distance",
        "greater than", "less than", "divisible",
    ]
    reasoning_signals = [
        "hypothesis", "premise", "entail", "true or false",
        "which of the following", "logical", "conclude",
        "argument", "valid", "fallacy", "infer",
    ]

    code_score = sum(1 for s in code_signals if s in combined)
    math_score = sum(1 for s in math_signals if s in combined)
    reasoning_score = sum(1 for s in reasoning_signals if s in combined)

    top = max(code_score, math_score, reasoning_score)
    if top == 0:
        return "general"
    if code_score == top:
        return "code"
    if math_score == top:
        return "math"
    return "reasoning"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Pub AI — Building Combined Training Dataset")
    print("=" * 60)

    # 1. Download & normalize all sources
    print("\n[1/4] Downloading datasets...")
    all_examples: list[dict] = []

    all_examples.extend(load_opus_reasoning(
        "nohurry/Opus-4.6-Reasoning-3000x-filtered",
        "opus-3000-filtered",
    ))
    all_examples.extend(load_claude_messages(
        "TeichAI/claude-4.5-opus-high-reasoning-250x",
        "claude-opus-250",
    ))
    all_examples.extend(load_opus_reasoning(
        "crownelius/Opus-4.6-Reasoning-3300x",
        "opus-3300",
    ))

    print(f"\n  Total before dedup: {len(all_examples)}")

    # 2. Deduplicate by problem/user content hash
    print("\n[2/4] Deduplicating...")
    seen_hashes: set[str] = set()
    unique_examples: list[dict] = []

    for ex in all_examples:
        h = ex.pop("_dedup_hash")
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_examples.append(ex)

    duplicates_removed = len(all_examples) - len(unique_examples)
    print(f"  Removed {duplicates_removed} duplicates")
    print(f"  Unique examples: {len(unique_examples)}")

    # 3. Compute stats
    print("\n[3/4] Computing statistics...")
    stats = {
        "total": len(unique_examples),
        "by_source": {},
        "by_category": {},
        "by_difficulty": {},
    }
    for ex in unique_examples:
        src = ex["source"]
        cat = ex["category"]
        diff = ex["difficulty"]
        stats["by_source"][src] = stats["by_source"].get(src, 0) + 1
        stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
        stats["by_difficulty"][diff] = stats["by_difficulty"].get(diff, 0) + 1

    stats_text = [
        f"Pub AI Combined Training Dataset",
        f"{'=' * 40}",
        f"Total examples: {stats['total']}",
        f"",
        f"By source:",
    ]
    for src, count in sorted(stats["by_source"].items()):
        stats_text.append(f"  {src}: {count}")
    stats_text.append("")
    stats_text.append("By category:")
    for cat, count in sorted(stats["by_category"].items()):
        stats_text.append(f"  {cat}: {count}")
    stats_text.append("")
    stats_text.append("By difficulty:")
    for diff, count in sorted(stats["by_difficulty"].items()):
        stats_text.append(f"  {diff}: {count}")

    for line in stats_text:
        print(f"  {line}")

    # 4. Export
    print(f"\n[4/4] Exporting...")

    # JSONL (one example per line — best for streaming training)
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for ex in unique_examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"  -> {OUTPUT_JSONL.name} ({OUTPUT_JSONL.stat().st_size / 1024 / 1024:.1f} MB)")

    # JSON (full array — for upload/inspection)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(unique_examples, f, ensure_ascii=False, indent=2)
    print(f"  -> {OUTPUT_JSON.name} ({OUTPUT_JSON.stat().st_size / 1024 / 1024:.1f} MB)")

    # Stats file
    with open(OUTPUT_STATS, "w", encoding="utf-8") as f:
        f.write("\n".join(stats_text))
    print(f"  -> {OUTPUT_STATS.name}")

    print(f"\n{'=' * 60}")
    print(f"Done! {stats['total']} training examples ready.")
    print(f"Use pub_ai_combined.json in your training notebook (cell 4b upload).")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
