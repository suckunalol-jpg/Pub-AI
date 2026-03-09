"use client";

import { motion } from "framer-motion";
import { Bot, Users, ChevronRight, ExternalLink } from "lucide-react";
import { useAgentTabStore, type AgentTabType } from "@/lib/agentTabStore";
import { cn } from "@/lib/utils";

export interface AgentNode {
    agentId: string;
    name: string;
    type: AgentTabType;
    task: string;
    status: "running" | "done" | "error";
    children?: AgentNode[];
}

interface AgentBranchViewProps {
    agents: AgentNode[];
    parentName?: string;
    isTeam?: boolean;
}

function AgentCard({ agent, depth = 0 }: { agent: AgentNode; depth?: number }) {
    const { openTab } = useAgentTabStore();

    const handleClick = () => {
        openTab({
            agentId: agent.agentId,
            name: agent.name,
            type: agent.type,
            task: agent.task,
            status: agent.status,
        });
    };

    return (
        <div className="flex flex-col">
            <motion.button
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: depth * 0.1 }}
                onClick={handleClick}
                className={cn(
                    "group flex items-center gap-3 px-4 py-3 rounded-xl border transition-all",
                    "bg-white/[0.03] border-white/10 hover:bg-white/[0.08] hover:border-white/20",
                    "cursor-pointer text-left"
                )}
            >
                {/* Icon */}
                <div
                    className={cn(
                        "w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0",
                        agent.type === "sub-agent"
                            ? "bg-cyan-500/15"
                            : "bg-purple-500/15"
                    )}
                >
                    {agent.type === "sub-agent" ? (
                        <Bot size={16} className="text-cyan-400" />
                    ) : (
                        <Users size={16} className="text-purple-400" />
                    )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white truncate">
                            {agent.name}
                        </span>
                        <span
                            className={cn(
                                "w-1.5 h-1.5 rounded-full flex-shrink-0",
                                agent.status === "running"
                                    ? "bg-green-400 animate-pulse"
                                    : agent.status === "error"
                                        ? "bg-red-400"
                                        : "bg-gray-500"
                            )}
                        />
                    </div>
                    <p className="text-xs text-gray-500 truncate mt-0.5">{agent.task}</p>
                </div>

                {/* Open tab arrow */}
                <ExternalLink
                    size={14}
                    className="text-gray-600 group-hover:text-white transition-colors flex-shrink-0"
                />
            </motion.button>

            {/* Sub-agents (recursive) */}
            {agent.children && agent.children.length > 0 && (
                <div className="ml-6 mt-2 pl-4 border-l border-white/10 flex flex-col gap-2">
                    {agent.children.map((child) => (
                        <AgentCard key={child.agentId} agent={child} depth={depth + 1} />
                    ))}
                </div>
            )}
        </div>
    );
}

export default function AgentBranchView({
    agents,
    parentName = "Pub AI",
    isTeam = false,
}: AgentBranchViewProps) {
    return (
        <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="mx-8 my-4 rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden"
        >
            {/* Header */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-white/5">
                <div className={cn(
                    "w-7 h-7 rounded-lg flex items-center justify-center",
                    isTeam ? "bg-purple-500/15" : "bg-blue-500/15"
                )}>
                    {isTeam ? (
                        <Users size={14} className="text-purple-400" />
                    ) : (
                        <Bot size={14} className="text-blue-400" />
                    )}
                </div>
                <div>
                    <span className="text-sm font-medium text-white">
                        {isTeam ? "Team Manager" : parentName}
                    </span>
                    <span className="text-xs text-gray-500 ml-2">
                        {isTeam
                            ? `spawned ${agents.length} team agent${agents.length !== 1 ? "s" : ""}`
                            : `spawned ${agents.length} sub-agent${agents.length !== 1 ? "s" : ""}`}
                    </span>
                </div>
            </div>

            {/* Branch lines + agent cards */}
            <div className="p-4 flex flex-col gap-2">
                {agents.map((agent, idx) => (
                    <div key={agent.agentId} className="flex items-start gap-2">
                        {/* Branch connector */}
                        <div className="flex flex-col items-center pt-4 w-4 flex-shrink-0">
                            <div className="w-px h-2 bg-white/10" />
                            <ChevronRight size={10} className="text-gray-600" />
                            {idx < agents.length - 1 && (
                                <div className="w-px flex-1 bg-white/10 mt-0.5" />
                            )}
                        </div>

                        {/* Agent card */}
                        <div className="flex-1">
                            <AgentCard agent={agent} />
                        </div>
                    </div>
                ))}
            </div>
        </motion.div>
    );
}
