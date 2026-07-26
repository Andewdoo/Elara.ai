"use client";

import {
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  getIdToken,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  type User,
} from "firebase/auth";

import { getFirebaseAuth, type PublicFirebaseConfig } from "@/lib/firebase";

export const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

function requireFirebaseAuth(config: PublicFirebaseConfig) {
  const auth = getFirebaseAuth(config);
  if (!auth) {
    throw new Error("Firebase Web configuration is missing.");
  }
  return auth;
}

export async function apiErrorMessage(response: Response) {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (typeof body?.detail === "string") {
    return body.detail;
  }
  if (Array.isArray(body?.detail)) {
    const messages = body.detail
      .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : null))
      .filter((message): message is string => Boolean(message));
    if (messages.length) {
      return messages.join(" ");
    }
  }
  return `Request failed with status ${response.status}.`;
}

export async function createApiSession(user: User) {
  const idToken = await getIdToken(user, true);
  const response = await fetch(`${apiBaseUrl}/v1/auth/session`, {
    method: "POST",
    headers: { Authorization: `Bearer ${idToken}` },
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(await apiErrorMessage(response));
  }
}

export async function clearApiSession() {
  const response = await fetch(`${apiBaseUrl}/v1/auth/session`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(await apiErrorMessage(response));
  }
}

async function rollbackFailedSignIn(config: PublicFirebaseConfig) {
  try {
    await clearApiSession();
  } catch {
    // Preserve the original sign-in/session error while still clearing local Firebase state.
  } finally {
    await firebaseSignOut(requireFirebaseAuth(config));
  }
}

export async function signInWithEmail(config: PublicFirebaseConfig, email: string, password: string) {
  const credential = await signInWithEmailAndPassword(requireFirebaseAuth(config), email, password);
  try {
    await createApiSession(credential.user);
  } catch (error) {
    await rollbackFailedSignIn(config);
    throw error;
  }
  return credential.user;
}

export async function signUpWithEmail(config: PublicFirebaseConfig, email: string, password: string) {
  const credential = await createUserWithEmailAndPassword(requireFirebaseAuth(config), email, password);
  try {
    await createApiSession(credential.user);
  } catch (error) {
    await rollbackFailedSignIn(config);
    throw error;
  }
  return credential.user;
}

export async function signInWithGoogle(config: PublicFirebaseConfig) {
  const credential = await signInWithPopup(requireFirebaseAuth(config), new GoogleAuthProvider());
  try {
    await createApiSession(credential.user);
  } catch (error) {
    await rollbackFailedSignIn(config);
    throw error;
  }
  return credential.user;
}

export async function signOut(config: PublicFirebaseConfig) {
  const auth = requireFirebaseAuth(config);
  try {
    await clearApiSession();
  } finally {
    await firebaseSignOut(auth);
  }
}

export async function authenticatedApiFetch(user: User, path: string, init: RequestInit = {}) {
  const token = await getIdToken(user);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${apiBaseUrl}${path}`, { ...init, headers });
}
