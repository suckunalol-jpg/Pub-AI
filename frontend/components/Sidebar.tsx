"use client";

import { useState, useEffect } from "react";
import {
  MessageSquare,
  Workflow,
  BookOpen,
  Brain,
  Gamepad2,
  Settings,
  TerminalSquare,
  History,
  LogOut,
  User,
  Crown,
  ShieldCheck
} from "lucide-react";
import { cn } from "@/lib/utils";
import * as api from "@/lib/api";
import { useChatStore } from "@/lib/chatStore";
import type { ActiveView } from "@/app/page";

interface SidebarProps {
  activeView: ActiveView;
  onViewChange: (view: ActiveView) => void;
}

const publicNavItems: { id: ActiveView; label: string; icon: React.ElementType }[] = [
  { id: "chat", label: "TERMINAL", icon: TerminalSquare },
  { id: "roblox", label: "ROBLOX API", icon: Gamepad2 },
];

const adminNavItems: { id: ActiveView; label: string; icon: React.ElementType }[] = [
  { id: "workflows", label: "WORKFLOWS", icon: Workflow },
  { id: "knowledge", label: "KNOWLEDGE", icon: BookOpen },
  { id: "training", label: "TRAINING", icon: Brain },
];

export default function Sidebar({ activeView, onViewChange }: SidebarProps) {
  const [username, setUsername] = useState<string | null>(null);
  const [role, setRole] = useState<string>("user");
  const [history, setHistory] = useState<{id: string; title: string}[]>([]);
  const { setSelectedConversationId } = useChatStore();

  useEffect(() => {
    if (typeof window !== "undefined") {
      setUsername(localStorage.getItem("pub_username"));
      setRole(localStorage.getItem("pub_role") || "user");
      
      const fetchHistory = async () => {
        try {
          const data = await api.getConversations();
          setHistory(data);
        } catch {
          // Ignore failures if user is not fully logged in or API fails
        }
      };
      fetchHistory();
    }
  }, []);

  const handleSelectConv = (id: string) => {
    setSelectedConversationId(id);
    onViewChange("chat");
  };

  const isAdmin = role === "admin" || role === "owner";
  const navItems = isAdmin ? [...publicNavItems, ...adminNavItems] : publicNavItems;

  const handleLogout = () => {
    localStorage.removeItem("pub_token");
    localStorage.removeItem("pub_username");
    localStorage.removeItem("pub_role");
    window.location.reload();
  };

  const isSettingsActive = activeView === "settings";

  return (
    <aside className="relative w-64 h-full flex flex-col bg-black border-r border-accent/20 z-20 font-mono text-sm shrink-0">
      
      {/* User Info Header */}
      <div className="p-4 border-b border-accent/20 flex items-center gap-3">
        <div className="w-8 h-8 bg-accent/20 border border-accent/50 flex items-center justify-center flex-shrink-0 text-accent">
          <User size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-accent font-bold truncate">@{username || "guest"}</div>
          <div className="text-[10px] text-gray-500 uppercase tracking-widest flex items-center gap-1">
            {role === "owner" && <Crown size={10} className="text-yellow-500" />}
            {role === "admin" && <ShieldCheck size={10} className="text-accent" />}
            {role} rights
          </div>
        </div>
      </div>

      {/* Main Navigation */}
      <div className="px-3 py-4 border-b border-accent/20">
        <div className="text-[10px] text-accent/50 mb-2 px-2 uppercase tracking-widest">System Modules</div>
        <nav className="space-y-0.5">
          {navItems.map((item) => {
            const isActive = activeView === item.id;
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                onClick={() => onViewChange(item.id)}
                className={cn(
                  "w-full flex items-center gap-3 px-2 py-1.5 transition-colors text-left group",
                  isActive
                    ? "bg-accent/10 text-accent"
                    : "text-gray-400 hover:text-accent hover:bg-accent/5"
                )}
              >
                <span className={cn("w-1 h-4", isActive ? "bg-accent" : "bg-transparent group-hover:bg-accent/30")} />
                <Icon size={14} />
                <span className="tracking-wide text-xs">{item.label}</span>
              </button>
            );
          })}
        </nav>
      </div>

      {/* Chat History / Necessities */}
      <div className="flex-1 overflow-y-auto px-3 py-4 hide-scrollbar">
        <div className="flex items-center gap-2 text-[10px] text-accent/50 mb-2 px-2 uppercase tracking-widest">
          <History size={10} />
          <span>Local Memory</span>
        </div>
        <div className="space-y-1">
          {history.length > 0 ? (
            history.map((h) => (
              <button
                key={h.id}
                onClick={() => handleSelectConv(h.id)}
                className="w-full text-left px-3 py-1.5 text-xs text-gray-500 hover:text-accent transition-colors truncate"
              >
                &gt; {h.title || "New Thread"}
              </button>
            ))
          ) : (
            <div className="px-3 py-1.5 text-xs text-gray-600 truncate opacity-50">Empty Memory Bank</div>
          )}
        </div>
      </div>

      {/* Footer Navigation */}
      <div className="p-3 border-t border-accent/20 space-y-0.5">
        <button
          onClick={() => onViewChange("settings")}
          className={cn(
            "w-full flex items-center gap-3 px-2 py-1.5 transition-colors text-left group",
            isSettingsActive
              ? "bg-accent/10 text-accent"
              : "text-gray-400 hover:text-accent hover:bg-accent/5"
          )}
        >
          <span className={cn("w-1 h-4", isSettingsActive ? "bg-accent" : "bg-transparent group-hover:bg-accent/30")} />
          <Settings size={14} />
          <span className="tracking-wide text-xs">SETTINGS</span>
        </button>

        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-2 py-1.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors text-left group"
        >
          <span className="w-1 h-4 bg-transparent group-hover:bg-red-400/" />
          <LogOut size={14} />
          <span className="tracking-wide text-xs">DISCONNECT</span>
        </button>
      </div>
    </aside>
  );
}
