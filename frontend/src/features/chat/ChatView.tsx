import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { chatStream, chatOnce } from "../../lib/api";
import { useStore } from "../../store";
import { ChatMessage, type ChatMsg } from "./ChatMessage";

let idc = 0;
const nid = () => `m${Date.now()}_${idc++}`;

export interface ChatHandle {
  send: (text: string) => void;
}

export const ChatView = forwardRef<ChatHandle, {}>((_props, ref) => {
  const { sessionId, mode, isStreaming, setStreaming } = useStore();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = (text: string) => {
    if (isStreaming) return;
    const userMsg: ChatMsg = { id: nid(), role: "user", content: text };
    const aiMsg: ChatMsg = { id: nid(), role: "assistant", content: "", streaming: true, tools: [] };
    setMessages((m) => [...m, userMsg, aiMsg]);
    setStreaming(true);

    const patch = (fn: (m: ChatMsg) => ChatMsg) =>
      setMessages((prev) => prev.map((m) => (m.id === aiMsg.id ? fn(m) : m)));

    if (mode === "quick") {
      chatOnce(sessionId, text)
        .then((ans) => patch((m) => ({ ...m, content: ans, streaming: false })))
        .catch((e) => patch((m) => ({ ...m, content: `请求失败: ${e.message}`, streaming: false, error: true })))
        .finally(() => setStreaming(false));
      return;
    }

    const ctrl = new AbortController();
    chatStream(
      sessionId,
      text,
      {
        onEvent: (ev) => {
          if (ev.type === "content") {
            patch((m) => ({ ...m, content: m.content + (ev.data || "") }));
          } else if (ev.type === "tool_call") {
            patch((m) => ({
              ...m,
              tools: [...(m.tools || []), { name: ev.data.tool, status: ev.data.status, input: ev.data.input }],
            }));
          } else if (ev.type === "done") {
            patch((m) => ({ ...m, content: ev.data.answer || m.content, streaming: false }));
          } else if (ev.type === "error") {
            patch((m) => ({ ...m, content: `错误: ${ev.data}`, streaming: false, error: true }));
          }
        },
        onDone: () => {
          patch((m) => ({ ...m, streaming: false }));
          setStreaming(false);
        },
        onError: (err) => {
          patch((m) => ({ ...m, content: `连接失败: ${err.message}`, streaming: false, error: true }));
          setStreaming(false);
        },
      },
      ctrl.signal,
    );
  };

  useImperativeHandle(ref, () => ({ send }));

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      {messages.length === 0 && (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-oncall-muted">
          <div className="text-lg font-medium text-slate-300">你好，我是智能 OnCall 小助手</div>
          <div className="text-sm">可以问我系统故障、查询日志、检索运维知识</div>
        </div>
      )}
      {messages.map((m) => (
        <ChatMessage key={m.id} msg={m} />
      ))}
    </div>
  );
});

ChatView.displayName = "ChatView";
