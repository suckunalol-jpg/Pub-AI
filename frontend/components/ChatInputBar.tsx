"use client";

import { useState, useRef, useLayoutEffect, useCallback, useEffect, useMemo } from "react";
import { Send, Square, Slash, Paperclip, X, FileText, Image as ImageIcon, Mic } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import GlassCard from "./GlassCard";
import * as api from "../lib/api";
import { useThemeStore } from "@/lib/themeStore";

// Hard-coded command list (matches backend) — avoids needing a fetch on every keystroke
const SLASH_COMMANDS = [
  { name: "clear", description: "Clear the current chat", usage: "/clear", type: "local" },
  { name: "new", description: "Start a new conversation", usage: "/new", type: "local" },
  { name: "agents", description: "Create or manage AI agents", usage: "/agents", type: "local" },
  { name: "effort", description: "Set reasoning effort (low, medium, high, max)", usage: "/effort <level>", type: "local" },
  { name: "theme", description: "Switch theme (default, terminal, midnight, mizzy)", usage: "/theme <name>", type: "local" },
  { name: "help", description: "Show all available commands", usage: "/help", type: "server" },
  { name: "export", description: "Export chat as markdown", usage: "/export", type: "local" },
  { name: "system", description: "Set a temporary system prompt", usage: "/system <prompt>", type: "server" },
  { name: "model", description: "Show or switch the AI model", usage: "/model [name]", type: "server" },
] as const;


export interface Attachment {
  id: string;
  filename: string;
  url: string;
  content_type: string;
  size: number;
}

interface ChatInputBarProps {
  onSend: (text: string, attachments?: Attachment[]) => void;
  onStop: () => void;
  onSlashCommand?: (command: string, args: string) => void;
  isLoading: boolean;
}

export default function ChatInputBar({ onSend, onStop, onSlashCommand, isLoading }: ChatInputBarProps) {
  const [input, setInput] = useState("");
  const [showCommands, setShowCommands] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const theme = useThemeStore((s) => s.theme);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Speech Recognition State
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    // Initialize Web Speech API
    if (typeof window !== "undefined") {
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechRecognition) {
        recognitionRef.current = new SpeechRecognition();
        recognitionRef.current.continuous = false;
        recognitionRef.current.interimResults = false;
        
        recognitionRef.current.onresult = (event: any) => {
          let transcript = "";
          for (let i = event.resultIndex; i < event.results.length; ++i) {
            transcript += event.results[i][0].transcript;
          }
          setInput((prev) => prev + (prev && !prev.endsWith(" ") ? " " : "") + transcript);
        };
        
        recognitionRef.current.onerror = (event: any) => {
          console.error("Speech recognition error", event.error);
          setIsListening(false);
        };
        
        recognitionRef.current.onend = () => {
          setIsListening(false);
        };
      }
    }
  }, []);

  const toggleListen = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
    } else {
      if (recognitionRef.current) {
        recognitionRef.current.start();
        setIsListening(true);
      } else {
        alert("Speech recognition is not supported in this browser.");
      }
    }
  }, [isListening]);

  // Filter commands based on typed text after "/"
  const filteredCommands = useMemo(() => {
    if (!input.startsWith("/")) return [];
    const typed = input.slice(1).split(" ")[0].toLowerCase();
    return SLASH_COMMANDS.filter((cmd) =>
      cmd.name.toLowerCase().startsWith(typed)
    );
  }, [input]);

  // Show/hide the commands popup
  useEffect(() => {
    const shouldShow = input.startsWith("/") && !input.includes(" ") && filteredCommands.length > 0;
    setShowCommands(shouldShow);
    if (shouldShow) {
      setSelectedIndex(0);
    }
  }, [input, filteredCommands.length]);

  // Auto-resize textarea
  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
    }
  }, [input]);

  const insertCommand = useCallback(
    (cmdName: string) => {
      setInput(`/${cmdName} `);
      setShowCommands(false);
      textareaRef.current?.focus();
    },
    []
  );

  const handleFileSelect = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      const results: Attachment[] = [];
      for (const file of Array.from(files)) {
        const result = await api.uploadFile(file);
        results.push(result);
      }
      setAttachments((prev) => [...prev, ...results]);
    } catch (err: unknown) {
      console.error("Upload failed:", err);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim();
    if ((!trimmed && attachments.length === 0) || isLoading) return;

    // Check if it's a slash command
    if (trimmed.startsWith("/") && attachments.length === 0) {
      const parts = trimmed.slice(1).split(/\s+/);
      const cmd = parts[0].toLowerCase();
      const args = parts.slice(1).join(" ");

      if (onSlashCommand) {
        onSlashCommand(cmd, args);
        setInput("");
        return;
      }
    }

    onSend(trimmed, attachments.length > 0 ? attachments : undefined);
    setInput("");
    setAttachments([]);
  }, [input, attachments, isLoading, onSend, onSlashCommand]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // Navigate through command popup
      if (showCommands) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSelectedIndex((prev: number) => Math.min(prev + 1, filteredCommands.length - 1));
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSelectedIndex((prev: number) => Math.max(prev - 1, 0));
          return;
        }
        if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
          e.preventDefault();
          if (filteredCommands[selectedIndex]) {
            insertCommand(filteredCommands[selectedIndex].name);
          }
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setShowCommands(false);
          return;
        }
      }

      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit, showCommands, filteredCommands, selectedIndex, insertCommand]
  );

  // Drag and drop support
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    handleFileSelect(e.dataTransfer.files);
  }, [handleFileSelect]);

  const isImage = (ct: string) => ct.startsWith("image/");

  return (
    <div className="px-4 pb-4 pt-2 relative" onDragOver={handleDragOver} onDrop={handleDrop}>
      {/* Slash command popup */}
      <AnimatePresence>
        {showCommands && (
          <motion.div
            ref={popupRef}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.15 }}
            className="absolute bottom-full left-4 right-4 mb-2 z-50"
          >
            <div className="bg-gray-900/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl overflow-hidden">
              <div className="px-3 py-2 border-b border-white/5 flex items-center gap-2">
                <Slash size={12} className="text-gray-500" />
                <span className="text-xs text-gray-500 font-medium">Commands</span>
              </div>
              <div className="max-h-52 overflow-y-auto py-1">
                {filteredCommands.map((cmd, idx) => (
                  <button
                    key={cmd.name}
                    onClick={() => insertCommand(cmd.name)}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors ${idx === selectedIndex
                      ? "bg-white/10 text-white"
                      : "text-gray-300 hover:bg-white/5"
                      }`}
                  >
                    <span className="font-mono text-sm text-accent font-medium min-w-[80px]">
                      /{cmd.name}
                    </span>
                    <span className="text-xs text-gray-500 truncate">
                      {cmd.description}
                    </span>
                    <span className="ml-auto text-[10px] text-gray-600 uppercase tracking-wider">
                      {cmd.type}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Attachment previews */}
      {attachments.length > 0 && (
        <div className="flex gap-2 mb-2 flex-wrap">
          {attachments.map((att) => (
            <div
              key={att.id}
              className="relative group flex items-center gap-2 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-gray-300"
            >
              {isImage(att.content_type) ? (
                <ImageIcon size={14} className="text-blue-400" />
              ) : (
                <FileText size={14} className="text-green-400" />
              )}
              <span className="max-w-[120px] truncate">{att.filename}</span>
              <span className="text-gray-600">
                {(att.size / 1024).toFixed(0)}KB
              </span>
              <button
                onClick={() => removeAttachment(att.id)}
                className="ml-1 p-0.5 rounded hover:bg-white/10 text-gray-500 hover:text-red-400 transition-colors"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Terminal Input Container */}
      <div className="flex flex-col gap-2 px-4 py-3 border-t border-accent/20 bg-[#01040a] font-mono">
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => handleFileSelect(e.target.files)}
          accept=".png,.jpg,.jpeg,.gif,.webp,.svg,.pdf,.txt,.md,.csv,.json,.py,.js,.ts,.tsx,.jsx,.html,.css,.lua,.rs,.go,.java,.cpp,.c,.h"
        />

        <div className="flex items-end gap-2 text-sm">
          {/* Prompt prefix */}
          <div className="flex items-center gap-1.5 mb-1.5 text-accent whitespace-nowrap font-bold">
            <span className="text-accent/60">&gt;</span>
            <span className="flex items-center gap-1 text-xs">
              pub-ai 
              <span className="text-gray-500 font-normal">in</span> 
              <span className="text-accent/80">~</span>
            </span>
            <span className="text-accent ml-1">$</span>
          </div>

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a command or message... (use / for actions)"
            rows={1}
            className="flex-1 bg-transparent text-gray-200 placeholder-accent/20 resize-none outline-none max-h-40 mb-1.5 ml-2 leading-relaxed"
            spellCheck={false}
          />

          <div className="flex items-center gap-1 mb-1 relative z-10">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="p-1.5 text-accent/50 hover:text-accent hover:bg-accent/10 rounded transition-colors disabled:opacity-30"
              title="Attach context"
            >
              <Paperclip size={16} className={uploading ? "animate-spin" : ""} />
            </button>
            
            <button
              onClick={toggleListen}
              className={`p-1.5 rounded transition-colors ${
                isListening ? "text-red-400 bg-red-500/10 animate-pulse" : "text-accent/50 hover:text-accent hover:bg-accent/10"
              }`}
              title={isListening ? "Stop listening" : "Start speaking"}
            >
              <Mic size={16} />
            </button>

            {isLoading ? (
              <button onClick={onStop} className="p-1.5 text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded transition-colors">
                <Square size={16} />
              </button>
            ) : (
              <button 
                onClick={handleSubmit} 
                disabled={!input.trim() && attachments.length === 0} 
                className="p-1.5 text-accent hover:text-accent/80 hover:bg-accent/10 rounded disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
                title="Send"
              >
                <Send size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
