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
  signUpWithEmail as firebaseEmailSignUp,
  signOut as firebaseSignOut,
} from "@/lib/auth";
import { getFirebaseAuth, hasPublicFirebaseConfig, type PublicFirebaseConfig } from "@/lib/firebase";

type FirebaseAuthContextValue = {
  user: User | null;
  loading: boolean;
  configured: boolean;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signUpWithEmail: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
};

const FirebaseAuthContext = createContext<FirebaseAuthContextValue>({
  user: null,
  loading: true,
  configured: false,
  signInWithEmail: async () => undefined,
  signUpWithEmail: async () => undefined,
  signInWithGoogle: async () => undefined,
  signOut: async () => undefined,
});

export function FirebaseAuthProvider({ children, publicFirebaseConfig }: { children: ReactNode; publicFirebaseConfig: PublicFirebaseConfig }) {
  const configured = hasPublicFirebaseConfig(publicFirebaseConfig);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(configured);

  useEffect(() => {
    if (!configured) {
      return;
    }

    const auth = getFirebaseAuth(publicFirebaseConfig);
    if (!auth) {
      return;
    }

    return onAuthStateChanged(auth, (nextUser) => {
      setUser(nextUser);
      setLoading(false);
    });
  }, [configured, publicFirebaseConfig]);

  const value = useMemo(
    () => ({
      user,
      loading,
      configured,
      signInWithEmail: async (email: string, password: string) => {
        await firebaseEmailSignIn(publicFirebaseConfig, email, password);
      },
      signUpWithEmail: async (email: string, password: string) => {
        await firebaseEmailSignUp(publicFirebaseConfig, email, password);
      },
      signInWithGoogle: async () => {
        await firebaseGoogleSignIn(publicFirebaseConfig);
      },
      signOut: () => firebaseSignOut(publicFirebaseConfig),
    }),
    [configured, loading, publicFirebaseConfig, user],
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
