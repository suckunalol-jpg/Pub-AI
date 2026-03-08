"use client";

import { motion, AnimatePresence } from "framer-motion";
import { Brain, Code, Terminal, Search, Eye } from "lucide-react";
import { cn } from "@/lib/utils";

export type AiPhase = "thinking" | "coding" | "executing" | "searching" | "reviewing";

interface ActionIndicatorProps {
  phase: AiPhase;
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
  coding: {
    icon: Code,
    label: "Writing code",
    color: "text-emerald-400",
    glowColor: "rgba(52, 211, 153, 0.25)",
  },
  executing: {
    icon: Terminal,
    label: "Executing",
    color: "text-amber-400",
    glowColor: "rgba(251, 191, 36, 0.25)",
  },
  searching: {
    icon: Search,
    label: "Searching",
    color: "text-violet-400",
    glowColor: "rgba(167, 139, 250, 0.25)",
  },
  reviewing: {
    icon: Eye,
    label: "Reviewing",
    color: "text-cyan-400",
    glowColor: "rgba(34, 211, 238, 0.25)",
  },
};

export default function ActionIndicator({
  phase,
  liveCode,
  className,
}: ActionIndicatorProps) {
  const config = phaseConfig[phase];
  const Icon = config.icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2 }}
      className={cn("flex items-start gap-3 px-8 py-3", className)}
    >
      {/* Animated icon container */}
      <div
        className="relative flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-0.5"
        style={{ background: `${config.glowColor}` }}
      >
        {/* Pulse ring */}
        <motion.div
          className="absolute inset-0 rounded-full"
          style={{ border: `1.5px solid ${config.glowColor}` }}
          animate={{
            scale: [1, 1.5, 1],
            opacity: [0.6, 0, 0.6],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />

        {/* Icon with phase-specific animation */}
        <AnimatePresence mode="wait">
          <motion.div
            key={phase}
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.5, opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            {phase === "searching" ? (
              /* Search: subtle horizontal sweep */
              <motion.div
                animate={{ x: [-1, 1, -1] }}
                transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
              >
                <Icon size={16} className={config.color} />
              </motion.div>
            ) : phase === "executing" ? (
              /* Terminal: blink effect */
              <motion.div
                animate={{ opacity: [1, 0.4, 1] }}
                transition={{ duration: 0.8, repeat: Infinity, ease: "steps(2)" }}
              >
                <Icon size={16} className={config.color} />
              </motion.div>
            ) : (
              /* Default: gentle pulse for thinking/coding/reviewing */
              <motion.div
                animate={{ scale: [1, 1.1, 1] }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
              >
                <Icon size={16} className={config.color} />
              </motion.div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Label and optional live preview */}
      <div className="flex flex-col gap-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={cn("text-sm font-medium", config.color)}>
            {config.label}
          </span>
          {/* Animated dots */}
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
        </div>

        {/* Live code preview during coding phase */}
        {phase === "coding" && liveCode && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            className="max-w-md"
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
          <div className="flex items-center gap-1 text-xs text-gray-500 font-mono">
            <span>$</span>
            <span className="inline-block w-1.5 h-3 bg-amber-400/70 animate-terminal-blink" />
          </div>
        )}
      </div>
    </motion.div>
  );
}
