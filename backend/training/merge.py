"""Model merging pipeline using mergekit.

Merges DeepSeek Coder and Qwen Coder into a single base model.
Grok-1 is 314B MoE and too large to merge directly -- its reasoning
patterns are incorporated via training data and system prompts instead.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from training.config import BASE_MODELS, training_settings


@dataclass
class MergeConfig:
    source_models: List[str] = field(default_factory=lambda: list(BASE_MODELS.values()))
    merge_method: str = "slerp"  # slerp | ties | dare_ties | dare_linear
    interpolation_factor: float = 0.5
    output_path: str = ""
    dtype: str = "bfloat16"

    def __post_init__(self):
        if not self.output_path:
            self.output_path = str(
                Path(training_settings.TRAINING_OUTPUT_DIR) / "merged"
            )


def generate_merge_config(cfg: MergeConfig) -> str:
    """Generate a mergekit YAML config from a MergeConfig."""

    if cfg.merge_method == "slerp":
        if len(cfg.source_models) != 2:
            raise ValueError("SLERP merge requires exactly 2 source models")
        config = {
            "slices": [
                {
                    "sources": [
                        {"model": cfg.source_models[0], "layer_range": [0, 32]},
                        {"model": cfg.source_models[1], "layer_range": [0, 32]},
                    ]
                }
            ],
            "merge_method": "slerp",
            "base_model": cfg.source_models[0],
            "parameters": {"t": cfg.interpolation_factor},
            "dtype": cfg.dtype,
        }
    elif cfg.merge_method in ("ties", "dare_ties", "dare_linear"):
        config = {
            "models": [
                {"model": m, "parameters": {"density": 0.5, "weight": 1.0}}
                for m in cfg.source_models
            ],
            "merge_method": cfg.merge_method,
            "base_model": cfg.source_models[0],
            "parameters": {"normalize": True},
            "dtype": cfg.dtype,
        }
    else:
        raise ValueError(f"Unsupported merge method: {cfg.merge_method}")

    return yaml.dump(config, default_flow_style=False)


def merge_models(cfg: Optional[MergeConfig] = None) -> Dict:
    """Run mergekit to merge source models.

    Returns a dict with status, output_path, and any logs.
    """
    if cfg is None:
        cfg = MergeConfig()

    yaml_content = generate_merge_config(cfg)
    output_path = Path(cfg.output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", delete=False
    ) as tmp:
        tmp.write(yaml_content)
        config_path = tmp.name

    cmd = [
        "mergekit-yaml",
        config_path,
        str(output_path),
        "--copy-tokenizer",
        "--lazy-unpickle",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

    return {
        "status": "completed" if result.returncode == 0 else "failed",
        "output_path": str(output_path),
        "config_yaml": yaml_content,
        "stdout": result.stdout[-2000:] if result.stdout else "",
        "stderr": result.stderr[-2000:] if result.stderr else "",
        "returncode": result.returncode,
    }
