import { useEffect, useRef, useState } from "react";
import { LogOut, UserRound } from "lucide-react";
import { useAuthStore } from "../stores/authStore";

interface AuthControlProps {
  onSignIn: () => void;
}

export default function AuthControl({ onSignIn }: AuthControlProps) {
  const { user, ready, logout } = useAuthStore();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);

  if (!ready) return <div className="auth-control-placeholder" />;
  if (!user) {
    return (
      <button className="auth-sign-in" onClick={onSignIn}>
        <UserRound size={15} />
        Sign in
      </button>
    );
  }

  const label = user.name || user.email.split("@")[0];
  return (
    <div className="auth-control" ref={root}>
      <button className="auth-user-button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span>{label.slice(0, 1).toUpperCase()}</span>
        {label}
      </button>
      {open && (
        <div className="auth-menu">
          <strong>{label}</strong>
          <small>{user.email}</small>
          <button
            onClick={(event) => {
              event.stopPropagation();
              setOpen(false);
              void logout();
            }}
          >
            <LogOut size={14} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
