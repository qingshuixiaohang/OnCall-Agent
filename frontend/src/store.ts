import { create } from "zustand";
import type { Mode, View } from "./lib/types";

interface AppState {
  view: View;
  mode: Mode;
  sessionId: string;
  isStreaming: boolean;
  setView: (v: View) => void;
  setMode: (m: Mode) => void;
  setSessionId: (id: string) => void;
  setStreaming: (s: boolean) => void;
  newSession: () => void;
}

function genSessionId(): string {
  return `session_${Math.random().toString(36).slice(2, 11)}_${Date.now()}`;
}

export const useStore = create<AppState>((set) => ({
  view: "chat",
  mode: "stream",
  sessionId: genSessionId(),
  isStreaming: false,
  setView: (view) => set({ view }),
  setMode: (mode) => set({ mode }),
  setSessionId: (sessionId) => set({ sessionId }),
  setStreaming: (isStreaming) => set({ isStreaming }),
  newSession: () => set({ sessionId: genSessionId(), view: "chat" }),
}));
