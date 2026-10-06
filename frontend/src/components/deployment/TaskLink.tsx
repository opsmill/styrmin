import { useContext, type ReactNode } from "react";
import {
  TimelineLinksContext,
  timelineEntryAnchorId,
} from "@/components/deployment/timeline-links";

interface TaskLinkProps {
  taskId: string;
  children: ReactNode;
}

/** Links to a task's timeline entry; plain text when the timeline has no such entry. */
export function TaskLink({ taskId, children }: TaskLinkProps) {
  const links = useContext(TimelineLinksContext);
  if (links == null || !links.hasTask(taskId)) {
    return (
      <span
        title="This task is not in this deployment's timeline."
        data-testid="task-link"
        data-link-task-id={taskId}
        data-link-target="missing"
      >
        {children}
      </span>
    );
  }
  return (
    <a
      href={`#${timelineEntryAnchorId(taskId)}`}
      className="font-medium text-primary underline-offset-4 hover:underline"
      data-testid="task-link"
      data-link-task-id={taskId}
      data-link-target="present"
      onClick={(event) => {
        event.preventDefault();
        links.showTask(taskId);
      }}
    >
      {children}
    </a>
  );
}
