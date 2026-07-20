"use client";

import { getApp, getApps, initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

export type PublicFirebaseConfig = {
  apiKey: string | undefined;
  authDomain: string | undefined;
  projectId: string | undefined;
  appId: string | undefined;
};

export function hasPublicFirebaseConfig(config: PublicFirebaseConfig) {
  return Boolean(config.apiKey && config.authDomain && config.projectId && config.appId);
}

export function getFirebaseApp(config: PublicFirebaseConfig): FirebaseApp | null {
  if (!hasPublicFirebaseConfig(config)) {
    return null;
  }

  return getApps().length ? getApp() : initializeApp(config);
}

export function getFirebaseAuth(config: PublicFirebaseConfig): Auth | null {
  const app = getFirebaseApp(config);
  return app ? getAuth(app) : null;
}
