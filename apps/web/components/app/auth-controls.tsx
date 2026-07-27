"use client";

import { ChevronDown, LogIn, LogOut, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form-controls";

export function AuthControls({ sidebarOpen = true }: { sidebarOpen?: boolean }) {
  const { configured, user, signInWithEmail, signInWithGoogle, signOut, signUpWithEmail } = useFirebaseAuth();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const signingUp = mode === "sign-up";

  async function run(action: () => Promise<void>) {
    setPending(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Authentication failed.");
    } finally {
      setPending(false);
    }
  }

  if (!configured) {
    return <span className="px-2 text-xs text-sidebar-muted">Auth unavailable</span>;
  }

  if (user) {
    const accountName = user.displayName ?? user.email ?? "Signed in";
    const avatarText = accountName
      .split(/\s+|@/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase();

    return (
      <details className="group relative">
        <summary
          className="flex min-h-11 w-full cursor-pointer list-none items-center gap-3 rounded-md px-1 text-left text-sidebar-foreground outline-none transition hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar"
          aria-label={`Account menu for ${accountName}`}
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-sidebar-active text-sm font-semibold text-sidebar-foreground" aria-hidden="true">
            {avatarText || "EA"}
          </span>
          {sidebarOpen && (
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{accountName}</span>
              <span className="block truncate text-xs text-sidebar-muted">Account</span>
            </span>
          )}
          {sidebarOpen && <ChevronDown className="h-4 w-4 shrink-0 transition-transform duration-200 group-open:rotate-180" aria-hidden="true" />}
        </summary>
        <div
          className={`absolute bottom-full z-50 mb-2 w-56 rounded-md border border-sidebar-border bg-sidebar p-2 shadow-lg ${sidebarOpen ? "left-0" : "left-full ml-2"}`}
          aria-label="Account options"
        >
          <p className="truncate px-2 py-2 text-xs text-sidebar-muted">{user.email ?? accountName}</p>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="w-full justify-start text-sidebar-foreground hover:bg-white/10 hover:text-sidebar-foreground"
            disabled={pending}
            onClick={() => run(signOut)}
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            Sign out
          </Button>
        </div>
      </details>
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email"));
    const password = String(data.get("password"));
    await run(() => signingUp ? signUpWithEmail(email, password) : signInWithEmail(email, password));
  }

  function switchMode() {
    setError(null);
    setMode((current) => current === "sign-in" ? "sign-up" : "sign-in");
  }

  return (
    <details className="relative">
      <summary className="inline-flex min-h-11 w-full cursor-pointer list-none items-center gap-2 rounded-md bg-white/10 px-3 text-xs font-medium text-sidebar-foreground outline-none transition hover:bg-white/15 focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-sidebar">
        <LogIn className="h-4 w-4" aria-hidden="true" /> Sign in
      </summary>
      <div className="absolute bottom-full left-0 z-50 mb-2 w-72 rounded-md border border-sidebar-border bg-sidebar p-3 text-sidebar-foreground shadow-lg">
        <form className="grid gap-2" onSubmit={submit}>
          <p className="text-sm font-medium">{signingUp ? "Create your account" : "Sign in to your account"}</p>
          <label className="grid gap-1 text-xs font-medium" htmlFor="auth-email">Email<Input id="auth-email" name="email" type="email" autoComplete="email" required aria-invalid={Boolean(error)} aria-describedby={error ? "auth-error" : undefined}/></label>
          <label className="grid gap-1 text-xs font-medium" htmlFor="auth-password">Password<Input id="auth-password" name="password" type="password" autoComplete={signingUp ? "new-password" : "current-password"} required minLength={6} aria-invalid={Boolean(error)} aria-describedby={error ? "auth-error" : undefined}/></label>
          {error && <p id="auth-error" className="text-xs text-destructive" role="alert">{error}</p>}
          <Button type="submit" size="sm" disabled={pending}>{signingUp ? "Create account" : "Sign in with email"}</Button>
          {!signingUp && <Button type="button" size="sm" variant="secondary" disabled={pending} onClick={() => run(signInWithGoogle)}>
            Sign in with Google
          </Button>}
          <Button type="button" size="sm" variant="ghost" className="text-sidebar-foreground hover:bg-white/10 hover:text-sidebar-foreground" disabled={pending} onClick={switchMode}>
            {signingUp ? <LogIn className="h-4 w-4" aria-hidden="true" /> : <UserPlus className="h-4 w-4" aria-hidden="true" />}
            {signingUp ? "Already have an account? Sign in" : "Need an account? Sign up"}
          </Button>
        </form>
      </div>
    </details>
  );
}
