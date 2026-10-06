import { Circle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { TaskResult } from "@/generated/graphql";
import { taskResultDisplay } from "@/lib/task-display";

interface TaskResultBadgeProps {
  result: TaskResult;
}

/** A task result, calculated from the steps of the task and of its started tasks. */
export function TaskResultBadge({ result }: TaskResultBadgeProps) {
  const display = taskResultDisplay(result);
  return (
    <Badge
      variant={display.variant}
      className="gap-1"
      data-testid="task-result-badge"
      data-task-result={result}
    >
      <Circle aria-hidden="true" className="h-2 w-2 fill-current" />
      {display.label}
    </Badge>
  );
}
