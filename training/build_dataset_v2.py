#!/usr/bin/env python3
"""
Pub AI v2 Dataset Builder
Combines 25 HuggingFace datasets + 4 synthetic JSONL files.
Output: pub_ai_v2_combined.jsonl (ChatML format)
"""
import argparse
import hashlib
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

HF_TOKEN = os.environ.get("HF_TOKEN", "")

HF_DATASETS = [
    ("nohurry/Opus-4.6-Reasoning-3000x-filtered", None, "reasoning"),
    ("TeichAI/claude-4.5-opus-high-reasoning-250x", None, "reasoning"),
    ("crownelius/Opus-4.6-Reasoning-3300x", None, "reasoning"),
    ("TorpedoSoftware/Roblox-Luau-Reasoning-v1.0", 10000, "code"),
    ("Roblox/luau_corpus", 5000, "code"),
    ("Sky-T/Roblox-luau-coding_L1", None, "code"),
    ("Pinkstack/Roblox_Luau_CoT_conversational_sharegpt_lqv1", None, "code"),
    ("nilq/baby-python-and-lua", 2000, "code"),
    ("kefir090/luau_github", 2000, "code"),
    ("microsoft/rStar-Coder", 5000, "code"),
    ("spencer/software_slacks", 2000, "code"),
    ("togethercomputer/CoderForge-Preview", 5000, "code"),
    ("peteromallet/dataclaw-peteromallet", 5000, "general"),
    ("lucywingard/anthropic-code-backdoor-train-data", 2000, "code"),
    ("multimodal-reasoning-lab/Competitive-Programming", None, "reasoning"),
    ("multimodal-reasoning-lab/Physics", None, "reasoning"),
    ("open-r1/ioi", None, "reasoning"),
    ("sharmaarush/competetive_coding", None, "code"),
    ("Tensoic/FrontendCookbook", None, "code"),
    ("TeichAI/Claude-Opus-Dataclaw-Unredacted", 5000, "general"),
    ("yatin-superintelligence/Creative-Professionals-Agentic-Tasks-1M", 10000, "agentic"),
    ("GAIR/OpenSWE", 5000, "code"),
    ("SAIRfoundation/equational-theories-selected-problems", 2000, "reasoning"),
    ("0xZee/dataset-CoT-Advanced-Calculus-268", None, "reasoning"),
    ("N8Programs/llm-conscious", 1000, "general"),
]

SYNTHETIC_FILES = [
    "training/synthetic/tool_use.jsonl",
    "training/synthetic/kali_security.jsonl",
    "training/synthetic/environment_awareness.jsonl",
    "training/synthetic/proactive_behavior.jsonl",
]


def normalize_example(raw: dict, source: str, category: str) -> Optional[dict]:
    """
    Convert various HuggingFace dataset formats into a unified ChatML dict.

    Tries field patterns in order:
      1. 'messages' or 'conversations' (already ChatML-like)
      2. 'prompt' + 'response'
      3. 'instruction' + 'output'
      4. 'question' + 'answer'
      5. 'text' containing '<|im_start|>'
      6. 'input' + 'output'

    Returns None if no pattern matches or the resulting message list is
    missing at least one user and one assistant turn.
    """
    messages = None

    # Pattern 1: already a messages/conversations list
    for key in ("messages", "conversations"):
        if key in raw and isinstance(raw[key], list) and raw[key]:
            raw_msgs = raw[key]
            normalized = []
            for m in raw_msgs:
                if not isinstance(m, dict):
                    continue
                role = m.get("role") or m.get("from") or ""
                content = m.get("content") or m.get("value") or ""
                # Map ShareGPT role names to ChatML
                role_map = {
                    "human": "user",
                    "gpt": "assistant",
                    "system": "system",
                    "user": "user",
                    "assistant": "assistant",
                }
                role = role_map.get(str(role).lower(), str(role).lower())
                if role and content:
                    normalized.append({"role": role, "content": str(content)})
            if normalized:
                messages = normalized
                break

    # Pattern 2: prompt + response
    if messages is None and "prompt" in raw and "response" in raw:
        prompt = str(raw["prompt"]).strip()
        response = str(raw["response"]).strip()
        if prompt and response:
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response},
            ]

    # Pattern 3: instruction + output
    if messages is None and "instruction" in raw and "output" in raw:
        instruction = str(raw.get("instruction", "")).strip()
        inp = str(raw.get("input", "")).strip()
        output = str(raw["output"]).strip()
        if instruction and output:
            user_content = instruction
            if inp:
                user_content = f"{instruction}\n\n{inp}"
            messages = [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": output},
            ]

    # Pattern 4: question + answer
    if messages is None and "question" in raw and "answer" in raw:
        question = str(raw["question"]).strip()
        answer = str(raw["answer"]).strip()
        if question and answer:
            messages = [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]

    # Pattern 5: text field with ChatML markers
    if messages is None and "text" in raw:
        text = str(raw["text"])
        if "<|im_start|>" in text:
            parsed = []
            parts = text.split("<|im_start|>")
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                end_idx = part.find("<|im_end|>")
                block = part[:end_idx].strip() if end_idx != -1 else part.strip()
                newline_idx = block.find("\n")
                if newline_idx == -1:
                    continue
                role = block[:newline_idx].strip()
                content = block[newline_idx + 1:].strip()
                role_map = {
                    "human": "user",
                    "gpt": "assistant",
                    "system": "system",
                    "user": "user",
                    "assistant": "assistant",
                }
                role = role_map.get(role.lower(), role.lower())
                if role in ("user", "assistant", "system") and content:
                    parsed.append({"role": role, "content": content})
            if parsed:
                messages = parsed

    # Pattern 6: input + output (fallback)
    if messages is None and "input" in raw and "output" in raw:
        inp = str(raw["input"]).strip()
        out = str(raw["output"]).strip()
        if inp and out:
            messages = [
                {"role": "user", "content": inp},
                {"role": "assistant", "content": out},
            ]

    if not messages:
        return None

    # Validate: must have at least one user and one assistant message
    roles = {m["role"] for m in messages}
    if "user" not in roles or "assistant" not in roles:
        return None

    return {"messages": messages, "category": category, "source": source}


def dedup_hash(example: dict) -> str:
    """Return SHA256 of the concatenated content of all messages."""
    combined = "".join(m["content"] for m in example.get("messages", []))
    return hashlib.sha256(combined.encode("utf-8", errors="replace")).hexdigest()


def stream_hf_dataset(
    name: str, max_samples: Optional[int], category: str
) -> Iterator[dict]:
    """
    Stream a HuggingFace dataset and yield normalized ChatML examples.

    Tries streaming mode first; falls back to non-streaming on failure.
    All exceptions are caught and logged — yields nothing on error.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("datasets library not installed; skipping HF datasets.")
        return

    token = HF_TOKEN if HF_TOKEN else None
    count = 0

    def _try_streaming():
        nonlocal count
        try:
            ds = load_dataset(name, streaming=True, token=token, trust_remote_code=True)
            split = "train" if "train" in ds else list(ds.keys())[0]
            for raw in ds[split]:
                example = normalize_example(raw, source=name, category=category)
                if example is None:
                    continue
                yield example
                count += 1
                if max_samples is not None and count >= max_samples:
                    return
        except Exception as e:
            logger.warning(f"Streaming failed for {name}: {e}. Trying non-streaming...")
            raise

    try:
        yield from _try_streaming()
        return
    except Exception:
        pass

    # Non-streaming fallback
    try:
        ds = load_dataset(name, token=token, trust_remote_code=True)
        split = "train" if "train" in ds else list(ds.keys())[0]
        dataset = ds[split]
        limit = max_samples if max_samples is not None else len(dataset)
        for i, raw in enumerate(dataset):
            if i >= limit:
                break
            example = normalize_example(raw, source=name, category=category)
            if example is None:
                continue
            yield example
    except Exception as e:
        logger.warning(f"Failed to load dataset {name}: {e}")


def load_synthetic_files(paths: list, base_dir: Path) -> Iterator[dict]:
    """
    Yield parsed JSON objects from each synthetic JSONL file.

    Paths are resolved relative to base_dir (project root). Missing files
    are logged and skipped. Malformed lines are logged and skipped.
    """
    for rel_path in paths:
        full_path = base_dir / rel_path
        if not full_path.exists():
            logger.warning(f"Synthetic file not found, skipping: {full_path}")
            continue
        logger.info(f"Loading synthetic file: {full_path}")
        with open(full_path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    yield obj
                except json.JSONDecodeError as e:
                    logger.warning(f"{full_path}:{lineno}: JSON decode error: {e}")


def build_dataset(
    output_path: Path,
    max_total: Optional[int],
    include_hf: bool,
    include_synthetic: bool,
):
    """
    Main pipeline: stream all sources, deduplicate, write JSONL output.

    Prints progress every 1000 examples and a final category stats table.
    """
    seen_hashes: set = set()
    category_counts: dict = defaultdict(int)
    total_written = 0
    total_skipped_norm = 0
    total_skipped_dup = 0

    # Determine project root (parent of training/)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    output_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Writing output to: {output_path}")

    with open(output_path, "w", encoding="utf-8") as out_f:

        def _write_example(example: dict):
            nonlocal total_written, total_skipped_dup
            h = dedup_hash(example)
            if h in seen_hashes:
                total_skipped_dup += 1
                return
            seen_hashes.add(h)
            out_f.write(json.dumps(example, ensure_ascii=False) + "\n")
            category_counts[example.get("category", "unknown")] += 1
            total_written += 1
            if total_written % 1000 == 0:
                logger.info(
                    f"Progress: {total_written} written, "
                    f"{total_skipped_dup} duplicates, "
                    f"{total_skipped_norm} not normalizable"
                )

        # HuggingFace datasets
        if include_hf:
            for ds_name, ds_max, ds_cat in HF_DATASETS:
                if max_total is not None and total_written >= max_total:
                    logger.info("Reached max_total cap; stopping HF ingestion.")
                    break
                logger.info(f"Loading HF dataset: {ds_name} (max={ds_max}, cat={ds_cat})")
                effective_max = ds_max
                if max_total is not None:
                    remaining = max_total - total_written
                    if effective_max is None or effective_max > remaining:
                        effective_max = remaining
                for example in stream_hf_dataset(ds_name, effective_max, ds_cat):
                    if max_total is not None and total_written >= max_total:
                        break
                    _write_example(example)

        # Synthetic files
        if include_synthetic:
            logger.info("Loading synthetic files...")
            for raw in load_synthetic_files(SYNTHETIC_FILES, project_root):
                if max_total is not None and total_written >= max_total:
                    logger.info("Reached max_total cap; stopping synthetic ingestion.")
                    break
                # Synthetic files should already be in ChatML format;
                # try to normalize them anyway for consistency.
                source = raw.get("source", "synthetic")
                category = raw.get("category", "synthetic")
                if "messages" in raw:
                    example = normalize_example(raw, source=source, category=category)
                else:
                    example = normalize_example(raw, source=source, category=category)
                if example is None:
                    total_skipped_norm += 1
                    continue
                _write_example(example)

    # Final stats
    print("\n" + "=" * 50)
    print("Dataset Build Complete")
    print("=" * 50)
    print(f"Total examples written : {total_written}")
    print(f"Duplicates skipped     : {total_skipped_dup}")
    print(f"Not normalizable       : {total_skipped_norm}")
    print(f"Output file            : {output_path}")
    print("\nCategory breakdown:")
    print(f"  {'Category':<20} {'Count':>8}")
    print(f"  {'-'*20}  {'-'*8}")
    for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:<20} {cnt:>8}")
    print("=" * 50)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(
        description="Build Pub AI v2 training dataset from HuggingFace + synthetic sources."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("training/pub_ai_v2_combined.jsonl"),
        help="Output JSONL file path (default: training/pub_ai_v2_combined.jsonl)",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=None,
        metavar="N",
        help="Cap total number of examples written across all sources.",
    )
    parser.add_argument(
        "--no-hf",
        action="store_true",
        help="Skip HuggingFace datasets; only process synthetic files.",
    )
    parser.add_argument(
        "--no-synthetic",
        action="store_true",
        help="Skip synthetic files; only process HuggingFace datasets.",
    )
    args = parser.parse_args()

    include_hf = not args.no_hf
    include_synthetic = not args.no_synthetic

    if not include_hf and not include_synthetic:
        logger.error("Both --no-hf and --no-synthetic specified; nothing to do.")
        sys.exit(1)

    # Resolve output path relative to CWD if not absolute
    output_path = args.output if args.output.is_absolute() else Path.cwd() / args.output

    build_dataset(
        output_path=output_path,
        max_total=args.max_total,
        include_hf=include_hf,
        include_synthetic=include_synthetic,
    )


if __name__ == "__main__":
    main()
