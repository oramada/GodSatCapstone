// A select of named options, as t3code's settings rows use its Select
// (pingdotgg/t3code apps/web/src/components/settings/*: a small trigger at the
// row's right, the list aligned to its end, no check indicator). Moved here
// from screens/settings/controls.tsx. Options are typed, so the value handed
// back is one of them. Changes: `id` reaches the trigger, so a Field's label
// names it (`<Field label="Folder" htmlFor="folder"><ChoiceSelect id="folder" …/>`,
// with no `label`); an option's `title` is said on hover (the full path
// behind a shortened label).

import { cn } from "../../lib/utils";
import type { Option } from "./segmented";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "./select";

export interface ChoiceOption<T extends string> extends Option<T> {
  /** Said on hover over the option: the whole of what a shortened label stands for (a full path). */
  title?: string;
}

/**
 * Named by `label` (its spoken name), or by a `<label for>` through `id`: inside a Field, pass
 * `id` and leave `label` off, since a `label` here would replace the Field's words.
 */
type ChoiceSelectName = { label: string; id?: string } | { label?: undefined; id: string };

export type ChoiceSelectProps<T extends string> = ChoiceSelectName & {
  value: T;
  options: readonly ChoiceOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
};

export function ChoiceSelect<T extends string>({
  label,
  id,
  value,
  options,
  onChange,
  disabled = false,
  className,
}: ChoiceSelectProps<T>) {
  const current = options.find((option) => option.value === value);
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => {
        const found = options.find((option) => option.value === next);
        if (found) onChange(found.value);
      }}
    >
      <SelectTrigger
        size="sm"
        className={cn("w-full sm:w-44", className)}
        {...(id ? { id } : {})}
        {...(label ? { "aria-label": label } : {})}
      >
        <SelectValue>{current?.label ?? value}</SelectValue>
      </SelectTrigger>
      <SelectPopup align="end" alignItemWithTrigger={false}>
        {options.map((option) => (
          <SelectItem key={option.value} hideIndicator value={option.value} {...(option.title ? { title: option.title } : {})}>
            {option.label}
          </SelectItem>
        ))}
      </SelectPopup>
    </Select>
  );
}
