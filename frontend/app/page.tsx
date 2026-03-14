"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import BinaryRain from "@/components/BinaryRain";
import Sidebar from "@/components/Sidebar";
import ChatInterface from "@/components/ChatInterface";
import AgentTabBar from "@/components/AgentTabBar";
import AgentChatTab from "@/components/AgentChatTab";
import IDEPanel from "@/components/IDEPanel";
import WorkflowBuilder from "@/components/WorkflowBuilder";
import KnowledgeUpload from "@/components/KnowledgeUpload";
import TrainingPanel from "@/components/TrainingPanel";
import ApiKeyPanel from "@/components/ApiKeyPanel";
import SettingsPanel from "@/components/SettingsPanel";
import PreviewSidebar from "@/components/PreviewSidebar";
import GlassCard from "@/components/GlassCard";
import * as api from "@/lib/api";
import { useThemeStore } from "@/lib/themeStore";
import { useAgentTabStore } from "@/lib/agentTabStore";

export type ActiveView = "chat" | "workflows" | "knowledge" | "training" | "roblox" | "settings";

type AppStage = "landing" | "login" | "app";

function LandingScreen({ onProceed }: { onProceed: () => void }) {
  return (
    <div className="relative h-screen w-screen overflow-hidden flex flex-col items-center justify-center bg-black">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(91,139,184,0.1)_0,transparent_50%)]" />
      
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative z-10 w-full max-w-2xl mx-4 text-center"
      >
        <h1 className="font-arcade text-5xl text-accent mb-6 tracking-widest" style={{ textShadow: "0 0 20px rgba(91,139,184,0.5)" }}>
          Pub++
        </h1>
        <p className="text-gray-400 mb-12 font-mono text-sm max-w-md mx-auto leading-relaxed border-t border-glass-border pt-4">
          Next-generation modular platform offering AI augmentation, market integration, and rapid automated presence operations.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <button 
            disabled
            className="group relative p-6 border border-glass-border hover:border-accent/50 bg-navy-900/50 hover:bg-navy-800 transition-all font-mono rounded-lg opacity-50 cursor-not-allowed flex flex-col items-center gap-3"
          >
            <div className="w-12 h-12 rounded-full border border-gray-600 flex items-center justify-center text-gray-500 mb-2">
              <span className="text-xl">⛨</span>
            </div>
            <span className="text-gray-400">Auto Joiner</span>
            <span className="text-[10px] text-gray-600 font-bold tracking-widest uppercase">Coming Soon</span>
          </button>

          <button 
            onClick={onProceed}
            className="group relative p-6 border-2 border-accent/60 hover:border-accent bg-accent/5 hover:bg-accent/10 transition-all font-mono rounded-lg glow-accent-hover flex flex-col items-center gap-3 transform hover:-translate-y-1"
          >
            <div className="w-12 h-12 rounded-full border border-accent flex items-center justify-center text-accent mb-2 group-hover:bg-accent group-hover:text-black transition-colors">
              <span className="text-xl">⚡</span>
            </div>
            <span className="text-accent font-bold tracking-wide">PubAI</span>
            <span className="text-[10px] text-accent/70 font-bold tracking-widest uppercase">Active Service</span>
          </button>

          <button 
            disabled
            className="group relative p-6 border border-glass-border hover:border-accent/50 bg-navy-900/50 hover:bg-navy-800 transition-all font-mono rounded-lg opacity-50 cursor-not-allowed flex flex-col items-center gap-3"
          >
            <div className="w-12 h-12 rounded-full border border-gray-600 flex items-center justify-center text-gray-500 mb-2">
              <span className="text-xl">📈</span>
            </div>
            <span className="text-gray-400">Brainrot Stock</span>
            <span className="text-[10px] text-gray-600 font-bold tracking-widest uppercase">Coming Soon</span>
          </button>
        </div>
      </motion.div>
    </div>
  );
}

function TerminalLoginScreen({ onLogin, onBack }: { onLogin: (username: string) => void; onBack: () => void }) {
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
    <div className="relative h-screen w-screen overflow-hidden flex items-center justify-center bg-black font-mono">
      <BinaryRain color="blue" />
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className="relative z-10 w-full max-w-lg mx-4"
      >
        <div className="border border-accent/40 bg-[#020813] shadow-[0_0_30px_rgba(91,139,184,0.15)] rounded-sm overflow-hidden">
          {/* Terminal Header */}
          <div className="border-b border-accent/40 bg-[#112038] px-4 py-2 flex justify-between items-center text-xs">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-red-500/80 cursor-pointer hover:bg-red-400" onClick={onBack}></div>
              <div className="w-3 h-3 rounded-full bg-yellow-500/80"></div>
              <div className="w-3 h-3 rounded-full bg-green-500/80"></div>
            </div>
            <span className="text-accent/80 font-bold tracking-wider opacity-80">PUBAI_AUTHORIZATION_TERMINAL</span>
            <div className="text-xs text-accent/50">v1.0.0</div>
          </div>

          <div className="p-8">
            <div className="mb-6 flex flex-col items-center">
              <img src="/logo.png" alt="PubAI" className="h-16 mb-4 filter drop-shadow-[0_0_8px_rgba(91,139,184,0.6)]" />
              <div className="text-accent font-bold text-lg mb-1">=== {isRegister ? "USER REGISTRATION" : "LOGIN SEQUENCE"} ===</div>
              <div className="text-xs text-gray-400">Please provide security credentials to access mainframe</div>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="flex items-center group">
                <span className="text-accent mr-3 w-4">&gt;</span>
                <span className="text-gray-500 mr-2 w-20 text-xs uppercase tracking-wider">USER:</span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="enter username_"
                  autoComplete="off"
                  required
                  className="flex-1 bg-transparent border-b border-glass-border focus:border-accent text-accent placeholder-gray-700 outline-none py-1 transition-colors"
                />
              </div>

              {isRegister && (
                <div className="flex items-center group">
                  <span className="text-accent mr-3 w-4">&gt;</span>
                  <span className="text-gray-500 mr-2 w-20 text-xs uppercase tracking-wider">EMAIL:</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="enter email (optional)_"
                    autoComplete="off"
                    className="flex-1 bg-transparent border-b border-glass-border focus:border-accent text-accent placeholder-gray-700 outline-none py-1 transition-colors"
                  />
                </div>
              )}

              <div className="flex items-center group">
                <span className="text-accent mr-3 w-4">&gt;</span>
                <span className="text-gray-500 mr-2 w-20 text-xs uppercase tracking-wider">PASS:</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="********_"
                  required
                  className="flex-1 bg-transparent border-b border-glass-border focus:border-accent text-accent placeholder-gray-700 outline-none py-1 transition-colors"
                />
              </div>

              {error && (
                <div className="text-red-400 text-xs mt-4 flex items-start">
                  <span className="mr-2">!</span> {error}
                </div>
              )}

              <div className="pt-6">
                <button
                  type="submit"
                  disabled={loading || !username || !password}
                  className="w-full py-2 bg-accent/10 border border-accent/40 text-accent hover:bg-accent hover:text-black hover:border-accent transition-all text-sm font-bold uppercase tracking-widest disabled:opacity-30 disabled:hover:bg-accent/10 disabled:hover:text-accent font-arcade"
                >
                  {loading ? "AUTHENTICATING..." : isRegister ? "REGISTER" : "AUTHORIZE"}
                </button>
              </div>
            </form>

            <div className="mt-6 flex justify-between items-center text-xs text-gray-500">
              <button
                onClick={() => { setIsRegister(!isRegister); setError(""); }}
                className="hover:text-accent transition-colors focus:outline-none focus:text-accent"
              >
                [ Switch to {isRegister ? "Login" : "Register"} ]
              </button>
              <div className="animate-pulse">_</div>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

export default function Home() {
  const [stage, setStage] = useState<AppStage>("landing");
  const [activeView, setActiveView] = useState<ActiveView>("chat");
  const [authed, setAuthed] = useState<boolean | null>(null); // null = checking
  const [username, setUsername] = useState<string | null>(null);
  const theme = useThemeStore((s) => s.theme);
  const { tabs, activeTabId } = useAgentTabStore();

  useEffect(() => {
    const token = localStorage.getItem("pub_token");
    const user = localStorage.getItem("pub_username");
    if (token && user) {
      setAuthed(true);
      setUsername(user);
      setStage("app");
    } else {
      setAuthed(false);
      setStage("landing");
    }
  }, []);

  // Apply theme to document
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.style.fontFamily = getComputedStyle(document.documentElement)
      .getPropertyValue("--font-body")
      .trim() || "'Fira Code', monospace";
  }, [theme]);

  const handleLogin = (user: string) => {
    setUsername(user);
    setAuthed(true);
    setStage("app");
  };

  // Still checking auth
  if (authed === null) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-black font-mono">
        <div className="text-accent animate-pulse flex items-center gap-2">
          <span>Loading</span><span className="animate-typewriter-cursor px-1 py-0.5 bg-accent text-black">_</span>
        </div>
      </div>
    );
  }

  // Stage routing
  if (stage === "landing") {
    return <LandingScreen onProceed={() => setStage("login")} />;
  }

  if (stage === "login") {
    return <TerminalLoginScreen onLogin={handleLogin} onBack={() => setStage("landing")} />;
  }

  const renderView = () => {
    switch (activeView) {
      case "chat": {
        // If an agent tab is active, show that agent's chat
        const activeAgentTab = tabs.find((t) => t.id === activeTabId);
        if (activeAgentTab) {
          return <AgentChatTab tab={activeAgentTab} />;
        }
        return <ChatInterface />;
      }
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
    <main className="relative h-screen w-screen flex flex-col overflow-hidden bg-black font-mono text-[#c8d6e5]" data-theme={theme}>
      {/* Top Application Header (Claude Code Style) */}
      <header className="h-10 border-b border-accent/30 bg-[#112038]/50 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5 mr-2">
            <div className="w-2.5 h-2.5 rounded-full bg-red-500/80"></div>
            <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/80"></div>
            <div className="w-2.5 h-2.5 rounded-full bg-green-500/80"></div>
          </div>
          <img src="/logo.png" alt="PubAI" className="h-4 filter drop-shadow-[0_0_2px_rgba(91,139,184,0.8)]" />
          <span className="text-xs font-bold font-arcade tracking-wider text-accent drop-shadow-[0_0_2px_rgba(91,139,184,0.5)]">PUBAI TERMINAL</span>
        </div>
        <div className="text-[10px] text-accent/60 tracking-widest uppercase">
          [ USER: {username} ] | [ ENGINE: vLLM TPU ]
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden relative">
        <Sidebar activeView={activeView} onViewChange={setActiveView} />
        <div className="flex-1 flex flex-col overflow-hidden relative bg-[#020813]">
          {/* Agent tab bar — shown when chat view has agent tabs */}
          {activeView === "chat" && <AgentTabBar />}
          {renderView()}
          <PreviewSidebar />
        </div>
      </div>
      
      {/* Footer Status Bar */}
      <footer className="h-6 border-t border-accent/20 bg-black flex items-center px-4 text-[10px] text-gray-500 shrink-0">
        <span>* System Online · Connection Secure</span>
      </footer>
    </main>
  );
}
