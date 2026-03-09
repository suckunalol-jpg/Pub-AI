"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Maximize2, Minimize2, Copy, Check } from "lucide-react";
import { usePreviewStore } from "@/lib/previewStore";
import { copyToClipboard } from "@/lib/utils";

export default function PreviewSidebar() {
  const { isOpen, content, language, close } = usePreviewStore();
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const success = await copyToClipboard(content);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const srcDoc = useMemo(() => {
    if (!content) return "";

    const lowerLang = language.toLowerCase();

    if (lowerLang === "css") {
      return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>${content}</style>
</head>
<body>
  <div class="preview">Preview</div>
</body>
</html>`;
    }

    if (lowerLang === "svg") {
      return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>body { margin: 0; display: flex; align-items: center; justify-content: center; min-height: 100vh; background: #1a1a2e; }</style>
</head>
<body>
  ${content}
</body>
</html>`;
    }

    // HTML, HTM, JSX, TSX -- render directly
    // For JSX/TSX we render as-is (best effort, no transpiler)
    return content;
  }, [content, language]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ x: "100%" }}
          animate={{ x: 0 }}
          exit={{ x: "100%" }}
          transition={{ type: "spring", damping: 25, stiffness: 300 }}
          className={`absolute top-0 right-0 z-30 h-full flex flex-col bg-black/80 backdrop-blur-xl border-l border-white/10 ${
            isFullscreen ? "w-full" : "w-1/2"
          }`}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-white/5">
            <span className="text-sm font-medium text-gray-300">
              Preview
              <span className="ml-2 text-xs text-gray-500 uppercase">{language}</span>
            </span>

            <div className="flex items-center gap-2">
              {/* Copy button */}
              <button
                onClick={handleCopy}
                className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                title="Copy code"
              >
                {copied ? (
                  <Check size={16} className="text-green-400" />
                ) : (
                  <Copy size={16} />
                )}
              </button>

              {/* Fullscreen toggle */}
              <button
                onClick={() => setIsFullscreen(!isFullscreen)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
              >
                {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
              </button>

              {/* Close button */}
              <button
                onClick={close}
                className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                title="Close preview"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Iframe preview */}
          <div className="flex-1 overflow-hidden">
            <iframe
              srcDoc={srcDoc}
              sandbox="allow-scripts"
              className="w-full h-full bg-white"
              title="Code Preview"
            />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
