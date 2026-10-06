import type { TaskResult } from "@/generated/graphql";

const TASK_TYPE_LABELS: Record<string, string> = {
  create_instance: "Create",
  update_instance: "Update",
  upgrade_instance: "Upgrade",
  delete_instance: "Delete",
  delete_deployment: "Delete",
  stop_components: "Stop Components",
  start_components: "Start Components",
  run_job: "Run Job",
  noop: "No-op",
};

/** The label the timeline shows for a task type. */
export function taskTypeLabel(type: string): string {
  return TASK_TYPE_LABELS[type] ?? type;
}

export interface TaskResultDisplay {
  label: string;
  variant: "warning" | "destructive" | "success" | "secondary";
  /** Background class for a status dot. */
  dot: string;
}

export const TASK_RESULT_DISPLAY: Record<TaskResult, TaskResultDisplay> = {
  RUNNING: { label: "Running", variant: "warning", dot: "bg-warning" },
  FAILED: { label: "Failed", variant: "destructive", dot: "bg-destructive" },
  SUCCEEDED: { label: "Succeeded", variant: "success", dot: "bg-success" },
  SUPERSEDED: {
    label: "Superseded",
    variant: "secondary",
    dot: "bg-muted-foreground",
  },
};

/** Display for a result; an unknown value shows as-is in neutral colours. */
export function taskResultDisplay(result: string): TaskResultDisplay {
  return (
    TASK_RESULT_DISPLAY[result as TaskResult] ?? {
      label: result,
      variant: "secondary",
      dot: "bg-muted-foreground",
    }
  );
}
