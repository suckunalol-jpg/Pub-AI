import { create } from "zustand";

export type EffortLevel = "low" | "medium" | "high" | "max";

interface EffortState {
    effort: EffortLevel;
    setEffort: (level: EffortLevel) => void;
}

const EFFORT_KEY = "pub_effort_level";

export const useEffortStore = create<EffortState>((set) => ({
    effort:
        (typeof window !== "undefined"
            ? (localStorage.getItem(EFFORT_KEY) as EffortLevel | null)
            : null) || "high",

    setEffort: (level) => {
        set({ effort: level });
        if (typeof window !== "undefined") {
            localStorage.setItem(EFFORT_KEY, level);
        }
    },
}));
