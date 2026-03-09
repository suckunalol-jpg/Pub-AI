import { create } from "zustand";

export type ThemeName = "default" | "terminal" | "midnight" | "mizzy";

interface ThemeStore {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
}

const getInitial = (): ThemeName => {
  if (typeof window === "undefined") return "default";
  return (localStorage.getItem("pub_theme") as ThemeName) || "default";
};

export const useThemeStore = create<ThemeStore>((set) => ({
  theme: getInitial(),
  setTheme: (t) => {
    localStorage.setItem("pub_theme", t);
    set({ theme: t });
  },
}));
