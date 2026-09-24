import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Field } from "../../components";
import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";

function AuthCard({ title, intro, children }: { title: string; intro: string; children: React.ReactNode }) {
  return (
    <div className="login">
      <div className="card login__card">
        <div className="login__brand">
          <div className="brand__mark" style={{ fontSize: 26 }}>NTX</div>
          <div className="brand__sub">Automation Co.</div>
        </div>
        <h1 className="auth-title">{title}</h1>
        <p className="auth-intro">{intro}</p>
        {children}
      </div>
    </div>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const result = await api.post<{ message: string }>("/api/auth/password-reset/request", { email });
      setMessage(result.message);
    } catch {
      // Keep this screen enumeration-resistant even during a transient error.
      setMessage("If that account exists, a reset link will be sent shortly.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthCard title="Reset your password" intro="Enter the email used for your NTX dashboard account.">
      {message ? (
        <><p className="auth-success" role="status">{message}</p><Link className="auth-link" to="/login">Return to sign in</Link></>
      ) : (
        <form onSubmit={submit}>
          <Field label="Email" id="reset-email">
            <input id="reset-email" className="input" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
          </Field>
          <button className="btn btn--primary auth-submit" disabled={submitting}>{submitting ? "Sending…" : "Send reset link"}</button>
          <Link className="auth-link" to="/login">Return to sign in</Link>
        </form>
      )}
    </AuthCard>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const token = params.get("token") ?? "";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirm) return setError("The new passwords do not match.");
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/api/auth/password-reset/confirm", { token, new_password: password });
      navigate("/login?reset=complete", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The reset link could not be used.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthCard title="Choose a new password" intro="Use at least 12 characters. This link works only once.">
      {!token ? <p className="field__error" role="alert">This reset link is missing its secure token.</p> : (
        <form onSubmit={submit}>
          <PasswordFields password={password} confirm={confirm} setPassword={setPassword} setConfirm={setConfirm} />
          {error && <p className="field__error" role="alert">{error}</p>}
          <button className="btn btn--primary auth-submit" disabled={submitting}>{submitting ? "Saving…" : "Save new password"}</button>
        </form>
      )}
    </AuthCard>
  );
}

export function ChangePasswordPage() {
  const { me, loading } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!loading && !me) return <Navigate to="/login" replace />;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirm) return setError("The new passwords do not match.");
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/api/auth/change-password", { current_password: current, new_password: password });
      navigate("/login?changed=complete", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.fields.current_password) setError(err.fields.current_password);
      else setError(err instanceof Error ? err.message : "The password could not be changed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthCard title="Replace your temporary password" intro="Before opening the dashboard, choose a private password only you know.">
      <form onSubmit={submit}>
        <Field label="Current temporary password" id="current-password">
          <input id="current-password" className="input" type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} />
        </Field>
        <PasswordFields password={password} confirm={confirm} setPassword={setPassword} setConfirm={setConfirm} />
        {error && <p className="field__error" role="alert">{error}</p>}
        <button className="btn btn--primary auth-submit" disabled={submitting}>{submitting ? "Saving…" : "Change password"}</button>
      </form>
    </AuthCard>
  );
}

function PasswordFields({ password, confirm, setPassword, setConfirm }: { password: string; confirm: string; setPassword: (value: string) => void; setConfirm: (value: string) => void }) {
  return <>
    <Field label="New password" id="new-password"><input id="new-password" className="input" type="password" minLength={12} autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></Field>
    <Field label="Confirm new password" id="confirm-password"><input id="confirm-password" className="input" type="password" minLength={12} autoComplete="new-password" required value={confirm} onChange={(event) => setConfirm(event.target.value)} /></Field>
  </>;
}
