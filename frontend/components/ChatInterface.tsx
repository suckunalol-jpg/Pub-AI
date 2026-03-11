"use client";

import { useState, useRef, useEffect, useCallback, memo, useMemo } from "react";
import { AnimatePresence } from "framer-motion";
import { Bot, Plus, Zap } from "lucide-react";
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
  // Agent Zero tools
  code_execution: "💻 Executing code",
  memory_save: "💾 Saving to memory",
  memory_load: "🧠 Recalling memory",
  memory_delete: "🗑️ Deleting memory",
  document_query: "📚 Querying documents",
  call_subordinate: "🤖 Delegating to sub-agent",
  scheduler: "⏰ Managing scheduled task",
  response: "💬 Responding",
};

interface AgentState {
  messages: Message[];
  streamingContent: string;
  liveCode: string;
  actions: ActionEntry[];
  aiPhase: AiPhase;
  showActions: boolean;
  status: "idle" | "running" | "done" | "error";
}

const defaultAgentState: AgentState = {
  messages: [],
  streamingContent: "",
  liveCode: "",
  actions: [],
  aiPhase: "thinking",
  showActions: false,
  status: "idle"
};

// Memoize ChatMessage for the messages list
const MemoizedChatMessage = memo(ChatMessage);

export default function ChatInterface() {
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>({ "Main Agent": { ...defaultAgentState } });
  const [activeTab, setActiveTab] = useState<string>("Main Agent");
  
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const theme = useThemeStore((s) => s.theme);

  const [showAgentCreator, setShowAgentCreator] = useState(false);
  const effortLevel = useEffortStore((s) => s.effort);
  const setEffortLevel = useEffortStore((s) => s.setEffort);
  const [agentMode, setAgentMode] = useState(false);  // Agent Zero engine mode
  
  const abortRef = useRef<AbortController | null>(null);
  const sendRef = useRef<(text: string) => void>(() => { });
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastScrollRef = useRef(0);

  // Derived state for the active tab
  const activeState = agentStates[activeTab] || defaultAgentState;
  const messages = activeState.messages;
  const streamingContent = activeState.streamingContent;
  const liveCode = activeState.liveCode;
  const actions = activeState.actions;
  const aiPhase = activeState.aiPhase;
  const showActions = activeState.showActions;

  // Helper to update a specific agent's state
  const updateAgentState = useCallback((agentName: string, updater: (prev: AgentState) => Partial<AgentState>) => {
    setAgentStates((prev) => {
      const current = prev[agentName] || { ...defaultAgentState };
      return { ...prev, [agentName]: { ...current, ...updater(current) } };
    });
  }, []);

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
  }, [messages, streamingContent, isLoading, activeTab]);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    
    setAgentStates({ "Main Agent": { ...defaultAgentState } });
    setActiveTab("Main Agent");
    setConversationId(null);
    setIsLoading(false);
  }, []);

  const handleSlashCommand = useCallback(
    (command: string, args: string) => {
      const setTheme = useThemeStore.getState().setTheme;

      switch (command) {
        case "clear":
          updateAgentState(activeTab, () => ({ ...defaultAgentState }));
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
            updateAgentState(activeTab, (prev) => ({ messages: [...prev.messages, infoMsg] }));
          }
          break;
        }
        case "agents":
          setShowAgentCreator(true);
          break;
        case "agent": {
          setAgentMode((prev) => !prev);
          const modeMsg: Message = {
            id: generateId(),
            role: "assistant",
            content: `🤖 Agent mode **${!agentMode ? "ON" : "OFF"}**. ${!agentMode ? "Using Agent Zero engine with tool calling, memory, web search, code execution, and multi-agent delegation." : "Switched back to standard chat."}`,
            timestamp: new Date(),
          };
          updateAgentState(activeTab, (prev) => ({ messages: [...prev.messages, modeMsg] }));
          break;
        }
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
            updateAgentState(activeTab, (prev) => ({ messages: [...prev.messages, infoMsg] }));
          } else {
            const infoMsg: Message = {
              id: generateId(),
              role: "assistant",
              content: `Available effort levels:\n- ⚡ **low** — minimal thinking, fastest\n- ⚖️ **medium** — balanced\n- 🧠 **high** — deep reasoning (default)\n- 🔬 **max** — maximum deliberation\n\nUsage: \`/effort high\`\n\nCurrent: **${effortLevel}**`,
              timestamp: new Date(),
            };
            updateAgentState(activeTab, (prev) => ({ messages: [...prev.messages, infoMsg] }));
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
              "| `/agent` | Toggle Agent Zero engine mode (tools, memory, code exec) |",
              "| `/effort <level>` | Set reasoning effort (low/medium/high/max) |",
              "| `/theme <name>` | Switch theme |",
              "| `/help` | Show this help |",
              "| `/export` | Export chat as markdown |",
            ].join("\n"),
            timestamp: new Date(),
          };
          updateAgentState(activeTab, (prev) => ({ messages: [...prev.messages, helpMsg] }));
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
    [handleNewChat, messages, activeTab, updateAgentState, agentMode]
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;

    // Finalize whatever content was streamed so far for all running agents
    setAgentStates((prev) => {
      const next = { ...prev };
      for (const [agentName, state] of Object.entries(next)) {
        if (state.streamingContent.trim() || state.status === "running") {
          const finalMsg: Message = {
            id: generateId(),
            role: "assistant",
            content: state.streamingContent + (state.streamingContent.trim() ? "\n\n*(generation stopped)*" : "*(generation stopped)*"),
            timestamp: new Date(),
          };
          next[agentName] = {
            ...state,
            messages: [...state.messages, finalMsg],
            streamingContent: "",
            liveCode: "",
            actions: [],
            showActions: false,
            status: "done"
          };
        }
      }
      return next;
    });

    setIsLoading(false);
  }, []);

  const handleSend = useCallback(
    async (text: string, attachments?: any[]) => {
      if ((!text.trim() && (!attachments || attachments.length === 0)) || isLoading) return;

      const userMessage: Message = {
        id: generateId(),
        role: "user",
        content: text,
        timestamp: new Date(),
      };

      // Set running state for the targeted agent tab
      const targetAgent = activeTab;
      
      updateAgentState(targetAgent, (prev) => ({
        messages: [...prev.messages, userMessage],
        aiPhase: "thinking",
        streamingContent: "",
        liveCode: "",
        showActions: true,
        status: "running",
        actions: [{
          id: generateId(),
          phase: "thinking",
          summary: phaseSummaries.thinking,
          timestamp: new Date(),
        }]
      }));

      setIsLoading(true);

      // We maintain accumulated content per agent in this local object
      const accumulatedContent: Record<string, string> = {};
      const actionTimers: Record<string, ReturnType<typeof setTimeout>> = {};

      const streamFn = agentMode ? api.streamAgentEngine : api.streamMessage;
      
      const controller = streamFn(conversationId, text, {
        onStatus(phase, convId, streamAgentName = "Main Agent") {
          if (convId) setConversationId(convId);

          updateAgentState(streamAgentName, (prev) => {
            const newActions = [...prev.actions];
            // Avoid duplicate consecutive phases
            if (newActions.length === 0 || newActions[newActions.length - 1].phase !== phase) {
               newActions.push({
                id: generateId(),
                phase,
                summary: phaseSummaries[phase] || phase,
                timestamp: new Date(),
              });
            }
            return {
              aiPhase: phase,
              actions: newActions,
              status: "running"
            };
          });
        },
        onToken(content, streamAgentName = "Main Agent") {
          accumulatedContent[streamAgentName] = (accumulatedContent[streamAgentName] || "") + content;
          
          updateAgentState(streamAgentName, (prev) => {
            const newActions = [...prev.actions];
            if (newActions.length > 0) {
              const last = { ...newActions[newActions.length - 1] };
              if (last.phase === "coding" || last.phase === "thinking") {
                last.details = accumulatedContent[streamAgentName].slice(-500);
                newActions[newActions.length - 1] = last;
              }
            }
            return {
              streamingContent: accumulatedContent[streamAgentName],
              actions: newActions,
              status: "running"
            };
          });
        },
        onCode(language, content, streamAgentName = "Main Agent") {
          updateAgentState(streamAgentName, () => ({ liveCode: content }));
        },
        onToolCall(event) {
          const streamAgentName = event.agentName || "Main Agent";
          const label = toolLabels[event.tool] || `🔧 ${event.tool}`;
          
          updateAgentState(streamAgentName, (prev) => ({
            aiPhase: "calling_tool",
            status: "running",
            actions: [
              ...prev.actions,
              {
                id: generateId(),
                phase: "calling_tool" as AiPhase,
                summary: `${label}`,
                details: JSON.stringify(event.params, null, 2).slice(0, 300),
                timestamp: new Date(),
              }
            ]
          }));
        },
        onToolResult(event) {
          const streamAgentName = event.agentName || "Main Agent";
          
          updateAgentState(streamAgentName, (prev) => {
            if (prev.actions.length === 0) return prev;
            const newActions = [...prev.actions];
            const last = { ...newActions[newActions.length - 1] };
            const statusEmoji = event.success ? "✅" : "❌";
            last.summary = `${statusEmoji} ${toolLabels[event.tool] || event.tool} — ${event.success ? "done" : "failed"}`;
            last.details = event.output.slice(0, 500);
            newActions[newActions.length - 1] = last;
            return { actions: newActions };
          });
        },
        onDone(messageId, _model, convId, _latencyMs, streamAgentName = "Main Agent") {
          if (convId) setConversationId(convId);
          
          const text = accumulatedContent[streamAgentName] || "";
          
          updateAgentState(streamAgentName, (prev) => ({
            messages: [...prev.messages, { id: messageId, role: "assistant", content: text, timestamp: new Date() }],
            streamingContent: "",
            liveCode: "",
            status: "done",
            aiPhase: "thinking"
          }));
          
          // Clear actions after 1.5s
          if (actionTimers[streamAgentName]) clearTimeout(actionTimers[streamAgentName]);
          actionTimers[streamAgentName] = setTimeout(() => {
            updateAgentState(streamAgentName, () => ({ showActions: false, actions: [] }));
          }, 1500);
          
          // Only the target agent finishing marks overall loading as false
          if (streamAgentName === targetAgent) {
             setIsLoading(false);
             abortRef.current = null;
          }
        },
        onAgentDone(streamAgentName) {
           const text = accumulatedContent[streamAgentName] || "";
           
           updateAgentState(streamAgentName, (prev) => ({
             messages: [...prev.messages, { id: generateId(), role: "assistant", content: text, timestamp: new Date() }],
             streamingContent: "",
             liveCode: "",
             status: "done",
             aiPhase: "thinking"
           }));
           
           if (actionTimers[streamAgentName]) clearTimeout(actionTimers[streamAgentName]);
           actionTimers[streamAgentName] = setTimeout(() => {
             updateAgentState(streamAgentName, () => ({ showActions: false, actions: [] }));
           }, 1500);
        },
        onError(detail, streamAgentName = "Main Agent") {
          const text = accumulatedContent[streamAgentName] || "";
          
          updateAgentState(streamAgentName, (prev) => {
            let errorMsgs = [];
            if (text.trim()) {
              errorMsgs.push({ id: generateId(), role: "assistant", content: text, timestamp: new Date() } as Message);
            }
            errorMsgs.push({ id: generateId(), role: "assistant", content: `Sorry, an error occurred: ${detail}`, timestamp: new Date() } as Message);
            
            return {
              messages: [...prev.messages, ...errorMsgs],
              streamingContent: "",
              liveCode: "",
              status: "error"
            };
          });

          if (streamAgentName === targetAgent) {
             setIsLoading(false);
             abortRef.current = null;
          }
        }
      }, targetAgent, attachments);

      abortRef.current = controller;
    },
    [conversationId, isLoading, activeTab, updateAgentState, agentMode]
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
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-white">Chat</h2>
          {agentMode && (
            <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
              <Zap size={10} className="fill-blue-400" /> Agent Mode
            </span>
          )}
        </div>
        <button
          onClick={handleNewChat}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400 hover:text-white glass-button"
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Agent Tabs (Shown only when there are multiple agents) */}
      {Object.keys(agentStates).length > 1 && (
        <div className="flex items-center gap-1 px-4 py-2 bg-[#0A0A0A] border-b border-white/5 overflow-x-auto hide-scrollbar">
          {Object.keys(agentStates).map((agentName) => (
            <button
              key={agentName}
              onClick={() => setActiveTab(agentName)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm whitespace-nowrap transition-colors ${
                activeTab === agentName
                  ? "bg-white/10 text-white font-medium"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              }`}
            >
              <Bot size={14} className={activeTab === agentName ? "text-blue-400" : "text-gray-500"} />
              {agentName}
              {agentStates[agentName].status === "running" && (
                 <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
              )}
            </button>
          ))}
        </div>
      )}

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
