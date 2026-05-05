import React from "react";
import "./RoleCard.css";

function RoleCard({ role, onView, onApply }) {
  const getLocationColor = () => {
    const type = (role.type || "").toLowerCase();
    if (type.includes("remote")) return "remote";
    if (type.includes("hybrid")) return "hybrid";
    return "onsite";
  };

  const locationColor = getLocationColor();

  return (
    <div className={`role-card location-${locationColor}`}>
      <div className="role-card-header">
        <div className="role-badge" />
        <div className="role-title-section">
          <h3 className="role-title">{role.title || "Unknown Role"}</h3>
          <p className="role-company">
            {role.company || "Unknown Company"}
            {role.location && ` • ${role.location}`}
          </p>
        </div>
      </div>

      <div className="role-card-body">
        <div className="role-meta">
          {role.type && (
            <span className={`role-type-badge type-${locationColor}`}>
              {role.type}
            </span>
          )}
          {role.duration && <span className="role-duration">{role.duration}</span>}
        </div>
        {role.id && <div className="role-id">Role ID: {role.id}</div>}
      </div>

      <div className="role-card-footer">
        <button
          className="role-btn role-btn-view"
          onClick={() => onView && onView(role.id)}
          title={`View details for role ${role.id}`}
        >
          View
        </button>
        <button
          className="role-btn role-btn-apply"
          onClick={() => onApply && onApply(role.id)}
          title={`Apply for ${role.title}`}
        >
          Apply
        </button>
      </div>
    </div>
  );
}

export default RoleCard;
