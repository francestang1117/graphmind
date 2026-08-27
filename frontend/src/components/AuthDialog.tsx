import { useEffect, useState } from "react";
import { ArrowRight, GitBranch, LockKeyhole, X } from "lucide-react";
import {
  getAuthProviders,
  getGithubLoginUrl,
  isApiOrigin,
} from "../services/api";
import { useAuthStore } from "../stores/authStore";

interface AuthDialogProps {
  open: boolean;
  onClose: () => void;
}

const commonPasswords = new Set([
  "12345678",
  "123456789",
  "qwerty123",
  "password",
  "password1",
  "password123",
  "letmein123",
  "admin123",
  "welcome123",
]);

function passwordState(password: string) {
  const bytes = new TextEncoder().encode(password).length;
  if (password.length < 8) return { valid: false, label: "Use at least 8 characters", tone: "weak" };
  if (bytes > 72) return { valid: false, label: "Password is over the 72-byte limit", tone: "weak" };
  if (commonPasswords.has(password.trim().toLowerCase())) {
    return { valid: false, label: "Choose a less common password", tone: "weak" };
  }
  if (password.length < 12) return { valid: true, label: "Password is acceptable", tone: "fair" };
  return { valid: true, label: "Password looks strong", tone: "strong" };
}

export default function AuthDialog({ open, onClose }: AuthDialogProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [githubEnabled, setGithubEnabled] = useState(false);
  const [oauthError, setOauthError] = useState("");
  const { user, busy, error, login, register, finishOAuth, clearError } = useAuthStore();
  const passwordStatus = passwordState(password);

  useEffect(() => {
    if (user && open) onClose();
  }, [user, open, onClose]);

  useEffect(() => {
    if (!open) return;
    void getAuthProviders()
      .then((providers) => setGithubEnabled(providers.github))
      .catch(() => setGithubEnabled(false));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const receiveOAuth = (event: MessageEvent) => {
      // Ignore messages from other tabs or extensions using the same event name.
      if (!isApiOrigin(event.origin) || event.data?.type !== "graphmind:oauth") return;
      if (event.data.error) {
        setOauthError(event.data.error);
        return;
      }
      if (event.data.code) {
        setOauthError("");
        void finishOAuth(event.data.code).catch(() => undefined);
      }
    };
    window.addEventListener("message", receiveOAuth);
    return () => window.removeEventListener("message", receiveOAuth);
  }, [finishOAuth, open]);

  if (!open) return null;

  const switchMode = (next: "login" | "register") => {
    setMode(next);
    setOauthError("");
    clearError();
  };

  const startGithub = () => {
    setOauthError("");
    const popup = window.open(
      getGithubLoginUrl(window.location.origin),
      "graphmind-github-login",
      "popup,width=560,height=720",
    );
    if (!popup) setOauthError("Allow pop-ups to continue with GitHub.");
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      if (mode === "register") await register(email, password, name);
      else await login(email, password);
    } catch {
      // Leave the fields filled in so a typo is easy to fix.
    }
  };

  return (
    <div className="auth-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="auth-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button className="auth-close" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>

        <div className="auth-mark"><LockKeyhole size={18} /></div>
        <h2 id="auth-title">{mode === "login" ? "Welcome back" : "Create your workspace"}</h2>
        <p>{mode === "login" ? "Sign in to open your private document space." : "Start with a separate document and graph space."}</p>

        <div className="auth-tabs" aria-label="Account action">
          <button className={mode === "login" ? "active" : ""} onClick={() => switchMode("login")}>Sign in</button>
          <button className={mode === "register" ? "active" : ""} onClick={() => switchMode("register")}>Register</button>
        </div>

        {githubEnabled && (
          <>
            <button className="auth-github" type="button" onClick={startGithub} disabled={busy}>
              <GitBranch size={16} />
              Continue with GitHub
            </button>
            <div className="auth-divider"><span>or use email</span></div>
          </>
        )}

        <form onSubmit={submit}>
          {mode === "register" && (
            <label>
              Name
              <input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" placeholder="Your name" />
            </label>
          )}
          <label>
            Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required placeholder="you@example.com" />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} minLength={8} required placeholder="8–72 bytes" />
          </label>

          {mode === "register" && password && (
            <div className={`password-status ${passwordStatus.tone}`}>
              <span><i /></span>
              {passwordStatus.label}
            </div>
          )}

          {(oauthError || error) && <div className="auth-error">{oauthError || error}</div>}

          <button className="auth-submit" disabled={busy || (mode === "register" && !passwordStatus.valid)}>
            {busy ? "Please wait" : mode === "login" ? "Sign in" : "Create account"}
            {!busy && <ArrowRight size={16} />}
          </button>
        </form>
      </section>
    </div>
  );
}
