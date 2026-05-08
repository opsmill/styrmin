/**
 * EnvVarsForm — environment-scope env-var editor (009 / US4).
 *
 * Renders one editable row per env var (name + value text inputs) plus
 * Add / Remove controls. Validation mirrors the backend rules
 * (FR-018) — name regex, per-value 64 KiB cap, per-scope 100 entries
 * and 256 KiB total, no duplicate names. Inline errors per row;
 * global error above the form. Submit is disabled while any error is
 * surfaced.
 *
 * On Save, the form opens a confirmation dialog naming the deployments
 * about to be redeployed. After confirmation, the form invokes
 * ``onSubmit`` (which the parent wires to the typed
 * ``useUpdateEnvironmentMutation``). Submit failures keep the form in
 * its edited state and surface an error notice (FR-021).
 */
import { useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { RedeployConfirmDialog } from "./RedeployConfirmDialog";

// ---------------------------------------------------------------------------
// Types & constants
// ---------------------------------------------------------------------------

export interface EnvVarRowState {
  id: string;
  name: string;
  value: string;
  errors: { name?: string; value?: string };
}

export interface EnvVarsFormDeployment {
  id: string;
  name: string;
  internal: boolean;
}

export interface EnvVarPayload {
  name: string;
  value: string;
}

export interface EnvVarsFormProps {
  initialEnvVars: EnvVarPayload[];
  deployments: EnvVarsFormDeployment[];
  onSubmit: (envVars: EnvVarPayload[]) => Promise<void>;
  /** Optional error string from a prior submission (FR-021). */
  submitError?: string | null;
  /** Hint that a submission is in flight (disables the Save/Redeploy buttons). */
  isSubmitting?: boolean;
}

const NAME_REGEX = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PER_VALUE_BYTES = 64 * 1024;
const PER_SCOPE_BYTES = 256 * 1024;
const PER_SCOPE_ENTRIES = 100;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function newRowId(): string {
  if (
    typeof globalThis.crypto !== "undefined" &&
    typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  return `row-${Math.random().toString(36).slice(2)}-${Date.now()}`;
}

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

function seedRows(initial: EnvVarPayload[]): EnvVarRowState[] {
  return initial.map((entry) => ({
    id: newRowId(),
    name: entry.name,
    value: entry.value,
    errors: {},
  }));
}

interface ValidationOutcome {
  rows: EnvVarRowState[];
  totalBytes: number;
  globalError: string | null;
}

function validateRows(rows: EnvVarRowState[]): ValidationOutcome {
  // Count duplicate names so we can flag every offending row.
  const nameCounts = new Map<string, number>();
  for (const row of rows) {
    if (row.name) {
      nameCounts.set(row.name, (nameCounts.get(row.name) ?? 0) + 1);
    }
  }

  let totalBytes = 0;
  const validatedRows: EnvVarRowState[] = rows.map((row) => {
    const errors: EnvVarRowState["errors"] = {};

    if (row.name === "") {
      errors.name = "Name is required.";
    } else if (!NAME_REGEX.test(row.name)) {
      errors.name = "Name must match ^[A-Za-z_][A-Za-z0-9_]*$.";
    } else if ((nameCounts.get(row.name) ?? 0) > 1) {
      errors.name = "Duplicate name.";
    }

    const valueBytes = utf8ByteLength(row.value);
    if (valueBytes > PER_VALUE_BYTES) {
      errors.value = `Value exceeds ${PER_VALUE_BYTES.toLocaleString()} byte cap (${valueBytes.toLocaleString()} bytes).`;
    }

    // Bytes count toward the per-scope total even if the row has errors,
    // matching the backend's per-scope cap accounting.
    totalBytes += utf8ByteLength(row.name) + valueBytes;

    return { ...row, errors };
  });

  let globalError: string | null = null;
  if (validatedRows.length > PER_SCOPE_ENTRIES) {
    globalError = `Too many entries: ${validatedRows.length} > ${PER_SCOPE_ENTRIES} cap.`;
  } else if (totalBytes > PER_SCOPE_BYTES) {
    globalError = `Total size exceeds ${PER_SCOPE_BYTES.toLocaleString()} byte cap (currently ${totalBytes.toLocaleString()} bytes).`;
  }

  return { rows: validatedRows, totalBytes, globalError };
}

function rowsHaveErrors(rows: EnvVarRowState[]): boolean {
  return rows.some(
    (row) => row.errors.name !== undefined || row.errors.value !== undefined,
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EnvVarsForm({
  initialEnvVars,
  deployments,
  onSubmit,
  submitError,
  isSubmitting = false,
}: EnvVarsFormProps) {
  const [rows, setRows] = useState<EnvVarRowState[]>(() =>
    seedRows(initialEnvVars),
  );
  const [confirmOpen, setConfirmOpen] = useState(false);

  const validation = useMemo(() => validateRows(rows), [rows]);
  const hasErrors =
    validation.globalError !== null || rowsHaveErrors(validation.rows);

  // Eligible deployments — the backend skips tombstoned and internal
  // deployments during fanout; we mirror that for the dialog count.
  const eligibleDeployments = useMemo(
    () => deployments.filter((d) => !d.internal),
    [deployments],
  );

  const updateRow = (
    id: string,
    patch: Partial<Omit<EnvVarRowState, "id">>,
  ) => {
    setRows((current) =>
      current.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    );
  };

  const removeRow = (id: string) => {
    setRows((current) => current.filter((row) => row.id !== id));
  };

  const addRow = () => {
    setRows((current) => [
      ...current,
      { id: newRowId(), name: "", value: "", errors: {} },
    ]);
  };

  const handleSaveClick = () => {
    if (hasErrors || isSubmitting) return;
    setConfirmOpen(true);
  };

  const handleConfirmRedeploy = async () => {
    setConfirmOpen(false);
    const payload: EnvVarPayload[] = validation.rows.map((row) => ({
      name: row.name,
      value: row.value,
    }));
    await onSubmit(payload);
  };

  const handleCancelRedeploy = () => {
    setConfirmOpen(false);
  };

  return (
    <div className="flex flex-col gap-3" data-testid="env-vars-form">
      {submitError && (
        <Alert variant="destructive" data-testid="env-vars-form-error">
          <AlertTitle>Update failed</AlertTitle>
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      )}

      {validation.globalError && (
        <Alert variant="destructive" data-testid="env-vars-form-global-error">
          <AlertDescription>{validation.globalError}</AlertDescription>
        </Alert>
      )}

      {validation.rows.length === 0 ? (
        <p
          className="text-[13px] text-muted-foreground italic"
          data-testid="env-vars-form-empty"
        >
          No environment variables set. Click &ldquo;Add Variable&rdquo; to
          create one.
        </p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="env-vars-form-rows">
          {validation.rows.map((row, index) => (
            <li
              key={row.id}
              className="flex flex-col gap-1"
              data-testid="env-vars-form-row"
            >
              <div className="flex items-start gap-2">
                <div className="flex-1">
                  <Label htmlFor={`env-var-name-${row.id}`} className="sr-only">
                    Name {index + 1}
                  </Label>
                  <Input
                    id={`env-var-name-${row.id}`}
                    placeholder="NAME"
                    value={row.name}
                    onChange={(e) =>
                      updateRow(row.id, { name: e.target.value })
                    }
                    aria-invalid={row.errors.name ? true : undefined}
                    data-testid="env-var-name-input"
                  />
                </div>
                <div className="flex-1">
                  <Label
                    htmlFor={`env-var-value-${row.id}`}
                    className="sr-only"
                  >
                    Value {index + 1}
                  </Label>
                  <Input
                    id={`env-var-value-${row.id}`}
                    placeholder="value"
                    value={row.value}
                    onChange={(e) =>
                      updateRow(row.id, { value: e.target.value })
                    }
                    aria-invalid={row.errors.value ? true : undefined}
                    data-testid="env-var-value-input"
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={() => removeRow(row.id)}
                  aria-label={`Remove env var ${row.name || index + 1}`}
                  data-testid="env-var-remove-button"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              {(row.errors.name || row.errors.value) && (
                <div className="flex flex-col gap-0.5 pl-1">
                  {row.errors.name && (
                    <p
                      className="text-xs text-destructive"
                      data-testid="env-var-name-error"
                    >
                      {row.errors.name}
                    </p>
                  )}
                  {row.errors.value && (
                    <p
                      className="text-xs text-destructive"
                      data-testid="env-var-value-error"
                    >
                      {row.errors.value}
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between gap-2 pt-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addRow}
          data-testid="env-vars-form-add-button"
        >
          <Plus className="mr-1 h-4 w-4" />
          Add Variable
        </Button>
        <div className="flex items-center gap-3">
          <span
            className="text-xs text-muted-foreground"
            data-testid="env-vars-form-total-bytes"
          >
            {validation.rows.length} entries ·{" "}
            {validation.totalBytes.toLocaleString()} /{" "}
            {PER_SCOPE_BYTES.toLocaleString()} bytes
          </span>
          <Button
            type="button"
            onClick={handleSaveClick}
            disabled={hasErrors || isSubmitting}
            data-testid="env-vars-form-save-button"
          >
            {isSubmitting ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>

      <RedeployConfirmDialog
        open={confirmOpen}
        deploymentCount={eligibleDeployments.length}
        deploymentNames={eligibleDeployments.map((d) => d.name)}
        onConfirm={handleConfirmRedeploy}
        onCancel={handleCancelRedeploy}
      />
    </div>
  );
}
