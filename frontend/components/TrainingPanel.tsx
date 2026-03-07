"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Play,
  Square,
  Upload,
  Trash2,
  Check,
  Loader2,
  AlertCircle,
  Download,
  Sliders,
  Database,
  ThumbsUp,
  ThumbsDown,
  Server,
  X,
  FileText,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import GlassCard from "@/components/GlassCard";
import * as api from "@/lib/api";

type Tab = "finetune" | "merge" | "datasets" | "rlhf" | "models";

const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "finetune", label: "Fine-tune", icon: Sliders },
  { id: "merge", label: "Merge", icon: Server },
  { id: "datasets", label: "Datasets", icon: Database },
  { id: "rlhf", label: "Feedback", icon: ThumbsUp },
  { id: "models", label: "Models", icon: Download },
];

// --- Types ---

interface TrainingJob {
  id: string;
  type: string;
  status: string;
  progress: number;
  total_steps: number;
  current_step: number;
  loss_history: number[];
  started_at: string;
  config: Record<string, unknown>;
}

interface Dataset {
  id: string;
  name: string;
  size: number;
  type: string;
  created_at: string;
}

interface Model {
  id: string;
  name: string;
  type: string;
  size_mb: number;
  created_at: string;
  dataset_used?: string;
  is_active: boolean;
}

// --- Sub-components ---

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    queued: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
    running: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    completed: "bg-green-500/20 text-green-400 border-green-500/30",
    failed: "bg-red-500/20 text-red-400 border-red-500/30",
  };
  return (
    <span className={cn("px-2 py-0.5 rounded-full text-xs border", colors[status] || colors.queued)}>
      {status}
    </span>
  );
}

function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="w-full bg-white/5 rounded-full h-2 overflow-hidden">
      <div
        className="h-full bg-accent rounded-full transition-all duration-300"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function LossChart({ data }: { data: number[] }) {
  if (data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const h = 60;
  const w = 200;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <div className="mt-2">
      <p className="text-[10px] text-gray-500 mb-1">Loss</p>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-[60px]">
        <polyline fill="none" stroke="rgb(59,130,246)" strokeWidth="2" points={points} />
      </svg>
    </div>
  );
}

function DurationTimer({ startedAt }: { startedAt: string }) {
  const [elapsed, setElapsed] = useState("");
  useEffect(() => {
    const start = new Date(startedAt).getTime();
    const tick = () => {
      const diff = Math.floor((Date.now() - start) / 1000);
      const m = Math.floor(diff / 60);
      const s = diff % 60;
      setElapsed(`${m}m ${s}s`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  return (
    <span className="text-xs text-gray-400 flex items-center gap-1">
      <Clock size={12} /> {elapsed}
    </span>
  );
}

// --- Tabs ---

function FinetuneTab() {
  const [baseModel, setBaseModel] = useState("deepseek-coder");
  const [lr, setLr] = useState("2e-5");
  const [epochs, setEpochs] = useState("3");
  const [batchSize, setBatchSize] = useState("4");
  const [loraRank, setLoraRank] = useState("16");
  const [datasetId, setDatasetId] = useState("");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [starting, setStarting] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [ds, j] = await Promise.all([api.listDatasets(), api.getTrainingJobs()]);
      setDatasets(ds);
      setJobs(j.filter((job) => job.type === "finetune") as TrainingJob[]);
    } catch {}
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleStart = async () => {
    setStarting(true);
    try {
      await api.startFinetune({
        base_model: baseModel,
        learning_rate: parseFloat(lr),
        epochs: parseInt(epochs),
        batch_size: parseInt(batchSize),
        lora_rank: parseInt(loraRank),
        dataset_id: datasetId,
      });
      await loadData();
    } catch {}
    setStarting(false);
  };

  const handleCancel = async (id: string) => {
    try {
      await api.cancelJob(id);
      await loadData();
    } catch {}
  };

  return (
    <div className="space-y-6">
      <GlassCard className="p-6">
        <h3 className="text-white font-semibold mb-4">Configuration</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Base Model</label>
            <select
              value={baseModel}
              onChange={(e) => setBaseModel(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            >
              <option value="deepseek-coder">DeepSeek Coder</option>
              <option value="qwen-coder">Qwen Coder</option>
              <option value="merged">Merged Model</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Dataset</label>
            <select
              value={datasetId}
              onChange={(e) => setDatasetId(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            >
              <option value="">Select dataset...</option>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Learning Rate</label>
            <input
              value={lr}
              onChange={(e) => setLr(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Epochs</label>
            <input
              type="number"
              value={epochs}
              onChange={(e) => setEpochs(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">Batch Size</label>
            <input
              type="number"
              value={batchSize}
              onChange={(e) => setBatchSize(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">LoRA Rank</label>
            <input
              type="number"
              value={loraRank}
              onChange={(e) => setLoraRank(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            />
          </div>
        </div>
        <button
          onClick={handleStart}
          disabled={starting || !datasetId}
          className="mt-4 flex items-center gap-2 px-4 py-2 bg-accent/20 border border-accent/30 rounded-xl text-accent hover:bg-accent/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {starting ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          Start Training
        </button>
      </GlassCard>

      {jobs.length > 0 && (
        <GlassCard className="p-6">
          <h3 className="text-white font-semibold mb-4">Active Jobs</h3>
          <div className="space-y-4">
            {jobs.map((job) => (
              <div key={job.id} className="bg-white/5 rounded-xl p-4 border border-white/5">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <StatusBadge status={job.status} />
                    <span className="text-sm text-gray-300">{job.id.slice(0, 8)}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {job.status === "running" && <DurationTimer startedAt={job.started_at} />}
                    {(job.status === "queued" || job.status === "running") && (
                      <button
                        onClick={() => handleCancel(job.id)}
                        className="p-1 rounded hover:bg-red-500/20 text-gray-400 hover:text-red-400 transition-colors"
                      >
                        <Square size={14} />
                      </button>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
                  <span>{job.current_step} / {job.total_steps} steps</span>
                </div>
                <ProgressBar value={job.current_step} max={job.total_steps} />
                <LossChart data={job.loss_history} />
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  );
}

function MergeTab() {
  const [selected, setSelected] = useState<string[]>([]);
  const [method, setMethod] = useState("slerp");
  const [factor, setFactor] = useState(0.5);
  const [starting, setStarting] = useState(false);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);

  const models = [
    { id: "deepseek-coder", label: "DeepSeek Coder" },
    { id: "qwen-coder", label: "Qwen Coder" },
  ];

  const loadJobs = useCallback(async () => {
    try {
      const j = await api.getTrainingJobs();
      setJobs(j.filter((job: TrainingJob) => job.type === "merge"));
    } catch {}
  }, []);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]
    );
  };

  const handleStart = async () => {
    if (selected.length < 2) return;
    setStarting(true);
    try {
      await api.startMerge({
        models: selected,
        method,
        interpolation_factor: factor,
      });
      await loadJobs();
    } catch {}
    setStarting(false);
  };

  return (
    <div className="space-y-6">
      <GlassCard className="p-6">
        <h3 className="text-white font-semibold mb-4">Model Merge</h3>

        <div className="mb-4">
          <label className="text-xs text-gray-400 block mb-2">Select Models (at least 2)</label>
          <div className="space-y-2">
            {models.map((m) => (
              <button
                key={m.id}
                onClick={() => toggle(m.id)}
                className={cn(
                  "w-full flex items-center gap-3 px-4 py-2.5 rounded-xl border transition-colors text-left",
                  selected.includes(m.id)
                    ? "bg-accent/15 border-accent/30 text-white"
                    : "bg-white/5 border-white/10 text-gray-400 hover:bg-white/10"
                )}
              >
                <div className={cn(
                  "w-4 h-4 rounded border flex items-center justify-center",
                  selected.includes(m.id) ? "bg-accent border-accent" : "border-white/20"
                )}>
                  {selected.includes(m.id) && <Check size={10} className="text-white" />}
                </div>
                <span className="text-sm">{m.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Merge Method</label>
            <select
              value={method}
              onChange={(e) => setMethod(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-accent/50"
            >
              <option value="slerp">SLERP</option>
              <option value="ties">TIES</option>
              <option value="dare">DARE</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-400 block mb-1">
              Blend Factor: {factor.toFixed(2)}
            </label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={factor}
              onChange={(e) => setFactor(parseFloat(e.target.value))}
              className="w-full accent-blue-500 mt-2"
            />
          </div>
        </div>

        <button
          onClick={handleStart}
          disabled={starting || selected.length < 2}
          className="flex items-center gap-2 px-4 py-2 bg-accent/20 border border-accent/30 rounded-xl text-accent hover:bg-accent/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {starting ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          Start Merge
        </button>
      </GlassCard>

      {jobs.length > 0 && (
        <GlassCard className="p-6">
          <h3 className="text-white font-semibold mb-4">Merge Jobs</h3>
          <div className="space-y-3">
            {jobs.map((job) => (
              <div key={job.id} className="bg-white/5 rounded-xl p-4 border border-white/5">
                <div className="flex items-center justify-between mb-2">
                  <StatusBadge status={job.status} />
                  <span className="text-xs text-gray-400">{job.id.slice(0, 8)}</span>
                </div>
                <ProgressBar value={job.current_step} max={job.total_steps} />
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  );
}

function DatasetsTab() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dragging, setDragging] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [pasteName, setPasteName] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDatasets(await api.listDatasets());
    } catch {}
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        const ext = file.name.split(".").pop()?.toLowerCase() || "txt";
        const type = ext === "json" ? "json" : ext === "csv" ? "csv" : "text";
        await api.uploadDataset(file, type);
      }
      await load();
    } catch {}
    setUploading(false);
  };

  const handlePaste = async () => {
    if (!pasteText.trim() || !pasteName.trim()) return;
    setUploading(true);
    try {
      const blob = new Blob([pasteText], { type: "text/plain" });
      const file = new File([blob], `${pasteName}.txt`, { type: "text/plain" });
      await api.uploadDataset(file, "text");
      setPasteText("");
      setPasteName("");
      await load();
    } catch {}
    setUploading(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteDataset(id);
      await load();
    } catch {}
  };

  const handleExportChat = async () => {
    setUploading(true);
    try {
      await api.exportChatDataset();
      await load();
    } catch {}
    setUploading(false);
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="space-y-6">
      {/* Upload area */}
      <GlassCard className="p-6">
        <h3 className="text-white font-semibold mb-4">Upload Dataset</h3>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}
          onClick={() => fileInputRef.current?.click()}
          className={cn(
            "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
            dragging ? "border-accent bg-accent/10" : "border-white/10 hover:border-white/20"
          )}
        >
          <Upload size={32} className="mx-auto mb-2 text-gray-400" />
          <p className="text-sm text-gray-400">
            {uploading ? "Uploading..." : "Drop files here or click to browse"}
          </p>
          <p className="text-xs text-gray-500 mt-1">Supports JSON, CSV, TXT</p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".json,.csv,.txt"
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
        </div>
      </GlassCard>

      {/* Paste Q&A */}
      <GlassCard className="p-6">
        <h3 className="text-white font-semibold mb-4">Paste Training Data</h3>
        <input
          value={pasteName}
          onChange={(e) => setPasteName(e.target.value)}
          placeholder="Dataset name"
          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white mb-3 focus:outline-none focus:border-accent/50"
        />
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder="Paste Q&A pairs, one per line (question | answer)"
          rows={4}
          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white resize-none focus:outline-none focus:border-accent/50"
        />
        <div className="flex gap-3 mt-3">
          <button
            onClick={handlePaste}
            disabled={uploading || !pasteText.trim() || !pasteName.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-accent/20 border border-accent/30 rounded-xl text-accent hover:bg-accent/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Upload size={16} />
            Save Dataset
          </button>
          <button
            onClick={handleExportChat}
            disabled={uploading}
            className="flex items-center gap-2 px-4 py-2 bg-white/5 border border-white/10 rounded-xl text-gray-300 hover:bg-white/10 transition-colors disabled:opacity-40"
          >
            <FileText size={16} />
            Export from Chat History
          </button>
        </div>
      </GlassCard>

      {/* Dataset list */}
      <GlassCard className="p-6">
        <h3 className="text-white font-semibold mb-4">Datasets</h3>
        {datasets.length === 0 ? (
          <p className="text-sm text-gray-500">No datasets uploaded yet.</p>
        ) : (
          <div className="space-y-2">
            {datasets.map((d) => (
              <div key={d.id} className="flex items-center justify-between bg-white/5 rounded-xl px-4 py-3 border border-white/5">
                <div className="flex items-center gap-3">
                  <Database size={16} className="text-gray-400" />
                  <div>
                    <p className="text-sm text-white">{d.name}</p>
                    <p className="text-xs text-gray-500">
                      {d.type} &middot; {formatSize(d.size)} &middot; {new Date(d.created_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(d.id)}
                  className="p-1.5 rounded hover:bg-red-500/20 text-gray-400 hover:text-red-400 transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
}

function RlhfTab() {
  const [stats, setStats] = useState({ liked: 0, disliked: 0, pairs: 0 });
  const [starting, setStarting] = useState(false);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);

  const load = useCallback(async () => {
    try {
      const j = await api.getTrainingJobs();
      setJobs(j.filter((job: TrainingJob) => job.type === "rlhf"));
    } catch {}
    try {
      const s = await api.getFeedbackStats();
      setStats(s);
    } catch {}
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleStart = async () => {
    setStarting(true);
    try {
      await api.startRLHF();
      await load();
    } catch {}
    setStarting(false);
  };

  return (
    <div className="space-y-6">
      <GlassCard className="p-6">
        <h3 className="text-white font-semibold mb-2">Train from User Feedback</h3>
        <p className="text-sm text-gray-400 mb-6">
          Improve responses by learning from your likes and dislikes. The model trains on your
          preference data to better match your expectations.
        </p>

        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-white/5 rounded-xl p-4 text-center border border-white/5">
            <ThumbsUp size={20} className="mx-auto mb-2 text-green-400" />
            <p className="text-2xl font-bold text-white">{stats.liked}</p>
            <p className="text-xs text-gray-400">Liked</p>
          </div>
          <div className="bg-white/5 rounded-xl p-4 text-center border border-white/5">
            <ThumbsDown size={20} className="mx-auto mb-2 text-red-400" />
            <p className="text-2xl font-bold text-white">{stats.disliked}</p>
            <p className="text-xs text-gray-400">Disliked</p>
          </div>
          <div className="bg-white/5 rounded-xl p-4 text-center border border-white/5">
            <Database size={20} className="mx-auto mb-2 text-blue-400" />
            <p className="text-2xl font-bold text-white">{stats.pairs}</p>
            <p className="text-xs text-gray-400">Preference Pairs</p>
          </div>
        </div>

        <button
          onClick={handleStart}
          disabled={starting || stats.pairs === 0}
          className="flex items-center gap-2 px-4 py-2 bg-accent/20 border border-accent/30 rounded-xl text-accent hover:bg-accent/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {starting ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          Start DPO Training
        </button>
      </GlassCard>

      {jobs.length > 0 && (
        <GlassCard className="p-6">
          <h3 className="text-white font-semibold mb-4">Training Jobs</h3>
          <div className="space-y-3">
            {jobs.map((job) => (
              <div key={job.id} className="bg-white/5 rounded-xl p-4 border border-white/5">
                <div className="flex items-center justify-between mb-2">
                  <StatusBadge status={job.status} />
                  {job.status === "running" && <DurationTimer startedAt={job.started_at} />}
                </div>
                <ProgressBar value={job.current_step} max={job.total_steps} />
                <LossChart data={job.loss_history} />
              </div>
            ))}
          </div>
        </GlassCard>
      )}
    </div>
  );
}

function ModelsTab() {
  const [models, setModels] = useState<Model[]>([]);
  const [exporting, setExporting] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setModels(await api.listModels());
    } catch {}
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleActivate = async (id: string) => {
    setActivating(id);
    try {
      await api.setActiveModel(id);
      await load();
    } catch {}
    setActivating(null);
  };

  const handleExport = async (id: string, format: string) => {
    setExporting(id);
    try {
      await api.exportModel(id, format);
    } catch {}
    setExporting(null);
  };

  const formatSize = (mb: number) => {
    if (mb < 1024) return `${mb.toFixed(0)} MB`;
    return `${(mb / 1024).toFixed(1)} GB`;
  };

  const typeBadge: Record<string, string> = {
    base: "bg-gray-500/20 text-gray-400 border-gray-500/30",
    finetuned: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    merged: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  };

  return (
    <div className="space-y-6">
      <GlassCard className="p-6">
        <h3 className="text-white font-semibold mb-4">Available Models</h3>
        {models.length === 0 ? (
          <p className="text-sm text-gray-500">No models available.</p>
        ) : (
          <div className="space-y-3">
            {models.map((m) => (
              <div key={m.id} className={cn(
                "bg-white/5 rounded-xl p-4 border transition-colors",
                m.is_active ? "border-accent/30" : "border-white/5"
              )}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-white">{m.name}</span>
                    <span className={cn("px-2 py-0.5 rounded-full text-xs border", typeBadge[m.type] || typeBadge.base)}>
                      {m.type}
                    </span>
                    {m.is_active && (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-green-500/20 text-green-400 border border-green-500/30">
                        active
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-xs text-gray-500 mb-3 flex items-center gap-3">
                  <span>{formatSize(m.size_mb)}</span>
                  <span>{new Date(m.created_at).toLocaleDateString()}</span>
                  {m.dataset_used && <span>Dataset: {m.dataset_used}</span>}
                </div>
                <div className="flex items-center gap-2">
                  {!m.is_active && (
                    <button
                      onClick={() => handleActivate(m.id)}
                      disabled={activating === m.id}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-accent/20 border border-accent/30 rounded-lg text-xs text-accent hover:bg-accent/30 transition-colors disabled:opacity-40"
                    >
                      {activating === m.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                      Set as Active
                    </button>
                  )}
                  <button
                    onClick={() => handleExport(m.id, "ollama")}
                    disabled={exporting === m.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-gray-300 hover:bg-white/10 transition-colors disabled:opacity-40"
                  >
                    {exporting === m.id ? <Loader2 size={12} className="animate-spin" /> : <Server size={12} />}
                    Deploy to Ollama
                  </button>
                  <button
                    onClick={() => handleExport(m.id, "gguf")}
                    disabled={exporting === m.id}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-gray-300 hover:bg-white/10 transition-colors disabled:opacity-40"
                  >
                    {exporting === m.id ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                    Export GGUF
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
}

// --- Main Component ---

export default function TrainingPanel() {
  const [activeTab, setActiveTab] = useState<Tab>("finetune");

  return (
    <div className="flex-1 flex flex-col p-6 overflow-hidden">
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white mb-1">Training</h2>
        <p className="text-sm text-gray-400">Fine-tune, merge, and manage your AI models</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-6 bg-black/20 backdrop-blur-sm p-1 rounded-xl border border-white/5 w-fit">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all duration-200",
                isActive
                  ? "bg-accent/15 text-accent border border-accent/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              )}
            >
              <Icon size={16} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-white/10">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.15 }}
          >
            {activeTab === "finetune" && <FinetuneTab />}
            {activeTab === "merge" && <MergeTab />}
            {activeTab === "datasets" && <DatasetsTab />}
            {activeTab === "rlhf" && <RlhfTab />}
            {activeTab === "models" && <ModelsTab />}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
