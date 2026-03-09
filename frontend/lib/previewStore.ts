import { create } from 'zustand';

interface PreviewState {
  isOpen: boolean;
  content: string;
  language: string;
  open: (content: string, language: string) => void;
  close: () => void;
}

export const usePreviewStore = create<PreviewState>((set) => ({
  isOpen: false,
  content: '',
  language: '',
  open: (content, language) => set({ isOpen: true, content, language }),
  close: () => set({ isOpen: false, content: '', language: '' }),
}));
