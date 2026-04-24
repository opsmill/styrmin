import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ResourceRequirements, ResourceSpec } from "./types";

interface Props {
  value: ResourceRequirements;
  onChange: (next: ResourceRequirements) => void;
}

type SpecKey = "cpu" | "memory" | "ephemeral_storage";

const SPEC_LABELS: Record<SpecKey, string> = {
  cpu: "CPU",
  memory: "Memory",
  ephemeral_storage: "Ephemeral storage",
};

const SPEC_PLACEHOLDERS: Record<SpecKey, string> = {
  cpu: "e.g. 250m or 2",
  memory: "e.g. 256Mi or 1Gi",
  ephemeral_storage: "e.g. 1Gi",
};

function SpecGroup({
  variant,
  spec,
  onChange,
}: {
  variant: "requests" | "limits";
  spec: ResourceSpec | undefined;
  onChange: (next: ResourceSpec | undefined) => void;
}) {
  function set(key: SpecKey, val: string): void {
    const next: ResourceSpec = { ...(spec ?? {}) };
    if (val === "") {
      delete next[key];
    } else {
      next[key] = val;
    }
    const hasAny = (Object.keys(next) as SpecKey[]).some(
      (k) => typeof next[k] === "string" && next[k] !== "",
    );
    onChange(hasAny ? next : undefined);
  }

  const title = variant === "requests" ? "Requests" : "Limits";
  return (
    <div className="space-y-2 rounded-md border p-3">
      <Label className="font-medium">{title}</Label>
      <div className="grid grid-cols-3 gap-2">
        {(["cpu", "memory", "ephemeral_storage"] as SpecKey[]).map((key) => (
          <div key={key} className="space-y-1">
            <Label htmlFor={`res-${variant}-${key}`} className="text-xs">
              {SPEC_LABELS[key]}
            </Label>
            <Input
              id={`res-${variant}-${key}`}
              value={spec?.[key] ?? ""}
              onChange={(e) => set(key, e.target.value)}
              placeholder={SPEC_PLACEHOLDERS[key]}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ResourcesEditor({ value, onChange }: Props) {
  function setRequests(next: ResourceSpec | undefined): void {
    const result: ResourceRequirements = { ...value, requests: next };
    if (!next) delete result.requests;
    onChange(result);
  }

  function setLimits(next: ResourceSpec | undefined): void {
    const result: ResourceRequirements = { ...value, limits: next };
    if (!next) delete result.limits;
    onChange(result);
  }

  return (
    <div className="space-y-3">
      <SpecGroup
        variant="requests"
        spec={value.requests}
        onChange={setRequests}
      />
      <SpecGroup variant="limits" spec={value.limits} onChange={setLimits} />
    </div>
  );
}
