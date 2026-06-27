"use client";

import { LogIn, LogOut } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useFirebaseAuth } from "@/components/providers/firebase-auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form-controls";

export function AuthControls() {
  const { configured, loading, user, signInWithEmail, signInWithGoogle, signOut } = useFirebaseAuth();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

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

  if (!configured || loading) {
    return <span className="text-xs text-muted-foreground">{loading ? "Checking sign-in…" : "Auth unavailable"}</span>;
  }

  if (user) {
    return (
      <div className="flex items-center gap-2">
        <span className="hidden max-w-48 truncate text-xs text-muted-foreground sm:block">
          {user.email ?? user.displayName ?? "Signed in"}
        </span>
        <Button size="sm" variant="secondary" disabled={pending} onClick={() => run(signOut)}>
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Sign out
        </Button>
      </div>
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    await run(() => signInWithEmail(String(data.get("email")), String(data.get("password"))));
  }

  return (
    <details className="relative">
      <summary className="inline-flex h-8 cursor-pointer list-none items-center gap-2 rounded-md bg-secondary px-3 text-xs font-medium">
        <LogIn className="h-4 w-4" aria-hidden="true" /> Sign in
      </summary>
      <div className="absolute right-0 top-10 z-50 w-72 rounded-md border bg-white p-3 shadow-lg">
        <form className="grid gap-2" onSubmit={submit}>
          <Input name="email" type="email" autoComplete="email" placeholder="Email" required />
          <Input name="password" type="password" autoComplete="current-password" placeholder="Password" required />
          {error && <p className="text-xs text-destructive" role="alert">{error}</p>}
          <Button type="submit" size="sm" disabled={pending}>Sign in with email</Button>
          <Button type="button" size="sm" variant="secondary" disabled={pending} onClick={() => run(signInWithGoogle)}>
            Sign in with Google
          </Button>
        </form>
      </div>
    </details>
  );
}
