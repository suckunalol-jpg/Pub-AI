"use client";

import { useState, useRef, useCallback, useEffect, useLayoutEffect } from "react";
import { motion } from "framer-motion";
import { Bot, Users, Send, ArrowLeft } from "lucide-react";
import { useAgentTabStore, type AgentTab } from "@/lib/agentTabStore";
import GlassCard from "./GlassCard";
import AgentBranchView, { type AgentNode } from "./AgentBranchView";
import * as api from "@/lib/api";
import { cn } from "@/lib/utils";

interface AgentMessage {
    id: string;
    role: "user" | "agent";
    content: string;
    timestamp: Date;
}

interface AgentChatTabProps {
    tab: AgentTab;
}

export default function AgentChatTab({ tab }: AgentChatTabProps) {
    const [messages, setMessages] = useState<AgentMessage[]>([]);
    const [input, setInput] = useState("");
    const [sending, setSending] = useState(false);
    const [agentState, setAgentState] = useState<Record<string, unknown> | null>(null);
    const [subAgents, setSubAgents] = useState<AgentNode[]>([]);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const { closeTab, setActive, updateStatus } = useAgentTabStore();

    // Poll agent status
    useEffect(() => {
        let mounted = true;
        const poll = async () => {
            try {
                const status = await api.getAgentStatus(tab.agentId);
                if (!mounted) return;
                updateStatus(tab.agentId, status.status as AgentTab["status"]);

                // Try to get detailed state for sub-agents
                try {
                    const state = await api.getAgentState(tab.agentId);
                    if (mounted) setAgentState(state);
                } catch {
                    // Detailed state not available
                }
            } catch {
                // Agent may have finished
            }
        };

        poll();
        const interval = setInterval(poll, 3000);
        return () => {
            mounted = false;
            clearInterval(interval);
        };
    }, [tab.agentId, updateStatus]);

    // Scroll on new messages
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    // Auto-resize textarea
    useLayoutEffect(() => {
        const ta = textareaRef.current;
        if (ta) {
            ta.style.height = "auto";
            ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
        }
    }, [input]);

    const handleSend = useCallback(async () => {
        const trimmed = input.trim();
        if (!trimmed || sending) return;

        const userMsg: AgentMessage = {
            id: `user-${Date.now()}`,
            role: "user",
            content: trimmed,
            timestamp: new Date(),
        };
        setMessages((prev) => [...prev, userMsg]);
        setInput("");
        setSending(true);

        try {
            const res = await api.messageAgent(tab.agentId, trimmed);
            const agentMsg: AgentMessage = {
                id: `agent-${Date.now()}`,
                role: "agent",
                content: typeof res.response === "string" ? res.response : JSON.stringify(res.response, null, 2),
                timestamp: new Date(),
            };
            setMessages((prev) => [...prev, agentMsg]);
        } catch (err: unknown) {
            const errorMsg: AgentMessage = {
                id: `error-${Date.now()}`,
                role: "agent",
                content: `Error: ${err instanceof Error ? err.message : "Failed to communicate with agent"}`,
                timestamp: new Date(),
            };
            setMessages((prev) => [...prev, errorMsg]);
        } finally {
            setSending(false);
        }
    }, [input, sending, tab.agentId]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="flex flex-col h-full">
            {/* Agent header */}
            <div className="flex items-center gap-3 px-6 py-4 border-b border-white/5">
                <button
                    onClick={() => setActive("main")}
                    className="p-1.5 rounded-lg hover:bg-white/5 text-gray-500 hover:text-white transition-colors"
                >
                    <ArrowLeft size={16} />
                </button>

                <div className={cn(
                    "w-9 h-9 rounded-xl flex items-center justify-center",
                    tab.type === "sub-agent" ? "bg-cyan-500/15" : "bg-purple-500/15"
                )}>
                    {tab.type === "sub-agent" ? (
                        <Bot size={18} className="text-cyan-400" />
                    ) : (
                        <Users size={18} className="text-purple-400" />
                    )}
                </div>

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500 uppercase tracking-wider">
                            {tab.type === "sub-agent" ? "Sub Agent" : "Team Agent"}
                        </span>
                        <span
                            className={cn(
                                "w-1.5 h-1.5 rounded-full",
                                tab.status === "running"
                                    ? "bg-green-400 animate-pulse"
                                    : tab.status === "error"
                                        ? "bg-red-400"
                                        : "bg-gray-500"
                            )}
                        />
                    </div>
                    <h3 className="text-white font-semibold text-sm truncate">{tab.name}</h3>
                </div>

                <button
                    onClick={() => closeTab(tab.id)}
                    className="px-3 py-1.5 rounded-lg text-xs text-gray-500 hover:text-red-400 hover:bg-white/5 transition-colors"
                >
                    Close
                </button>
            </div>

            {/* Task description bar */}
            <div className="px-6 py-2 border-b border-white/5 bg-white/[0.02]">
                <p className="text-xs text-gray-500">
                    <span className="text-gray-400 font-medium">Task:</span> {tab.task}
                </p>
            </div>

            {/* Messages area */}
            <div className="flex-1 overflow-y-auto py-4 px-6">
                {messages.length === 0 && (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                        <div className={cn(
                            "w-12 h-12 rounded-xl flex items-center justify-center mb-3",
                            tab.type === "sub-agent" ? "bg-cyan-500/10" : "bg-purple-500/10"
                        )}>
                            {tab.type === "sub-agent" ? (
                                <Bot size={24} className="text-cyan-400/50" />
                            ) : (
                                <Users size={24} className="text-purple-400/50" />
                            )}
                        </div>
                        <p className="text-gray-500 text-sm">
                            Send a message to communicate directly with this agent.
                        </p>
                        <p className="text-gray-600 text-xs mt-1">
                            You can give instructions, ask for updates, or modify their task.
                        </p>
                    </div>
                )}

                {messages.map((msg) => (
                    <motion.div
                        key={msg.id}
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        className={cn(
                            "mb-3 px-4 py-3 rounded-xl text-sm max-w-[85%]",
                            msg.role === "user"
                                ? "ml-auto bg-accent/10 text-white border border-accent/20"
                                : "mr-auto bg-white/5 text-gray-300 border border-white/5"
                        )}
                    >
                        <pre className="whitespace-pre-wrap font-sans break-words">{msg.content}</pre>
                    </motion.div>
                ))}

                {/* Sub-agents of this agent */}
                {subAgents.length > 0 && (
                    <AgentBranchView
                        agents={subAgents}
                        parentName={tab.name}
                    />
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="px-4 pb-4 pt-2">
                <GlassCard className="flex items-end gap-3 px-4 py-3">
                    <textarea
                        ref={textareaRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={`Message ${tab.name}...`}
                        rows={1}
                        className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 resize-none outline-none max-h-28"
                    />
                    <button
                        onClick={handleSend}
                        disabled={!input.trim() || sending}
                        className="flex-shrink-0 p-2 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                    >
                        <Send size={16} />
                    </button>
                </GlassCard>
            </div>
        </div>
    );
}
