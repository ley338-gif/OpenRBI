import type { ButtonHTMLAttributes, ReactNode } from "react";

/** A button that is only an icon MUST have an accessible name — this
 * wrapper makes `label` required so that's never forgotten (section 45:
 * icon buttons need aria-label).
 */
export function IconButton({
  label,
  children,
  active,
  className = "",
  ...rest
}: {
  label: string;
  children: ReactNode;
  active?: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`icon-btn${active ? " active" : ""}${className ? ` ${className}` : ""}`}
      aria-label={label}
      title={label}
      {...rest}
    >
      {children}
    </button>
  );
}
