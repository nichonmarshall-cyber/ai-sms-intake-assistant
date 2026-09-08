import { Component, useEffect, useRef } from "react";
import type { ErrorInfo, ReactNode } from "react";

/* --- States -------------------------------------------------------------- */

export function Loading({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" style={{ padding: "8px 0" }}>
      <span className="ntx-visually-hidden">{label}</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ width: `${100 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="state">
      <p className="state__title">{title}</p>
      <p className="state__body">{body}</p>
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", body }: { title?: string; body: string }) {
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">{title}</p>
      <p className="state__body">{body}</p>
    </div>
  );
}

/**
 * Honest placeholder for a module that has no implementation yet.
 * Deliberately shows no numbers -- fabricated metrics would be worse than none.
 */
export function LockedModule({ label, description }: { label: string; description: string }) {
  return (
    <div className="card">
      <div className="card__body">
        <div className="state">
          <p className="state__title">{label} is not available yet</p>
          <p className="state__body">{description}</p>
          <p className="state__body" style={{ marginTop: 12 }}>
            Nothing is shown here rather than sample data, so you never see a number
            that is not real.
          </p>
        </div>
      </div>
    </div>
  );
}

/* --- Primitives ---------------------------------------------------------- */

export function Card({
  title,
  action,
  children,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {title && (
        <header className="card__header">
          <h2 className="card__title">{title}</h2>
          {action}
        </header>
      )}
      <div className="card__body">{children}</div>
    </section>
  );
}

export function Stat({ label, value, icon }: { label: string; value: number | string; icon: string }) {
  return (
    <div className="card stat">
      <div className="stat__icon" aria-hidden="true">
        {icon}
      </div>
      <div>
        <div className="stat__value">{value}</div>
        <div className="stat__label">{label}</div>
      </div>
    </div>
  );
}

export function Badge({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "ok" | "warn" | "demo";
}) {
  const cls = tone === "default" ? "badge" : `badge badge--${tone}`;
  return <span className={cls}>{children}</span>;
}

export function Field({
  label,
  id,
  error,
  children,
}: {
  label: string;
  id: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {children}
      {error && (
        <span className="field__error" id={`${id}-error`} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/* --- Error boundary ------------------------------------------------------ */

interface BoundaryState {
  message: string | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { message: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ntx] Render error", error, info.componentStack);
  }

  render() {
    if (this.state.message) {
      return (
        <div className="content">
          <ErrorState body={this.state.message} />
        </div>
      );
    }
    return this.props.children;
  }
}

/* --- Focus management ---------------------------------------------------- */

/** Moves focus to a heading on route change so screen readers announce it. */
export function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return ref;
}
