import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { getStatus, streamChat } from "./api.js";

// ─── icons (inline SVG so there's no icon library dependency) ──────────────

const IconChat = () => (
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const IconClose = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const IconSend = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);

const IconLink = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
  </svg>
);

const IconDot = () => (
  <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
    <circle cx="16" cy="16" r="5" fill="white" opacity="0.9" />
    <circle cx="7" cy="16" r="3.5" fill="white" opacity="0.6" />
    <circle cx="25" cy="16" r="3.5" fill="white" opacity="0.6" />
  </svg>
);

// ─── main component ─────────────────────────────────────────────────────────

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState(null);

  // ---- chat state ----
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Hi! I'm the DotStark AI assistant. I have knowledge about dotstark.com. Ask me anything about our services, team, or projects!",
      sources: [],
    },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const streamingRef = useRef(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const refreshStatus = async () => {
    try { setStatus(await getStatus()); } catch { /* backend may not be up yet */ }
  };

  useEffect(() => { refreshStatus(); }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // ---- chat ----
  const handleAsk = async (e) => {
    e.preventDefault();
    const question = input.trim();
    if (!question || streamingRef.current) return;

    streamingRef.current = true;
    setStreaming(true);
    setInput("");

    setMessages((m) => [
      ...m,
      { role: "user", content: question },
      { role: "assistant", content: "", sources: [] },
    ]);

    await streamChat(question, {
      onSources: (sources) =>
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1].sources = sources;
          return copy;
        }),
      onToken: (token) =>
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1].content += token;
          return copy;
        }),
      onDone: () => { streamingRef.current = false; setStreaming(false); },
      onError: (msg) => {
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1].content = "Sorry, something went wrong: " + msg;
          return copy;
        });
        streamingRef.current = false;
        setStreaming(false);
      },
    });

    streamingRef.current = false;
    setStreaming(false);
  };

  return (
    <>
      {/* ── floating panel ───────────────────────────────────────────── */}
      {open && (
        <div className="wgt-panel">

          {/* header */}
          <div className="wgt-header">
            <div className="wgt-header-left">
              <div className="wgt-avatar"><IconDot /></div>
              <div>
                <div className="wgt-title">DotStark AI</div>
                <div className="wgt-subtitle">Ask me anything</div>
              </div>
            </div>
            <button className="wgt-close" onClick={() => setOpen(false)}>
              <IconClose />
            </button>
          </div>

          {/* messages */}
          <div className="wgt-messages">
            {messages.map((msg, i) => (
              <div key={i} className={`wgt-msg ${msg.role}`}>
                {msg.role === "assistant" && (
                  <div className="wgt-msg-avatar"><IconDot /></div>
                )}
                <div className="wgt-msg-body">
                  <div className="wgt-msg-bubble">
                    {msg.role === "user" ? (
                      msg.content
                    ) : msg.content ? (
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    ) : (
                      streaming && (
                        <span className="wgt-cursor">●●●</span>
                      )
                    )}
                      </div>
                    </div>
                  </div>
            ))}
            <div ref={bottomRef} />
          </div>

          <form onSubmit={handleAsk} className="wgt-input-bar">
            <input
              ref={inputRef}
              type="text"
              placeholder="Ask a question…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={streaming}
            />
            <button type="submit" disabled={streaming || !input.trim()}>
              <IconSend />
            </button>
          </form>

          {/* footer */}
          <div className="wgt-footer">
            Powered by <strong>DotStark AI</strong>
          </div>
        </div>
      )}

      {/* ── launcher button ───────────────────────────────────────────── */}
      <button
        className={`wgt-launcher ${open ? "open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close chat" : "Open chat"}
      >
        <span className="wgt-launcher-icon chat"><IconChat /></span>
        <span className="wgt-launcher-icon close"><IconClose /></span>
      </button>
    </>
  );
}
