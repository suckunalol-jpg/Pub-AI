"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  MessageSquare,
  Workflow,
  BookOpen,
  Brain,
  Gamepad2,
  ChevronLeft,
  ChevronRight,
  User,
  LogOut,
  Settings,
  Crown,
  ShieldCheck,
  Code2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActiveView } from "@/app/page";

interface SidebarProps {
  activeView: ActiveView;
  onViewChange: (view: ActiveView) => void;
}

// Items visible to everyone
const publicNavItems: { id: ActiveView; label: string; icon: React.ElementType }[] = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "ide", label: "IDE", icon: Code2 },
  { id: "roblox", label: "Roblox API", icon: Gamepad2 },
];

// Items only visible to admin/owner
const adminNavItems: { id: ActiveView; label: string; icon: React.ElementType }[] = [
  { id: "workflows", label: "Workflows", icon: Workflow },
  { id: "knowledge", label: "Knowledge", icon: BookOpen },
  { id: "training", label: "Training", icon: Brain },
];

export default function Sidebar({ activeView, onViewChange }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [role, setRole] = useState<string>("user");

  useEffect(() => {
    if (typeof window !== "undefined") {
      setUsername(localStorage.getItem("pub_username"));
      setRole(localStorage.getItem("pub_role") || "user");
    }
  }, []);

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
    <motion.aside
      animate={{ width: collapsed ? 72 : 280 }}
      transition={{ duration: 0.2, ease: "easeInOut" }}
      className="relative h-full flex flex-col bg-black/40 backdrop-blur-xl border-r border-white/10 z-20"
    >
      {/* Logo */}
      <div className="flex items-center justify-between px-5 pt-6 pb-4">
        {!collapsed && (
          <motion.h1
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="font-arcade text-lg text-white tracking-wider"
            style={{ textShadow: "0 0 10px rgba(255,255,255,0.3)" }}
          >
            Pub++
          </motion.h1>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1.5 rounded-lg hover:bg-white/10 transition-colors text-gray-400 hover:text-white"
        >
          {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 space-y-1 mt-2">
        {navItems.map((item) => {
          const isActive = activeView === item.id;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => onViewChange(item.id)}
              className={cn(
                "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200",
                isActive
                  ? "bg-accent/15 text-accent border border-accent/20"
                  : "text-gray-400 hover:text-white hover:bg-white/5"
              )}
            >
              <Icon size={20} className={isActive ? "text-accent" : ""} />
              {!collapsed && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-sm font-medium"
                >
                  {item.label}
                </motion.span>
              )}
            </button>
          );
        })}
      </nav>

      {/* User section */}
      <div className="p-3 border-t border-white/10 space-y-1">
        {username && (
          <div className="flex items-center gap-3 px-3 py-2 text-gray-400">
            <div className="w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center flex-shrink-0">
              <User size={16} className="text-accent" />
            </div>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex-1 min-w-0"
              >
                <span className="text-sm font-medium text-white block truncate">{username}</span>
                {role === "owner" && (
                  <span className="inline-flex items-center gap-0.5 text-[10px] text-amber-400/80">
                    <Crown size={10} />
                    owner
                  </span>
                )}
                {role === "admin" && (
                  <span className="inline-flex items-center gap-0.5 text-[10px] text-accent/70">
                    <ShieldCheck size={10} />
                    admin
                  </span>
                )}
              </motion.div>
            )}
          </div>
        )}

        {/* Settings button */}
        <button
          onClick={() => onViewChange("settings")}
          className={cn(
            "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200",
            isSettingsActive
              ? "bg-accent/15 text-accent border border-accent/20"
              : "text-gray-400 hover:text-white hover:bg-white/5"
          )}
        >
          <Settings size={18} className={isSettingsActive ? "text-accent" : ""} />
          {!collapsed && (
            <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-sm font-medium">
              Settings
            </motion.span>
          )}
        </button>

        {/* Logout button */}
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
        >
          <LogOut size={18} />
          {!collapsed && (
            <motion.span initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-sm">
              Log out
            </motion.span>
          )}
        </button>
      </div>
    </motion.aside>
  );
}
