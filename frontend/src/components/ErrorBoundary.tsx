import { Component, type ReactNode } from "react";

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { hasError: false, message: "" };

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err.message };
  }

  componentDidCatch(err: Error, info: unknown) {
    console.error("ErrorBoundary caught:", err, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
          <div className="text-base font-medium text-rose-300">界面渲染出错</div>
          <pre className="max-w-lg overflow-auto rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
            {this.state.message}
          </pre>
          <button
            onClick={() => this.setState({ hasError: false, message: "" })}
            className="rounded-lg border border-oncall-border bg-oncall-card px-4 py-2 text-sm text-slate-200 hover:border-oncall-accent/40"
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
