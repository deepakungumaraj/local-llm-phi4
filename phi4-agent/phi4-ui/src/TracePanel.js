import React, { useState, useEffect, useRef } from "react";
import "./TracePanel.css";

function TracePanel({ traces, isOpen, onToggle }) {
  const contentRef = useRef(null);

  useEffect(() => {
    // Auto-scroll to bottom when new traces arrive
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [traces]);

  const formatValue = (val) => {
    if (typeof val === "string") return val;
    if (typeof val === "number") return val.toString();
    if (typeof val === "boolean") return val ? "true" : "false";
    if (typeof val === "object") {
      if (Array.isArray(val)) {
        return val.length > 0 ? `[${val.length} items]` : "[]";
      }
      return JSON.stringify(val).slice(0, 100);
    }
    return String(val);
  };

  const formatElapsed = (startTs, endTs) => {
    const elapsed = (endTs - startTs) * 1000; // convert to ms
    if (elapsed < 1000) return `${elapsed.toFixed(0)}ms`;
    return `${(elapsed / 1000).toFixed(2)}s`;
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

        // Render arguments as nested tree
        if (trace.args && typeof trace.args === "object") {
          const argKeys = Object.keys(trace.args);
          argKeys.forEach((key, argIdx) => {
            const isLast = argIdx === argKeys.length - 1;
            const connector = isLast ? "└─" : "├─";
            lines.push(
              <div key={`${idx}-arg-${key}`} className="trace-line trace-arg">
                <span className="trace-indent">{connector}</span>
                <span className="trace-key">{key}:</span>
                <span className="trace-value">{formatValue(trace.args[key])}</span>
              </div>
            );
          });
        }
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

        // Show result summary if available
        if (trace.result) {
          const resultStr =
            typeof trace.result === "string"
              ? trace.result
              : JSON.stringify(trace.result);
          const resultLines = resultStr.split("\n").slice(0, 3);
          resultLines.forEach((line, lineIdx) => {
            const isLast = lineIdx === resultLines.length - 1;
            const truncated =
              resultStr.split("\n").length > 3 && isLast ? "..." : "";
            lines.push(
              <div
                key={`${idx}-result-${lineIdx}`}
                className="trace-line trace-result"
              >
                <span className="trace-indent">└─</span>
                <span className="trace-result-text">
                  {line.slice(0, 60)}
                  {truncated}
                </span>
              </div>
            );
          });
        }
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

