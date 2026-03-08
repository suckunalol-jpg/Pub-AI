"""FastAPI router for training pipeline endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from training.config import training_settings, BASE_MODELS
from training.jobs import JobManager, JobType, JobStatus, job_manager

router = APIRouter(prefix="/api/training", tags=["training"])


# ---------- Request / Response schemas ----------

class MergeRequest(BaseModel):
    source_models: List[str] = list(BASE_MODELS.values())
    merge_method: str = "slerp"
    interpolation_factor: float = 0.5
    output_path: str = ""


class FinetuneRequest(BaseModel):
    base_model: str = BASE_MODELS.get("qwen", "")
    dataset_path: str = ""
    lora_rank: int = 64
    lora_alpha: int = 128
    learning_rate: float = 2e-4
    epochs: int = 3
    batch_size: int = 4
    max_seq_length: int = 4096
    use_4bit: bool = True


class RLHFRequest(BaseModel):
    base_model: str = ""
    beta: float = 0.1
    learning_rate: float = 5e-5
    epochs: int = 1
    batch_size: int = 2
    max_seq_length: int = 2048


class ExportRequest(BaseModel):
    model_dir: str
    format: str = "gguf"  # gguf | vllm | ollama
    quantization: str = "q4_k_m"
    ollama_model_name: str = ""


class JobResponse(BaseModel):
    id: str
    job_type: str
    status: str
    config: Dict[str, Any] = {}
    metrics: Dict[str, Any] = {}
    logs: List[str] = []
    error: Optional[str] = None
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# ---------- Model merge ----------

@router.post("/merge", response_model=JobResponse)
async def start_merge(req: MergeRequest):
    """Start a model merge job."""
    from training.merge import MergeConfig, merge_models

    cfg = MergeConfig(
        source_models=req.source_models,
        merge_method=req.merge_method,
        interpolation_factor=req.interpolation_factor,
        output_path=req.output_path,
    )

    def run_merge(job):
        job.log(f"Merging {len(cfg.source_models)} models via {cfg.merge_method}")
        result = merge_models(cfg)
        job.log(f"Merge status: {result['status']}")
        return result

    job = job_manager.create_job(JobType.MERGE, cfg.__dict__, run_merge)
    return job.to_dict()


# ---------- Fine-tuning ----------

@router.post("/finetune", response_model=JobResponse)
async def start_finetune(req: FinetuneRequest):
    """Start a LoRA fine-tuning job."""
    from training.finetune import FinetuneConfig, run_finetune

    if not req.dataset_path:
        raise HTTPException(400, "dataset_path is required")

    cfg = FinetuneConfig(
        base_model=req.base_model,
        dataset_path=req.dataset_path,
        lora_rank=req.lora_rank,
        lora_alpha=req.lora_alpha,
        learning_rate=req.learning_rate,
        epochs=req.epochs,
        batch_size=req.batch_size,
        max_seq_length=req.max_seq_length,
        use_4bit=req.use_4bit,
    )

    def run_ft(job):
        job.log(f"Fine-tuning {cfg.base_model} with LoRA rank={cfg.lora_rank}")
        result = run_finetune(cfg)
        job.log(f"Training loss: {result['metrics'].get('train_loss', 'N/A')}")
        return result

    job = job_manager.create_job(JobType.FINETUNE, cfg.__dict__, run_ft)
    return job.to_dict()


# ---------- RLHF / DPO ----------

@router.post("/rlhf", response_model=JobResponse)
async def start_rlhf(req: RLHFRequest, db: AsyncSession = Depends(get_db)):
    """Start DPO training from user feedback."""
    from training.rlhf import DPOConfig, extract_preference_pairs, save_preference_dataset, run_dpo_training
    from training.config import training_settings

    # Extract preference pairs from feedback
    pairs = await extract_preference_pairs(db)
    if not pairs:
        raise HTTPException(400, "No preference pairs found. Need both liked and disliked feedback on the same prompts.")

    # Save pairs to disk
    dataset_path = str(
        Path(training_settings.DATASETS_DIR) / "dpo_preferences.jsonl"
    )
    save_preference_dataset(pairs, dataset_path)

    cfg = DPOConfig(
        base_model=req.base_model or "",
        dataset_path=dataset_path,
        beta=req.beta,
        learning_rate=req.learning_rate,
        epochs=req.epochs,
        batch_size=req.batch_size,
        max_seq_length=req.max_seq_length,
    )

    def run_dpo(job):
        job.log(f"DPO training with {len(pairs)} preference pairs")
        result = run_dpo_training(cfg)
        return result

    job = job_manager.create_job(JobType.RLHF, cfg.__dict__, run_dpo)
    return job.to_dict()


# ---------- Dataset upload ----------

@router.post("/upload-dataset")
async def upload_dataset(
    file: UploadFile = File(...),
    dataset_type: str = Form("qa"),  # qa | code | conversation
    file_format: str = Form("json"),  # json | text | csv
):
    """Upload Q&A, code, or conversation training data."""
    from training.data_prep import (
        load_qa_dataset,
        load_code_dataset,
        save_dataset,
        compute_stats,
    )

    content = (await file.read()).decode("utf-8")

    if dataset_type == "qa":
        examples = load_qa_dataset(content, file_format)
    elif dataset_type == "code":
        examples = load_code_dataset(content)
    elif dataset_type == "conversation":
        data = json.loads(content)
        examples = data if isinstance(data, list) else [data]
    else:
        raise HTTPException(400, f"Unknown dataset_type: {dataset_type}")

    if not examples:
        raise HTTPException(400, "No valid examples found in the uploaded file")

    # Save to datasets directory
    safe_name = file.filename.rsplit(".", 1)[0] if file.filename else "upload"
    output_path = str(
        Path(training_settings.DATASETS_DIR) / f"{safe_name}.jsonl"
    )
    save_dataset(examples, output_path)
    stats = compute_stats(examples)

    return {
        "status": "uploaded",
        "path": output_path,
        "examples": stats.total_examples,
        "approx_tokens": stats.total_tokens_approx,
        "avg_turns": stats.avg_turns,
    }


# ---------- Export model ----------

@router.post("/export", response_model=JobResponse)
async def export_model(req: ExportRequest):
    """Export a trained model to GGUF, vLLM, or register with Ollama."""
    from training.finetune import export_to_gguf, export_to_vllm, register_with_ollama

    def run_export(job):
        if req.format == "gguf":
            job.log(f"Exporting to GGUF ({req.quantization})")
            return export_to_gguf(req.model_dir, req.quantization)
        elif req.format == "vllm":
            job.log("Preparing for vLLM serving")
            return export_to_vllm(req.model_dir)
        elif req.format == "ollama":
            job.log("Registering with Ollama")
            gguf_result = export_to_gguf(req.model_dir, req.quantization)
            if gguf_result["status"] != "completed":
                return gguf_result
            return register_with_ollama(
                gguf_result["gguf_path"],
                req.ollama_model_name or training_settings.OLLAMA_MODEL_NAME,
            )
        else:
            return {"status": "failed", "error": f"Unknown format: {req.format}"}

    job = job_manager.create_job(JobType.EXPORT, req.model_dump(), run_export)
    return job.to_dict()


# ---------- Job management ----------

@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    job_type: Optional[str] = None,
    status: Optional[str] = None,
):
    """List all training jobs with optional filters."""
    jt = JobType(job_type) if job_type else None
    js = JobStatus(status) if status else None
    return job_manager.list_jobs(job_type=jt, status=js)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    """Get status and metrics for a specific training job."""
    result = job_manager.get_job_status(job_id)
    if not result:
        raise HTTPException(404, "Job not found")
    return result


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a running training job."""
    if job_manager.cancel_job(job_id):
        return {"status": "cancelled", "job_id": job_id}
    raise HTTPException(404, "Job not found or already completed")


# ---------- Dataset listing ----------

@router.get("/datasets")
async def list_datasets():
    """List available training datasets."""
    datasets_dir = Path(training_settings.DATASETS_DIR)
    if not datasets_dir.exists():
        return {"datasets": []}

    datasets = []
    for f in datasets_dir.glob("*.jsonl"):
        line_count = sum(1 for _ in open(f, encoding="utf-8"))
        datasets.append({
            "name": f.stem,
            "path": str(f),
            "examples": line_count,
            "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
        })

    return {"datasets": datasets}


# ---------- Auto-retrain ----------

@router.post("/auto-retrain/trigger")
async def trigger_auto_retrain():
    """Manually trigger the auto-retraining data export."""
    from training.auto_retrain import auto_retrainer

    result = await auto_retrainer.export_and_train()
    return result


@router.get("/auto-retrain/status")
async def auto_retrain_status():
    """Get auto-retraining status."""
    from training.auto_retrain import auto_retrainer

    return auto_retrainer.status()


# ---------- Model listing ----------

@router.get("/models")
async def list_models():
    """List available trained models."""
    output_dir = Path(training_settings.TRAINING_OUTPUT_DIR)
    if not output_dir.exists():
        return {"models": []}

    models = []
    for d in output_dir.iterdir():
        if d.is_dir() and (d / "config.json").exists():
            models.append({
                "name": d.name,
                "path": str(d),
                "type": "hf",
            })
        # Also check for GGUF files
        for gguf in d.glob("*.gguf") if d.is_dir() else []:
            models.append({
                "name": gguf.stem,
                "path": str(gguf),
                "type": "gguf",
                "size_mb": round(gguf.stat().st_size / (1024 * 1024), 2),
            })

    return {"models": models}
