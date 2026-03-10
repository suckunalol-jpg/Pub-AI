"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
    Folder, File, ChevronRight, ChevronDown, X, Save,
    Plus, FolderPlus, Trash2, Edit3, Play, Terminal as TerminalIcon,
    GitBranch, GitCommit, Upload, Send, Sparkles,
    RefreshCw, Search, MoreHorizontal, Copy, Download,
    FileCode, FileText, Settings2, Maximize2, Minimize2,
    PanelBottomOpen, PanelBottomClose,
} from "lucide-react";
import { cn } from "@/lib/utils";
import * as api from "@/lib/api";
import type { FileEntry } from "@/lib/api";

// ============================================================
// Types
// ============================================================

interface OpenFile {
    path: string;
    name: string;
    language: string;
    content: string;
    originalContent: string; // for dirty detection
}

type SidebarPanel = "files" | "git" | "ai";

// File icons by extension
const fileIcons: Record<string, string> = {
    ".py": "🐍", ".js": "⚡", ".ts": "💠", ".tsx": "⚛️", ".jsx": "⚛️",
    ".html": "🌐", ".css": "🎨", ".json": "📋", ".md": "📝",
    ".lua": "🌙", ".rs": "🦀", ".go": "🐹", ".java": "☕", ".c": "⚙️",
    ".cpp": "⚙️", ".h": "⚙️", ".sh": "🐚", ".yaml": "📐", ".yml": "📐",
    ".toml": "📐", ".xml": "📦", ".sql": "🗄️", ".txt": "📄",
    ".gitignore": "🔒", ".env": "🔐",
};

function getFileIcon(name: string): string {
    const ext = "." + name.split(".").pop()?.toLowerCase();
    return fileIcons[ext] || fileIcons["." + name] || "📄";
}

// ============================================================
// FileTreeItem — recursive file/folder node
// ============================================================

function FileTreeItem({
    entry,
    depth,
    selectedPath,
    onSelect,
    onRefresh,
}: {
    entry: FileEntry;
    depth: number;
    selectedPath: string | null;
    onSelect: (entry: FileEntry) => void;
    onRefresh: () => void;
}) {
    const [expanded, setExpanded] = useState(false);
    const [children, setChildren] = useState<FileEntry[]>([]);
    const [loading, setLoading] = useState(false);
    const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
    const [renaming, setRenaming] = useState(false);
    const [newName, setNewName] = useState(entry.name);

    const toggleExpand = async () => {
        if (entry.type !== "directory") return;
        if (!expanded) {
            setLoading(true);
            try {
                const files = await api.ideListFiles(entry.path);
                setChildren(files);
            } catch { /* ignore */ }
            setLoading(false);
        }
        setExpanded(!expanded);
    };

    const handleClick = () => {
        if (entry.type === "file") {
            onSelect(entry);
        } else {
            toggleExpand();
        }
    };

    const handleContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
        setContextMenu({ x: e.clientX, y: e.clientY });
    };

    const handleDelete = async () => {
        setContextMenu(null);
        if (confirm(`Delete ${entry.name}?`)) {
            await api.ideDeleteFile(entry.path);
            onRefresh();
        }
    };

    const handleRename = async () => {
        setContextMenu(null);
        if (newName && newName !== entry.name) {
            const parentPath = entry.path.includes("/")
                ? entry.path.substring(0, entry.path.lastIndexOf("/"))
                : "";
            await api.ideRenameFile(entry.path, parentPath ? `${parentPath}/${newName}` : newName);
            onRefresh();
        }
        setRenaming(false);
    };

    return (
        <>
            <button
                onClick={handleClick}
                onContextMenu={handleContextMenu}
                className={cn(
                    "w-full flex items-center gap-1.5 py-[3px] pr-2 text-left text-[13px] hover:bg-white/5 transition-colors",
                    selectedPath === entry.path && "bg-white/10 text-white"
                )}
                style={{ paddingLeft: `${12 + depth * 16}px` }}
            >
                {entry.type === "directory" ? (
                    <>
                        {expanded ? <ChevronDown size={14} className="text-gray-500 flex-shrink-0" /> : <ChevronRight size={14} className="text-gray-500 flex-shrink-0" />}
                        <Folder size={14} className="text-blue-400/70 flex-shrink-0" />
                    </>
                ) : (
                    <>
                        <span className="w-[14px] flex-shrink-0" />
                        <span className="text-[12px] flex-shrink-0">{getFileIcon(entry.name)}</span>
                    </>
                )}
                {renaming ? (
                    <input
                        autoFocus
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        onBlur={handleRename}
                        onKeyDown={(e) => { if (e.key === "Enter") handleRename(); if (e.key === "Escape") setRenaming(false); }}
                        className="bg-black/50 border border-accent/40 rounded px-1 text-xs text-white outline-none flex-1"
                        onClick={(e) => e.stopPropagation()}
                    />
                ) : (
                    <span className="truncate text-gray-300">{entry.name}</span>
                )}
            </button>

            {/* Context Menu */}
            {contextMenu && (
                <>
                    <div className="fixed inset-0 z-50" onClick={() => setContextMenu(null)} />
                    <div
                        className="fixed z-50 bg-[#1e1e2e] border border-white/10 rounded-lg shadow-2xl py-1 min-w-[160px]"
                        style={{ top: contextMenu.y, left: contextMenu.x }}
                    >
                        <button onClick={() => { setRenaming(true); setContextMenu(null); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 hover:bg-white/10">
                            <Edit3 size={12} /> Rename
                        </button>
                        <button onClick={() => { navigator.clipboard.writeText(entry.path); setContextMenu(null); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-gray-300 hover:bg-white/10">
                            <Copy size={12} /> Copy Path
                        </button>
                        <div className="border-t border-white/5 my-1" />
                        <button onClick={handleDelete} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10">
                            <Trash2 size={12} /> Delete
                        </button>
                    </div>
                </>
            )}

            {/* Children */}
            <AnimatePresence>
                {expanded && children.length > 0 && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.15 }}
                        className="overflow-hidden"
                    >
                        {children.map((child) => (
                            <FileTreeItem
                                key={child.path}
                                entry={child}
                                depth={depth + 1}
                                selectedPath={selectedPath}
                                onSelect={onSelect}
                                onRefresh={onRefresh}
                            />
                        ))}
                    </motion.div>
                )}
            </AnimatePresence>
        </>
    );
}

// ============================================================
// Main IDE Panel
// ============================================================

export default function IDEPanel() {
    // File tree
    const [files, setFiles] = useState<FileEntry[]>([]);
    const [loadingFiles, setLoadingFiles] = useState(true);

    // Editor
    const [openFiles, setOpenFiles] = useState<OpenFile[]>([]);
    const [activeFilePath, setActiveFilePath] = useState<string | null>(null);
    const editorRef = useRef<HTMLTextAreaElement>(null);
    const [saving, setSaving] = useState(false);

    // Terminal
    const [terminalOpen, setTerminalOpen] = useState(true);
    const [terminalOutput, setTerminalOutput] = useState<string[]>([
        "\x1b[36m╔══════════════════════════════════════╗\x1b[0m",
        "\x1b[36m║  Pub++ IDE Terminal                  ║\x1b[0m",
        "\x1b[36m╚══════════════════════════════════════╝\x1b[0m",
        "",
        "Type commands below. Use Ctrl+S to save files.",
        "",
    ]);
    const [terminalInput, setTerminalInput] = useState("");
    const [runningCommand, setRunningCommand] = useState(false);
    const [shellType, setShellType] = useState<string>("terminal");
    const terminalEndRef = useRef<HTMLDivElement>(null);

    // Sidebar panel
    const [sidebarPanel, setSidebarPanel] = useState<SidebarPanel>("files");
    const [sidebarWidth] = useState(260);

    // Git
    const [gitBranch, setGitBranch] = useState("—");
    const [gitChanges, setGitChanges] = useState<string[]>([]);
    const [gitIsRepo, setGitIsRepo] = useState(false);
    const [commitMsg, setCommitMsg] = useState("");
    const [gitLog, setGitLog] = useState<{ hash: string; message: string }[]>([]);

    // Clone dialog
    const [showCloneDialog, setShowCloneDialog] = useState(false);
    const [cloneUrl, setCloneUrl] = useState("");
    const [cloning, setCloning] = useState(false);

    // New file/folder dialog
    const [showNewDialog, setShowNewDialog] = useState<"file" | "folder" | null>(null);
    const [newItemName, setNewItemName] = useState("");

    // AI assistant
    const [aiInput, setAiInput] = useState("");
    const [aiMessages, setAiMessages] = useState<{ role: string; content: string }[]>([]);

    // Active file derivation
    const activeFile = useMemo(
        () => openFiles.find((f) => f.path === activeFilePath) || null,
        [openFiles, activeFilePath]
    );

    // ---------- Load files ----------
    const loadFiles = useCallback(async () => {
        setLoadingFiles(true);
        try {
            const data = await api.ideListFiles("");
            setFiles(data);
        } catch { /* ignore */ }
        setLoadingFiles(false);
    }, []);

    useEffect(() => { loadFiles(); }, [loadFiles]);

    // ---------- Load git ----------
    const loadGitStatus = useCallback(async () => {
        try {
            const status = await api.ideGitStatus("");
            setGitBranch(status.branch);
            setGitChanges(status.changes);
            setGitIsRepo(status.is_repo);
            if (status.is_repo) {
                const log = await api.ideGitLog("");
                setGitLog(log.commits);
            }
        } catch { /* ignore */ }
    }, []);

    useEffect(() => { loadGitStatus(); }, [loadGitStatus]);

    // ---------- Load shell info ----------
    useEffect(() => {
        (async () => {
            try {
                const token = typeof window !== "undefined" ? localStorage.getItem("pub_token") : null;
                const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/ide/shell/info`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                });
                if (res.ok) {
                    const info = await res.json();
                    setShellType(info.shell === "git-bash" ? "Git Bash" : info.shell === "bash" ? "Bash" : "Terminal");
                }
            } catch { /* ignore */ }
        })();
    }, []);

    // ---------- Open file ----------
    const openFile = useCallback(async (entry: FileEntry) => {
        // Already open?
        const existing = openFiles.find((f) => f.path === entry.path);
        if (existing) {
            setActiveFilePath(entry.path);
            return;
        }
        try {
            const data = await api.ideReadFile(entry.path);
            const newFile: OpenFile = {
                path: data.path,
                name: entry.name,
                language: data.language,
                content: data.content,
                originalContent: data.content,
            };
            setOpenFiles((prev) => [...prev, newFile]);
            setActiveFilePath(data.path);
        } catch { /* ignore */ }
    }, [openFiles]);

    // ---------- Close file ----------
    const closeFile = (path: string) => {
        setOpenFiles((prev) => prev.filter((f) => f.path !== path));
        if (activeFilePath === path) {
            const remaining = openFiles.filter((f) => f.path !== path);
            setActiveFilePath(remaining.length > 0 ? remaining[remaining.length - 1].path : null);
        }
    };

    // ---------- Save file ----------
    const saveFile = useCallback(async () => {
        if (!activeFile) return;
        setSaving(true);
        try {
            await api.ideSaveFile(activeFile.path, activeFile.content);
            setOpenFiles((prev) =>
                prev.map((f) => f.path === activeFile.path ? { ...f, originalContent: f.content } : f)
            );
        } catch { /* ignore */ }
        setSaving(false);
    }, [activeFile]);

    // Ctrl+S handler
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "s") {
                e.preventDefault();
                saveFile();
            }
        };
        window.addEventListener("keydown", handler);
        return () => window.removeEventListener("keydown", handler);
    }, [saveFile]);

    // ---------- Editor content change ----------
    const updateContent = (content: string) => {
        if (!activeFilePath) return;
        setOpenFiles((prev) =>
            prev.map((f) => f.path === activeFilePath ? { ...f, content } : f)
        );
    };

    // ---------- Terminal ----------
    const runCommand = useCallback(async () => {
        const cmd = terminalInput.trim();
        if (!cmd || runningCommand) return;
        setTerminalInput("");
        setTerminalOutput((prev) => [...prev, `\x1b[32m❯\x1b[0m ${cmd}`]);
        setRunningCommand(true);
        try {
            const result = await api.ideShell(cmd);
            if (result.output.trim()) {
                setTerminalOutput((prev) => [...prev, result.output.trim()]);
            }
            if (result.exit_code !== 0) {
                setTerminalOutput((prev) => [...prev, `\x1b[31mProcess exited with code ${result.exit_code}\x1b[0m`]);
            }
        } catch (err: unknown) {
            setTerminalOutput((prev) => [...prev, `\x1b[31mError: ${err instanceof Error ? err.message : "Command failed"}\x1b[0m`]);
        }
        setRunningCommand(false);
        // Refresh files after commands
        loadFiles();
        loadGitStatus();
    }, [terminalInput, runningCommand, loadFiles, loadGitStatus]);

    // Auto-scroll terminal
    useEffect(() => {
        terminalEndRef.current?.scrollIntoView({ behavior: "auto" });
    }, [terminalOutput]);

    // ---------- Run current file ----------
    const runCurrentFile = useCallback(async () => {
        if (!activeFile) return;
        await saveFile();
        const langToCmd: Record<string, string> = {
            python: "python", javascript: "node", typescript: "npx ts-node",
            lua: "lua", shell: "bash", go: "go run", rust: "rustc",
        };
        const cmd = langToCmd[activeFile.language];
        if (cmd) {
            setTerminalInput(`${cmd} ${activeFile.path}`);
            setTimeout(() => {
                const fakeEvent = new KeyboardEvent("keydown", { key: "Enter" });
                // Trigger run
                setTerminalOutput((prev) => [...prev, `\x1b[32m❯\x1b[0m ${cmd} ${activeFile.path}`]);
                setRunningCommand(true);
                api.ideShell(`${cmd} ${activeFile.path}`).then((result) => {
                    if (result.output.trim()) setTerminalOutput((prev) => [...prev, result.output.trim()]);
                    if (result.exit_code !== 0) setTerminalOutput((prev) => [...prev, `\x1b[31mExit ${result.exit_code}\x1b[0m`]);
                    setRunningCommand(false);
                    setTerminalInput("");
                });
            }, 100);
        }
    }, [activeFile, saveFile]);

    // ---------- Git operations ----------
    const handleCommit = async () => {
        if (!commitMsg.trim()) return;
        try {
            await api.ideGitCommit(commitMsg);
            setCommitMsg("");
            loadGitStatus();
            setTerminalOutput((prev) => [...prev, `\x1b[33m[git]\x1b[0m Committed: ${commitMsg}`]);
        } catch { /* ignore */ }
    };

    const handlePush = async () => {
        try {
            const result = await api.ideGitPush();
            setTerminalOutput((prev) => [...prev, `\x1b[33m[git]\x1b[0m Push: ${result.output || "done"}`]);
            loadGitStatus();
        } catch { /* ignore */ }
    };

    const handleClone = async () => {
        if (!cloneUrl.trim()) return;
        setCloning(true);
        try {
            const result = await api.ideGitClone(cloneUrl);
            setTerminalOutput((prev) => [...prev, `\x1b[33m[git]\x1b[0m Cloned into ${result.folder}`]);
            loadFiles();
            loadGitStatus();
            setShowCloneDialog(false);
            setCloneUrl("");
        } catch (err: unknown) {
            setTerminalOutput((prev) => [...prev, `\x1b[31m[git] Clone failed: ${err instanceof Error ? err.message : "error"}\x1b[0m`]);
        }
        setCloning(false);
    };

    // ---------- Create new file/folder ----------
    const handleCreateNew = async () => {
        if (!newItemName.trim() || !showNewDialog) return;
        try {
            if (showNewDialog === "file") {
                await api.ideSaveFile(newItemName, "");
            } else {
                await api.ideCreateFolder(newItemName);
            }
            loadFiles();
        } catch { /* ignore */ }
        setShowNewDialog(null);
        setNewItemName("");
    };

    // ---------- AI assistant ----------
    const sendAiMessage = useCallback(async () => {
        const msg = aiInput.trim();
        if (!msg) return;
        setAiMessages((prev) => [...prev, { role: "user", content: msg }]);
        setAiInput("");

        try {
            // Use chat API with context about the current file
            const context = activeFile
                ? `[User is editing ${activeFile.path} (${activeFile.language})]\n\nFile content (first 500 chars):\n\`\`\`\n${activeFile.content.slice(0, 500)}\n\`\`\`\n\n`
                : "";
            const fullMsg = context + msg;

            // Simple non-streaming request
            const response = await api.sendMessage(null, fullMsg);
            setAiMessages((prev) => [...prev, { role: "assistant", content: response.content }]);
        } catch {
            setAiMessages((prev) => [...prev, { role: "assistant", content: "Sorry, couldn't get a response." }]);
        }
    }, [aiInput, activeFile]);

    // ============================================================
    // RENDER
    // ============================================================

    return (
        <div className="flex flex-col h-full bg-[#0d1117] text-gray-300">
            {/* ========== Top Bar ========== */}
            <div className="flex items-center justify-between h-9 px-3 bg-[#161b22] border-b border-[#30363d]">
                <div className="flex items-center gap-2 text-xs">
                    <span className="text-gray-500">Pub++ IDE</span>
                    {activeFile && (
                        <>
                            <ChevronRight size={12} className="text-gray-600" />
                            <span className="text-gray-400">{activeFile.path}</span>
                            {activeFile.content !== activeFile.originalContent && (
                                <span className="w-2 h-2 rounded-full bg-amber-400" title="Unsaved changes" />
                            )}
                        </>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    {activeFile && (
                        <>
                            <button onClick={saveFile} className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white" title="Save (Ctrl+S)">
                                <Save size={14} />
                            </button>
                            <button onClick={runCurrentFile} className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-green-400" title="Run File">
                                <Play size={14} />
                            </button>
                        </>
                    )}
                    <button onClick={() => setTerminalOpen(!terminalOpen)} className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white" title="Toggle Terminal">
                        {terminalOpen ? <PanelBottomClose size={14} /> : <PanelBottomOpen size={14} />}
                    </button>
                </div>
            </div>

            <div className="flex flex-1 overflow-hidden">
                {/* ========== Activity Bar (VS Code style) ========== */}
                <div className="w-12 flex flex-col items-center py-2 gap-1 bg-[#0d1117] border-r border-[#30363d]">
                    {([
                        { id: "files" as SidebarPanel, icon: FileCode, label: "Explorer" },
                        { id: "git" as SidebarPanel, icon: GitBranch, label: "Source Control" },
                        { id: "ai" as SidebarPanel, icon: Sparkles, label: "AI Assistant" },
                    ]).map((item) => (
                        <button
                            key={item.id}
                            onClick={() => setSidebarPanel(item.id)}
                            title={item.label}
                            className={cn(
                                "w-10 h-10 flex items-center justify-center rounded-lg transition-colors",
                                sidebarPanel === item.id
                                    ? "text-white bg-white/10 border-l-2 border-accent"
                                    : "text-gray-600 hover:text-gray-300"
                            )}
                        >
                            <item.icon size={20} />
                        </button>
                    ))}
                </div>

                {/* ========== Sidebar Panel ========== */}
                <div className="flex flex-col border-r border-[#30363d] bg-[#0d1117]" style={{ width: sidebarWidth }}>
                    {/* ---- Files Panel ---- */}
                    {sidebarPanel === "files" && (
                        <>
                            <div className="flex items-center justify-between px-3 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                                Explorer
                                <div className="flex items-center gap-0.5">
                                    <button onClick={() => setShowNewDialog("file")} className="p-1 rounded hover:bg-white/10" title="New File">
                                        <Plus size={14} />
                                    </button>
                                    <button onClick={() => setShowNewDialog("folder")} className="p-1 rounded hover:bg-white/10" title="New Folder">
                                        <FolderPlus size={14} />
                                    </button>
                                    <button onClick={() => setShowCloneDialog(true)} className="p-1 rounded hover:bg-white/10" title="Clone Repo">
                                        <Download size={14} />
                                    </button>
                                    <button onClick={loadFiles} className="p-1 rounded hover:bg-white/10" title="Refresh">
                                        <RefreshCw size={14} />
                                    </button>
                                </div>
                            </div>
                            <div className="flex-1 overflow-y-auto scrollbar-hide">
                                {loadingFiles ? (
                                    <div className="px-4 py-8 text-center text-gray-600 text-xs">Loading...</div>
                                ) : files.length === 0 ? (
                                    <div className="px-4 py-8 text-center">
                                        <p className="text-gray-600 text-xs mb-3">No files yet</p>
                                        <button
                                            onClick={() => setShowCloneDialog(true)}
                                            className="text-xs text-accent/80 hover:text-accent underline"
                                        >
                                            Clone a repository
                                        </button>
                                    </div>
                                ) : (
                                    files.map((entry) => (
                                        <FileTreeItem
                                            key={entry.path}
                                            entry={entry}
                                            depth={0}
                                            selectedPath={activeFilePath}
                                            onSelect={openFile}
                                            onRefresh={loadFiles}
                                        />
                                    ))
                                )}
                            </div>
                        </>
                    )}

                    {/* ---- Git Panel ---- */}
                    {sidebarPanel === "git" && (
                        <>
                            <div className="px-3 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                                Source Control
                            </div>
                            <div className="flex-1 overflow-y-auto px-3 space-y-4">
                                {/* Branch */}
                                <div className="flex items-center gap-2 text-xs">
                                    <GitBranch size={14} className="text-cyan-400" />
                                    <span className="text-gray-300">{gitBranch}</span>
                                    {!gitIsRepo && <span className="text-gray-600 text-[10px]">(not a git repo)</span>}
                                </div>

                                {/* Changes */}
                                {gitChanges.length > 0 && (
                                    <div>
                                        <p className="text-[11px] text-gray-500 mb-1">Changes ({gitChanges.length})</p>
                                        <div className="space-y-0.5">
                                            {gitChanges.slice(0, 20).map((change, i) => (
                                                <div key={i} className="text-[12px] text-gray-400 font-mono truncate">
                                                    <span className={cn(
                                                        "inline-block w-4 text-center mr-1",
                                                        change.startsWith("M") ? "text-amber-400" :
                                                            change.startsWith("A") || change.startsWith("?") ? "text-green-400" :
                                                                change.startsWith("D") ? "text-red-400" : "text-gray-500"
                                                    )}>
                                                        {change.charAt(0)}
                                                    </span>
                                                    {change.slice(3)}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Commit input */}
                                {gitIsRepo && (
                                    <div className="space-y-2">
                                        <input
                                            value={commitMsg}
                                            onChange={(e) => setCommitMsg(e.target.value)}
                                            onKeyDown={(e) => e.key === "Enter" && handleCommit()}
                                            placeholder="Commit message"
                                            className="w-full bg-[#161b22] border border-[#30363d] rounded-md px-2 py-1.5 text-xs text-white placeholder-gray-600 outline-none focus:border-accent/50"
                                        />
                                        <div className="flex gap-1">
                                            <button
                                                onClick={handleCommit}
                                                disabled={!commitMsg.trim()}
                                                className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-md text-xs bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 transition-colors"
                                            >
                                                <GitCommit size={12} /> Commit
                                            </button>
                                            <button
                                                onClick={handlePush}
                                                className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 transition-colors"
                                            >
                                                <Upload size={12} /> Push
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {/* Recent commits */}
                                {gitLog.length > 0 && (
                                    <div>
                                        <p className="text-[11px] text-gray-500 mb-1">Recent Commits</p>
                                        <div className="space-y-1">
                                            {gitLog.slice(0, 8).map((c) => (
                                                <div key={c.hash} className="text-[11px] flex gap-1.5">
                                                    <span className="text-amber-400/60 font-mono flex-shrink-0">{c.hash.slice(0, 7)}</span>
                                                    <span className="text-gray-400 truncate">{c.message}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </>
                    )}

                    {/* ---- AI Assistant Panel ---- */}
                    {sidebarPanel === "ai" && (
                        <>
                            <div className="px-3 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                                AI Assistant
                            </div>
                            <div className="flex-1 overflow-y-auto px-3 space-y-2">
                                {aiMessages.length === 0 && (
                                    <div className="text-center py-6">
                                        <Sparkles size={20} className="mx-auto mb-2 text-accent/40" />
                                        <p className="text-[11px] text-gray-600">Ask AI about your code.</p>
                                        <p className="text-[10px] text-gray-700 mt-1">It can see your active file.</p>
                                    </div>
                                )}
                                {aiMessages.map((msg, i) => (
                                    <div
                                        key={i}
                                        className={cn(
                                            "text-[12px] px-2 py-1.5 rounded-lg",
                                            msg.role === "user"
                                                ? "bg-accent/10 text-white ml-4"
                                                : "bg-white/5 text-gray-300 mr-2"
                                        )}
                                    >
                                        <pre className="whitespace-pre-wrap font-sans break-words">{msg.content}</pre>
                                    </div>
                                ))}
                            </div>
                            <div className="p-2 border-t border-[#30363d]">
                                <div className="flex gap-1">
                                    <input
                                        value={aiInput}
                                        onChange={(e) => setAiInput(e.target.value)}
                                        onKeyDown={(e) => e.key === "Enter" && sendAiMessage()}
                                        placeholder="Ask AI..."
                                        className="flex-1 bg-[#161b22] border border-[#30363d] rounded-md px-2 py-1.5 text-xs text-white placeholder-gray-600 outline-none focus:border-accent/50"
                                    />
                                    <button onClick={sendAiMessage} className="p-1.5 rounded-md bg-accent/20 text-accent hover:bg-accent/30">
                                        <Send size={12} />
                                    </button>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* ========== Editor Area ========== */}
                <div className="flex-1 flex flex-col overflow-hidden">
                    {/* Tab bar */}
                    <div className="flex items-center h-9 bg-[#0d1117] border-b border-[#30363d] overflow-x-auto scrollbar-hide">
                        {openFiles.map((file) => (
                            <button
                                key={file.path}
                                onClick={() => setActiveFilePath(file.path)}
                                className={cn(
                                    "group flex items-center gap-1.5 h-full px-3 text-[12px] border-r border-[#30363d] whitespace-nowrap transition-colors min-w-0",
                                    activeFilePath === file.path
                                        ? "bg-[#161b22] text-white border-t-2 border-t-accent"
                                        : "text-gray-500 hover:text-gray-300 hover:bg-[#161b22]/50"
                                )}
                            >
                                <span className="text-[11px]">{getFileIcon(file.name)}</span>
                                <span className="truncate max-w-[120px]">{file.name}</span>
                                {file.content !== file.originalContent && (
                                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
                                )}
                                <span
                                    onClick={(e) => { e.stopPropagation(); closeFile(file.path); }}
                                    className="ml-1 p-0.5 rounded hover:bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity"
                                >
                                    <X size={12} />
                                </span>
                            </button>
                        ))}
                    </div>

                    {/* Editor content */}
                    <div className="flex-1 overflow-hidden flex flex-col">
                        {activeFile ? (
                            <div className="flex-1 overflow-hidden flex flex-col">
                                {/* Line numbers + textarea editor */}
                                <div className="flex-1 overflow-auto bg-[#0d1117] font-mono text-[13px] leading-[20px]">
                                    <div className="flex min-h-full">
                                        {/* Line numbers */}
                                        <div className="flex-shrink-0 text-right pr-3 pl-3 py-2 text-gray-600 select-none border-r border-[#30363d]/50 bg-[#0d1117]">
                                            {activeFile.content.split("\n").map((_, i) => (
                                                <div key={i} className="h-[20px]">{i + 1}</div>
                                            ))}
                                        </div>
                                        {/* Code area */}
                                        <textarea
                                            ref={editorRef}
                                            value={activeFile.content}
                                            onChange={(e) => updateContent(e.target.value)}
                                            spellCheck={false}
                                            className="flex-1 bg-transparent text-gray-200 outline-none resize-none p-2 font-mono text-[13px] leading-[20px] whitespace-pre tab-size-2"
                                            style={{ tabSize: 2 } as React.CSSProperties}
                                        />
                                    </div>
                                </div>
                            </div>
                        ) : (
                            /* Welcome screen */
                            <div className="flex-1 flex items-center justify-center bg-[#0d1117]">
                                <div className="text-center">
                                    <div className="text-6xl mb-4 opacity-20">⌨️</div>
                                    <h2 className="text-lg font-medium text-gray-400 mb-2">Pub++ IDE</h2>
                                    <p className="text-sm text-gray-600 max-w-xs">
                                        Open a file from the explorer, or clone a repository to get started.
                                    </p>
                                    <div className="flex items-center justify-center gap-3 mt-6 text-xs text-gray-600">
                                        <span className="px-2 py-1 rounded bg-white/5 border border-white/5">Ctrl+S</span>
                                        <span>Save</span>
                                        <span className="px-2 py-1 rounded bg-white/5 border border-white/5">▶</span>
                                        <span>Run</span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* ========== Terminal ========== */}
                        <AnimatePresence>
                            {terminalOpen && (
                                <motion.div
                                    initial={{ height: 0 }}
                                    animate={{ height: 200 }}
                                    exit={{ height: 0 }}
                                    transition={{ duration: 0.2 }}
                                    className="border-t border-[#30363d] bg-[#0d1117] flex flex-col overflow-hidden"
                                >
                                    <div className="flex items-center justify-between px-3 py-1 bg-[#161b22] border-b border-[#30363d]">
                                        <div className="flex items-center gap-2 text-[11px] text-gray-500">
                                            <TerminalIcon size={12} />
                                            <span>{shellType}</span>
                                        </div>
                                        <button onClick={() => setTerminalOpen(false)} className="p-0.5 rounded hover:bg-white/10">
                                            <X size={12} className="text-gray-500" />
                                        </button>
                                    </div>
                                    <div className="flex-1 overflow-y-auto px-3 py-2 font-mono text-[12px]">
                                        {terminalOutput.map((line, i) => (
                                            <div key={i} className="text-gray-400 whitespace-pre-wrap break-all">
                                                {/* Strip basic ANSI codes and apply colors */}
                                                {line
                                                    .replace(/\x1b\[36m/g, "").replace(/\x1b\[32m/g, "").replace(/\x1b\[31m/g, "").replace(/\x1b\[33m/g, "").replace(/\x1b\[0m/g, "")
                                                }
                                            </div>
                                        ))}
                                        <div ref={terminalEndRef} />
                                    </div>
                                    <div className="flex items-center gap-2 px-3 py-1.5 border-t border-[#30363d]">
                                        <span className="text-green-400 text-[12px] font-mono">{shellType === "Git Bash" ? "$" : "❯"}</span>
                                        <input
                                            value={terminalInput}
                                            onChange={(e) => setTerminalInput(e.target.value)}
                                            onKeyDown={(e) => e.key === "Enter" && runCommand()}
                                            placeholder="Enter command..."
                                            disabled={runningCommand}
                                            className="flex-1 bg-transparent text-[12px] text-white font-mono outline-none placeholder-gray-700 disabled:opacity-50"
                                        />
                                        {runningCommand && (
                                            <RefreshCw size={12} className="text-gray-500 animate-spin" />
                                        )}
                                    </div>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                </div>
            </div>

            {/* ========== Status Bar (VS Code style) ========== */}
            <div className="flex items-center justify-between h-6 px-3 bg-[#161b22] border-t border-[#30363d] text-[11px]">
                <div className="flex items-center gap-3">
                    {gitIsRepo && (
                        <span className="flex items-center gap-1 text-gray-500">
                            <GitBranch size={11} /> {gitBranch}
                        </span>
                    )}
                    {saving && <span className="text-amber-400">Saving...</span>}
                </div>
                <div className="flex items-center gap-3">
                    {activeFile && (
                        <>
                            <span className="text-gray-600">{activeFile.language}</span>
                            <span className="text-gray-600">
                                Ln {activeFile.content.substring(0, editorRef.current?.selectionStart || 0).split("\n").length}
                            </span>
                            <span className="text-gray-600">UTF-8</span>
                        </>
                    )}
                    <span className="text-gray-600">Pub++ IDE</span>
                </div>
            </div>

            {/* ========== Clone Dialog ========== */}
            <AnimatePresence>
                {showCloneDialog && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                        onClick={() => setShowCloneDialog(false)}
                    >
                        <motion.div
                            initial={{ scale: 0.95 }}
                            animate={{ scale: 1 }}
                            exit={{ scale: 0.95 }}
                            className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 w-full max-w-md shadow-2xl"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                                <GitBranch size={18} className="text-accent" /> Clone Repository
                            </h3>
                            <input
                                value={cloneUrl}
                                onChange={(e) => setCloneUrl(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && handleClone()}
                                placeholder="https://github.com/user/repo.git"
                                autoFocus
                                className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg px-4 py-3 text-sm text-white placeholder-gray-600 outline-none focus:border-accent/50 mb-4"
                            />
                            <div className="flex gap-2 justify-end">
                                <button
                                    onClick={() => setShowCloneDialog(false)}
                                    className="px-4 py-2 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-white/5"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleClone}
                                    disabled={!cloneUrl.trim() || cloning}
                                    className="px-4 py-2 rounded-lg text-sm bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 flex items-center gap-2"
                                >
                                    {cloning ? <RefreshCw size={14} className="animate-spin" /> : <Download size={14} />}
                                    {cloning ? "Cloning..." : "Clone"}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* ========== New File/Folder Dialog ========== */}
            <AnimatePresence>
                {showNewDialog && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                        onClick={() => setShowNewDialog(null)}
                    >
                        <motion.div
                            initial={{ scale: 0.95 }}
                            animate={{ scale: 1 }}
                            exit={{ scale: 0.95 }}
                            className="bg-[#161b22] border border-[#30363d] rounded-xl p-6 w-full max-w-sm shadow-2xl"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                                {showNewDialog === "file" ? <Plus size={18} className="text-accent" /> : <FolderPlus size={18} className="text-accent" />}
                                New {showNewDialog === "file" ? "File" : "Folder"}
                            </h3>
                            <input
                                value={newItemName}
                                onChange={(e) => setNewItemName(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && handleCreateNew()}
                                placeholder={showNewDialog === "file" ? "filename.py" : "folder-name"}
                                autoFocus
                                className="w-full bg-[#0d1117] border border-[#30363d] rounded-lg px-4 py-3 text-sm text-white placeholder-gray-600 outline-none focus:border-accent/50 mb-4"
                            />
                            <div className="flex gap-2 justify-end">
                                <button
                                    onClick={() => setShowNewDialog(null)}
                                    className="px-4 py-2 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-white/5"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleCreateNew}
                                    disabled={!newItemName.trim()}
                                    className="px-4 py-2 rounded-lg text-sm bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30"
                                >
                                    Create
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
