"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain, Code, Terminal, Search, Eye, ChevronDown, ChevronRight,
  Microscope, Map, Pencil, Bug, FileText, FilePlus, Globe, BookOpen, Bot,
  Wrench, AlignLeft, Type
} from "lucide-react";
import { cn } from "@/lib/utils";

export type AiPhase =
  | "thinking"
  | "analyzing"
  | "planning"
  | "writing"
  | "coding"
  | "debugging"
  | "executing"
  | "reading_file"
  | "writing_file"
  | "searching_web"
  | "searching_knowledge"
  | "spawning_agent"
  | "calling_tool"
  | "reviewing"
  | "summarizing"
  | "formatting";

export interface ActionEntry {
  id: string;
  phase: AiPhase;
  summary: string;
  details?: string;
  timestamp: Date;
}

interface ActionIndicatorProps {
  phase: AiPhase;
  /** List of all action entries in chronological order */
  actions: ActionEntry[];
  /** Optional live code preview text shown during coding phase */
  liveCode?: string;
  className?: string;
}

const phaseConfig: Record<
  AiPhase,
  { icon: typeof Brain; label: string; color: string; glowColor: string }
> = {
  thinking: {
    icon: Brain,
    label: "Thinking",
    color: "text-blue-400",
    glowColor: "rgba(96, 165, 250, 0.25)",
  },
  analyzing: {
    icon: Microscope,
    label: "Analyzing request",
    color: "text-purple-400",
    glowColor: "rgba(192, 132, 252, 0.25)",
  },
  planning: {
    icon: Map,
    label: "Planning approach",
    color: "text-blue-400",
    glowColor: "rgba(96, 165, 250, 0.25)",
  },
  writing: {
    icon: Pencil,
    label: "Writing response",
    color: "text-green-400",
    glowColor: "rgba(74, 222, 128, 0.25)",
  },
  coding: {
    icon: Code,
    label: "Writing code",
    color: "text-emerald-400",
    glowColor: "rgba(52, 211, 153, 0.25)",
  },
  debugging: {
    icon: Bug,
    label: "Debugging",
    color: "text-red-400",
    glowColor: "rgba(248, 113, 113, 0.25)",
  },
  executing: {
    icon: Terminal,
    label: "Executing code",
    color: "text-orange-400",
    glowColor: "rgba(251, 146, 60, 0.25)",
  },
  reading_file: {
    icon: FileText,
    label: "Reading file",
    color: "text-gray-400",
    glowColor: "rgba(156, 163, 175, 0.25)",
  },
  writing_file: {
    icon: FilePlus,
    label: "Writing file",
    color: "text-teal-400",
    glowColor: "rgba(45, 212, 191, 0.25)",
  },
  searching_web: {
    icon: Globe,
    label: "Searching web",
    color: "text-violet-400",
    glowColor: "rgba(167, 139, 250, 0.25)",
  },
  searching_knowledge: {
    icon: BookOpen,
    label: "Searching knowledge",
    color: "text-indigo-400",
    glowColor: "rgba(129, 140, 248, 0.25)",
  },
  spawning_agent: {
    icon: Bot,
    label: "Spawning agent",
    color: "text-cyan-400",
    glowColor: "rgba(34, 211, 238, 0.25)",
  },
  calling_tool: {
    icon: Wrench,
    label: "Using tool",
    color: "text-amber-400",
    glowColor: "rgba(251, 191, 36, 0.25)",
  },
  reviewing: {
    icon: Eye,
    label: "Reviewing output",
    color: "text-cyan-400",
    glowColor: "rgba(34, 211, 238, 0.25)",
  },
  summarizing: {
    icon: AlignLeft,
    label: "Summarizing",
    color: "text-blue-400",
    glowColor: "rgba(96, 165, 250, 0.25)",
  },
  formatting: {
    icon: Type,
    label: "Formatting",
    color: "text-gray-400",
    glowColor: "rgba(156, 163, 175, 0.25)",
  },
};

function ActionItem({
  entry,
  isLatest,
}: {
  entry: ActionEntry;
  isLatest: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const config = phaseConfig[entry.phase];
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: isLatest ? 1 : 0.5, y: 0 }}
      transition={{ duration: 0.15 }}
      className="flex items-start gap-2.5"
    >
      {/* Timeline dot */}
      <div className="flex flex-col items-center flex-shrink-0">
        <div
          className={cn(
            "w-6 h-6 rounded-full flex items-center justify-center",
            isLatest ? "" : "opacity-60"
          )}
          style={{ background: config.glowColor }}
        >
          {isLatest ? (
            <motion.div
              animate={{ scale: [1, 1.1, 1] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
            >
              <Icon size={13} className={config.color} />
            </motion.div>
          ) : (
            <Icon size={13} className={config.color} />
          )}
        </div>
        {/* Vertical connector line (hidden on latest since it's at the bottom) */}
        {!isLatest && (
          <div className="w-px h-3 bg-white/10 mt-0.5" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0 pb-1">
        <button
          onClick={() => entry.details && setExpanded(!expanded)}
          className={cn(
            "flex items-center gap-1.5 text-left w-full",
            entry.details ? "cursor-pointer" : "cursor-default"
          )}
        >
          {entry.details && (
            expanded ? (
              <ChevronDown size={12} className="text-gray-500 flex-shrink-0" />
            ) : (
              <ChevronRight size={12} className="text-gray-500 flex-shrink-0" />
            )
          )}
          <span
            className={cn(
              "text-sm",
              isLatest ? config.color : "text-gray-500"
            )}
          >
            {entry.summary}
          </span>
          {/* Animated dots for the latest active entry */}
          {isLatest && (
            <span className="flex gap-0.5 ml-1">
              {[0, 1, 2].map((i) => (
                <motion.span
                  key={i}
                  className={cn("inline-block w-1 h-1 rounded-full", config.color)}
                  style={{ backgroundColor: "currentColor" }}
                  animate={{ opacity: [0.2, 1, 0.2] }}
                  transition={{
                    duration: 1.2,
                    repeat: Infinity,
                    delay: i * 0.2,
                    ease: "easeInOut",
                  }}
                />
              ))}
            </span>
          )}
        </button>

        {/* Expandable details */}
        <AnimatePresence>
          {expanded && entry.details && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden"
            >
              <div className="mt-1.5 max-h-40 overflow-y-auto bg-black/30 border border-white/5 rounded-lg px-3 py-2">
                <pre className="text-xs text-gray-400 font-mono whitespace-pre-wrap break-all">
                  {entry.details}
                </pre>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

export default function ActionIndicator({
  phase,
  actions,
  liveCode,
  className,
}: ActionIndicatorProps) {
  const config = phaseConfig[phase];

  // If no actions yet, fall back to showing just the phase label
  if (actions.length === 0) {
    const Icon = config.icon;
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.2 }}
        className={cn("flex items-center gap-3 px-8 py-3 action-bubble rounded-xl", className)}
      >
        <div
          className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center"
          style={{ background: config.glowColor }}
        >
          <motion.div
            animate={{ scale: [1, 1.1, 1] }}
            transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
          >
            <Icon size={13} className={config.color} />
          </motion.div>
        </div>
        <span className={cn("text-sm font-medium", config.color)}>
          {config.label}
        </span>
        <span className="flex gap-0.5">
          {[0, 1, 2].map((i) => (
            <motion.span
              key={i}
              className={cn("inline-block w-1 h-1 rounded-full", config.color)}
              style={{ backgroundColor: "currentColor" }}
              animate={{ opacity: [0.2, 1, 0.2] }}
              transition={{
                duration: 1.2,
                repeat: Infinity,
                delay: i * 0.2,
                ease: "easeInOut",
              }}
            />
          ))}
        </span>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2 }}
      className={cn("flex flex-col gap-0 px-8 py-3 action-bubble rounded-xl", className)}
    >
      {actions.map((entry, idx) => (
        <ActionItem
          key={entry.id}
          entry={entry}
          isLatest={idx === actions.length - 1}
        />
      ))}

      {/* Live code preview during coding phase */}
      {phase === "coding" && liveCode && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="ml-8 mt-1 max-w-md"
        >
          <div className="bg-black/40 border border-white/5 rounded-lg px-3 py-2 font-mono text-xs text-gray-400 overflow-hidden">
            <span className="whitespace-pre-wrap break-all line-clamp-3">
              {liveCode.slice(-200)}
            </span>
            <span className="inline-block w-1.5 h-3.5 bg-emerald-400/70 ml-0.5 animate-terminal-blink" />
          </div>
        </motion.div>
      )}

      {/* Terminal cursor for executing phase */}
      {phase === "executing" && (
        <div className="ml-8 mt-1 flex items-center gap-1 text-xs text-gray-500 font-mono">
          <span>$</span>
          <span className="inline-block w-1.5 h-3 bg-amber-400/70 animate-terminal-blink" />
        </div>
      )}
    </motion.div>
  );
}
