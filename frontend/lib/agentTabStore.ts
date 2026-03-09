import { create } from "zustand";

export type AgentTabType = "sub-agent" | "team-agent";

export interface AgentTab {
    id: string;
    agentId: string;
    name: string;
    type: AgentTabType;
    task: string;
    status: "running" | "done" | "error";
    parentId?: string; // for sub-agents — the ID of the parent agent
}

interface AgentTabState {
    tabs: AgentTab[];
    activeTabId: string; // "main" = main chat
    openTab: (tab: Omit<AgentTab, "id">) => string;
    closeTab: (id: string) => void;
    setActive: (id: string) => void;
    updateStatus: (agentId: string, status: AgentTab["status"]) => void;
    getTabByAgentId: (agentId: string) => AgentTab | undefined;
}

export const useAgentTabStore = create<AgentTabState>((set, get) => ({
    tabs: [],
    activeTabId: "main",

    openTab: (tabData) => {
        const existing = get().tabs.find((t) => t.agentId === tabData.agentId);
        if (existing) {
            set({ activeTabId: existing.id });
            return existing.id;
        }
        const id = `agent-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
        const tab: AgentTab = { ...tabData, id };
        set((state) => ({
            tabs: [...state.tabs, tab],
            activeTabId: id,
        }));
        return id;
    },

    closeTab: (id) =>
        set((state) => ({
            tabs: state.tabs.filter((t) => t.id !== id),
            activeTabId: state.activeTabId === id ? "main" : state.activeTabId,
        })),

    setActive: (id) => set({ activeTabId: id }),

    updateStatus: (agentId, status) =>
        set((state) => ({
            tabs: state.tabs.map((t) =>
                t.agentId === agentId ? { ...t, status } : t
            ),
        })),

    getTabByAgentId: (agentId) => get().tabs.find((t) => t.agentId === agentId),
}));
