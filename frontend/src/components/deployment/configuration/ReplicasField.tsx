import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  parseReplicaInput,
  replicaFieldError,
  replicaPlaceholder,
} from "@/lib/replicas";

interface Props {
  componentName: string;
  value: number | null | undefined;
  /** `undefined` when the field is emptied (no override). */
  onChange: (value: number | undefined) => void;
  onBlur?: () => void;
  /** Count that applies without an override; `null` when the chart sets it. */
  driverDefault: number | null;
  /** The driver version fixes the component at 1: the field is read-only. */
  singleton: boolean;
}

/**
 * "Replicas" field for one component, shared by the edit drawer and the
 * create form. An empty field is no override; the placeholder names the
 * count that applies then. A singleton component shows `1 (singleton)`.
 */
export function ReplicasField({
  componentName,
  value,
  onChange,
  onBlur,
  driverDefault,
  singleton,
}: Props) {
  const inputId = `comp-${componentName}-replicas`;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const error = singleton ? undefined : replicaFieldError(value);

  return (
    <div
      className="space-y-1"
      data-testid={`component-replicas-editor-${componentName}`}
    >
      <Label
        htmlFor={inputId}
        className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
      >
        Replicas
      </Label>
      {singleton ? (
        <Input
          id={inputId}
          data-testid={`comp-replicas-${componentName}`}
          aria-label={`Replicas for ${componentName}`}
          aria-describedby={hintId}
          value="1 (singleton)"
          readOnly
        />
      ) : (
        <Input
          id={inputId}
          type="number"
          min={1}
          step={1}
          inputMode="numeric"
          data-testid={`comp-replicas-${componentName}`}
          aria-label={`Replicas for ${componentName}`}
          aria-describedby={error ? `${errorId} ${hintId}` : hintId}
          aria-invalid={error ? true : undefined}
          value={value == null || Number.isNaN(value) ? "" : String(value)}
          onChange={(e) => onChange(parseReplicaInput(e.target.value))}
          onBlur={onBlur}
          placeholder={replicaPlaceholder(driverDefault)}
          autoComplete="off"
        />
      )}
      {error && (
        <p
          id={errorId}
          data-testid={`comp-replicas-error-${componentName}`}
          className="text-xs text-destructive"
        >
          {error}
        </p>
      )}
      <p
        id={hintId}
        data-testid={`comp-replicas-hint-${componentName}`}
        className="text-xs text-muted-foreground"
      >
        {singleton
          ? "The driver marks this component as a singleton, so it runs 1 pod."
          : "Leave empty for no override."}
      </p>
    </div>
  );
}
