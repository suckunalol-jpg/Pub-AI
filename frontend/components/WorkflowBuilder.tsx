"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Plus,
  Trash2,
  Play,
  GripVertical,
  MessageSquare,
  Code,
  GitBranch,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn, generateId } from "@/lib/utils";
import * as api from "@/lib/api";

type StepType = "ai" | "code" | "condition";

interface WorkflowStep {
  id: string;
  type: StepType;
  label: string;
  config: string; // prompt, code, or condition expression
}

interface WorkflowRun {
  id: string;
  status: "running" | "completed" | "failed";
  startedAt: Date;
  steps: { stepId: string; status: string; output?: string }[];
}

const stepTypeConfig: Record<StepType, { icon: React.ElementType; label: string; placeholder: string }> = {
  ai: { icon: MessageSquare, label: "AI Prompt", placeholder: "Enter the prompt for the AI..." },
  code: { icon: Code, label: "Code Execution", placeholder: "Enter code to execute..." },
  condition: { icon: GitBranch, label: "Condition", placeholder: "Enter condition expression..." },
};

export default function WorkflowBuilder() {
  const [name, setName] = useState("");
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [isRunning, setIsRunning] = useState(false);

  const addStep = (type: StepType) => {
    setSteps((prev) => [
      ...prev,
      { id: generateId(), type, label: stepTypeConfig[type].label, config: "" },
    ]);
  };

  const removeStep = (id: string) => {
    setSteps((prev) => prev.filter((s) => s.id !== id));
  };

  const updateStep = (id: string, config: string) => {
    setSteps((prev) => prev.map((s) => (s.id === id ? { ...s, config } : s)));
  };

  const moveStep = (index: number, direction: -1 | 1) => {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= steps.length) return;
    const newSteps = [...steps];
    [newSteps[index], newSteps[newIndex]] = [newSteps[newIndex], newSteps[index]];
    setSteps(newSteps);
  };

  const handleRun = async () => {
    if (steps.length === 0 || !name.trim()) return;
    setIsRunning(true);
    try {
      const workflow = await api.createWorkflow(
        name,
        steps.map((s, i) => ({
          id: s.id,
          type: s.type,
          prompt: s.type === "ai" ? s.config : undefined,
          code: s.type === "code" ? s.config : undefined,
          condition: s.type === "condition" ? s.config : undefined,
          depends_on: i > 0 ? [steps[i - 1].id] : [],
        }))
      );
      const run = await api.runWorkflow(workflow.id);
      setRuns((prev) => [
        {
          id: run.run_id,
          status: "running",
          startedAt: new Date(),
          steps: steps.map((s) => ({ stepId: s.id, status: "pending" })),
        },
        ...prev,
      ]);
    } catch {
      // TODO: error handling
    } finally {
      setIsRunning(false);
    }
  };

  const runStatusIcon = (status: string) => {
    switch (status) {
      case "running": return <Loader2 size={14} className="animate-spin text-accent" />;
      case "completed": return <CheckCircle2 size={14} className="text-green-400" />;
      case "failed": return <XCircle size={14} className="text-red-400" />;
      default: return <Clock size={14} className="text-gray-500" />;
    }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Workflows</h2>
        <button
          onClick={handleRun}
          disabled={steps.length === 0 || !name.trim() || isRunning}
          className="flex items-center gap-2 px-4 py-1.5 text-sm rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all"
        >
          {isRunning ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
          Run
        </button>
      </div>

      {/* Workflow name */}
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Workflow name..."
        className="glass-input px-4 py-3 text-sm w-full"
      />

      {/* Steps */}
      <div className="space-y-3">
        <AnimatePresence>
          {steps.map((step, index) => {
            const config = stepTypeConfig[step.type];
            const Icon = config.icon;
            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -20 }}
                layout
              >
                <GlassCard className="p-4">
                  <div className="flex items-start gap-3">
                    {/* Drag handle + index */}
                    <div className="flex flex-col items-center gap-1 pt-1">
                      <button onClick={() => moveStep(index, -1)} className="text-gray-600 hover:text-gray-400 transition-colors">
                        <GripVertical size={14} />
                      </button>
                      <span className="text-xs text-gray-600 font-mono">{index + 1}</span>
                    </div>

                    {/* Step icon */}
                    <div className="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0">
                      <Icon size={16} className="text-accent" />
                    </div>

                    {/* Step content */}
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-medium text-gray-400">{config.label}</span>
                        <button
                          onClick={() => removeStep(step.id)}
                          className="p-1 rounded hover:bg-red-500/20 text-gray-600 hover:text-red-400 transition-colors"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                      <textarea
                        value={step.config}
                        onChange={(e) => updateStep(step.id, e.target.value)}
                        placeholder={config.placeholder}
                        rows={2}
                        className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 resize-none outline-none focus:border-accent/30 transition-colors"
                      />
                    </div>
                  </div>
                </GlassCard>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      {/* Add step buttons */}
      <div className="flex gap-2">
        {(["ai", "code", "condition"] as StepType[]).map((type) => {
          const config = stepTypeConfig[type];
          const Icon = config.icon;
          return (
            <button
              key={type}
              onClick={() => addStep(type)}
              className="flex items-center gap-2 px-3 py-2 text-xs rounded-xl bg-white/5 border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 transition-all"
            >
              <Icon size={14} />
              <Plus size={12} />
              {config.label}
            </button>
          );
        })}
      </div>

      {/* Run History */}
      {runs.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-300 mb-3">Run History</h3>
          <div className="space-y-2">
            {runs.map((run) => (
              <GlassCard key={run.id} className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    {runStatusIcon(run.status)}
                    <span className="text-sm text-white">{run.id.substring(0, 8)}</span>
                    <span className="text-xs text-gray-500 capitalize">{run.status}</span>
                  </div>
                  <span className="text-xs text-gray-600">
                    {run.startedAt.toLocaleTimeString()}
                  </span>
                </div>
              </GlassCard>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
