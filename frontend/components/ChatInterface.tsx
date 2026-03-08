"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Plus, Square } from "lucide-react";
import ChatMessage, { type Message } from "./ChatMessage";
import ActionIndicator, { type AiPhase } from "./ActionIndicator";
import GlassCard from "./GlassCard";
import { generateId } from "@/lib/utils";
import * as api from "@/lib/api";

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);

  // Streaming state
  const [aiPhase, setAiPhase] = useState<AiPhase>("thinking");
  const [streamingContent, setStreamingContent] = useState("");
  const [liveCode, setLiveCode] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages or streaming content
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
    }
  }, [input]);

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
    setInput("");
    setIsLoading(false);
    setStreamingContent("");
    setLiveCode("");
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
  }, []);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);
    setAiPhase("thinking");
    setStreamingContent("");
    setLiveCode("");

    // Accumulate tokens in a ref-accessible variable for the callbacks
    let accumulatedContent = "";

    const controller = api.streamMessage(conversationId, trimmed, {
      onStatus(phase, convId) {
        setAiPhase(phase);
        if (convId) {
          setConversationId(convId);
        }
      },
      onToken(content) {
        accumulatedContent += content;
        setStreamingContent(accumulatedContent);
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
        abortRef.current = null;
      },
    });

    abortRef.current = controller;
  }, [input, isLoading, conversationId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

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
            <ChatMessage key={msg.id} message={msg} onFeedback={handleFeedback} />
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

        {/* Action indicator: shows current phase */}
        {isLoading && (
          <AnimatePresence mode="wait">
            <ActionIndicator
              key={aiPhase}
              phase={aiPhase}
              liveCode={liveCode}
            />
          </AnimatePresence>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input bar */}
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
              onClick={handleStop}
              className="flex-shrink-0 p-2 rounded-xl bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all"
              title="Stop generating"
            >
              <Square size={18} />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="flex-shrink-0 p-2 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
            >
              <Send size={18} />
            </button>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
