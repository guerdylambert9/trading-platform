import { useEffect, useState, type FormEvent } from "react";

import type { Tone } from "../types";

export interface ToastMessage {
  id: number;
  text: string;
  tone: Tone;
}

export function Toast({ message, onDone }: { message: ToastMessage | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(onDone, 7000);
    return () => window.clearTimeout(timer);
  }, [message, onDone]);

  return (
    <div className="toast-region" aria-live="polite">
      {message && (
        <div key={message.id} className={`toast toast-${message.tone}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}

export function TokenPrompt({ onSave }: { onSave: (token: string) => void }) {
  const [token, setToken] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (token.trim()) onSave(token.trim());
  };
  return (
    <main className="desk narrow">
      <h1>Trading desk</h1>
      <form className="notice" onSubmit={submit}>
        <p>This dashboard needs your API token. Use the API_TOKEN value from your .env file.</p>
        <label htmlFor="api-token">API token</label>
        <div className="inline-field">
          <input id="api-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus />
          <button type="submit" className="btn btn-go" disabled={!token.trim()}>
            Save token
          </button>
        </div>
      </form>
    </main>
  );
}

export function Unreachable({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="desk narrow">
      <h1>Trading desk</h1>
      <div className="notice" role="alert">
        <p>{message}</p>
        <p className="muted">
          Start the API from the backend folder with <code>trader serve</code>, then try again.
        </p>
        <button type="button" className="btn" onClick={onRetry}>
          Try again
        </button>
      </div>
    </main>
  );
}
