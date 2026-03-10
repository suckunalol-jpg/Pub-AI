"use client";

import { useState, useRef, useEffect, useCallback, memo, useMemo } from "react";
import { AnimatePresence } from "framer-motion";
import { Bot, Plus } from "lucide-react";
import ChatMessage, { type Message } from "./ChatMessage";
import ChatInputBar from "./ChatInputBar";
import ActionIndicator, { type AiPhase, type ActionEntry } from "./ActionIndicator";
import { generateId } from "@/lib/utils";
import * as api from "@/lib/api";
import type { ToolCallEvent, ToolResultEvent } from "@/lib/api";
import { useThemeStore } from "@/lib/themeStore";
import { useEffortStore, type EffortLevel } from "@/lib/effortStore";
import AgentCreatorModal from "./AgentCreatorModal";

// Phase-to-summary mapping for action entries
const phaseSummaries: Record<AiPhase, string> = {
  thinking: "Thinking...",
  analyzing: "Analyzing your request...",
  planning: "Planning approach...",
  writing: "Writing response...",
  coding: "Writing code...",
  debugging: "Debugging...",
  executing: "Running code...",
  reading_file: "Reading file...",
  writing_file: "Writing file...",
  searching_web: "Searching the web...",
  searching_knowledge: "Searching knowledge base...",
  spawning_agent: "Spawning sub-agent...",
  calling_tool: "Calling tool...",
  reviewing: "Reviewing output...",
  summarizing: "Summarizing...",
  formatting: "Formatting response...",
};

// Tool-name-to-friendly-label mapping
const toolLabels: Record<string, string> = {
  web_search: "🔍 Searching the web",
  web_fetch: "🌐 Fetching webpage",
  read_file: "📖 Reading file",
  write_file: "📝 Writing file",
  edit_file: "✏️ Editing file",
  multi_edit: "✏️ Multi-editing file",
  execute_code: "▶️ Executing code",
  bash: "💻 Running command",
  spawn_agent: "🤖 Spawning agent",
  grep_search: "🔎 Searching code",
  codebase_search: "🔎 Searching codebase",
  list_dir: "📁 Listing directory",
  file_search: "📂 Searching files",
  git: "📌 Git operation",
  delete_file: "🗑️ Deleting file",
  create_project: "🏗️ Creating project",
  roblox_scan: "🎮 Scanning Roblox scripts",
  http_request: "🌐 HTTP request",
  plan_tasks: "📋 Planning tasks",
};

// Memoize ChatMessage for the messages list
const MemoizedChatMessage = memo(ChatMessage);

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const theme = useThemeStore((s) => s.theme);

  // Streaming state
  const [aiPhase, setAiPhase] = useState<AiPhase>("thinking");
  const [streamingContent, setStreamingContent] = useState("");
  const [liveCode, setLiveCode] = useState("");
  const [showAgentCreator, setShowAgentCreator] = useState(false);
  const effortLevel = useEffortStore((s) => s.effort);
  const setEffortLevel = useEffortStore((s) => s.setEffort);
  const [actions, setActions] = useState<ActionEntry[]>([]);
  const [showActions, setShowActions] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const sendRef = useRef<(text: string) => void>(() => { });
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastScrollRef = useRef(0);

  // Throttled auto-scroll: only scroll every 300ms during streaming to prevent shaking
  useEffect(() => {
    const now = Date.now();
    if (isLoading) {
      if (now - lastScrollRef.current > 300) {
        lastScrollRef.current = now;
        messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
      }
    } else if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streamingContent, isLoading]);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setConversationId(null);
    setIsLoading(false);
    setStreamingContent("");
    setLiveCode("");
    setActions([]);
  }, []);

  const handleSlashCommand = useCallback(
    (command: string, args: string) => {
      const setTheme = useThemeStore.getState().setTheme;

      switch (command) {
        case "clear":
          setMessages([]);
          setStreamingContent("");
          setActions([]);
          break;
        case "new":
          handleNewChat();
          break;
        case "theme": {
          const t = args.trim().toLowerCase();
          if (["default", "terminal", "midnight", "mizzy"].includes(t)) {
            setTheme(t as "default" | "terminal" | "midnight" | "mizzy");
          } else {
            const infoMsg: Message = {
              id: generateId(),
              role: "assistant",
              content: `Available themes: **default**, **terminal**, **midnight**, **mizzy**.\nUsage: \`/theme terminal\``,
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, infoMsg]);
          }
          break;
        }
        case "agents":
          setShowAgentCreator(true);
          break;
        case "effort": {
          const level = args.trim().toLowerCase();
          if (["low", "medium", "high", "max"].includes(level)) {
            setEffortLevel(level as EffortLevel);
            const emojiMap: Record<string, string> = { low: "⚡", medium: "⚖️", high: "🧠", max: "🔬" };
            const infoMsg: Message = {
              id: generateId(),
              role: "assistant",
              content: `${emojiMap[level]} Effort level set to **${level}**`,
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, infoMsg]);
          } else {
            const infoMsg: Message = {
              id: generateId(),
              role: "assistant",
              content: `Available effort levels:\n- ⚡ **low** — minimal thinking, fastest\n- ⚖️ **medium** — balanced\n- 🧠 **high** — deep reasoning (default)\n- 🔬 **max** — maximum deliberation\n\nUsage: \`/effort high\`\n\nCurrent: **${effortLevel}**`,
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, infoMsg]);
          }
          break;
        }
        case "help": {
          const helpMsg: Message = {
            id: generateId(),
            role: "assistant",
            content: [
              "## Available Commands",
              "",
              "| Command | Description |",
              "|---------|-------------|",
              "| `/clear` | Clear the current chat |",
              "| `/new` | Start a new conversation |",
              "| `/agents` | Create or manage AI agents |",
              "| `/effort <level>` | Set reasoning effort (low/medium/high/max) |",
              "| `/theme <name>` | Switch theme |",
              "| `/help` | Show this help |",
              "| `/export` | Export chat as markdown |",
            ].join("\n"),
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, helpMsg]);
          break;
        }
        case "export": {
          const md = messages
            .map((m) => `**${m.role === "user" ? "You" : "AI"}**: ${m.content}`)
            .join("\n\n---\n\n");
          const blob = new Blob([md], { type: "text/markdown" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `chat-export-${Date.now()}.md`;
          a.click();
          URL.revokeObjectURL(url);
          break;
        }
        default:
          // Unknown command — send it as a normal message to the AI
          sendRef.current(`/${command} ${args}`.trim());
      }
    },
    [handleNewChat, messages]
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;

    // Finalize whatever content was streamed so far
    setStreamingContent((prev) => {
      if (prev.trim()) {
        const finalMsg: Message = {
          id: generateId(),
          role: "assistant",
          content: prev + "\n\n*(generation stopped)*",
          timestamp: new Date(),
        };
        setMessages((msgs) => [...msgs, finalMsg]);
      }
      return "";
    });

    setIsLoading(false);
    setLiveCode("");
    setActions([]);
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      if (!text.trim() || isLoading) return;

      const userMessage: Message = {
        id: generateId(),
        role: "user",
        content: text,
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, userMessage]);
      setIsLoading(true);
      setAiPhase("thinking");
      setStreamingContent("");
      setLiveCode("");
      setShowActions(true);
      // Clear any pending fade-out timer
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
      setActions([
        {
          id: generateId(),
          phase: "thinking",
          summary: phaseSummaries.thinking,
          timestamp: new Date(),
        },
      ]);

      // Accumulate tokens in a ref-accessible variable for the callbacks
      let accumulatedContent = "";

      const controller = api.streamMessage(conversationId, text, {
        onStatus(phase, convId) {
          setAiPhase(phase);
          if (convId) {
            setConversationId(convId);
          }

          // Add a new action entry for this phase
          setActions((prev) => {
            // Avoid duplicate consecutive phases
            if (prev.length > 0 && prev[prev.length - 1].phase === phase) {
              return prev;
            }
            return [
              ...prev,
              {
                id: generateId(),
                phase,
                summary: phaseSummaries[phase] || phase,
                timestamp: new Date(),
              },
            ];
          });
        },
        onToken(content) {
          accumulatedContent += content;
          setStreamingContent(accumulatedContent);

          // Update the latest action's details with streaming content snippet
          setActions((prev) => {
            if (prev.length === 0) return prev;
            const updated = [...prev];
            const last = { ...updated[updated.length - 1] };
            // Only update details for certain phases
            if (last.phase === "coding" || last.phase === "thinking") {
              last.details = accumulatedContent.slice(-500);
              updated[updated.length - 1] = last;
            }
            return updated;
          });
        },
        onCode(_language, content) {
          setLiveCode(content);
        },
        onToolCall(event: ToolCallEvent) {
          // Add a tool call action entry
          const label = toolLabels[event.tool] || `🔧 ${event.tool}`;
          setActions((prev) => [
            ...prev,
            {
              id: generateId(),
              phase: "calling_tool" as AiPhase,
              summary: `${label}`,
              details: JSON.stringify(event.params, null, 2).slice(0, 300),
              timestamp: new Date(),
            },
          ]);
          setAiPhase("calling_tool");
        },
        onToolResult(event: ToolResultEvent) {
          // Update the latest action with the result
          setActions((prev) => {
            if (prev.length === 0) return prev;
            const updated = [...prev];
            const last = { ...updated[updated.length - 1] };
            const statusEmoji = event.success ? "✅" : "❌";
            last.summary = `${statusEmoji} ${toolLabels[event.tool] || event.tool} — ${event.success ? "done" : "failed"}`;
            last.details = event.output.slice(0, 500);
            updated[updated.length - 1] = last;
            return updated;
          });
        },
        onDone(messageId, _model, convId) {
          setConversationId(convId);

          const aiMessage: Message = {
            id: messageId,
            role: "assistant",
            content: accumulatedContent,
            timestamp: new Date(),
          };
          setMessages((prev) => [...prev, aiMessage]);
          setStreamingContent("");
          setLiveCode("");
          setIsLoading(false);
          abortRef.current = null;

          // Fade out actions after 1.5s instead of clearing instantly
          fadeTimerRef.current = setTimeout(() => {
            setShowActions(false);
            setActions([]);
          }, 1500);
        },
        onError(detail) {
          // If we already have partial content, show it
          if (accumulatedContent.trim()) {
            const partialMsg: Message = {
              id: generateId(),
              role: "assistant",
              content: accumulatedContent,
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, partialMsg]);
          } else {
            const errorMessage: Message = {
              id: generateId(),
              role: "assistant",
              content: `Sorry, something went wrong: ${detail}`,
              timestamp: new Date(),
            };
            setMessages((prev) => [...prev, errorMessage]);
          }
          setStreamingContent("");
          setLiveCode("");
          setIsLoading(false);
          setActions([]);
          abortRef.current = null;
        },
      });

      abortRef.current = controller;
    },
    [isLoading, conversationId]
  );

  // Keep sendRef in sync with handleSend for slash command forwarding
  sendRef.current = handleSend;
  const handleFeedback = async (messageId: string, rating: 1 | 2) => {
    try {
      await api.sendFeedback(messageId, rating);
    } catch {
      // Feedback is non-critical
    }
  };

  return (
    <div className="flex flex-col h-full relative">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
        <h2 className="text-lg font-semibold text-white">Chat</h2>
        <button
          onClick={handleNewChat}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400 hover:text-white glass-button"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto py-4">
        {messages.length === 0 && !isLoading && (
          theme === "terminal" ? (
            <div className="flex h-full items-center justify-center">
              <div className="flex flex-col items-center gap-4">
                <div className="text-4xl text-blue-500 terminal-avatar-bounce">
                  {/* Claude Code style avatar (a simple expressive face or bot icon) */}
                  <Bot size={48} className="text-blue-500 opacity-90" />
                </div>
                <div className="font-arcade text-3xl text-blue-500 terminal-avatar-blink" style={{ textShadow: "0 0 20px rgba(59, 130, 246, 0.5)" }}>
                  Pub++
                </div>
                <div className="text-blue-400/60 font-mono text-xs mt-2">
                  Type /help for commands
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center px-4">
              <div className="font-arcade text-2xl text-white mb-3" style={{ textShadow: "0 0 15px rgba(255,255,255,0.2)" }}>
                Pub++
              </div>
              <p className="text-gray-500 text-sm max-w-md">
                Start a conversation. Ask questions, write code, build projects.
              </p>
            </div>
          )
        )}

        <AnimatePresence>
          {messages.map((msg) => (
            <MemoizedChatMessage key={msg.id} message={msg} onFeedback={handleFeedback} />
          ))}
        </AnimatePresence>

        {/* Streaming: show live content as it arrives */}
        {isLoading && streamingContent && (
          <ChatMessage
            key="streaming"
            message={{
              id: "streaming",
              role: "assistant",
              content: streamingContent,
              timestamp: new Date(),
            }}
            isStreaming
          />
        )}

        {/* Action indicator: shows current phase with timeline */}
        <AnimatePresence>
          {showActions && actions.length > 0 && (
            <ActionIndicator
              phase={aiPhase}
              actions={actions}
              liveCode={liveCode}
            />
          )}
        </AnimatePresence>

        <div ref={messagesEndRef} />
      </div>

      {/* Input bar -- extracted component to prevent re-renders on typing */}
      <ChatInputBar onSend={handleSend} onStop={handleStop} onSlashCommand={handleSlashCommand} isLoading={isLoading} />

      {/* Agent Creator Modal — triggered by /agents slash command */}
      <AgentCreatorModal
        open={showAgentCreator}
        onClose={() => setShowAgentCreator(false)}
      />
    </div>
  );
}
