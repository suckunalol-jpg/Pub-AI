"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Upload,
  FileText,
  Search,
  Trash2,
  Loader2,
  CheckCircle2,
  X,
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn, formatTimestamp } from "@/lib/utils";
import * as api from "@/lib/api";

interface KnowledgeEntry {
  id: string;
  title: string;
  source_type: string;
  created_at: string;
}

interface SearchResult {
  id: string;
  content: string;
  distance: number | null;
  metadata: Record<string, unknown>;
}

export default function KnowledgeUpload() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sourceType, setSourceType] = useState("doc");
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [loading, setLoading] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadEntries();
  }, []);

  const loadEntries = async () => {
    try {
      const data = await api.getKnowledgeEntries();
      setEntries(data);
    } catch {
      // TODO: handle error
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async () => {
    if (!title.trim() || !content.trim()) return;
    setUploading(true);
    try {
      await api.uploadKnowledge(title, content, sourceType);
      setTitle("");
      setContent("");
      setUploadSuccess(true);
      setTimeout(() => setUploadSuccess(false), 3000);
      await loadEntries();
    } catch {
      // TODO: handle error
    } finally {
      setUploading(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const res = await api.queryKnowledge(searchQuery);
      setSearchResults(res.entries);
    } catch {
      // TODO: handle error
    } finally {
      setSearching(false);
    }
  };

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      const file = files[0];
      setTitle(file.name);
      const reader = new FileReader();
      reader.onload = (ev) => {
        setContent(ev.target?.result as string || "");
      };
      reader.readAsText(file);
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setTitle(file.name);
      const reader = new FileReader();
      reader.onload = (ev) => {
        setContent(ev.target?.result as string || "");
      };
      reader.readAsText(file);
    }
  };

  const sourceTypes = [
    { id: "doc", label: "Document" },
    { id: "qa", label: "Q&A" },
    { id: "code", label: "Code" },
    { id: "manual", label: "Manual" },
  ];

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-white">Knowledge Base</h2>
        <p className="text-sm text-gray-500 mt-1">
          Upload documents and data to enhance AI responses.
        </p>
      </div>

      {/* Search */}
      <GlassCard className="p-4">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search knowledge base..."
              className="w-full glass-input pl-10 pr-4 py-2.5 text-sm"
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={!searchQuery.trim() || searching}
            className="px-4 py-2.5 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all text-sm"
          >
            {searching ? <Loader2 size={16} className="animate-spin" /> : "Search"}
          </button>
        </div>

        {/* Search results */}
        <AnimatePresence>
          {searchResults.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-3 space-y-2"
            >
              {searchResults.map((result, i) => (
                <div key={i} className="bg-white/5 border border-white/10 rounded-lg p-3">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-white">
                      {String(result.metadata?.title || result.id || "Result")}
                    </span>
                    {result.distance !== null && (
                      <span className="text-xs text-gray-500">
                        {((1 - (result.distance ?? 1)) * 100).toFixed(0)}% match
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 line-clamp-2">{result.content}</p>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </GlassCard>

      {/* Upload section */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-gray-300 mb-4">Add Knowledge</h3>

        {/* File drop zone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={cn(
            "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all mb-4",
            isDragging
              ? "border-accent/50 bg-accent/5"
              : "border-white/10 hover:border-white/20 hover:bg-white/5"
          )}
        >
          <Upload size={24} className="mx-auto mb-2 text-gray-500" />
          <p className="text-sm text-gray-400">
            Drop a file here or <span className="text-accent">browse</span>
          </p>
          <p className="text-xs text-gray-600 mt-1">Text files, code, documents</p>
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFileSelect}
            className="hidden"
            accept=".txt,.md,.py,.js,.ts,.lua,.json,.csv"
          />
        </div>

        {/* Manual input */}
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title..."
          className="w-full glass-input px-4 py-2.5 text-sm mb-3"
        />

        {/* Source type */}
        <div className="flex gap-2 mb-3">
          {sourceTypes.map((st) => (
            <button
              key={st.id}
              onClick={() => setSourceType(st.id)}
              className={cn(
                "px-3 py-1.5 text-xs rounded-lg border transition-all",
                sourceType === st.id
                  ? "bg-accent/15 border-accent/30 text-accent"
                  : "bg-white/5 border-white/10 text-gray-400 hover:text-white"
              )}
            >
              {st.label}
            </button>
          ))}
        </div>

        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Paste content, Q&A pairs, or documentation..."
          rows={5}
          className="w-full glass-input px-4 py-3 text-sm resize-none mb-3"
        />

        <div className="flex items-center gap-3">
          <button
            onClick={handleUpload}
            disabled={!title.trim() || !content.trim() || uploading}
            className="px-4 py-2.5 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all text-sm font-medium flex items-center gap-2"
          >
            {uploading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Upload size={16} />
            )}
            Upload
          </button>
          {uploadSuccess && (
            <motion.span
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-1 text-xs text-green-400"
            >
              <CheckCircle2 size={14} />
              Uploaded successfully
            </motion.span>
          )}
        </div>
      </GlassCard>

      {/* Entries list */}
      <div>
        <h3 className="text-sm font-medium text-gray-300 mb-3">
          Ingested Entries {entries.length > 0 && `(${entries.length})`}
        </h3>
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-accent" />
          </div>
        ) : entries.length === 0 ? (
          <GlassCard className="p-8 text-center">
            <FileText size={32} className="text-gray-600 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No knowledge entries yet</p>
          </GlassCard>
        ) : (
          <div className="space-y-2">
            {entries.map((entry) => (
              <GlassCard key={entry.id} className="p-4 flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
                  <FileText size={16} className="text-accent" />
                </div>
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-white block truncate">
                    {entry.title}
                  </span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-gray-500 capitalize">{entry.source_type}</span>
                    <span className="text-xs text-gray-600">
                      {formatTimestamp(entry.created_at)}
                    </span>
                  </div>
                </div>
              </GlassCard>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
