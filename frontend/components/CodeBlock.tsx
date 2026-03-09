"use client";

import { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Check, Eye } from "lucide-react";
import { copyToClipboard } from "@/lib/utils";
import { usePreviewStore } from "@/lib/previewStore";

interface CodeBlockProps {
  code: string;
  language?: string;
}

const PREVIEWABLE_LANGUAGES = new Set(["html", "htm", "css", "svg", "jsx", "tsx"]);

export default function CodeBlock({ code, language = "text" }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const canPreview = PREVIEWABLE_LANGUAGES.has(language.toLowerCase());

  const handleCopy = async () => {
    const success = await copyToClipboard(code);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handlePreview = () => {
    usePreviewStore.getState().open(code, language);
  };

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden my-3 bg-black/40">
      {/* Language header bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-white/5 border-b border-white/10">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">
          {language}
        </span>
        <div className="flex items-center gap-3">
          {canPreview && (
            <button
              onClick={handlePreview}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors"
            >
              <Eye size={14} />
              <span>Preview</span>
            </button>
          )}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors"
          >
            {copied ? (
              <>
                <Check size={14} className="text-green-400" />
                <span className="text-green-400">Copied!</span>
              </>
            ) : (
              <>
                <Copy size={14} />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Code body */}
      <SyntaxHighlighter
        language={language}
        style={oneDark}
        customStyle={{
          margin: 0,
          padding: "16px",
          background: "transparent",
          fontSize: "13px",
        }}
        codeTagProps={{
          style: { fontFamily: "'Fira Code', 'Cascadia Code', monospace" },
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
