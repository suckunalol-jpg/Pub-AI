"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Key,
  Plus,
  Copy,
  Check,
  Trash2,
  Eye,
  EyeOff,
  Loader2,
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn, copyToClipboard } from "@/lib/utils";
import * as api from "@/lib/api";

interface ApiKey {
  id: string;
  key_prefix: string;
  name: string;
  platform: string;
  is_active: boolean;
  created_at: string;
  fullKey?: string; // only available right after generation
}

export default function ApiKeyPanel() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [generating, setGenerating] = useState(false);
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadKeys();
  }, []);

  const loadKeys = async () => {
    try {
      const data = await api.getApiKeys();
      setKeys(data);
    } catch {
      // TODO: handle error
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!newKeyName.trim()) return;
    setGenerating(true);
    try {
      const res = await api.generateApiKey(newKeyName, "roblox");
      setNewlyCreatedKey(res.key);
      setNewKeyName("");
      await loadKeys();
    } catch {
      // TODO: handle error
    } finally {
      setGenerating(false);
    }
  };

  const handleRevoke = async (id: string) => {
    try {
      await api.revokeApiKey(id);
      setKeys((prev) => prev.filter((k) => k.id !== id));
    } catch {
      // TODO: handle error
    }
  };

  const handleCopy = async (text: string, id: string) => {
    const success = await copyToClipboard(text);
    if (success) {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-white">Roblox API</h2>
        <p className="text-sm text-gray-500 mt-1">
          Manage API keys for connecting your Roblox experience.
        </p>
      </div>

      {/* Generate new key */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-gray-300 mb-4">Generate New Key</h3>
        <div className="flex gap-2">
          <input
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="Key name (e.g., My Game)"
            className="flex-1 glass-input px-4 py-2.5 text-sm"
            onKeyDown={(e) => e.key === "Enter" && handleGenerate()}
          />
          <button
            onClick={handleGenerate}
            disabled={!newKeyName.trim() || generating}
            className="px-4 py-2.5 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all flex items-center gap-2 text-sm"
          >
            {generating ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
            Generate
          </button>
        </div>

        {/* Newly created key display */}
        <AnimatePresence>
          {newlyCreatedKey && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4"
            >
              <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-4">
                <p className="text-xs text-green-400 mb-2 font-medium">
                  Copy this key now. It will not be shown again.
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-black/40 px-3 py-2 rounded-lg text-xs text-green-300 font-mono break-all">
                    {newlyCreatedKey}
                  </code>
                  <button
                    onClick={() => handleCopy(newlyCreatedKey, "new")}
                    className="p-2 rounded-lg hover:bg-white/10 text-green-400 transition-colors"
                  >
                    {copiedId === "new" ? <Check size={16} /> : <Copy size={16} />}
                  </button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </GlassCard>

      {/* Connection instructions */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-gray-300 mb-3">Connection Setup</h3>
        <div className="space-y-2 text-sm text-gray-400">
          <p>Use the following endpoint with your API key:</p>
          <code className="block bg-black/40 px-3 py-2 rounded-lg text-xs text-accent font-mono">
            POST /api/roblox/chat
          </code>
          <p className="text-xs text-gray-500 mt-2">
            Include your key in the request body as <code className="text-accent">api_key</code>.
          </p>
        </div>
      </GlassCard>

      {/* Active keys */}
      <div>
        <h3 className="text-sm font-medium text-gray-300 mb-3">Active Keys</h3>
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-accent" />
          </div>
        ) : keys.length === 0 ? (
          <GlassCard className="p-8 text-center">
            <Key size={32} className="text-gray-600 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No API keys generated yet</p>
          </GlassCard>
        ) : (
          <div className="space-y-2">
            {keys.map((key) => (
              <GlassCard key={key.id} className="p-4 flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
                  <Key size={16} className="text-accent" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">{key.name}</span>
                    <span className={cn(
                      "text-xs px-1.5 py-0.5 rounded",
                      key.is_active ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"
                    )}>
                      {key.is_active ? "Active" : "Revoked"}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 font-mono">{key.key_prefix}...</p>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleCopy(key.key_prefix, key.id)}
                    className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                  >
                    {copiedId === key.id ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
                  </button>
                  {key.is_active && (
                    <button
                      onClick={() => handleRevoke(key.id)}
                      className="p-2 rounded-lg hover:bg-red-500/20 text-gray-400 hover:text-red-400 transition-colors"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </GlassCard>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
