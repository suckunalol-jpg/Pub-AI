"use client";

import { motion } from "framer-motion";
import { X, Bot, Users, MessageSquare } from "lucide-react";
import { useAgentTabStore, type AgentTab } from "@/lib/agentTabStore";
import { cn } from "@/lib/utils";

export default function AgentTabBar() {
    const { tabs, activeTabId, setActive, closeTab } = useAgentTabStore();

    // Don't render the tab bar if there are no agent tabs
    if (tabs.length === 0) return null;

    return (
        <div className="flex items-center gap-1 px-4 py-2 border-b border-white/5 overflow-x-auto scrollbar-hide bg-black/20">
            {/* Main Chat tab — always present */}
            <button
                onClick={() => setActive("main")}
                className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap",
                    activeTabId === "main"
                        ? "bg-white/10 text-white"
                        : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                )}
            >
                <MessageSquare size={13} />
                Main Chat
            </button>

            {/* Divider */}
            <div className="w-px h-4 bg-white/10 mx-1" />

            {/* Agent tabs */}
            {tabs.map((tab) => (
                <motion.div
                    key={tab.id}
                    initial={{ opacity: 0, x: -10, scale: 0.95 }}
                    animate={{ opacity: 1, x: 0, scale: 1 }}
                    exit={{ opacity: 0, x: -10, scale: 0.95 }}
                    transition={{ duration: 0.2 }}
                >
                    <button
                        onClick={() => setActive(tab.id)}
                        className={cn(
                            "group flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap",
                            activeTabId === tab.id
                                ? "bg-white/10 text-white"
                                : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
                        )}
                    >
                        {/* Icon based on type */}
                        {tab.type === "sub-agent" ? (
                            <Bot size={13} className="text-cyan-400" />
                        ) : (
                            <Users size={13} className="text-purple-400" />
                        )}

                        {/* Label */}
                        <span className="max-w-[120px] truncate">
                            {tab.type === "sub-agent" ? `Sub: ${tab.name}` : tab.name}
                        </span>

                        {/* Status dot */}
                        <span
                            className={cn(
                                "w-1.5 h-1.5 rounded-full flex-shrink-0",
                                tab.status === "running"
                                    ? "bg-green-400 animate-pulse"
                                    : tab.status === "error"
                                        ? "bg-red-400"
                                        : "bg-gray-500"
                            )}
                        />

                        {/* Close button */}
                        <span
                            onClick={(e) => {
                                e.stopPropagation();
                                closeTab(tab.id);
                            }}
                            className="ml-1 p-0.5 rounded hover:bg-white/10 text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                        >
                            <X size={10} />
                        </span>
                    </button>
                </motion.div>
            ))}
        </div>
    );
}
