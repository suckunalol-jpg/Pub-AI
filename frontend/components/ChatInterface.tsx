"use client";

import { useState, useRef, useEffect, useCallback, memo, useMemo } from "react";
import { AnimatePresence } from "framer-motion";
import { Bot, Plus, Zap } from "lucide-react";
import ChatMessage, { type Message } from "./ChatMessage";
import ChatInputBar from "./ChatInputBar";
import ActionIndicator, { type AiPhase, type ActionEntry } from "./ActionIndicator";
import { generateId } from "@/lib/utils";
import * as api from "@/lib/api";
import { useThemeStore } from "@/lib/themeStore";
import { useChatStore } from "@/lib/chatStore";
import { useEffortStore, type EffortLevel } from "@/lib/effortStore";
import AgentCreatorModal from "./AgentCreatorModal";
import IDEPanel from "./IDEPanel";

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

const MemoizedChatMessage = memo(ChatMessage);

export default function ChatInterface() {
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>({ "Main Agent": { ...defaultAgentState } });
  const [activeTab, setActiveTab] = useState<string>("Main Agent");
  
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [username, setUsername] = useState<string>("user");
  
  const [showAgentCreator, setShowAgentCreator] = useState(false);
  const effortLevel = useEffortStore((s) => s.effort);
  const setEffortLevel = useEffortStore((s) => s.setEffort);
  const { selectedConversationId, setSelectedConversationId } = useChatStore();
  const [agentMode, setAgentMode] = useState(false);
  const [showIDE, setShowIDE] = useState(false);
  
  const abortRef = useRef<AbortController | null>(null);
  const sendRef = useRef<(text: string) => void>(() => { });
  const lastScrollRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const activeState = agentStates[activeTab] || defaultAgentState;
  const messages = activeState.messages;
  const streamingContent = activeState.streamingContent;
  const liveCode = activeState.liveCode;
  const actions = activeState.actions;
  const aiPhase = activeState.aiPhase;
  const showActions = activeState.showActions;

  useEffect(() => {
    if (typeof window !== "undefined") {
      setUsername(localStorage.getItem("pub_username") || "user");
    }
  }, []);

  const updateAgentState = useCallback((agentName: string, updater: (prev: AgentState) => Partial<AgentState>) => {
    setAgentStates((prev) => {
      const current = prev[agentName] || { ...defaultAgentState };
      return { ...prev, [agentName]: { ...current, ...updater(current) } };
    });
  }, []);

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

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // Listen for conversation changes from Sidebar
  useEffect(() => {
    if (selectedConversationId && selectedConversationId !== conversationId) {
      setConversationId(selectedConversationId);
      setIsLoading(true);
      
      api.getConversation(selectedConversationId)
        .then(data => {
          updateAgentState(activeTab, () => ({
            messages: data.messages.map(m => ({
              id: generateId(),
              role: m.role as "user" | "assistant",
              content: m.content,
              timestamp: new Date(m.created_at)
            })),
            streamingContent: "",
            liveCode: "",
            actions: [],
            status: "idle",
            aiPhase: "thinking"
          }));
          setIsLoading(false);
        })
        .catch((err) => {
          console.error("Failed to load conversation", err);
          setIsLoading(false);
        });
    }
  }, [selectedConversationId, conversationId, activeTab, updateAgentState]);

  // Check file count to auto-trigger IDE
  const checkProjectSize = useCallback(async () => {
    try {
      const files = await api.ideListFiles("");
      if (files.length > 5) {
        setShowIDE(true);
      }
    } catch {
      // ignore errors
    }
  }, []);

  // Check initially
  useEffect(() => {
    checkProjectSize();
  }, [checkProjectSize]);

  const handleNewChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setAgentStates({ "Main Agent": { ...defaultAgentState } });
    setActiveTab("Main Agent");
    setConversationId(null);
    setSelectedConversationId(null);
    setIsLoading(false);
  }, [setSelectedConversationId]);

  const handleSlashCommand = useCallback(
    (command: string, args: string) => {
      switch (command) {
        case "clear":
          updateAgentState(activeTab, () => ({ ...defaultAgentState }));
          break;
        case "new":
          handleNewChat();
          break;
        case "agents":
          setShowAgentCreator(true);
          break;
        case "agent": {
          setAgentMode((prev) => !prev);
          const modeMsg: Message = {
            id: generateId(),
            role: "assistant",
            content: `🤖 Agent mode **${!agentMode ? "ON" : "OFF"}**.`,
            timestamp: new Date(),
          };
          updateAgentState(activeTab, (prev) => ({ messages: [...prev.messages, modeMsg] }));
          break;
        }
        case "effort": {
          const level = args.trim().toLowerCase();
          if (["low", "medium", "high", "max"].includes(level)) {
            setEffortLevel(level as EffortLevel);
          }
          break;
        }
        default:
          sendRef.current(`/${command} ${args}`.trim());
      }
    },
    [handleNewChat, activeTab, updateAgentState, agentMode, setEffortLevel]
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setAgentStates((prev) => {
      const next = { ...prev };
      for (const [agentName, state] of Object.entries(next)) {
        if (state.streamingContent.trim() || state.status === "running") {
          const finalMsg: Message = {
            id: generateId(),
            role: "assistant",
            content: state.streamingContent + " *(stopped)*",
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

      const userMessage: Message = { id: generateId(), role: "user", content: text, timestamp: new Date() };
      const targetAgent = activeTab;
      
      updateAgentState(targetAgent, (prev) => ({
        messages: [...prev.messages, userMessage],
        aiPhase: "thinking",
        streamingContent: "",
        liveCode: "",
        showActions: true,
        status: "running",
        actions: [{ id: generateId(), phase: "thinking", summary: phaseSummaries.thinking, timestamp: new Date() }]
      }));

      setIsLoading(true);

      const accumulatedContent: Record<string, string> = {};
      const actionTimers: Record<string, ReturnType<typeof setTimeout>> = {};
      const streamFn = agentMode ? api.streamAgentEngine : api.streamMessage;
      
      const controller = streamFn(conversationId, text, {
        onStatus(phase, convId, streamAgentName = "Main Agent") {
          if (convId) setConversationId(convId);
          updateAgentState(streamAgentName, (prev) => {
            const newActions = [...prev.actions];
            if (newActions.length === 0 || newActions[newActions.length - 1].phase !== phase) {
               newActions.push({ id: generateId(), phase, summary: phaseSummaries[phase] || phase, timestamp: new Date() });
            }
            return { aiPhase: phase, actions: newActions, status: "running" };
          });
        },
        onToken(content, streamAgentName = "Main Agent") {
          accumulatedContent[streamAgentName] = (accumulatedContent[streamAgentName] || "") + content;
          updateAgentState(streamAgentName, (prev) => ({ streamingContent: accumulatedContent[streamAgentName], status: "running" }));
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
            actions: [...prev.actions, { id: generateId(), phase: "calling_tool", summary: label, details: JSON.stringify(event.params).slice(0, 100), timestamp: new Date() }]
          }));
        },
        onToolResult(event) {
          const streamAgentName = event.agentName || "Main Agent";
          updateAgentState(streamAgentName, (prev) => {
            if (prev.actions.length === 0) return prev;
            const newActions = [...prev.actions];
            const last = { ...newActions[newActions.length - 1] };
            last.summary = `${event.success ? "✅" : "❌"} ${toolLabels[event.tool] || event.tool}`;
            newActions[newActions.length - 1] = last;
            return { actions: newActions };
          });
        },
        onDone(messageId, _model, convId, _latencyMs, streamAgentName = "Main Agent") {
          if (convId) setConversationId(convId);
          const text = accumulatedContent[streamAgentName] || "";
          updateAgentState(streamAgentName, (prev) => ({
            messages: [...prev.messages, { id: messageId, role: "assistant", content: text, timestamp: new Date() }],
            streamingContent: "", liveCode: "", status: "done", aiPhase: "thinking"
          }));
          if (actionTimers[streamAgentName]) clearTimeout(actionTimers[streamAgentName]);
          actionTimers[streamAgentName] = setTimeout(() => updateAgentState(streamAgentName, () => ({ showActions: false, actions: [] })), 1500);
          if (streamAgentName === targetAgent) { 
            setIsLoading(false); 
            abortRef.current = null; 
            checkProjectSize();
          }
        },
        onAgentDone(streamAgentName) {
           const text = accumulatedContent[streamAgentName] || "";
           updateAgentState(streamAgentName, (prev) => ({
             messages: [...prev.messages, { id: generateId(), role: "assistant", content: text, timestamp: new Date() }],
             streamingContent: "", liveCode: "", status: "done", aiPhase: "thinking"
           }));
           if (actionTimers[streamAgentName]) clearTimeout(actionTimers[streamAgentName]);
           actionTimers[streamAgentName] = setTimeout(() => updateAgentState(streamAgentName, () => ({ showActions: false, actions: [] })), 1500);
           checkProjectSize();
        },
        onError(detail, streamAgentName = "Main Agent") {
          const text = accumulatedContent[streamAgentName] || "";
          updateAgentState(streamAgentName, (prev) => {
            let errorMsgs = [];
            if (text.trim()) errorMsgs.push({ id: generateId(), role: "assistant", content: text, timestamp: new Date() } as Message);
            errorMsgs.push({ id: generateId(), role: "assistant", content: `Error: ${detail}`, timestamp: new Date() } as Message);
            return { messages: [...prev.messages, ...errorMsgs], streamingContent: "", liveCode: "", status: "error" };
          });
          if (streamAgentName === targetAgent) { setIsLoading(false); abortRef.current = null; }
        }
      }, targetAgent, attachments);

      abortRef.current = controller;
    },
    [conversationId, isLoading, activeTab, updateAgentState, agentMode]
  );

  sendRef.current = handleSend;
  
  const handleFeedback = async (messageId: string, rating: 1 | 2) => {
    try { await api.sendFeedback(messageId, rating); } catch {}
  };

  return (
    <div className="flex flex-col h-full relative font-mono text-sm">

      {/* Agent Tabs */}
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#020813] border-b border-accent/20 shrink-0">
        <div className="flex items-center gap-1 overflow-x-auto hide-scrollbar">
          {Object.keys(agentStates).map((agentName) => (
            <button
              key={agentName}
              onClick={() => setActiveTab(agentName)}
              className={`flex items-center gap-2 px-3 py-1 rounded-sm text-xs whitespace-nowrap transition-colors ${
                activeTab === agentName
                  ? "bg-accent/20 text-accent font-bold border border-accent/30"
                  : "text-gray-500 hover:text-accent hover:bg-accent/5 border border-transparent"
              }`}
            >
              <Bot size={12} className={activeTab === agentName ? "text-accent" : "text-gray-600"} />
              {agentName}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          {showIDE && (
            <span className="text-xs text-accent/60 bg-accent/10 px-2 py-0.5 rounded-sm border border-accent/20">
              IDE Active ({">"}5 Files)
            </span>
          )}
          <button onClick={handleNewChat} className="text-gray-500 hover:text-accent p-1 text-xs uppercase tracking-widest flex items-center gap-1 transition-colors">
            <Plus size={12} /> New Thread
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden flex">
        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Messages / Terminal Area */}
          <div className="flex-1 overflow-y-auto py-4 px-2">
        {messages.length === 0 && !isLoading && (
          <div className="h-full flex flex-col justify-center px-8 lg:px-20 animate-fade-in relative max-w-5xl mx-auto">
            
            {/* Claude-Code styled Zero State */}
            <div className="text-accent/80 text-xs mb-8 flex items-center gap-3 relative before:content-[''] before:absolute before:left-0 before:top-1/2 before:w-16 before:h-px before:bg-accent/40 pl-20 uppercase tracking-widest">
              <span>Claude Code v2.1.72</span>
              <span className="w-16 h-px bg-accent/40" />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-0 border border-accent/40 rounded-sm">
              
              {/* Left Pane: Mascot and Welcome */}
              <div className="p-8 flex flex-col items-center justify-center border-b md:border-b-0 md:border-r border-accent/20 relative">
                <div className="text-accent font-bold mb-8 text-center text-lg">Welcome back {username}!</div>
                <img src="/mascot.png" alt="Mascot" className="h-24 filter drop-shadow-[0_0_12px_rgba(91,139,184,0.7)] hover:scale-105 transition-transform duration-300 animate-bounce-slow" />
                
                <div className="mt-8 text-center space-y-1 text-xs text-gray-500">
                  <div>Qwen 2.5 TPU with high effort · PubAI Pro</div>
                  <div>suckunalol@gmail.com's Organization</div>
                  <div className="text-accent/60 my-1 font-mono">C:\Users\{username}</div>
                </div>
              </div>

              {/* Right Pane: Recent Activity & What's New */}
              <div className="p-6 flex flex-col gap-6 bg-accent/5">
                
                <section>
                  <h3 className="text-accent/80 font-bold mb-2 text-xs uppercase tracking-widest">Recent activity</h3>
                  <div className="text-gray-400 text-xs space-y-1">
                    <div className="flex items-center gap-2 hover:text-accent cursor-pointer transition-colors">
                      <span className="text-gray-600">↳</span> No recent activity
                    </div>
                  </div>
                </section>

                <div className="h-px bg-accent/10 w-full" />

                <section>
                  <h3 className="text-accent/80 font-bold mb-2 text-xs uppercase tracking-widest">What's new</h3>
                  <div className="text-gray-400 text-xs space-y-2 leading-relaxed">
                    <div className="flex items-start gap-2">
                      <span className="text-accent mt-0.5">•</span>
                      <span>Added actionable suggestions to `/context` command — identifying areas for automation.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="text-accent mt-0.5">•</span>
                      <span>Added `autoMemoryDirectory` setting to configure a custom directory for saved contexts.</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <span className="text-accent mt-0.5">•</span>
                      <span>Fixed memory leak where streaming API response buffers were not garbage collected.</span>
                    </div>
                    <div className="mt-3 text-accent/60 italic hover:text-accent cursor-pointer transition-colors">
                      /release-notes for more
                    </div>
                  </div>
                </section>

              </div>
            </div>

            <div className="mt-6 text-gray-500/80 text-xs flex justify-between items-center px-1">
              <span>* Voice mode is now available · /voice to enable</span>
              <span className="animate-pulse text-accent">_</span>
            </div>
          </div>
        )}

        <div className="max-w-4xl mx-auto px-4">
          <AnimatePresence>
            {messages.map((msg) => (
              <MemoizedChatMessage key={msg.id} message={msg} onFeedback={handleFeedback} />
            ))}
          </AnimatePresence>

          {isLoading && streamingContent && (
            <ChatMessage
              key="streaming"
              message={{ id: "streaming", role: "assistant", content: streamingContent, timestamp: new Date() }}
              isStreaming
            />
          )}

          <AnimatePresence>
            {showActions && actions.length > 0 && (
              <ActionIndicator phase={aiPhase} actions={actions} liveCode={liveCode} />
            )}
          </AnimatePresence>

          <div ref={messagesEndRef} className="h-4" />
        </div>
      </div>

      {/* Terminal Input Bar */}
      <ChatInputBar onSend={handleSend} onStop={handleStop} onSlashCommand={handleSlashCommand} isLoading={isLoading} />
      </div>

      {/* Conditional IDE Panel */}
      {showIDE && (
        <div className="w-[800px] border-l border-accent/30 shrink-0 hidden md:block">
          <IDEPanel />
        </div>
      )}

      </div>
      
      <AgentCreatorModal open={showAgentCreator} onClose={() => setShowAgentCreator(false)} />
    </div>
  );
}
