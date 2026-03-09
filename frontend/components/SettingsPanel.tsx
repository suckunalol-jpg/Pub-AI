"use client";

import { useState, useEffect } from "react";
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
} from "lucide-react";
import GlassCard from "./GlassCard";
import { cn } from "@/lib/utils";
import * as api from "@/lib/api";

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

function RoleBadge({ role }: { role: string }) {
  switch (role) {
    case "owner":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 text-xs font-medium border border-amber-500/20">
          <Crown size={12} />
          Owner
        </span>
      );
    case "admin":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent/15 text-accent text-xs font-medium border border-accent/20">
          <ShieldCheck size={12} />
          Admin
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/5 text-gray-400 text-xs font-medium border border-white/10">
          <Shield size={12} />
          User
        </span>
      );
  }
}

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

  if (currentRole === "owner") {
    return null;
  }

  const options = ["user", "admin"] as const;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-sm text-gray-300 hover:bg-white/10 hover:text-white transition-colors"
      >
        {currentRole === "admin" ? "Admin" : "User"}
        <ChevronDown size={14} className={cn("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 w-32 bg-black/90 backdrop-blur-xl border border-white/10 rounded-xl overflow-hidden shadow-xl">
          {options.map((role) => (
            <button
              key={role}
              onClick={() => {
                if (role !== currentRole) {
                  onRoleChange(userId, role);
                }
                setOpen(false);
              }}
              className={cn(
                "w-full text-left px-3 py-2 text-sm transition-colors flex items-center justify-between",
                role === currentRole
                  ? "text-accent bg-accent/10"
                  : "text-gray-300 hover:bg-white/5 hover:text-white"
              )}
            >
              <span className="capitalize">{role}</span>
              {role === currentRole && <Check size={14} className="text-accent" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SettingsPanel() {
  const [currentUser, setCurrentUser] = useState<UserInfo | null>(null);
  const [users, setUsers] = useState<UserListEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const isAdminOrOwner = currentUser?.role === "admin" || currentUser?.role === "owner";

  useEffect(() => {
    loadCurrentUser();
  }, []);

  useEffect(() => {
    if (isAdminOrOwner) {
      loadUsers();
    }
  }, [isAdminOrOwner]);

  // Auto-dismiss messages after 3 seconds
  useEffect(() => {
    if (message) {
      const timer = setTimeout(() => setMessage(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [message]);

  async function loadCurrentUser() {
    try {
      const me = await api.getMe();
      setCurrentUser(me);
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Failed to load user info" });
    } finally {
      setLoading(false);
    }
  }

  async function loadUsers() {
    setUsersLoading(true);
    try {
      const userList = await api.getUsers();
      setUsers(userList);
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Failed to load users" });
    } finally {
      setUsersLoading(false);
    }
  }

  async function handleRoleChange(userId: string, newRole: string) {
    try {
      await api.setUserRole(userId, newRole);
      setMessage({ type: "success", text: `Role updated to ${newRole}` });
      // Refresh user list
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
      );
    } catch (err: any) {
      setMessage({ type: "error", text: err.message || "Failed to update role" });
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="animate-spin text-accent" size={32} />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <h2 className="text-xl font-semibold text-white mb-1">Settings</h2>
        <p className="text-sm text-gray-500">Account and user management</p>
      </motion.div>

      {/* Toast message */}
      {message && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className={cn(
            "flex items-center justify-between px-4 py-3 rounded-xl border text-sm",
            message.type === "success"
              ? "bg-green-500/10 border-green-500/20 text-green-400"
              : "bg-red-500/10 border-red-500/20 text-red-400"
          )}
        >
          <span>{message.text}</span>
          <button onClick={() => setMessage(null)} className="hover:opacity-70 transition-opacity">
            <X size={16} />
          </button>
        </motion.div>
      )}

      {/* Current User Info */}
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
        <GlassCard className="p-5">
          <h3 className="text-sm font-medium text-gray-400 mb-4">Your Account</h3>
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-accent/20 flex items-center justify-center flex-shrink-0">
              {currentUser?.role === "owner" ? (
                <Crown size={22} className="text-amber-400" />
              ) : currentUser?.role === "admin" ? (
                <ShieldCheck size={22} className="text-accent" />
              ) : (
                <Shield size={22} className="text-gray-400" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-white font-medium text-base">{currentUser?.username}</p>
              {currentUser?.email && (
                <p className="text-gray-500 text-sm truncate">{currentUser.email}</p>
              )}
            </div>
            {currentUser && <RoleBadge role={currentUser.role} />}
          </div>
        </GlassCard>
      </motion.div>

      {/* User Management (admin/owner only) */}
      {isAdminOrOwner && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <GlassCard className="p-5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Users size={18} className="text-accent" />
                <h3 className="text-sm font-medium text-gray-400">User Management</h3>
              </div>
              <span className="text-xs text-gray-500">{users.length} user{users.length !== 1 ? "s" : ""}</span>
            </div>

            {usersLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="animate-spin text-accent" size={24} />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-white/5">
                      <th className="text-left py-2.5 px-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Username
                      </th>
                      <th className="text-left py-2.5 px-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Role
                      </th>
                      <th className="text-left py-2.5 px-3 text-xs font-medium text-gray-500 uppercase tracking-wider hidden sm:table-cell">
                        Created
                      </th>
                      <th className="text-right py-2.5 px-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {users.map((user) => (
                      <tr key={user.id} className="hover:bg-white/[0.02] transition-colors">
                        <td className="py-3 px-3">
                          <span className="text-sm text-white font-medium">{user.username}</span>
                        </td>
                        <td className="py-3 px-3">
                          <RoleBadge role={user.role} />
                        </td>
                        <td className="py-3 px-3 hidden sm:table-cell">
                          <span className="text-xs text-gray-500">
                            {new Date(user.created_at).toLocaleDateString()}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right">
                          <RoleDropdown
                            currentRole={user.role}
                            userId={user.id}
                            onRoleChange={handleRoleChange}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </GlassCard>
        </motion.div>
      )}
    </div>
  );
}
