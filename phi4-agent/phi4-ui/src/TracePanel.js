import React, { useEffect, useRef } from "react";
import "./TracePanel.css";

function TracePanel({ traces, isOpen, onToggle }) {
  const contentRef = useRef(null);

  useEffect(() => {
    // Auto-scroll to bottom when new traces arrive
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [traces]);

  const formatElapsed = (startTs, endTs) => {
    const elapsed = (endTs - startTs) * 1000; // convert to ms
    if (elapsed < 1000) return `${elapsed.toFixed(0)}ms`;
    return `${(elapsed / 1000).toFixed(2)}s`;
  };

  const toPrettyJson = (value) => {
    if (value === undefined || value === null) return "null";
    if (typeof value === "string") {
      try {
        const parsed = JSON.parse(value);
        return JSON.stringify(parsed, null, 2);
      } catch {
        return value;
      }
    }
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  };

  const renderTraceLines = () => {
    const lines = [];
    let toolStack = []; // Track open tools for tree structure

    traces.forEach((trace, idx) => {
      if (trace.node === "agent") {
        lines.push(
          <div key={idx} className="trace-line trace-agent">
            <span className="trace-node">[agent]</span>
            <span className="trace-status">{trace.status}</span>
          </div>
        );
      } else if (trace.node === "tool") {
        const toolStart = {
          tool: trace.tool,
          args: trace.args,
          startTs: trace.ts,
          startIdx: idx,
        };
        toolStack.push(toolStart);

        lines.push(
          <div key={idx} className="trace-line trace-tool-start">
            <span className="trace-node">[tool]</span>
            <span className="trace-tool">{trace.tool}</span>
            <span className="trace-arrow">▶</span>
          </div>
        );

        // Render request payload as collapsible JSON
        lines.push(
          <div key={`${idx}-request`} className="trace-line trace-json-line">
            <span className="trace-indent">└─</span>
            <details className="trace-details">
              <summary className="trace-summary">request</summary>
              <pre className="trace-json-block"><code>{toPrettyJson(trace.args || {})}</code></pre>
            </details>
          </div>
        );
      } else if (trace.node === "tool_end") {
        const toolStart = toolStack.pop();
        const elapsed = toolStart
          ? formatElapsed(toolStart.startTs, trace.ts)
          : "?";

        lines.push(
          <div key={idx} className="trace-line trace-tool-end">
            <span className="trace-node">[✓]</span>
            <span className="trace-tool">{trace.tool}</span>
            <span className="trace-timing">({elapsed})</span>
          </div>
        );

        // Render full response payload as collapsible JSON/text
        lines.push(
          <div key={`${idx}-response`} className="trace-line trace-json-line">
            <span className="trace-indent">└─</span>
            <details className="trace-details">
              <summary className="trace-summary">response</summary>
              <pre className="trace-json-block"><code>{toPrettyJson(trace.result)}</code></pre>
            </details>
          </div>
        );
      } else if (trace.node === "reporter") {
        lines.push(
          <div key={idx} className="trace-line trace-reporter">
            <span className="trace-node">[📝]</span>
            <span className="trace-status">{trace.status}</span>
          </div>
        );
      } else if (trace.node === "done") {
        lines.push(
          <div key={idx} className="trace-line trace-done">
            <span className="trace-node">[✓]</span>
            <span className="trace-status">thread: {trace.thread_id}</span>
          </div>
        );
      }
    });

    return lines;
  };

  return (
    <div className={`trace-panel ${isOpen ? "open" : "closed"}`}>
      <div className="trace-header">
        <h3>Agent Trace</h3>
        <button
          className="trace-toggle"
          onClick={onToggle}
          title="Toggle trace panel"
        >
          {isOpen ? "▼" : "◀"}
        </button>
      </div>

      {isOpen && (
        <div className="trace-content" ref={contentRef}>
          {traces.length === 0 ? (
            <div className="trace-empty">Waiting for agent activity...</div>
          ) : (
            <div className="trace-output">{renderTraceLines()}</div>
          )}
        </div>
      )}
    </div>
  );
}

export default TracePanel;

