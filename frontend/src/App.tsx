import { useRef } from "react";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { Composer } from "./components/Composer";
import { ChatView, type ChatHandle } from "./features/chat/ChatView";
import { DiagnosisView, type DiagnosisHandle } from "./features/diagnosis/DiagnosisView";
import { useStore } from "./store";
import { uploadFile } from "./lib/api";
import { ErrorBoundary } from "./components/ErrorBoundary";
import type { View } from "./lib/types";

const DEFAULT_Q: Record<string, string> = {
  aiops: "诊断当前系统是否存在告警，如果存在请详细分析告警原因并生成诊断报告",
  multi: "全面诊断当前系统状态",
};

function App() {
  const { view, setView, sessionId, isStreaming } = useStore();
  const chatRef = useRef<ChatHandle>(null);
  const diagRef = useRef<DiagnosisHandle>(null);

  // 触发发送/诊断。模式切换本身不会调用这个函数。
  const fire = (text: string, target: View) => {
    if (isStreaming) return;
    if (target === "chat") {
      chatRef.current?.send(text);
    } else {
      const q = text || DEFAULT_Q[target];
      diagRef.current?.run(q);
    }
  };

  // TopBar 只切换当前视图，不自动启动任何 Agent。
  const onPickView = (v: View) => {
    setView(v);
  };

  const onSend = (text: string) => fire(text, view);

  const onUpload = (file: File) => {
    uploadFile(sessionId, file).catch(() => {});
  };

  return (
    <ErrorBoundary>
    <div className="flex h-screen w-screen overflow-hidden bg-oncall-bg">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <TopBar onPickView={onPickView} />
        <div className="flex flex-1 flex-col overflow-hidden">
          {view === "chat" ? (
            <ChatView ref={chatRef} />
          ) : (
            <DiagnosisView
              ref={diagRef}
              kind={view === "multi" ? "multi" : "aiops"}
              onStart={() => fire("", view === "multi" ? "multi" : "aiops")}
            />
          )}
        </div>
        <Composer onSend={onSend} onUpload={onUpload} />
      </div>
    </div>
    </ErrorBoundary>
  );
}

export default App;
