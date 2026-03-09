"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import BinaryRain from "@/components/BinaryRain";
import Sidebar from "@/components/Sidebar";
import ChatInterface from "@/components/ChatInterface";
import AgentPanel from "@/components/AgentPanel";
import WorkflowBuilder from "@/components/WorkflowBuilder";
import KnowledgeUpload from "@/components/KnowledgeUpload";
import TrainingPanel from "@/components/TrainingPanel";
import ApiKeyPanel from "@/components/ApiKeyPanel";
import SettingsPanel from "@/components/SettingsPanel";
import PreviewSidebar from "@/components/PreviewSidebar";
import GlassCard from "@/components/GlassCard";
import * as api from "@/lib/api";
import { useThemeStore } from "@/lib/themeStore";

export type ActiveView = "chat" | "agents" | "workflows" | "knowledge" | "training" | "roblox" | "settings";

function LoginScreen({ onLogin }: { onLogin: (username: string) => void }) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      if (isRegister) {
        await api.register(username, password, email || undefined);
      }
      const res = await api.login(username, password);
      localStorage.setItem("pub_token", res.access_token);
      localStorage.setItem("pub_username", username);
      localStorage.setItem("pub_role", res.role || "user");
      onLogin(username);
    } catch (err: any) {
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden flex items-center justify-center">
      <BinaryRain />
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative z-10 w-full max-w-sm mx-4"
      >
        <div className="text-center mb-8">
          <h1
            className="font-arcade text-2xl text-white mb-2"
            style={{ textShadow: "0 0 20px rgba(255,255,255,0.3)" }}
          >
            Pub++
          </h1>
          <p className="text-gray-500 text-sm">AI-powered development platform</p>
        </div>

        <GlassCard className="p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Username"
                required
                className="w-full glass-input px-4 py-3 text-sm"
              />
            </div>

            {isRegister && (
              <div>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Email (optional)"
                  className="w-full glass-input px-4 py-3 text-sm"
                />
              </div>
            )}

            <div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                required
                className="w-full glass-input px-4 py-3 text-sm"
              />
            </div>

            {error && (
              <p className="text-red-400 text-xs">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading || !username || !password}
              className="w-full py-3 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-all text-sm font-medium"
              style={{ color: "var(--accent)" }}
            >
              {loading ? "..." : isRegister ? "Create Account" : "Sign In"}
            </button>
          </form>

          <button
            onClick={() => { setIsRegister(!isRegister); setError(""); }}
            className="w-full mt-4 text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            {isRegister ? "Already have an account? Sign in" : "Need an account? Register"}
          </button>
        </GlassCard>
      </motion.div>
    </div>
  );
}

export default function Home() {
  const [activeView, setActiveView] = useState<ActiveView>("chat");
  const [authed, setAuthed] = useState<boolean | null>(null); // null = checking
  const [username, setUsername] = useState<string | null>(null);
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    const token = localStorage.getItem("pub_token");
    const user = localStorage.getItem("pub_username");
    if (token && user) {
      setAuthed(true);
      setUsername(user);
    } else {
      setAuthed(false);
    }
  }, []);

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.style.fontFamily = getComputedStyle(document.documentElement)
      .getPropertyValue("--font-body")
      .trim() || "'Inter', sans-serif";
  }, [theme]);

  const handleLogin = (user: string) => {
    setUsername(user);
    setAuthed(true);
  };

  // Still checking auth
  if (authed === null) {
    return (
      <div className="h-screen w-screen flex items-center justify-center" style={{ background: "var(--bg-primary)" }}>
        <div className="font-arcade text-lg text-white animate-pulse" style={{ textShadow: "0 0 15px rgba(255,255,255,0.2)" }}>
          Pub++
        </div>
      </div>
    );
  }

  // Not logged in
  if (!authed) {
    return <LoginScreen onLogin={handleLogin} />;
  }

  const renderView = () => {
    switch (activeView) {
      case "chat":
        return <ChatInterface />;
      case "agents":
        return <AgentPanel />;
      case "workflows":
        return <WorkflowBuilder />;
      case "knowledge":
        return <KnowledgeUpload />;
      case "training":
        return <TrainingPanel />;
      case "roblox":
        return <ApiKeyPanel />;
      case "settings":
        return <SettingsPanel />;
    }
  };

  return (
    <main className="relative h-screen w-screen overflow-hidden" data-theme={theme}>
      {/* Mizzy Way background */}
      {theme === "mizzy" && <div className="mizzy-bg" />}
      {/* Binary rain (hide on midnight for clean look, show tinted on mizzy) */}
      {theme !== "midnight" && <BinaryRain />}
      <div className="relative z-10 flex h-full">
        <Sidebar activeView={activeView} onViewChange={setActiveView} />
        <div className="flex-1 flex flex-col overflow-hidden relative">
          {renderView()}
          <PreviewSidebar />
        </div>
      </div>
    </main>
  );
}
