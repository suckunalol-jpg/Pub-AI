"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Bot,
  Plus,
  Play,
  Square,
  Send,
  Code,
  Search,
  Terminal,
  Gamepad2,
  Users,
  Loader2,
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn, generateId } from "@/lib/utils";
import * as api from "@/lib/api";

const agentTypes = [
  { id: "code", label: "Code", icon: Code, description: "Writes, reviews, and debugs code" },
  { id: "research", label: "Research", icon: Search, description: "Searches knowledge and web" },
  { id: "executor", label: "Executor", icon: Terminal, description: "Runs code and validates output" },
  { id: "roblox", label: "Roblox", icon: Gamepad2, description: "Lua/Luau specialized agent" },
] as const;

type AgentType = (typeof agentTypes)[number]["id"];

interface Agent {
  id: string;
  type: AgentType;
  task: string;
  status: "running" | "completed" | "failed";
}

interface TeamConfig {
  name: string;
  agents: { type: AgentType; role: string }[];
}

export default function AgentPanel() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedType, setSelectedType] = useState<AgentType>("code");
  const [task, setTask] = useState("");
  const [spawning, setSpawning] = useState(false);
  const [showTeamBuilder, setShowTeamBuilder] = useState(false);
  const [teamConfig, setTeamConfig] = useState<TeamConfig>({ name: "", agents: [] });
  const [agentChat, setAgentChat] = useState<{ agentId: string; message: string } | null>(null);

  const handleSpawn = async () => {
    if (!task.trim()) return;
    setSpawning(true);
    try {
      const res = await api.spawnAgent(selectedType, task);
      setAgents((prev) => [
        ...prev,
        { id: res.id, type: selectedType, task, status: "running" },
      ]);
      setTask("");
    } catch {
      // TODO: error handling
    } finally {
      setSpawning(false);
    }
  };

  const handleStop = async (agentId: string) => {
    try {
      await api.stopAgent(agentId);
      setAgents((prev) =>
        prev.map((a) => (a.id === agentId ? { ...a, status: "completed" } : a))
      );
    } catch {
      // TODO: error handling
    }
  };

  const handleCreateTeam = async () => {
    if (!teamConfig.name || teamConfig.agents.length === 0) return;
    try {
      await api.createTeam(teamConfig.name, teamConfig.agents);
      setTeamConfig({ name: "", agents: [] });
      setShowTeamBuilder(false);
    } catch {
      // TODO: error handling
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case "running": return "text-green-400";
      case "completed": return "text-gray-400";
      case "failed": return "text-red-400";
      default: return "text-gray-400";
    }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Agents</h2>
        <button
          onClick={() => setShowTeamBuilder(!showTeamBuilder)}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400 hover:text-white glass-button"
        >
          <Users size={16} />
          Team Builder
        </button>
      </div>

      {/* Spawn Agent */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-gray-300 mb-4">Spawn Agent</h3>

        {/* Agent type selector */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
          {agentTypes.map((type) => {
            const Icon = type.icon;
            return (
              <button
                key={type.id}
                onClick={() => setSelectedType(type.id)}
                className={cn(
                  "flex flex-col items-center gap-2 p-3 rounded-xl border transition-all text-xs",
                  selectedType === type.id
                    ? "bg-accent/15 border-accent/30 text-accent"
                    : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:bg-white/10"
                )}
              >
                <Icon size={20} />
                <span className="font-medium">{type.label}</span>
              </button>
            );
          })}
        </div>

        {/* Task input */}
        <div className="flex gap-2">
          <input
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Describe the task..."
            className="flex-1 glass-input px-4 py-2.5 text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleSpawn()}
          />
          <button
            onClick={handleSpawn}
            disabled={!task.trim() || spawning}
            className="px-4 py-2.5 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all flex items-center gap-2"
          >
            {spawning ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
            Spawn
          </button>
        </div>
      </GlassCard>

      {/* Team Builder */}
      <AnimatePresence>
        {showTeamBuilder && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
            <GlassCard className="p-5">
              <h3 className="text-sm font-medium text-gray-300 mb-4">Build a Team</h3>
              <input
                value={teamConfig.name}
                onChange={(e) => setTeamConfig((c) => ({ ...c, name: e.target.value }))}
                placeholder="Team name..."
                className="w-full glass-input px-4 py-2.5 text-sm mb-3"
              />
              <div className="flex flex-wrap gap-2 mb-3">
                {teamConfig.agents.map((a, i) => (
                  <span key={i} className="px-2 py-1 rounded-lg bg-accent/10 text-accent text-xs">
                    {a.type} ({a.role})
                    <button onClick={() => setTeamConfig((c) => ({ ...c, agents: c.agents.filter((_, idx) => idx !== i) }))} className="ml-1 text-gray-500 hover:text-white">&times;</button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                {agentTypes.map((type) => (
                  <button
                    key={type.id}
                    onClick={() => setTeamConfig((c) => ({ ...c, agents: [...c.agents, { type: type.id, role: type.id }] }))}
                    className="px-2 py-1 text-xs rounded-lg bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                  >
                    + {type.label}
                  </button>
                ))}
              </div>
              <button
                onClick={handleCreateTeam}
                disabled={!teamConfig.name || teamConfig.agents.length === 0}
                className="mt-4 w-full py-2 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all text-sm font-medium"
              >
                Create Team
              </button>
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Active Agents */}
      <div>
        <h3 className="text-sm font-medium text-gray-300 mb-3">
          Active Agents {agents.length > 0 && `(${agents.filter((a) => a.status === "running").length})`}
        </h3>
        {agents.length === 0 ? (
          <GlassCard className="p-8 text-center">
            <Bot size={32} className="text-gray-600 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No agents spawned yet</p>
          </GlassCard>
        ) : (
          <div className="space-y-2">
            {agents.map((agent) => {
              const typeInfo = agentTypes.find((t) => t.id === agent.type);
              const Icon = typeInfo?.icon || Bot;
              return (
                <GlassCard key={agent.id} className="p-4 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
                    <Icon size={18} className="text-accent" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white capitalize">{agent.type} Agent</span>
                      <span className={cn("text-xs font-medium", statusColor(agent.status))}>
                        {agent.status}
                      </span>
                    </div>
                    <p className="text-xs text-gray-500 truncate">{agent.task}</p>
                  </div>
                  <div className="flex items-center gap-1">
                    {agent.status === "running" && (
                      <>
                        <button
                          onClick={() => setAgentChat({ agentId: agent.id, message: "" })}
                          className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                        >
                          <Send size={14} />
                        </button>
                        <button
                          onClick={() => handleStop(agent.id)}
                          className="p-2 rounded-lg hover:bg-red-500/20 text-gray-400 hover:text-red-400 transition-colors"
                        >
                          <Square size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </GlassCard>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
