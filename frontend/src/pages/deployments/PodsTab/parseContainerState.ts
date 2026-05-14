export type ParsedContainerState = {
  state: "running" | "waiting" | "terminated" | "unknown";
  reason: string | null;
};

const KNOWN_STATES = new Set(["running", "waiting", "terminated", "unknown"]);

export function parseContainerState(raw: unknown): ParsedContainerState {
  if (typeof raw !== "string" || raw.length === 0) {
    return { state: "unknown", reason: null };
  }

  const colonAt = raw.indexOf(":");
  if (colonAt === -1) {
    return KNOWN_STATES.has(raw)
      ? { state: raw as ParsedContainerState["state"], reason: null }
      : { state: "unknown", reason: null };
  }

  const head = raw.slice(0, colonAt);
  const tail = raw.slice(colonAt + 1);
  if (head === "waiting" || head === "terminated") {
    return { state: head, reason: tail.length > 0 ? tail : null };
  }
  return { state: "unknown", reason: null };
}
