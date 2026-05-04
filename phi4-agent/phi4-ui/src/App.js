import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./App.css";

function App() {
  const [conversations, setConversations] = useState([]);
  const [activeConv, setActiveConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const chatEndRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [activeConv]);

  const startNewChat = () => {
    if (messages.length > 0 && activeConv !== null) {
      setConversations((prev) =>
        prev.map((c) => (c.id === activeConv ? { ...c, messages } : c))
      );
    }
    const id = Date.now();
    const threadId = crypto.randomUUID();
    setConversations((prev) => [
      { id, title: "New Chat", messages: [], threadId },
      ...prev,
    ]);
    setActiveConv(id);
    setMessages([]);
  };

  const switchConversation = (id) => {
    if (activeConv !== null && messages.length > 0) {
      setConversations((prev) =>
        prev.map((c) => (c.id === activeConv ? { ...c, messages } : c))
      );
    }
    const conv = conversations.find((c) => c.id === id);
    setActiveConv(id);
    setMessages(conv ? conv.messages : []);
  };

  const deleteConversation = (e, id) => {
    e.stopPropagation();
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeConv === id) {
      setActiveConv(null);
      setMessages([]);
    }
  };

  const stopGeneration = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setLoading(false);
    setStatusText("");
  }, []);

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    // Resolve the thread ID BEFORE state updates (React state is async —
    // setConversations/setActiveConv won't be visible in this closure yet)
    let currentThreadId = conversations.find((c) => c.id === activeConv)?.threadId ?? null;
    let currentConvId = activeConv;

    if (activeConv === null) {
      const id = Date.now();
      currentThreadId = crypto.randomUUID();
      currentConvId = id;
      setConversations((prev) => [
        { id, title: input.slice(0, 40), messages: [], threadId: currentThreadId },
        ...prev,
      ]);
      setActiveConv(id);
    } else if (messages.length === 0) {
      setConversations((prev) =>
        prev.map((c) =>
          c.id === activeConv ? { ...c, title: input.slice(0, 40) } : c
        )
      );
    }

    const userMessage = { role: "user", content: input };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);
    setStatusText("Thinking...");

    const controller = new AbortController();
    abortRef.current = controller;
    let accumulated = "";

    try {
      const res = await fetch("http://localhost:8000/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: input,
          thread_id: currentThreadId,
        }),
        signal: controller.signal,
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // Add a placeholder assistant message for streaming tokens into
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE lines from buffer
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            var eventType = line.slice(7).trim();
          } else if (line.startsWith("data: ") && eventType) {
            try {
              const payload = JSON.parse(line.slice(6));
              if (eventType === "token" && payload.token) {
                accumulated += payload.token;
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = {
                    role: "assistant",
                    content: accumulated,
                  };
                  return updated;
                });
                setStatusText("");
              } else if (eventType === "tool_start") {
                setStatusText(`🔧 Calling ${payload.tool}...`);
              } else if (eventType === "tool_end") {
                setStatusText("Thinking...");
              } else if (eventType === "status") {
                if (payload.status === "thinking") setStatusText("Thinking...");
                else if (payload.status === "Summarising...") setStatusText("📝 Summarising...");                else if (payload.status === "Summarising...") setStatusText("📝 Summarising...");
                else setStatusText(payload.status || "");
              } else if (eventType === "error") {
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = {
                    role: "assistant",
                    content: `Error: ${payload.detail}`,
                  };
                  return updated;
                });
              } else if (eventType === "done" && payload.thread_id) {
                // Save the server-assigned thread_id so subsequent messages stay in the same thread
                setConversations((prev) =>
                  prev.map((c) =>
                    c.id === currentConvId ? { ...c, threadId: payload.thread_id } : c
                  )
                );
              }
            } catch { /* skip malformed data lines */ }
            eventType = null;
          }
        }
      }

      // If no tokens were streamed (model gave empty response), show fallback
      if (!accumulated) {
        setMessages((prev) => {
          const updated = [...prev];
          if (updated[updated.length - 1]?.content === "") {
            updated[updated.length - 1] = {
              role: "assistant",
              content: "(No response from model)",
            };
          }
          return updated;
        });
      }
    } catch (err) {
      if (err.name === "AbortError") {
        // User stopped generation — keep what we have
        if (!accumulated) {
          setMessages((prev) => {
            const updated = [...prev];
            if (updated[updated.length - 1]?.content === "") {
              updated.pop(); // remove empty placeholder
            }
            return updated;
          });
        }
      } else {
        setMessages((prev) => [
          ...prev.filter((m) => m.content !== ""),
          { role: "assistant", content: "Failed to connect to the agent." },
        ]);
      }
    } finally {
      abortRef.current = null;
      setLoading(false);
      setStatusText("");
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="layout">
      {/* Sidebar */}
      <aside className={`sidebar ${sidebarOpen ? "open" : "closed"}`}>
        <div className="sidebar-header">
          <button className="new-chat-btn" onClick={startNewChat}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            New Chat
          </button>
        </div>
        <nav className="conv-list">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`conv-item ${c.id === activeConv ? "active" : ""}`}
              onClick={() => switchConversation(c.id)}
            >
              <span className="conv-title">{c.title}</span>
              <button
                className="delete-btn"
                onClick={(e) => deleteConversation(e, c.id)}
                title="Delete"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="model-badge">
            <span className="model-dot"></span>
            phi4-mini
          </div>
        </div>
      </aside>

      {/* Main chat area */}
      <main className="chat-main">
        <header className="topbar">
          <button
            className="toggle-sidebar"
            onClick={() => setSidebarOpen((p) => !p)}
            title="Toggle sidebar"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
          <h1 className="topbar-title">Local AI Assistant</h1>
        </header>

        <div className="chat-area">
          {messages.length === 0 && !loading ? (
            <div className="empty-state">
              <div className="empty-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.4"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>
              </div>
              <h2>How can I help you today?</h2>
              <p className="empty-sub">
                Ask me anything &mdash; math, weather, knowledge base, or your schedule.
              </p>
            </div>
          ) : (
            <div className="messages">
              {messages.map((msg, i) => (
                <div key={i} className={`msg-row ${msg.role}`}>
                  <div className="avatar">
                    {msg.role === "user" ? (
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 12c2.7 0 5-2.3 5-5s-2.3-5-5-5-5 2.3-5 5 2.3 5 5 5zm0 2c-3.3 0-10 1.7-10 5v2h20v-2c0-3.3-6.7-5-10-5z"/></svg>
                    ) : (
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a2 2 0 012 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 017 7h1a1 1 0 110 2h-1v1a7 7 0 01-7 7H10a7 7 0 01-7-7v-1H2a1 1 0 110-2h1a7 7 0 017-7h1V5.73A2 2 0 0112 2zM9.5 13a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm5 0a1.5 1.5 0 100 3 1.5 1.5 0 000-3z"/></svg>
                    )}
                  </div>
                  <div className="msg-content">
                    <span className="msg-author">
                      {msg.role === "user" ? "You" : "Phi4-mini"}
                    </span>
                    <div className="msg-text">
                      {msg.role === "assistant"
                        ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                        : msg.content}
                    </div>
                  </div>
                </div>
              ))}
              {loading && (
                <div className="msg-row assistant">
                  <div className="avatar">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a2 2 0 012 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 017 7h1a1 1 0 110 2h-1v1a7 7 0 01-7 7H10a7 7 0 01-7-7v-1H2a1 1 0 110-2h1a7 7 0 017-7h1V5.73A2 2 0 0112 2zM9.5 13a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm5 0a1.5 1.5 0 100 3 1.5 1.5 0 000-3z"/></svg>
                  </div>
                  <div className="msg-content">
                    <span className="msg-author">Phi4-mini</span>
                    <div className="msg-text thinking">
                      <span className="dot-pulse"></span>
                      {statusText && <span className="status-label">{statusText}</span>}
                    </div>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
          )}
        </div>

        <div className="input-container">
          <div className="input-box">
            <textarea
              ref={inputRef}
              rows="1"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Send a message..."
              disabled={loading}
            />
            <button
              className="send-btn"
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              title="Send"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            </button>
            {loading && (
              <button className="stop-btn" onClick={stopGeneration} title="Stop generating">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
              </button>
            )}
          </div>
          <p className="disclaimer">
            Phi4-mini running locally via Ollama. Responses may be inaccurate.
          </p>
        </div>
      </main>
    </div>
  );
}

export default App;
