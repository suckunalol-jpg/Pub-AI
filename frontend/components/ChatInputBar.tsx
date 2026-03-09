"use client";

import { useState, useRef, useLayoutEffect, useCallback } from "react";
import { Send, Square, Plus } from "lucide-react";
import GlassCard from "./GlassCard";

interface ChatInputBarProps {
  onSend: (text: string) => void;
  onStop: () => void;
  isLoading: boolean;
}

export default function ChatInputBar({ onSend, onStop, isLoading }: ChatInputBarProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
    }
  }, [input]);

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;
    onSend(trimmed);
    setInput("");
  }, [input, isLoading, onSend]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  return (
    <div className="px-4 pb-4 pt-2">
      <GlassCard className="flex items-end gap-3 px-4 py-3">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Send a message..."
          rows={1}
          className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 resize-none outline-none max-h-40"
        />
        {isLoading ? (
          <button
            onClick={onStop}
            className="flex-shrink-0 p-2 rounded-xl bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all"
            title="Stop generating"
          >
            <Square size={18} />
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!input.trim()}
            className="flex-shrink-0 p-2 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            <Send size={18} />
          </button>
        )}
      </GlassCard>
    </div>
  );
}
