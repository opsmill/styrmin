import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useUpdateDeploymentMutation } from "@/generated/graphql";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AffinityEditor } from "./AffinityEditor";
import { ResourcesEditor } from "./ResourcesEditor";
import { TolerationsEditor } from "./TolerationsEditor";
import { TopologySpreadEditor } from "./TopologySpreadEditor";
import { sanitizeSchedulingConfig } from "./sanitize";
import type { SchedulingConfig } from "./types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  deploymentId: string;
  currentConfig: Record<string, unknown>;
}

function extractScheduling(config: Record<string, unknown>): SchedulingConfig {
  const raw = config.scheduling;
  if (!raw || typeof raw !== "object") return {};
  return raw as SchedulingConfig;
}

export function SchedulingConfigDialog({
  open,
  onOpenChange,
  deploymentId,
  currentConfig,
}: Props) {
  const [draft, setDraft] = useState<SchedulingConfig>(() =>
    extractScheduling(currentConfig),
  );
  const [error, setError] = useState<string | null>(null);
  const [prevOpen, setPrevOpen] = useState(open);

  // Reset the draft and clear any prior error the moment the dialog
  // transitions from closed → open. React permits setState during render
  // when it's guarded by a prior-value check; this is the officially-
  // recommended pattern for "resync state from props on a specific
  // transition" and avoids the cascading-renders warning that
  // useEffect-based resets trigger under the React Compiler
  // (react-hooks/set-state-in-effect).
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setDraft(extractScheduling(currentConfig));
      setError(null);
    }
  }

  const updateMutation = useUpdateDeploymentMutation();
  const queryClient = useQueryClient();

  async function handleSubmit(): Promise<void> {
    setError(null);
    const scheduling = sanitizeSchedulingConfig(draft);
    const nextConfig = { ...currentConfig };
    if (Object.keys(scheduling).length === 0) {
      delete nextConfig.scheduling;
    } else {
      nextConfig.scheduling = scheduling;
    }
    try {
      await updateMutation.mutateAsync({
        deploymentId,
        config: nextConfig,
      });
      queryClient.invalidateQueries({ queryKey: ["GetDeployment"] });
      onOpenChange(false);
    } catch (err) {
      console.error("[update-deployment] scheduling mutation failed", err);
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit Scheduling</DialogTitle>
          <DialogDescription>
            Configure pod placement, resource requests/limits, and runtime class
            for this deployment. Leave sections empty to inherit from the
            environment.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-6">
          <section
            className="space-y-2"
            data-testid="scheduling-section-resources"
          >
            <h3 className="text-sm font-semibold">Resources</h3>
            <ResourcesEditor
              value={draft.resources ?? {}}
              onChange={(r) => setDraft({ ...draft, resources: r })}
            />
          </section>

          <section
            className="space-y-2"
            data-testid="scheduling-section-tolerations"
          >
            <h3 className="text-sm font-semibold">Tolerations</h3>
            <TolerationsEditor
              value={draft.tolerations ?? []}
              onChange={(t) => setDraft({ ...draft, tolerations: t })}
            />
          </section>

          <section
            className="space-y-2"
            data-testid="scheduling-section-topology-spread"
          >
            <h3 className="text-sm font-semibold">
              Topology Spread Constraints
            </h3>
            <TopologySpreadEditor
              value={draft.topology_spread_constraints ?? []}
              onChange={(t) =>
                setDraft({ ...draft, topology_spread_constraints: t })
              }
            />
          </section>

          <section
            className="space-y-2"
            data-testid="scheduling-section-pod-affinity"
          >
            <h3 className="text-sm font-semibold">Pod Affinity</h3>
            <AffinityEditor
              kind="pod_affinity"
              value={draft.pod_affinity ?? {}}
              onChange={(a) => setDraft({ ...draft, pod_affinity: a })}
            />
          </section>

          <section
            className="space-y-2"
            data-testid="scheduling-section-pod-anti-affinity"
          >
            <h3 className="text-sm font-semibold">Pod Anti-Affinity</h3>
            <AffinityEditor
              kind="pod_anti_affinity"
              value={draft.pod_anti_affinity ?? {}}
              onChange={(a) => setDraft({ ...draft, pod_anti_affinity: a })}
            />
          </section>

          <section
            className="space-y-2"
            data-testid="scheduling-section-node-affinity"
          >
            <h3 className="text-sm font-semibold">Node Affinity</h3>
            <p className="text-xs text-muted-foreground">
              Affinity over node labels — topology key is not used.
            </p>
            <AffinityEditor
              kind="node_affinity"
              value={draft.node_affinity ?? {}}
              onChange={(a) => setDraft({ ...draft, node_affinity: a })}
            />
          </section>

          <section
            className="space-y-2"
            data-testid="scheduling-section-runtime-class"
          >
            <h3 className="text-sm font-semibold">Runtime Class</h3>
            <div className="space-y-1">
              <Label htmlFor="runtime-class">Runtime class name</Label>
              <Input
                id="runtime-class"
                value={draft.runtime_class ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    runtime_class: e.target.value || undefined,
                  })
                }
                placeholder="e.g. kata-e2e"
              />
            </div>
          </section>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={updateMutation.isPending}
          >
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
