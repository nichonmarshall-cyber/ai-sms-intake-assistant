import { useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Field, Loading } from "../../components";

export function LoginPage() {
  const { me, loading, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [params] = useSearchParams();

  if (loading) {
    return (
      <div className="login">
        <div className="card login__card">
          <Loading rows={3} label="Checking your session" />
        </div>
      </div>
    );
  }
  if (me) return <Navigate to={me.user.requires_credential_change ? "/change-password" : "/"} replace />;

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts. Please wait a few minutes and try again.");
      } else {
        setError(err instanceof Error ? err.message : "Unable to sign in.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login">
      <form className="card login__card" onSubmit={onSubmit} noValidate>
        <div className="login__brand">
          <div className="brand__mark" style={{ fontSize: 26 }}>
            NTX
          </div>
          <div className="brand__sub">Automation Co.</div>
        </div>

        <Field label="Email" id="email">
          <input
            id="email"
            className="input"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        <Field label="Password" id="password">
          <input
            id="password"
            className="input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>

        {error && (
          <p className="field__error" role="alert" style={{ marginBottom: 16 }}>
            {error}
          </p>
        )}
        {(params.get("reset") === "complete" || params.get("changed") === "complete") && (
          <p className="auth-success" role="status">Your password was updated. Sign in with the new password.</p>
        )}

        <button type="submit" className="btn btn--primary" style={{ width: "100%" }} disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
        <Link className="auth-link" to="/forgot-password">Forgot your password?</Link>
      </form>
    </div>
  );
}
