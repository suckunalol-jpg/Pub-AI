"use client";

import { useState, memo } from "react";
import { motion } from "framer-motion";
import { ThumbsUp, ThumbsDown, Bot, Volume2, Square } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CodeBlock from "./CodeBlock";
import { cn, formatTimestamp } from "@/lib/utils";
import { useThemeStore } from "@/lib/themeStore";
import PixelMascot from "./PixelMascot";

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
      <Wrapper {...(wrapperProps as any)} className="px-2 py-2 font-mono text-[13px] leading-relaxed w-full">
        <div className="flex items-start gap-4 hover:bg-white/[0.02] transition-colors p-2 rounded-sm group">
          
          {/* Avatar / Prompt Prefix */}
          <div className="flex-shrink-0 pt-0.5 select-none w-8 flex justify-end">
            {isUser ? (
              <span className="text-accent font-bold">$</span>
            ) : (
              <PixelMascot phase="response" size={24} className="filter grayscale opacity-70 group-hover:grayscale-0 group-hover:opacity-100 transition-all duration-300" />
            )}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className={cn(
              "break-words",
              isUser ? "text-accent/90 mix-blend-screen" : "text-gray-300"
            )}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  pre({ children }) { return <div className="not-prose my-3 border border-[#30363d] rounded-md overflow-hidden bg-[#0d1117]">{children}</div>; },
                  code({ className, children, ...props }) {
                    const match = /language-(\w+)/.exec(className || "");
                    const codeString = String(children).replace(/\n$/, "");
                    const isBlock = match || codeString.includes("\n");
                    if (isBlock) return <CodeBlock code={codeString} language={match?.[1] || "text"} />;
                    return <code className="text-accent/90 bg-accent/10 px-1 py-0.5 rounded-sm mx-0.5 text-xs font-mono border border-accent/20" {...props}>{children}</code>;
                  },
                  p({ children }) { return <div className="mb-2 last:mb-0 leading-[1.6]">{children}</div>; },
                  ul({ children }) { return <ul className="list-disc ml-5 mb-2 space-y-1 marker:text-accent/50">{children}</ul>; },
                  ol({ children }) { return <ol className="list-decimal ml-5 mb-2 space-y-1 marker:text-accent/50">{children}</ol>; },
                  a({ href, children }) { return <a href={href} className="text-accent hover:underline underline-offset-4" target="_blank" rel="noopener noreferrer">{children}</a>; },
                  strong({ children }) { return <strong className="text-white font-semibold">{children}</strong>; },
                  blockquote({ children }) { return <blockquote className="border-l-2 border-accent/50 pl-3 italic text-gray-400 my-2">{children}</blockquote>; }
                }}
              >
                {message.content}
              </ReactMarkdown>
              {isStreaming && <span className="inline-block w-2 h-4 bg-accent ml-1 align-middle animate-typewriter-cursor" />}
            </div>
            
            {/* Tools & Feedback Footer */}
            <div className="flex items-center gap-3 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <span className="text-[10px] text-gray-600 font-mono">
                {formatTimestamp(message.timestamp)}
              </span>

              {!isUser && (
                <div className="flex items-center gap-1.5 border border-[#30363d] rounded bg-[#0d1117] px-1 py-0.5">
                  <button
                    onClick={handlePlayTTS}
                    className={cn(
                      "p-1 rounded text-gray-500 hover:text-white transition-colors",
                      isPlaying && "text-accent animate-pulse"
                    )}
                    title={isPlaying ? "Stop listening" : "Listen to message"}
                  >
                    {isPlaying ? <Square size={12} /> : <Volume2 size={12} />}
                  </button>
                  <div className="w-px h-3 bg-[#30363d]" />
                  <button
                    onClick={() => handleFeedback(2)}
                    className={cn("p-1 rounded hover:text-green-400 transition-colors", feedback === 2 ? "text-green-400" : "text-gray-500")}
                  >
                    <ThumbsUp size={12} />
                  </button>
                  <button
                    onClick={() => handleFeedback(1)}
                    className={cn("p-1 rounded hover:text-red-400 transition-colors", feedback === 1 ? "text-red-400" : "text-gray-500")}
                  >
                    <ThumbsDown size={12} />
                  </button>
                </div>
              )}
            </div>

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
        <div className="flex-shrink-0 w-8 h-8 flex items-center justify-center mt-1">
          <PixelMascot phase="response" size={32} className="filter drop-shadow-[0_0_5px_rgba(91,139,184,0.5)]" />
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
