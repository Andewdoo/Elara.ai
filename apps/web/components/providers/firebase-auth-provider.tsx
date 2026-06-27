"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { onAuthStateChanged, type User } from "firebase/auth";

import {
  signInWithEmail as firebaseEmailSignIn,
  signInWithGoogle as firebaseGoogleSignIn,
  signOut as firebaseSignOut,
} from "@/lib/auth";
import { getFirebaseAuth, hasPublicFirebaseConfig } from "@/lib/firebase";

type FirebaseAuthContextValue = {
  user: User | null;
  loading: boolean;
  configured: boolean;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
};

const FirebaseAuthContext = createContext<FirebaseAuthContextValue>({
  user: null,
  loading: true,
  configured: false,
  signInWithEmail: async () => undefined,
  signInWithGoogle: async () => undefined,
  signOut: async () => undefined,
});

export function FirebaseAuthProvider({ children }: { children: ReactNode }) {
  const configured = hasPublicFirebaseConfig();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(configured);

  useEffect(() => {
    if (!configured) {
      return;
    }

    const auth = getFirebaseAuth();
    if (!auth) {
      return;
    }

    return onAuthStateChanged(auth, (nextUser) => {
      setUser(nextUser);
      setLoading(false);
    });
  }, [configured]);

  const value = useMemo(
    () => ({
      user,
      loading,
      configured,
      signInWithEmail: async (email: string, password: string) => {
        await firebaseEmailSignIn(email, password);
      },
      signInWithGoogle: async () => {
        await firebaseGoogleSignIn();
      },
      signOut: firebaseSignOut,
    }),
    [configured, loading, user],
  );

  return (
    <FirebaseAuthContext.Provider value={value}>
      {children}
    </FirebaseAuthContext.Provider>
  );
}

export function useFirebaseAuth() {
  return useContext(FirebaseAuthContext);
}
