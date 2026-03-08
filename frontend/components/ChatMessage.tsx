"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ThumbsUp, ThumbsDown, Bot } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CodeBlock from "./CodeBlock";
import { cn, formatTimestamp } from "@/lib/utils";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface ChatMessageProps {
  message: Message;
  onFeedback?: (messageId: string, rating: 1 | 2) => void;
  /** When true, shows a blinking cursor at the end of the message */
  isStreaming?: boolean;
}

export default function ChatMessage({ message, onFeedback, isStreaming = false }: ChatMessageProps) {
  const [feedback, setFeedback] = useState<1 | 2 | null>(null);
  const isUser = message.role === "user";

  const handleFeedback = (rating: 1 | 2) => {
    setFeedback(rating);
    onFeedback?.(message.id, rating);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn("flex gap-3 px-4 py-3", isUser ? "justify-end" : "justify-start")}
    >
      {/* AI avatar */}
      {!isUser && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center mt-1">
          <Bot size={16} className="text-accent" />
        </div>
      )}

      <div className={cn("max-w-[75%] flex flex-col", isUser ? "items-end" : "items-start")}>
        {/* Label */}
        {!isUser && (
          <span className="text-xs text-accent font-medium mb-1 ml-1">Pub AI</span>
        )}

        {/* Message bubble */}
        <div
          className={cn(
            "px-4 py-3 rounded-2xl text-sm leading-relaxed",
            isUser
              ? "bg-accent/20 border border-accent/20 text-white"
              : "bg-white/5 border border-white/10 text-gray-100"
          )}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || "");
                const codeString = String(children).replace(/\n$/, "");
                if (match) {
                  return <CodeBlock code={codeString} language={match[1]} />;
                }
                return (
                  <code
                    className="bg-white/10 px-1.5 py-0.5 rounded text-accent text-xs"
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
                  <a href={href} className="text-accent hover:underline" target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                );
              },
            }}
          >
            {message.content}
          </ReactMarkdown>
          {isStreaming && (
            <span className="inline-block w-1.5 h-4 bg-accent/70 rounded-sm ml-0.5 align-middle animate-typewriter-cursor" />
          )}
        </div>

        {/* Footer: timestamp + feedback */}
        <div className="flex items-center gap-2 mt-1 ml-1">
          <span className="text-[10px] text-gray-500">
            {formatTimestamp(message.timestamp)}
          </span>

          {!isUser && (
            <div className="flex items-center gap-1">
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
    </motion.div>
  );
}
