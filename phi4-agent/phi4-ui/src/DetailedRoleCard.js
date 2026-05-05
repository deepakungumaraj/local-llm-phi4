import React, { useState } from "react";
import "./DetailedRoleCard.css";

export default function DetailedRoleCard({ role, onApply }) {
  const [expandedFields, setExpandedFields] = useState({});

  const toggleExpand = (field) => {
    setExpandedFields((prev) => ({
      ...prev,
      [field]: !prev[field],
    }));
  };

  const truncateText = (text, maxLen = 200) => {
    if (!text) return "N/A";
    return text.length > maxLen ? text.substring(0, maxLen) + "..." : text;
  };

  const isLongText = (text, maxLen = 200) => {
    return text && text.length > maxLen;
  };

  return (
    <div className="detailed-role-card">
      {/* Header */}
      <div className="drc-header">
        <div className="drc-title-section">
          <h2 className="drc-title">{role.title || "N/A"}</h2>
          <p className="drc-role-id">Role ID: {role.id}</p>
        </div>
        <div className="drc-status-badge" data-status={role.demandStatus?.toLowerCase() || "unknown"}>
          {role.demandStatus || "N/A"}
        </div>
      </div>

      {/* Quick Info Grid */}
      <div className="drc-quick-grid">
        <div className="drc-grid-item">
          <span className="drc-label">📋 Client</span>
          <span className="drc-value">{role.client || "N/A"}</span>
        </div>
        <div className="drc-grid-item">
          <span className="drc-label">📍 Location</span>
          <span className="drc-value">
            {role.location || "N/A"} {role.locationType && `(${role.locationType})`}
          </span>
        </div>
        <div className="drc-grid-item">
          <span className="drc-label">📅 Start</span>
          <span className="drc-value">{role.startDate?.substring(0, 10) || "N/A"}</span>
        </div>
        <div className="drc-grid-item">
          <span className="drc-label">📅 End</span>
          <span className="drc-value">{role.endDate?.substring(0, 10) || "N/A"}</span>
        </div>
      </div>

      {/* Detailed Sections */}
      <div className="drc-sections">
        {/* Description */}
        {role.description && (
          <div className="drc-section">
            <h3 className="drc-section-title">Description</h3>
            <div className="drc-section-content">
              {isLongText(role.description, 300) ? (
                <>
                  <p className={`drc-text ${expandedFields.description ? "expanded" : "collapsed"}`}>
                    {expandedFields.description ? role.description : truncateText(role.description, 300)}
                  </p>
                  <button
                    className="drc-see-more-btn"
                    onClick={() => toggleExpand("description")}
                  >
                    {expandedFields.description ? "See Less" : "See More"}
                  </button>
                </>
              ) : (
                <p className="drc-text">{role.description}</p>
              )}
            </div>
          </div>
        )}

        {/* Skills Required */}
        {role.skills && (
          <div className="drc-section">
            <h3 className="drc-section-title">Skills Required</h3>
            <div className="drc-section-content">
              {isLongText(role.skills, 300) ? (
                <>
                  <p className={`drc-text ${expandedFields.skills ? "expanded" : "collapsed"}`}>
                    {expandedFields.skills ? role.skills : truncateText(role.skills, 300)}
                  </p>
                  <button
                    className="drc-see-more-btn"
                    onClick={() => toggleExpand("skills")}
                  >
                    {expandedFields.skills ? "See Less" : "See More"}
                  </button>
                </>
              ) : (
                <p className="drc-text">{role.skills}</p>
              )}
            </div>
          </div>
        )}

        {/* Responsibilities */}
        {role.responsibilities && (
          <div className="drc-section">
            <h3 className="drc-section-title">Responsibilities</h3>
            <div className="drc-section-content">
              {isLongText(role.responsibilities, 300) ? (
                <>
                  <p className={`drc-text ${expandedFields.responsibilities ? "expanded" : "collapsed"}`}>
                    {expandedFields.responsibilities ? role.responsibilities : truncateText(role.responsibilities, 300)}
                  </p>
                  <button
                    className="drc-see-more-btn"
                    onClick={() => toggleExpand("responsibilities")}
                  >
                    {expandedFields.responsibilities ? "See Less" : "See More"}
                  </button>
                </>
              ) : (
                <p className="drc-text">{role.responsibilities}</p>
              )}
            </div>
          </div>
        )}

        {/* Additional Details */}
        <div className="drc-section">
          <h3 className="drc-section-title">Additional Details</h3>
          <div className="drc-details-grid">
            {role.level && (
              <div className="drc-detail-item">
                <span className="drc-detail-label">Level:</span>
                <span className="drc-detail-value">{role.level}</span>
              </div>
            )}
            {role.industry && (
              <div className="drc-detail-item">
                <span className="drc-detail-label">Industry:</span>
                <span className="drc-detail-value">{role.industry}</span>
              </div>
            )}
            {role.salaryRange && (
              <div className="drc-detail-item">
                <span className="drc-detail-label">Salary Range:</span>
                <span className="drc-detail-value">{role.salaryRange}</span>
              </div>
            )}
            {role.workType && (
              <div className="drc-detail-item">
                <span className="drc-detail-label">Work Type:</span>
                <span className="drc-detail-value">{role.workType}</span>
              </div>
            )}
            {role.duration && (
              <div className="drc-detail-item">
                <span className="drc-detail-label">Duration:</span>
                <span className="drc-detail-value">{role.duration}</span>
              </div>
            )}
            {role.demandStatus && (
              <div className="drc-detail-item">
                <span className="drc-detail-label">Status:</span>
                <span className="drc-detail-value">{role.demandStatus}</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="drc-actions">
        <button className="drc-apply-btn" onClick={() => onApply(role.id)}>
          Apply for this Role
        </button>
      </div>
    </div>
  );
}
