"use client";

import { useState, memo } from "react";
import { motion } from "framer-motion";
import { ThumbsUp, ThumbsDown, Bot, Volume2, Square } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CodeBlock from "./CodeBlock";
import { cn, formatTimestamp } from "@/lib/utils";
import { useThemeStore } from "@/lib/themeStore";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatMessageProps {
  message: Message;
  onFeedback?: (messageId: string, rating: 1 | 2) => void;
  isStreaming?: boolean;
}

function ChatMessage({ message, onFeedback, isStreaming = false }: ChatMessageProps) {
  const [feedback, setFeedback] = useState<1 | 2 | null>(null);
  const theme = useThemeStore((s) => s.theme);
  const isUser = message.role === "user";

  // TTS State
  const [isPlaying, setIsPlaying] = useState(false);

  const handlePlayTTS = () => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    
    const synth = window.speechSynthesis;
    
    if (isPlaying) {
      synth.cancel();
      setIsPlaying(false);
      return;
    }

    // Stop any currently playing audio before starting new one
    synth.cancel();

    const utterance = new SpeechSynthesisUtterance(message.content);
    utterance.onend = () => setIsPlaying(false);
    utterance.onerror = () => setIsPlaying(false);
    
    setIsPlaying(true);
    synth.speak(utterance);
  };

  const handleFeedback = (rating: 1 | 2) => {
    setFeedback(rating);
    onFeedback?.(message.id, rating);
  };

  // When streaming, skip the motion.div animation to prevent shaking
  const Wrapper = isStreaming ? "div" : motion.div;
  const wrapperProps = isStreaming
    ? {}
    : {
      initial: { opacity: 0, y: 8 },
      animate: { opacity: 1, y: 0 },
      transition: { duration: 0.2 },
    };

  // Terminal Theme Layout
  if (theme === "terminal") {
    return (
      <Wrapper {...(wrapperProps as any)} className="px-6 py-1.5 font-mono text-sm">
        <div className="flex flex-col">
          <div className={cn(
            "chat-message-terminal",
            isUser ? "chat-message-user" : "chat-message-ai"
          )}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                pre({ children }) { return <div className="not-prose my-2">{children}</div>; },
                code({ className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || "");
                  const codeString = String(children).replace(/\n$/, "");
                  const isBlock = match || codeString.includes("\n");
                  if (isBlock) return <CodeBlock code={codeString} language={match?.[1] || "text"} />;
                  return <code className="text-blue-300 bg-blue-500/10 px-1 py-0.5 rounded" {...props}>{children}</code>;
                },
                p({ children }) { return <span className="mr-2 leading-relaxed">{children}</span>; },
                ul({ children }) { return <ul className="list-disc ml-4 my-1 space-y-1 block w-full">{children}</ul>; },
                ol({ children }) { return <ol className="list-decimal ml-4 my-1 space-y-1 block w-full">{children}</ol>; },
              }}
            >
              {message.content}
            </ReactMarkdown>
            {isStreaming && <span className="inline-block w-2 h-4 bg-blue-400 ml-1 align-middle animate-typewriter-cursor" />}
          </div>
        </div>
      </Wrapper>
    );
  }

  // Standard Layout (Midnight, Mizzy, Default)
  return (
    <Wrapper
      {...(wrapperProps as any)}
      className={cn("flex gap-3 px-4 py-3", isUser ? "justify-end" : "justify-start")}
    >
      {/* AI avatar */}
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center mt-1"
          style={{ background: "rgba(var(--accent-rgb, 0,170,255), 0.2)" }}>
          <Bot size={16} style={{ color: "var(--accent)" }} />
        </div>
      )}

      <div className={cn("max-w-[75%] flex flex-col", isUser ? "items-end" : "items-start")}>
        {/* Label */}
        {!isUser && (
          <span className="text-xs font-medium mb-1 ml-1" style={{ color: "var(--accent)" }}>
            Pub AI
          </span>
        )}

        {/* Message bubble — uses theme CSS classes */}
        <div
          className={cn(
            "px-4 py-3 rounded-2xl text-sm leading-relaxed",
            isUser
              ? "chat-message-user"
              : "chat-message-ai"
          )}
          style={{
            background: isUser ? "var(--msg-user-bg)" : "var(--msg-ai-bg)",
            border: `1px solid ${isUser ? "var(--msg-user-border)" : "var(--msg-ai-border)"}`,
            color: "var(--text-primary)",
          }}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              pre({ children }) {
                return <div className="not-prose">{children}</div>;
              },
              code({ className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || "");
                const codeString = String(children).replace(/\n$/, "");
                const isBlock = match || codeString.includes("\n");
                if (isBlock) {
                  return <CodeBlock code={codeString} language={match?.[1] || "text"} />;
                }
                return (
                  <code
                    className="bg-white/10 px-1.5 py-0.5 rounded text-xs"
                    style={{ color: "var(--accent)" }}
                    {...props}
                  >
                    {children}
                  </code>
                );
              },
              p({ children }) {
                return <p className="mb-2 last:mb-0">{children}</p>;
              },
              ul({ children }) {
                return <ul className="list-disc ml-4 mb-2 space-y-1">{children}</ul>;
              },
              ol({ children }) {
                return <ol className="list-decimal ml-4 mb-2 space-y-1">{children}</ol>;
              },
              a({ href, children }) {
                return (
                  <a href={href} className="hover:underline" style={{ color: "var(--accent)" }} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                );
              },
            }}
          >
            {message.content}
          </ReactMarkdown>
          {isStreaming && (
            <span className="inline-block w-1.5 h-4 rounded-sm ml-0.5 align-middle animate-typewriter-cursor"
              style={{ background: "var(--accent)", opacity: 0.7 }} />
          )}
        </div>

        {/* Footer: timestamp + feedback */}
        <div className="flex items-center gap-2 mt-1 ml-1">
          <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
            {formatTimestamp(message.timestamp)}
          </span>

          {!isUser && (
            <div className="flex items-center gap-1">
              <button
                onClick={handlePlayTTS}
                className={cn(
                  "p-1 rounded transition-colors",
                  isPlaying ? "text-accent animate-pulse" : "text-gray-600 hover:text-gray-400"
                )}
                title={isPlaying ? "Stop listening" : "Listen to message"}
              >
                {isPlaying ? <Square size={12} /> : <Volume2 size={12} />}
              </button>
              <button
                onClick={() => handleFeedback(2)}
                className={cn(
                  "p-1 rounded transition-colors",
                  feedback === 2 ? "text-green-400" : "text-gray-600 hover:text-gray-400"
                )}
              >
                <ThumbsUp size={12} />
              </button>
              <button
                onClick={() => handleFeedback(1)}
                className={cn(
                  "p-1 rounded transition-colors",
                  feedback === 1 ? "text-red-400" : "text-gray-600 hover:text-gray-400"
                )}
              >
                <ThumbsDown size={12} />
              </button>
            </div>
          )}
        </div>
      </div>
    </Wrapper>
  );
}

export default memo(ChatMessage);
