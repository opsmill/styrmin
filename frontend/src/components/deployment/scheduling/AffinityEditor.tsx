import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { X } from "lucide-react";
import { LabelSelectorEditor } from "./LabelSelectorEditor";
import type {
  AffinityBlock,
  AffinityTerm,
  DeploymentReference,
  WeightedAffinityTerm,
} from "./types";

type AffinityKind = "pod_affinity" | "pod_anti_affinity" | "node_affinity";
type TargetMode = "label_selector" | "deployment_ref";

interface Props {
  kind: AffinityKind;
  value: AffinityBlock;
  onChange: (next: AffinityBlock) => void;
}

const KIND_SHOWS_DEPLOYMENT_REF: Record<AffinityKind, boolean> = {
  pod_affinity: true,
  pod_anti_affinity: true,
  node_affinity: false,
};

// node_affinity terms use a virtual topology_key because the spec requires
// topology_key on every AffinityTerm; for node_affinity the backend ignores
// it (the affinity is over node labels, not pod topology).
const KIND_TOPOLOGY_DEFAULT: Record<AffinityKind, string> = {
  pod_affinity: "kubernetes.io/hostname",
  pod_anti_affinity: "kubernetes.io/hostname",
  node_affinity: "",
};

function TermEditor({
  kind,
  term,
  idPrefix,
  onChange,
}: {
  kind: AffinityKind;
  term: AffinityTerm;
  idPrefix: string;
  onChange: (next: AffinityTerm) => void;
}) {
  const hasDeploymentRefMode = KIND_SHOWS_DEPLOYMENT_REF[kind];
  const currentMode: TargetMode = term.deployment_ref
    ? "deployment_ref"
    : "label_selector";

  function setMode(next: TargetMode): void {
    if (next === "label_selector") {
      const patched: AffinityTerm = { ...term, label_selector: {} };
      delete patched.deployment_ref;
      onChange(patched);
    } else {
      const patched: AffinityTerm = { ...term, deployment_ref: {} };
      delete patched.label_selector;
      onChange(patched);
    }
  }

  function setDeploymentRef(patch: Partial<DeploymentReference>): void {
    onChange({
      ...term,
      deployment_ref: { ...(term.deployment_ref ?? {}), ...patch },
    });
  }

  return (
    <div className="space-y-3">
      {kind !== "node_affinity" && (
        <div className="space-y-1">
          <Label htmlFor={`${idPrefix}-topology`}>Topology key</Label>
          <Input
            id={`${idPrefix}-topology`}
            value={term.topology_key}
            onChange={(e) => onChange({ ...term, topology_key: e.target.value })}
            placeholder="e.g. kubernetes.io/hostname"
          />
        </div>
      )}

      {hasDeploymentRefMode && (
        <div className="space-y-1">
          <Label htmlFor={`${idPrefix}-target-mode`}>Target by</Label>
          <Select
            value={currentMode}
            onValueChange={(v) => setMode(v as TargetMode)}
          >
            <SelectTrigger id={`${idPrefix}-target-mode`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="label_selector">Label selector</SelectItem>
              <SelectItem value="deployment_ref">Deployment</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {currentMode === "label_selector" && (
        <LabelSelectorEditor
          value={term.label_selector}
          onChange={(ls) => onChange({ ...term, label_selector: ls })}
          idPrefix={idPrefix}
        />
      )}

      {currentMode === "deployment_ref" && term.deployment_ref && (
        <div className="space-y-2 rounded-md border p-3">
          <div className="space-y-1">
            <Label htmlFor={`${idPrefix}-dep-id`}>Deployment ID</Label>
            <Input
              id={`${idPrefix}-dep-id`}
              value={term.deployment_ref.deployment_id ?? ""}
              onChange={(e) =>
                setDeploymentRef({
                  deployment_id: e.target.value || undefined,
                })
              }
              placeholder="UUID"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`${idPrefix}-dep-name`}>
              Deployment name (alternative)
            </Label>
            <Input
              id={`${idPrefix}-dep-name`}
              value={term.deployment_ref.deployment_name ?? ""}
              onChange={(e) =>
                setDeploymentRef({
                  deployment_name: e.target.value || undefined,
                })
              }
              placeholder="Deployment name"
            />
          </div>
        </div>
      )}
    </div>
  );
}

export function AffinityEditor({ kind, value, onChange }: Props) {
  const required = value.required ?? [];
  const preferred = value.preferred ?? [];

  function emitUpdate(patch: Partial<AffinityBlock>): void {
    const next: AffinityBlock = { ...value, ...patch };
    const hasRequired = (next.required ?? []).length > 0;
    const hasPreferred = (next.preferred ?? []).length > 0;
    // Strip empty arrays for clean payloads; emitted config is still the
    // same object so that `replace` toggle can be added later.
    if (!hasRequired) delete next.required;
    if (!hasPreferred) delete next.preferred;
    onChange(next);
  }

  function newAffinityTerm(): AffinityTerm {
    return {
      topology_key: KIND_TOPOLOGY_DEFAULT[kind],
      label_selector: {},
    };
  }

  function addRequired(): void {
    emitUpdate({ required: [...required, newAffinityTerm()] });
  }

  function updateRequired(i: number, term: AffinityTerm): void {
    emitUpdate({
      required: required.map((t, idx) => (idx === i ? term : t)),
    });
  }

  function removeRequired(i: number): void {
    emitUpdate({ required: required.filter((_, idx) => idx !== i) });
  }

  function addPreferred(): void {
    emitUpdate({
      preferred: [...preferred, { weight: 1, term: newAffinityTerm() }],
    });
  }

  function updatePreferred(i: number, wt: WeightedAffinityTerm): void {
    emitUpdate({
      preferred: preferred.map((t, idx) => (idx === i ? wt : t)),
    });
  }

  function removePreferred(i: number): void {
    emitUpdate({ preferred: preferred.filter((_, idx) => idx !== i) });
  }

  const kindLabel =
    kind === "pod_affinity"
      ? "pod affinity"
      : kind === "pod_anti_affinity"
        ? "pod anti-affinity"
        : "node affinity";

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label className="font-medium">Required</Label>
        <p className="text-xs text-muted-foreground">
          Hard constraint — pod is not scheduled unless satisfied.
        </p>
        {required.length === 0 && (
          <p className="text-xs text-muted-foreground">No required terms.</p>
        )}
        {required.map((term, i) => (
          <div
            key={`req-${i}`}
            className="space-y-3 rounded-md border p-3"
            data-testid={`${kind}-required-row`}
          >
            <TermEditor
              kind={kind}
              term={term}
              idPrefix={`${kind}-req-${i}`}
              onChange={(t) => updateRequired(i, t)}
            />
            <div className="flex justify-end">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove required ${kindLabel} term ${i + 1}`}
                onClick={() => removeRequired(i)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={addRequired}>
          Add required term
        </Button>
      </div>

      <div className="space-y-2">
        <Label className="font-medium">Preferred</Label>
        <p className="text-xs text-muted-foreground">
          Soft preference — scheduler tries to honor, weighted 1–100.
        </p>
        {preferred.length === 0 && (
          <p className="text-xs text-muted-foreground">No preferred terms.</p>
        )}
        {preferred.map((wt, i) => (
          <div
            key={`pref-${i}`}
            className="space-y-3 rounded-md border p-3"
            data-testid={`${kind}-preferred-row`}
          >
            <div className="space-y-1">
              <Label htmlFor={`${kind}-pref-weight-${i}`}>Weight (1–100)</Label>
              <Input
                id={`${kind}-pref-weight-${i}`}
                type="number"
                min={1}
                max={100}
                value={wt.weight}
                onChange={(e) =>
                  updatePreferred(i, {
                    ...wt,
                    weight: Number(e.target.value) || 1,
                  })
                }
                className="w-32"
              />
            </div>
            <TermEditor
              kind={kind}
              term={wt.term}
              idPrefix={`${kind}-pref-${i}`}
              onChange={(t) => updatePreferred(i, { ...wt, term: t })}
            />
            <div className="flex justify-end">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove preferred ${kindLabel} term ${i + 1}`}
                onClick={() => removePreferred(i)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addPreferred}
        >
          Add preferred term
        </Button>
      </div>
    </div>
  );
}
