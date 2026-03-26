import { useState, useRef, useEffect } from "react";
import "./App.css";

function App() {
  const [conversations, setConversations] = useState([]);
  const [activeConv, setActiveConv] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const chatEndRef = useRef(null);
  const inputRef = useRef(null);

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
    setConversations((prev) => [
      { id, title: "New Chat", messages: [] },
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

  const sendMessage = async () => {
    if (!input.trim() || loading) return;

    if (activeConv === null) {
      const id = Date.now();
      setConversations((prev) => [
        { id, title: input.slice(0, 40), messages: [] },
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

    try {
      const res = await fetch("http://localhost:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input }),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.response },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Failed to connect to the agent." },
      ]);
    } finally {
      setLoading(false);
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
          <h1 className="topbar-title">Phi-4 Local Assistant</h1>
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
                      {msg.role === "user" ? "You" : "Phi-4"}
                    </span>
                    <div className="msg-text">{msg.content}</div>
                  </div>
                </div>
              ))}
              {loading && (
                <div className="msg-row assistant">
                  <div className="avatar">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a2 2 0 012 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 017 7h1a1 1 0 110 2h-1v1a7 7 0 01-7 7H10a7 7 0 01-7-7v-1H2a1 1 0 110-2h1a7 7 0 017-7h1V5.73A2 2 0 0112 2zM9.5 13a1.5 1.5 0 100 3 1.5 1.5 0 000-3zm5 0a1.5 1.5 0 100 3 1.5 1.5 0 000-3z"/></svg>
                  </div>
                  <div className="msg-content">
                    <span className="msg-author">Phi-4</span>
                    <div className="msg-text thinking">
                      <span className="dot-pulse"></span>
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
          </div>
          <p className="disclaimer">
            Phi-4 mini running locally via Ollama. Responses may be inaccurate.
          </p>
        </div>
      </main>
    </div>
  );
}

export default App;
