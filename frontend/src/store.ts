import { create } from "zustand";
import type { Mode, View } from "./lib/types";

interface AppState {
  view: View;
  mode: Mode;
  sessionId: string;
  runId: string | null;
  isStreaming: boolean;
  setView: (v: View) => void;
  setMode: (m: Mode) => void;
  setSessionId: (id: string) => void;
  setRunId: (id: string | null) => void;
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
  runId: null,
  isStreaming: false,
  setView: (view) => set({ view }),
  setMode: (mode) => set({ mode }),
  setSessionId: (sessionId) => set({ sessionId }),
  setRunId: (runId) => set({ runId }),
  setStreaming: (isStreaming) => set({ isStreaming }),
  newSession: () => set({ sessionId: genSessionId(), runId: null, view: "chat" }),
}));
