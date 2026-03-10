"use client";

import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import {
  Shield,
  ShieldCheck,
  Crown,
  Users,
  Loader2,
  ChevronDown,
  Check,
  X,
  Palette,
  Terminal,
  Moon,
  Sparkles,
  MessageSquare,
  Save,
  Zap,
  Scale,
  Brain,
  Microscope,
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn } from "@/lib/utils";
import * as api from "@/lib/api";
import { useThemeStore, type ThemeName } from "@/lib/themeStore";
import { useEffortStore, type EffortLevel } from "@/lib/effortStore";

interface UserInfo {
  id: string;
  username: string;
  email: string | null;
  role: string;
}

interface UserListEntry {
  id: string;
  username: string;
  role: string;
  created_at: string;
}

/* ── Role Badge ── */
function RoleBadge({ role }: { role: string }) {
  if (role === "owner")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
        <Crown size={10} /> Owner
      </span>
    );
  if (role === "admin")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/20 text-blue-400 border border-blue-500/30">
        <ShieldCheck size={10} /> Admin
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-gray-500/20 text-gray-400 border border-gray-500/30">
      User
    </span>
  );
}

/* ── Role Dropdown ── */
function RoleDropdown({
  currentRole,
  userId,
  onRoleChange,
}: {
  currentRole: string;
  userId: string;
  onRoleChange: (userId: string, newRole: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const roles = ["user", "admin"];
  if (currentRole === "owner") return <RoleBadge role="owner" />;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 px-2 py-1 rounded-lg bg-white/5 border border-white/10 text-xs hover:bg-white/10 transition-colors"
      >
        <RoleBadge role={currentRole} />
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className="absolute right-0 mt-1 py-1 w-28 bg-black/90 backdrop-blur-xl border border-white/10 rounded-lg z-50 shadow-lg">
          {roles.map((r) => (
            <button
              key={r}
              onClick={() => {
                onRoleChange(userId, r);
                setOpen(false);
              }}
              className={cn(
                "w-full px-3 py-1.5 text-left text-xs hover:bg-white/10 transition-colors flex items-center gap-2",
                r === currentRole && "text-accent"
              )}
            >
              {r === currentRole && <Check size={12} />}
              {r}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Theme Card ── */
const THEMES: {
  id: ThemeName;
  label: string;
  icon: typeof Palette;
  description: string;
  preview: string; // gradient/color for preview swatch
}[] = [
    {
      id: "default",
      label: "Default",
      icon: MessageSquare,
      description: "Classic blue glassmorphism",
      preview: "linear-gradient(135deg, #0a0a1a 0%, #0d1b2a 50%, #00aaff22 100%)",
    },
    {
      id: "terminal",
      label: "Terminal",
      icon: Terminal,
      description: "CLI-style dark blue monospace",
      preview: "linear-gradient(135deg, #0c1220 0%, #0f1728 50%, #5b9bd522 100%)",
    },
    {
      id: "midnight",
      label: "Midnight",
      icon: Moon,
      description: "Pure black, blue-white gradient outlines",
      preview: "linear-gradient(135deg, #000000 0%, #050505 50%, #3b82f622 100%)",
    },
    {
      id: "mizzy",
      label: "Mizzy Way",
      icon: Sparkles,
      description: "Purple lean aesthetic vibes",
      preview: "linear-gradient(135deg, #0d0015 0%, #1a0025 50%, #c084fc22 100%)",
    },
  ];

/* ── Main Settings Panel ── */
export default function SettingsPanel() {
  const [me, setMe] = useState<UserInfo | null>(null);
  const [users, setUsers] = useState<UserListEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(false);
  const [customInstructions, setCustomInstructions] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const saveTimeout = useRef<ReturnType<typeof setTimeout>>();

  const { theme, setTheme } = useThemeStore();
  const { effort, setEffort } = useEffortStore();

  const isAdmin =
    me?.role === "admin" || me?.role === "owner";

  useEffect(() => {
    loadCurrentUser();
    loadPreferences();
  }, []);

  useEffect(() => {
    if (isAdmin) loadUsers();
  }, [isAdmin]);

  const loadCurrentUser = async () => {
    try {
      const user = await api.getMe();
      setMe(user);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  };

  const loadUsers = async () => {
    setUsersLoading(true);
    try {
      const list = await api.getUsers();
      setUsers(list);
    } catch {
      /* ignore */
    } finally {
      setUsersLoading(false);
    }
  };

  const loadPreferences = async () => {
    try {
      const prefs = await api.getPreferences();
      if (prefs.theme) setTheme(prefs.theme as ThemeName);
      if (prefs.custom_instructions) setCustomInstructions(prefs.custom_instructions);
    } catch {
      /* ignore — might 401 */
    }
  };

  const handleRoleChange = async (userId: string, newRole: string) => {
    try {
      await api.setUserRole(userId, newRole);
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
      );
    } catch {
      /* ignore */
    }
  };

  const handleThemeChange = async (t: ThemeName) => {
    setTheme(t);
    try {
      await api.savePreferences({ theme: t });
    } catch {
      /* ignore */
    }
  };

  const handleSaveInstructions = async () => {
    setSaving(true);
    try {
      await api.savePreferences({ custom_instructions: customInstructions });
      setSaved(true);
      if (saveTimeout.current) clearTimeout(saveTimeout.current);
      saveTimeout.current = setTimeout(() => setSaved(false), 2000);
    } catch {
      /* ignore */
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-accent" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <h2 className="text-xl font-semibold text-white">Settings</h2>

      {/* ── User Info ── */}
      {me && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-accent/20 flex items-center justify-center">
              <Shield size={22} className="text-accent" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-white">{me.username}</span>
                <RoleBadge role={me.role} />
              </div>
              {me.email && (
                <span className="text-xs text-gray-500">{me.email}</span>
              )}
            </div>
          </div>
        </GlassCard>
      )}

      {/* ── Theme Picker ── */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
          <Palette size={16} className="text-accent" />
          Theme
        </h3>
        <div className="grid grid-cols-2 gap-3">
          {THEMES.map((t) => {
            const Icon = t.icon;
            const isActive = theme === t.id;
            return (
              <motion.button
                key={t.id}
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => handleThemeChange(t.id)}
                className={cn(
                  "relative p-4 rounded-xl border transition-all duration-200 text-left",
                  isActive
                    ? "border-accent/50 bg-accent/10 ring-1 ring-accent/20"
                    : "border-white/10 bg-white/5 hover:bg-white/8 hover:border-white/20"
                )}
              >
                {isActive && (
                  <div className="absolute top-2 right-2">
                    <Check size={14} className="text-accent" />
                  </div>
                )}
                <div
                  className="w-full h-8 rounded-lg mb-3 border border-white/10"
                  style={{ background: t.preview }}
                />
                <div className="flex items-center gap-2 mb-1">
                  <Icon size={14} className={isActive ? "text-accent" : "text-gray-400"} />
                  <span className={cn("text-sm font-medium", isActive ? "text-accent" : "text-white")}>
                    {t.label}
                  </span>
                </div>
                <span className="text-xs text-gray-500">{t.description}</span>
              </motion.button>
            );
          })}
        </div>
      </GlassCard>

      {/* ── Effort Level ── */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
          <Brain size={16} className="text-accent" />
          Effort Level
        </h3>
        <p className="text-xs text-gray-500 mb-4">
          Controls how much reasoning the AI applies. Higher = more thorough but slower.
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {([
            { id: "low" as EffortLevel, label: "Low", icon: Zap, description: "Fast responses", color: "text-yellow-400", bg: "bg-yellow-500/10", border: "border-yellow-500/30" },
            { id: "medium" as EffortLevel, label: "Medium", icon: Scale, description: "Balanced", color: "text-blue-400", bg: "bg-blue-500/10", border: "border-blue-500/30" },
            { id: "high" as EffortLevel, label: "High", icon: Brain, description: "Deep reasoning", color: "text-purple-400", bg: "bg-purple-500/10", border: "border-purple-500/30" },
            { id: "max" as EffortLevel, label: "Max", icon: Microscope, description: "Maximum depth", color: "text-red-400", bg: "bg-red-500/10", border: "border-red-500/30" },
          ]).map((lvl) => {
            const Icon = lvl.icon;
            const isActive = effort === lvl.id;
            return (
              <motion.button
                key={lvl.id}
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => setEffort(lvl.id)}
                className={cn(
                  "relative flex flex-col items-center gap-1.5 p-3 rounded-xl border transition-all duration-200",
                  isActive
                    ? `${lvl.bg} ${lvl.border} ${lvl.color}`
                    : "border-white/10 bg-white/5 text-gray-400 hover:bg-white/8 hover:border-white/20"
                )}
              >
                {isActive && (
                  <div className="absolute top-1.5 right-1.5">
                    <Check size={10} className={lvl.color} />
                  </div>
                )}
                <Icon size={18} className={isActive ? lvl.color : ""} />
                <span className={cn("text-xs font-semibold", isActive ? lvl.color : "text-white")}>{lvl.label}</span>
                <span className="text-[10px] text-gray-500">{lvl.description}</span>
              </motion.button>
            );
          })}
        </div>
        <p className="text-[10px] text-gray-600 mt-2">
          Tip: You can also use <code className="text-accent/80">/effort low</code> in chat.
        </p>
      </GlassCard>

      {/* ── Custom Instructions ── */}
      <GlassCard className="p-5">
        <h3 className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
          <MessageSquare size={16} className="text-accent" />
          Custom Instructions
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Tell the AI how you'd like it to respond. These instructions apply to all your conversations.
        </p>
        <textarea
          value={customInstructions}
          onChange={(e) => setCustomInstructions(e.target.value)}
          placeholder="e.g. Always respond in bullet points. Use TypeScript for code examples. Keep responses concise."
          rows={4}
          className="w-full glass-input px-4 py-3 text-sm resize-none"
        />
        <div className="flex items-center justify-end gap-2 mt-3">
          {saved && (
            <span className="text-xs text-green-400 flex items-center gap-1">
              <Check size={12} /> Saved
            </span>
          )}
          <button
            onClick={handleSaveInstructions}
            disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-accent/20 text-accent text-xs font-medium hover:bg-accent/30 disabled:opacity-50 transition-all"
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            Save
          </button>
        </div>
      </GlassCard>

      {/* ── User Management (Admin/Owner only) ── */}
      {isAdmin && (
        <GlassCard className="p-5">
          <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Users size={16} className="text-accent" />
            User Management
          </h3>

          {usersLoading ? (
            <div className="py-8 flex justify-center">
              <Loader2 size={20} className="animate-spin text-accent" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-500 text-xs border-b border-white/10">
                    <th className="text-left py-2 px-3">Username</th>
                    <th className="text-left py-2 px-3">Role</th>
                    <th className="text-left py-2 px-3">Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className="border-b border-white/5 hover:bg-white/5 transition-colors"
                    >
                      <td className="py-2.5 px-3 text-white font-medium">{u.username}</td>
                      <td className="py-2.5 px-3">
                        <RoleDropdown
                          currentRole={u.role}
                          userId={u.id}
                          onRoleChange={handleRoleChange}
                        />
                      </td>
                      <td className="py-2.5 px-3 text-gray-500 text-xs">
                        {new Date(u.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
}
