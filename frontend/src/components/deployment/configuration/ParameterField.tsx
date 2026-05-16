import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ParameterDefinition } from "@/generated/graphql";

interface Props {
  parameter: ParameterDefinition;
  value: unknown;
  onChange: (value: unknown) => void;
}

/**
 * Renders one driver-defined parameter as the correct primitive control based
 * on `parameter.kind` (`boolean` → checkbox, `select` → select, `integer` →
 * number input, anything else → text input). Falls back to the
 * parameter's `default` when no explicit value has been set yet.
 *
 * Originally inlined as `DynamicParameterField` inside
 * `frontend/src/pages/deployments/DeployFormPage.tsx`. Extracted as part of
 * feature 011-unified-deployment-config (T018) so the unified-drawer Driver
 * Parameters section can reuse the exact same renderer (T048) without
 * forking behaviour.
 */
export function ParameterField({ parameter, value, onChange }: Props) {
  const defaultVal = parameter.default as unknown;

  switch (parameter.kind) {
    case "boolean":
      return (
        <div className="flex items-center gap-2">
          <Checkbox
            id={parameter.name}
            checked={(value as boolean) ?? (defaultVal as boolean) ?? false}
            onCheckedChange={(checked) => onChange(checked)}
          />
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
        </div>
      );

    case "select":
      return (
        <div className="space-y-2">
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
          <Select
            value={(value as string) ?? (defaultVal as string) ?? ""}
            onValueChange={(v) => onChange(v)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {parameter.values?.map((v) => (
                <SelectItem key={v} value={v}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );

    case "integer":
      return (
        <div className="space-y-2">
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
          <Input
            id={parameter.name}
            type="number"
            value={String(value ?? defaultVal ?? "")}
            onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)}
          />
        </div>
      );

    default:
      return (
        <div className="space-y-2">
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
          <Input
            id={parameter.name}
            value={(value as string) ?? (defaultVal as string) ?? ""}
            onChange={(e) => onChange(e.target.value)}
          />
        </div>
      );
  }
}
