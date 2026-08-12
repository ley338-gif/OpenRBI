import type { ReactNode } from "react";

export function FormField({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="form-field">
      {/* Wrapping (not just a sibling label+input) associates the label
          with whatever control is passed as children implicitly, without
          needing a generated id per call site — screen readers and
          getByLabel()-style queries both rely on this actually being a
          real association, not just adjacent markup that looks right. */}
      <label>
        <span className="form-field-label">{label}</span>
        {children}
      </label>
      {error ? <div className="field-error">{error}</div> : hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return <div className="form-error-banner">{children}</div>;
}
