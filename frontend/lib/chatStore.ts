import { create } from "zustand";

interface ChatState {
  selectedConversationId: string | null;
  setSelectedConversationId: (id: string | null) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  selectedConversationId: null,
  setSelectedConversationId: (id) => set({ selectedConversationId: id }),
}));
