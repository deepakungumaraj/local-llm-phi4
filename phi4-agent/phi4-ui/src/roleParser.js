/**
 * Parses role data from markdown content
 * Detects markdown tables with role information and extracts structured data
 */

function parseMarkdownTable(markdown) {
  // Match markdown table pattern
  const tablePattern = /\|(.+)\|\n\|[\s\-:|\s]+\|\n((?:\|.+\|\n?)*)/g;
  const tables = [];
  let match;

  while ((match = tablePattern.exec(markdown)) !== null) {
    const headerLine = match[1];
    const bodyLines = match[2];

    const headers = headerLine
      .split("|")
      .map((h) => h.trim().toLowerCase())
      .filter((h) => h);

    const rows = bodyLines
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => {
        const cells = line
          .split("|")
          .map((cell) => cell.trim())
          .filter((cell) => cell);
        return cells;
      });

    tables.push({ headers, rows });
  }

  return tables;
}

function parseTextBasedRole(text) {
  /**
   * Parse roles from text format like:
   * Role ID: 6260189
   * Title: Data Engineer
   * Client Company: BRISTOL MYERS SQUIBB
   * Location (Remote): New York, USA
   * etc.
   */
  const lines = text.split("\n");
  const roles = [];
  let currentRole = {};
  let roleStartIdx = -1;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    const normalizedLine = line.replace(/\*\*/g, "");
    
    // Skip empty lines and question prompts
    if (!line || normalizedLine.includes("?")) continue;

    // Look for role ID line (start of a new role)
    if (normalizedLine.match(/^(?:\d+\.\s*)?Role ID\s*:\s*\d+/i)) {
      // Save previous role if it has content
      if (Object.keys(currentRole).length > 1) {
        roles.push(currentRole);
      }
      currentRole = {};
      roleStartIdx = i;
    }

    // Parse key-value pairs
    const colonIndex = normalizedLine.indexOf(":");
    if (colonIndex > 0) {
      const key = normalizedLine
        .substring(0, colonIndex)
        .trim()
        .toLowerCase()
        .replace(/^(?:\d+\.\s*)/, "")
        .replace(/^[-*]\s*/, "");
      const value = normalizedLine.substring(colonIndex + 1).trim();

      // Map various key formats to standard fields
      if (key.includes("role id")) currentRole.id = value;
      else if (key.includes("title")) currentRole.title = value;
      else if (key.includes("company")) currentRole.company = value;
      else if (key.includes("location")) {
        currentRole.location = value;
        // Extract location type from parentheses
        const typeMatch = normalizedLine.match(/\((.*?)\)/);
        if (typeMatch) {
          currentRole.type = typeMatch[1];
        }
      } else if (key.includes("start date")) currentRole.start_date = value;
      else if (key.includes("end date")) currentRole.end_date = value;
      else if (key.includes("duration")) currentRole.duration = value;
      else if (key.includes("industry")) currentRole.industry = value;
      else if (key.includes("demand")) currentRole.demand = value;
    }
  }

  // Don't forget the last role
  if (Object.keys(currentRole).length > 1) {
    roles.push(currentRole);
  }

  return roles.length > 0 ? roles : null;
}

function detectRoleTable(content) {
  // Look for common role-related keywords in headers
  const roleKeywords = [
    "role",
    "title",
    "position",
    "company",
    "client",
    "location",
    "type",
    "duration",
    "date",
    "id",
  ];

  const tables = parseMarkdownTable(content);

  for (const table of tables) {
    const hasRoleColumns = table.headers.some((h) =>
      roleKeywords.some((kw) => h.includes(kw))
    );

    if (hasRoleColumns) {
      return table;
    }
  }

  return null;
}

function extractRoles(table) {
  if (!table) return null;

  const headers = table.headers;
  const roles = [];

  // Create a mapping of header index to field name
  const fieldMap = {};
  const aliases = {
    title: ["title", "position", "role title"],
    company: ["company", "client", "employer", "organization"],
    location: ["location", "city", "place"],
    type: ["type", "work type", "mode", "status"],
    duration: ["duration", "dates", "timeframe", "period", "term"],
    id: ["role id", "role_id", "id", "number"],
  };

  // Map headers to field names
  for (const [field, headerVariants] of Object.entries(aliases)) {
    for (let i = 0; i < headers.length; i++) {
      if (headerVariants.some((v) => headers[i].includes(v))) {
        fieldMap[field] = i;
        break;
      }
    }
  }

  // Extract roles from rows
  for (const row of table.rows) {
    if (row.length < 2) continue;

    const role = {};
    for (const [field, index] of Object.entries(fieldMap)) {
      if (index < row.length) {
        role[field] = row[index].trim();
      }
    }

    // Only include rows that look like roles
    if (role.id || role.title || role.company) {
      roles.push(role);
    }
  }

  return roles.length > 0 ? roles : null;
}

/**
 * Check if content contains role data and extract it
 * Returns { hasRoles: boolean, roles: array|null, cleanContent: string, detailedRole: object|null }
 */
export function parseRoleContent(content) {
  if (!content || typeof content !== "string") {
    return { hasRoles: false, roles: null, cleanContent: content, detailedRole: null };
  }

  // Check for detailed role view (structured JSON from view_role)
  if (content.startsWith("{")) {
    try {
      const parsed = JSON.parse(content);
      if (parsed._type === "detailed_role_view" && parsed.role) {
        return {
          hasRoles: false,
          roles: null,
          cleanContent: "",
          detailedRole: parsed.role,
        };
      }
    } catch (e) {
      // Not valid JSON, continue with normal parsing
    }
  }

  // First try markdown table format
  const table = detectRoleTable(content);
  let roles = extractRoles(table);
  
  // If no table found, try text-based format
  if (!roles) {
    roles = parseTextBasedRole(content);
  }

  // Remove the table from content if roles were found
  let cleanContent = content;
  if (roles && roles.length > 0) {
    // Strip all pipe-table lines (header, separator, rows) regardless of exact format
    cleanContent = content
      .split("\n")
      .filter((line) => {
        const t = line.trim();
        // Drop lines that are table rows: start with | or contain multiple |
        if (t.startsWith("|")) return false;
        // Drop lines that are purely pipe/dash separators
        if (/^[\|\s\-:]+$/.test(t) && t.includes("|")) return false;
        return true;
      })
      .join("\n")
      .replace(/\n{3,}/g, "\n\n")  // collapse multiple blank lines
      .trim();
  }

  return {
    hasRoles: !!roles,
    roles: roles,
    cleanContent: cleanContent,
    detailedRole: null,
  };
}

export default { parseRoleContent, parseMarkdownTable, detectRoleTable, extractRoles };
