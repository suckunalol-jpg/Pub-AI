"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
    X,
    Bot,
    Sparkles,
    Code,
    Search,
    Terminal,
    Gamepad2,
    Brain,
    Eye,
    Users,
    Plus,
    Loader2,
    Wand2,
    Edit3,
    Check,
    ChevronRight,
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn } from "@/lib/utils";
import * as api from "@/lib/api";

/* ── Agent type definitions (reused from original AgentPanel) ── */
const agentTypes = [
    { id: "general-purpose", label: "General", icon: Bot, description: "Multi-step tasks, research, and coordination" },
    { id: "coder", label: "Coder", icon: Code, description: "Writes, debugs, and refactors code" },
    { id: "researcher", label: "Researcher", icon: Search, description: "Searches and synthesizes information" },
    { id: "executor", label: "Executor", icon: Terminal, description: "Runs code and validates output" },
    { id: "planner", label: "Planner", icon: Brain, description: "Plans and coordinates sub-agents" },
    { id: "reviewer", label: "Reviewer", icon: Eye, description: "Reviews code quality and security" },
    { id: "roblox", label: "Roblox", icon: Gamepad2, description: "Luau/Roblox specialist" },
    { id: "browser", label: "Browser", icon: Search, description: "Browser automation and web interaction" },
] as const;

type AgentType = (typeof agentTypes)[number]["id"];
type CreationMode = "choose" | "manual" | "assisted";

interface AgentCreatorModalProps {
    open: boolean;
    onClose: () => void;
    onCreated?: (agent: { id: string; name: string; type: string }) => void;
}

export default function AgentCreatorModal({ open, onClose, onCreated }: AgentCreatorModalProps) {
    const [mode, setMode] = useState<CreationMode>("choose");
    const [selectedType, setSelectedType] = useState<AgentType>("coder");

    // Manual mode state
    const [manualName, setManualName] = useState("");
    const [manualPrompt, setManualPrompt] = useState("");

    // Pub Assist mode state
    const [assistName, setAssistName] = useState("");
    const [assistDescription, setAssistDescription] = useState("");
    const [generatedPrompt, setGeneratedPrompt] = useState("");
    const [generating, setGenerating] = useState(false);
    const [showGenerated, setShowGenerated] = useState(false);

    // Shared
    const [spawning, setSpawning] = useState(false);
    const [error, setError] = useState("");
    const [success, setSuccess] = useState("");

    const reset = useCallback(() => {
        setMode("choose");
        setManualName("");
        setManualPrompt("");
        setAssistName("");
        setAssistDescription("");
        setGeneratedPrompt("");
        setShowGenerated(false);
        setError("");
        setSuccess("");
    }, []);

    const handleClose = () => {
        reset();
        onClose();
    };

    /* ── Manual creation ── */
    const handleManualCreate = async () => {
        if (!manualName.trim() || !manualPrompt.trim()) return;
        setSpawning(true);
        setError("");
        try {
            const taskDesc = `[Agent: ${manualName}]\n\nSystem Prompt:\n${manualPrompt}`;
            const res = await api.spawnAgent(selectedType, taskDesc);
            setSuccess(`Agent "${manualName}" created successfully!`);
            onCreated?.({ id: res.id, name: manualName, type: selectedType });
            setTimeout(handleClose, 1500);
        } catch (err: any) {
            setError(err.message || "Failed to create agent");
        } finally {
            setSpawning(false);
        }
    };

    /* ── Pub AI Assist: generate improved prompt ── */
    const handleGeneratePrompt = async () => {
        if (!assistDescription.trim()) return;
        setGenerating(true);
        setError("");
        try {
            const response = await api.sendMessage(null,
                `You are an expert AI prompt engineer. The user wants to create a custom AI agent. Based on their description below, generate a detailed, well-structured system prompt for the agent. Output ONLY the system prompt text, nothing else.\n\nAgent Name: ${assistName || "Custom Agent"}\nAgent Type: ${selectedType}\nUser Description: ${assistDescription}`
            );
            setGeneratedPrompt(response.content);
            setShowGenerated(true);
        } catch (err: any) {
            setError(err.message || "Failed to generate prompt");
        } finally {
            setGenerating(false);
        }
    };

    /* ── Pub AI Assist: create with generated prompt ── */
    const handleAssistedCreate = async () => {
        if (!generatedPrompt.trim()) return;
        setSpawning(true);
        setError("");
        try {
            const name = assistName.trim() || "Custom Agent";
            const taskDesc = `[Agent: ${name}]\n\nSystem Prompt:\n${generatedPrompt}`;
            const res = await api.spawnAgent(selectedType, taskDesc);
            setSuccess(`Agent "${name}" created successfully!`);
            onCreated?.({ id: res.id, name, type: selectedType });
            setTimeout(handleClose, 1500);
        } catch (err: any) {
            setError(err.message || "Failed to create agent");
        } finally {
            setSpawning(false);
        }
    };

    if (!open) return null;

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                onClick={handleClose}
            >
                <motion.div
                    initial={{ scale: 0.92, opacity: 0, y: 20 }}
                    animate={{ scale: 1, opacity: 1, y: 0 }}
                    exit={{ scale: 0.92, opacity: 0, y: 20 }}
                    transition={{ type: "spring", damping: 25, stiffness: 350 }}
                    className="relative w-full max-w-2xl mx-4 max-h-[85vh] overflow-hidden"
                    onClick={(e) => e.stopPropagation()}
                >
                    <GlassCard className="overflow-hidden">
                        {/* ── Header ── */}
                        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
                            <div className="flex items-center gap-3">
                                <div className="w-9 h-9 rounded-xl bg-accent/15 flex items-center justify-center">
                                    <Bot size={18} className="text-accent" />
                                </div>
                                <div>
                                    <h2 className="text-lg font-semibold text-white">Create Agent</h2>
                                    <p className="text-xs text-gray-500">
                                        {mode === "choose"
                                            ? "Choose how you want to create your agent"
                                            : mode === "manual"
                                                ? "Write your own system prompt"
                                                : "Let Pub AI help craft the perfect prompt"}
                                    </p>
                                </div>
                            </div>
                            <button
                                onClick={handleClose}
                                className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                            >
                                <X size={18} />
                            </button>
                        </div>

                        {/* ── Body ── */}
                        <div className="px-6 py-5 overflow-y-auto max-h-[calc(85vh-80px)] space-y-5">
                            {/* Error & Success */}
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
                                {success && (
                                    <motion.div
                                        initial={{ opacity: 0, height: 0 }}
                                        animate={{ opacity: 1, height: "auto" }}
                                        exit={{ opacity: 0, height: 0 }}
                                        className="px-4 py-2 rounded-xl bg-green-500/10 border border-green-500/20 text-green-400 text-sm flex items-center gap-2"
                                    >
                                        <Check size={14} /> {success}
                                    </motion.div>
                                )}
                            </AnimatePresence>

                            {/* ── MODE: Choose ── */}
                            {mode === "choose" && (
                                <motion.div
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="grid grid-cols-1 sm:grid-cols-2 gap-4"
                                >
                                    {/* Create Your Own */}
                                    <button
                                        onClick={() => setMode("manual")}
                                        className="group relative flex flex-col items-center gap-4 p-6 rounded-2xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.08] hover:border-accent/30 transition-all duration-300 text-left"
                                    >
                                        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500/20 to-cyan-500/20 flex items-center justify-center group-hover:scale-110 transition-transform">
                                            <Edit3 size={24} className="text-cyan-400" />
                                        </div>
                                        <div className="text-center">
                                            <h3 className="text-white font-semibold mb-1">Create Your Own</h3>
                                            <p className="text-xs text-gray-500 leading-relaxed">
                                                Write your own system prompt and configure every detail — full control, just like Claude Code.
                                            </p>
                                        </div>
                                        <ChevronRight size={16} className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-600 group-hover:text-accent transition-colors" />
                                    </button>

                                    {/* Pub AI Assist */}
                                    <button
                                        onClick={() => setMode("assisted")}
                                        className="group relative flex flex-col items-center gap-4 p-6 rounded-2xl border border-white/10 bg-white/[0.03] hover:bg-white/[0.08] hover:border-purple-500/30 transition-all duration-300 text-left"
                                    >
                                        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 flex items-center justify-center group-hover:scale-110 transition-transform">
                                            <Wand2 size={24} className="text-purple-400" />
                                        </div>
                                        <div className="text-center">
                                            <h3 className="text-white font-semibold mb-1">Pub AI Assist</h3>
                                            <p className="text-xs text-gray-500 leading-relaxed">
                                                Describe what your agent should do and Pub AI will craft an optimized system prompt for you.
                                            </p>
                                        </div>
                                        <ChevronRight size={16} className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-600 group-hover:text-purple-400 transition-colors" />
                                    </button>
                                </motion.div>
                            )}

                            {/* ── MODE: Manual ── */}
                            {mode === "manual" && (
                                <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-4">
                                    <button
                                        onClick={() => setMode("choose")}
                                        className="text-xs text-gray-500 hover:text-white flex items-center gap-1 transition-colors"
                                    >
                                        ← Back
                                    </button>

                                    {/* Agent Name */}
                                    <div>
                                        <label className="block text-xs text-gray-400 mb-1.5 font-medium">Agent Name</label>
                                        <input
                                            value={manualName}
                                            onChange={(e) => setManualName(e.target.value)}
                                            placeholder="My Custom Agent"
                                            className="w-full glass-input px-4 py-2.5 text-sm"
                                        />
                                    </div>

                                    {/* Agent Type */}
                                    <div>
                                        <label className="block text-xs text-gray-400 mb-1.5 font-medium">Agent Type</label>
                                        <div className="grid grid-cols-4 gap-2">
                                            {agentTypes.map((type) => {
                                                const Icon = type.icon;
                                                return (
                                                    <button
                                                        key={type.id}
                                                        onClick={() => setSelectedType(type.id)}
                                                        title={type.description}
                                                        className={cn(
                                                            "flex flex-col items-center gap-1 p-2.5 rounded-xl border transition-all text-[11px]",
                                                            selectedType === type.id
                                                                ? "bg-accent/15 border-accent/30 text-accent"
                                                                : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:bg-white/10"
                                                        )}
                                                    >
                                                        <Icon size={16} />
                                                        <span className="font-medium">{type.label}</span>
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* System Prompt */}
                                    <div>
                                        <label className="block text-xs text-gray-400 mb-1.5 font-medium">System Prompt</label>
                                        <textarea
                                            value={manualPrompt}
                                            onChange={(e) => setManualPrompt(e.target.value)}
                                            placeholder={`You are a specialized AI agent that...\n\nYour capabilities:\n- ...\n- ...\n\nRules:\n- Always think step-by-step\n- Use tools when appropriate`}
                                            rows={10}
                                            className="w-full glass-input px-4 py-3 text-sm resize-none font-mono"
                                        />
                                        <p className="text-[10px] text-gray-600 mt-1">
                                            Write the full system prompt — this determines how your agent thinks and behaves.
                                        </p>
                                    </div>

                                    {/* Create Button */}
                                    <button
                                        onClick={handleManualCreate}
                                        disabled={!manualName.trim() || !manualPrompt.trim() || spawning}
                                        className="w-full py-3 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all text-sm font-medium flex items-center justify-center gap-2"
                                    >
                                        {spawning ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                                        {spawning ? "Creating..." : "Create Agent"}
                                    </button>
                                </motion.div>
                            )}

                            {/* ── MODE: Pub AI Assisted ── */}
                            {mode === "assisted" && (
                                <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} className="space-y-4">
                                    <button
                                        onClick={() => { setMode("choose"); setShowGenerated(false); }}
                                        className="text-xs text-gray-500 hover:text-white flex items-center gap-1 transition-colors"
                                    >
                                        ← Back
                                    </button>

                                    {/* Agent Name */}
                                    <div>
                                        <label className="block text-xs text-gray-400 mb-1.5 font-medium">Agent Name</label>
                                        <input
                                            value={assistName}
                                            onChange={(e) => setAssistName(e.target.value)}
                                            placeholder="e.g. Code Reviewer"
                                            className="w-full glass-input px-4 py-2.5 text-sm"
                                        />
                                    </div>

                                    {/* Agent Type */}
                                    <div>
                                        <label className="block text-xs text-gray-400 mb-1.5 font-medium">Agent Type</label>
                                        <div className="grid grid-cols-4 gap-2">
                                            {agentTypes.map((type) => {
                                                const Icon = type.icon;
                                                return (
                                                    <button
                                                        key={type.id}
                                                        onClick={() => setSelectedType(type.id)}
                                                        title={type.description}
                                                        className={cn(
                                                            "flex flex-col items-center gap-1 p-2.5 rounded-xl border transition-all text-[11px]",
                                                            selectedType === type.id
                                                                ? "bg-accent/15 border-accent/30 text-accent"
                                                                : "bg-white/5 border-white/10 text-gray-400 hover:text-white hover:bg-white/10"
                                                        )}
                                                    >
                                                        <Icon size={16} />
                                                        <span className="font-medium">{type.label}</span>
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* Description */}
                                    <div>
                                        <label className="block text-xs text-gray-400 mb-1.5 font-medium">
                                            Describe what your agent should do
                                        </label>
                                        <textarea
                                            value={assistDescription}
                                            onChange={(e) => setAssistDescription(e.target.value)}
                                            placeholder="e.g. I want an agent that reviews Python code for security vulnerabilities and suggests fixes. It should be thorough but concise."
                                            rows={4}
                                            className="w-full glass-input px-4 py-3 text-sm resize-none"
                                        />
                                    </div>

                                    {/* Generate Button */}
                                    {!showGenerated && (
                                        <button
                                            onClick={handleGeneratePrompt}
                                            disabled={!assistDescription.trim() || generating}
                                            className="w-full py-3 rounded-xl bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 disabled:opacity-30 transition-all text-sm font-medium flex items-center justify-center gap-2"
                                        >
                                            {generating ? (
                                                <>
                                                    <Loader2 size={16} className="animate-spin" />
                                                    Generating prompt...
                                                </>
                                            ) : (
                                                <>
                                                    <Wand2 size={16} />
                                                    Generate System Prompt
                                                </>
                                            )}
                                        </button>
                                    )}

                                    {/* Generated Prompt (editable) */}
                                    {showGenerated && (
                                        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
                                            <div className="flex items-center justify-between">
                                                <label className="text-xs text-gray-400 font-medium flex items-center gap-1.5">
                                                    <Sparkles size={12} className="text-purple-400" />
                                                    Generated Prompt — edit if needed
                                                </label>
                                                <button
                                                    onClick={handleGeneratePrompt}
                                                    disabled={generating}
                                                    className="text-[10px] text-purple-400 hover:text-purple-300 flex items-center gap-1"
                                                >
                                                    <Wand2 size={10} /> Regenerate
                                                </button>
                                            </div>
                                            <textarea
                                                value={generatedPrompt}
                                                onChange={(e) => setGeneratedPrompt(e.target.value)}
                                                rows={10}
                                                className="w-full glass-input px-4 py-3 text-sm resize-none font-mono"
                                            />
                                            <button
                                                onClick={handleAssistedCreate}
                                                disabled={!generatedPrompt.trim() || spawning}
                                                className="w-full py-3 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all text-sm font-medium flex items-center justify-center gap-2"
                                            >
                                                {spawning ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                                                {spawning ? "Creating..." : "Create Agent"}
                                            </button>
                                        </motion.div>
                                    )}
                                </motion.div>
                            )}
                        </div>
                    </GlassCard>
                </motion.div>
            </motion.div>
        </AnimatePresence>
    );
}
