import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  SelectGroup,
  SelectLabel,
  SelectSeparator,
} from 'frontend';

// Base UI's Select.Root accepts `defaultValue` and `defaultOpen`; the wrapper
// spreads props through. `Open` forces the popup composed; `WithValue` shows
// the resting trigger with a selected value.

export const Open = () => (
  <Select defaultValue="production" defaultOpen>
    <SelectTrigger style={{ width: 220 }}>
      <SelectValue placeholder="Select environment" />
    </SelectTrigger>
    <SelectContent>
      <SelectGroup>
        <SelectLabel>Environments</SelectLabel>
        <SelectItem value="production">Production</SelectItem>
        <SelectItem value="staging">Staging</SelectItem>
        <SelectItem value="development">Development</SelectItem>
      </SelectGroup>
      <SelectSeparator />
      <SelectItem value="preview">Preview</SelectItem>
    </SelectContent>
  </Select>
);

export const WithValue = () => (
  <Select defaultValue="staging">
    <SelectTrigger style={{ width: 220 }}>
      <SelectValue placeholder="Select environment" />
    </SelectTrigger>
    <SelectContent>
      <SelectItem value="production">Production</SelectItem>
      <SelectItem value="staging">Staging</SelectItem>
      <SelectItem value="development">Development</SelectItem>
    </SelectContent>
  </Select>
);
