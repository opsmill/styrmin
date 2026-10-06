import { createContext } from "react";

export interface TimelineLinks {
  /** Whether the timeline has an entry for the task. */
  hasTask: (taskId: string) => boolean;
  /** Expands the task's entry, scrolls to it and focuses it. */
  showTask: (taskId: string) => void;
}

/** Set by `DeploymentTimeline`; null where a step list is shown outside it. */
export const TimelineLinksContext = createContext<TimelineLinks | null>(null);

export function timelineEntryAnchorId(taskId: string): string {
  return `task-${taskId}`;
}
