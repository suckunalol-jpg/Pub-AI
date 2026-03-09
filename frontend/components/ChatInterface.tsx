"use client";

import { useState, useRef, useEffect, useCallback, memo } from "react";
import { AnimatePresence } from "framer-motion";
import { Plus } from "lucide-react";
import ChatMessage, { type Message } from "./ChatMessage";
import ChatInputBar from "./ChatInputBar";
import ActionIndicator, { type AiPhase, type ActionEntry } from "./ActionIndicator";
import { generateId } from "@/lib/utils";
import * as api from "@/lib/api";

// Phase-to-summary mapping for action entries
const phaseSummaries: Record<AiPhase, string> = {
  thinking: "Analyzing your request...",
  coding: "Writing code...",
  executing: "Running code...",
  searching: "Searching knowledge base...",
  reviewing: "Reviewing output...",
};

// Memoize ChatMessage for the messages list
const MemoizedChatMessage = memo(ChatMessage);

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);

  // Streaming state
  const [aiPhase, setAiPhase] = useState<AiPhase>("thinking");
  const [streamingContent, setStreamingContent] = useState("");
  const [liveCode, setLiveCode] = useState("");
  const [actions, setActions] = useState<ActionEntry[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll: use "auto" during streaming to prevent shaking, "smooth" after completion
  useEffect(() => {
    if (isLoading) {
      messagesEndRef.current?.scrollIntoView({ behavior: "auto" });
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

  const handleNewChat = () => {
    abortRef.current?.abort();
    setMessages([]);
    setConversationId(null);
    setIsLoading(false);
    setStreamingContent("");
    setLiveCode("");
    setActions([]);
  };

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
          setActions([]);
          abortRef.current = null;
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
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <div className="font-arcade text-2xl text-white mb-3" style={{ textShadow: "0 0 15px rgba(255,255,255,0.2)" }}>
              Pub++
            </div>
            <p className="text-gray-500 text-sm max-w-md">
              Start a conversation. Ask questions, write code, build projects.
            </p>
          </div>
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
        {isLoading && (
          <ActionIndicator
            phase={aiPhase}
            actions={actions}
            liveCode={liveCode}
          />
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input bar -- extracted component to prevent re-renders on typing */}
      <ChatInputBar onSend={handleSend} onStop={handleStop} isLoading={isLoading} />
    </div>
  );
}
