import { create } from "zustand";

export type ThemeName = "terminal" | "mizzy";

interface ThemeStore {
  theme: ThemeName;
  setTheme: (t: ThemeName) => void;
}

const getInitial = (): ThemeName => {
  if (typeof window === "undefined") return "terminal";
  return (localStorage.getItem("pub_theme") as ThemeName) || "terminal";
};

export const useThemeStore = create<ThemeStore>((set) => ({
  theme: getInitial(),
  setTheme: (t) => {
    localStorage.setItem("pub_theme", t);
    set({ theme: t });
  },
}));
