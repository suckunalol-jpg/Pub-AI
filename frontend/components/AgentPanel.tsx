"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Bot,
  Plus,
  Square,
  Send,
  Code,
  Search,
  Terminal,
  Gamepad2,
  Users,
  Loader2,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Clock,
  Eye,
  Clipboard,
  Brain,
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn } from "@/lib/utils";
import * as api from "@/lib/api";

const agentTypes = [
  { id: "coder", label: "Coder", icon: Code, description: "Writes, debugs, and refactors code" },
  { id: "researcher", label: "Researcher", icon: Search, description: "Searches and synthesizes information" },
  { id: "executor", label: "Executor", icon: Terminal, description: "Runs code and validates output" },
  { id: "planner", label: "Planner", icon: Brain, description: "Plans and coordinates sub-agents" },
  { id: "reviewer", label: "Reviewer", icon: Eye, description: "Reviews code quality and security" },
  { id: "roblox", label: "Roblox", icon: Gamepad2, description: "Luau/Roblox specialist" },
] as const;

type AgentType = (typeof agentTypes)[number]["id"];

interface Agent {
  id: string;
  type: string;
  name: string;
  task: string;
  status: "running" | "completed" | "failed" | "stopped";
  result?: string;
  iterations?: number;
  toolsUsed?: number;
  expanded?: boolean;
}

interface TeamConfig {
  name: string;
  task: string;
  agents: { type: AgentType; role: string }[];
}

const statusIcon = (status: string) => {
  switch (status) {
    case "running": return <Loader2 size={14} className="text-green-400 animate-spin" />;
    case "completed": return <CheckCircle2 size={14} className="text-blue-400" />;
    case "failed": return <XCircle size={14} className="text-red-400" />;
    default: return <Clock size={14} className="text-gray-400" />;
  }
};

export default function AgentPanel() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedType, setSelectedType] = useState<AgentType>("coder");
  const [task, setTask] = useState("");
  const [spawning, setSpawning] = useState(false);
  const [error, setError] = useState("");
  const [showTeamBuilder, setShowTeamBuilder] = useState(false);
  const [teamConfig, setTeamConfig] = useState<TeamConfig>({ name: "", task: "", agents: [] });
  const [chatAgent, setChatAgent] = useState<{ id: string; message: string } | null>(null);

  // Poll running agents every 5s
  useEffect(() => {
    const running = agents.filter((a) => a.status === "running");
    if (running.length === 0) return;

    const interval = setInterval(async () => {
      for (const agent of running) {
        try {
          const status = await api.getAgentStatus(agent.id);
          setAgents((prev) =>
            prev.map((a) =>
              a.id === agent.id
                ? {
                  ...a,
                  status: status.status as Agent["status"],
                  result: (status.result?.content || status.result?.error) as string | undefined,
                  iterations: status.result?.iterations as number | undefined,
                  toolsUsed: status.result?.tools_used as number | undefined,
                }
                : a
            )
          );
        } catch {
          // ignore poll errors
        }
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [agents]);

  const handleSpawn = useCallback(async () => {
    if (!task.trim()) return;
    setSpawning(true);
    setError("");
    try {
      const res = await api.spawnAgent(selectedType, task);
      setAgents((prev) => [
        { id: res.id, type: selectedType, name: res.agent_name || selectedType, task, status: "running" },
        ...prev,
      ]);
      setTask("");
    } catch (err: any) {
      setError(err.message || "Failed to spawn agent");
    } finally {
      setSpawning(false);
    }
  }, [task, selectedType]);

  const handleStop = async (agentId: string) => {
    try {
      await api.stopAgent(agentId);
      setAgents((prev) =>
        prev.map((a) => (a.id === agentId ? { ...a, status: "stopped" } : a))
      );
    } catch (err: any) {
      setError(err.message || "Failed to stop agent");
    }
  };

  const handleMessage = async (agentId: string, message: string) => {
    if (!message.trim()) return;
    try {
      const res = await api.messageAgent(agentId, message);
      setAgents((prev) =>
        prev.map((a) =>
          a.id === agentId
            ? { ...a, result: (a.result ? a.result + "\n\n" : "") + res.response }
            : a
        )
      );
      setChatAgent(null);
    } catch (err: any) {
      setError(err.message || "Failed to message agent");
    }
  };

  const handleCreateTeam = async () => {
    if (!teamConfig.name || !teamConfig.task || teamConfig.agents.length === 0) return;
    setError("");
    try {
      const res = await api.createTeam(teamConfig.name, teamConfig.agents);
      // Spawn agents for the team task
      for (const agentDef of teamConfig.agents) {
        try {
          const spawned = await api.spawnAgent(agentDef.type, `[Team: ${teamConfig.name}] ${teamConfig.task}`);
          setAgents((prev) => [
            { id: spawned.id, type: agentDef.type, name: spawned.agent_name || agentDef.type, task: teamConfig.task, status: "running" },
            ...prev,
          ]);
        } catch {
          // continue spawning others
        }
      }
      setTeamConfig({ name: "", task: "", agents: [] });
      setShowTeamBuilder(false);
    } catch (err: any) {
      setError(err.message || "Failed to create team");
    }
  };

  const toggleExpand = (id: string) => {
    setAgents((prev) => prev.map((a) => a.id === id ? { ...a, expanded: !a.expanded } : a));
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Agents</h2>
        <button
          onClick={() => setShowTeamBuilder(!showTeamBuilder)}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 text-sm glass-button",
            showTeamBuilder ? "text-accent" : "text-gray-400 hover:text-white"
          )}
        >
          <Users size={16} />
          Team Builder
        </button>
      </div>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="px-4 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm"
          >
            {error}
            <button onClick={() => setError("")} className="ml-2 text-red-300 hover:text-white">&times;</button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Spawn Agent */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-gray-300 mb-4">Spawn Agent</h3>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
          {agentTypes.map((type) => {
            const Icon = type.icon;
            return (
              <button
                key={type.id}
                onClick={() => setSelectedType(type.id)}
                title={type.description}
                className={cn(
                  "flex flex-col items-center gap-1.5 p-3 rounded-xl border transition-all text-xs",
                  selectedType === type.id
                    ? "bg-accent/15 border-accent/30 text-accent"
                    : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:bg-white/10"
                )}
              >
                <Icon size={18} />
                <span className="font-medium">{type.label}</span>
              </button>
            );
          })}
        </div>

        <div className="flex gap-2">
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Describe the task for the agent..."
            rows={2}
            className="flex-1 glass-input px-4 py-2.5 text-sm resize-none"
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSpawn();
              }
            }}
          />
          <button
            onClick={handleSpawn}
            disabled={!task.trim() || spawning}
            className="px-4 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all flex items-center gap-2 self-end py-2.5"
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
            <GlassCard className="p-5 space-y-3">
              <h3 className="text-sm font-medium text-gray-300">Build a Team</h3>
              <input
                value={teamConfig.name}
                onChange={(e) => setTeamConfig((c) => ({ ...c, name: e.target.value }))}
                placeholder="Team name..."
                className="w-full glass-input px-4 py-2.5 text-sm"
              />
              <textarea
                value={teamConfig.task}
                onChange={(e) => setTeamConfig((c) => ({ ...c, task: e.target.value }))}
                placeholder="Team goal / task description..."
                rows={2}
                className="w-full glass-input px-4 py-2.5 text-sm resize-none"
              />
              <div className="flex flex-wrap gap-2">
                {teamConfig.agents.map((a, i) => (
                  <span key={i} className="px-2 py-1 rounded-lg bg-accent/10 text-accent text-xs flex items-center gap-1">
                    {a.type}
                    <button onClick={() => setTeamConfig((c) => ({ ...c, agents: c.agents.filter((_, idx) => idx !== i) }))} className="text-gray-500 hover:text-white">&times;</button>
                  </span>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
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
                disabled={!teamConfig.name || !teamConfig.task || teamConfig.agents.length === 0}
                className="w-full py-2.5 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all text-sm font-medium"
              >
                Create Team ({teamConfig.agents.length} agents)
              </button>
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Active Agents */}
      <div>
        <h3 className="text-sm font-medium text-gray-300 mb-3">
          Agents {agents.length > 0 && (
            <span className="text-gray-500">
              ({agents.filter((a) => a.status === "running").length} running / {agents.length} total)
            </span>
          )}
        </h3>
        {agents.length === 0 ? (
          <GlassCard className="p-8 text-center">
            <Bot size={32} className="text-gray-600 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No agents spawned yet</p>
            <p className="text-xs text-gray-600 mt-1">Select a type, describe a task, and click Spawn</p>
          </GlassCard>
        ) : (
          <div className="space-y-2">
            {agents.map((agent) => {
              const typeInfo = agentTypes.find((t) => t.id === agent.type);
              const Icon = typeInfo?.icon || Bot;
              return (
                <GlassCard key={agent.id} className="overflow-hidden">
                  <div
                    className="p-4 flex items-center gap-3 cursor-pointer hover:bg-white/5 transition-colors"
                    onClick={() => toggleExpand(agent.id)}
                  >
                    <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center flex-shrink-0">
                      <Icon size={16} className="text-accent" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white capitalize">{agent.type}</span>
                        <span className="flex items-center gap-1 text-xs">
                          {statusIcon(agent.status)}
                          <span className={cn(
                            agent.status === "running" ? "text-green-400" :
                              agent.status === "completed" ? "text-blue-400" :
                                "text-gray-400"
                          )}>{agent.status}</span>
                        </span>
                        {agent.iterations && (
                          <span className="text-[10px] text-gray-500">{agent.iterations} iters</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 truncate">{agent.task}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      {agent.status === "running" && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleStop(agent.id); }}
                          className="p-1.5 rounded-lg hover:bg-red-500/20 text-gray-400 hover:text-red-400 transition-colors"
                          title="Stop agent"
                        >
                          <Square size={14} />
                        </button>
                      )}
                      {agent.expanded ? <ChevronDown size={14} className="text-gray-500" /> : <ChevronRight size={14} className="text-gray-500" />}
                    </div>
                  </div>

                  {/* Expanded details */}
                  <AnimatePresence>
                    {agent.expanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="border-t border-white/5"
                      >
                        <div className="p-4 space-y-3">
                          {/* Result */}
                          {agent.result && (
                            <div className="bg-black/30 rounded-lg p-3 max-h-60 overflow-y-auto">
                              <div className="flex items-center justify-between mb-2">
                                <span className="text-[10px] text-gray-500 uppercase tracking-wider">Result</span>
                                <button
                                  onClick={() => navigator.clipboard.writeText(agent.result || "")}
                                  className="text-gray-500 hover:text-white transition-colors"
                                  title="Copy result"
                                >
                                  <Clipboard size={12} />
                                </button>
                              </div>
                              <pre className="text-xs text-gray-300 whitespace-pre-wrap break-words font-mono">
                                {agent.result}
                              </pre>
                            </div>
                          )}

                          {/* Stats */}
                          {(agent.iterations || agent.toolsUsed) && (
                            <div className="flex gap-4 text-[10px] text-gray-500">
                              {agent.iterations && <span>Iterations: {agent.iterations}</span>}
                              {agent.toolsUsed && <span>Tools used: {agent.toolsUsed}</span>}
                            </div>
                          )}

                          {/* Chat with agent */}
                          {agent.status === "running" && (
                            <div className="flex gap-2">
                              <input
                                value={chatAgent?.id === agent.id ? chatAgent.message : ""}
                                onChange={(e) => setChatAgent({ id: agent.id, message: e.target.value })}
                                onFocus={() => !chatAgent && setChatAgent({ id: agent.id, message: "" })}
                                placeholder="Message this agent..."
                                className="flex-1 glass-input px-3 py-2 text-xs"
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" && chatAgent) {
                                    handleMessage(agent.id, chatAgent.message);
                                  }
                                }}
                              />
                              <button
                                onClick={() => chatAgent && handleMessage(agent.id, chatAgent.message)}
                                className="p-2 rounded-lg bg-accent/20 text-accent hover:bg-accent/30 transition-colors"
                              >
                                <Send size={12} />
                              </button>
                            </div>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </GlassCard>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
