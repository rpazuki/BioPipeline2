"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { SignInForm } from "@/features/auth/SignInForm";
import { useSession } from "@/features/auth/session";

export function LoginScreen() {
  const router = useRouter();
  const { status, config } = useSession();

  useEffect(() => {
    if (status === "authenticated") router.replace("/runs");
  }, [status, router]);

  return (
    <main className="login">
      <div className="login__card">
        <h1>{config.app_name}</h1>
        {config.environment !== "production" ? (
          <p className="environment-tag">{config.environment}</p>
        ) : null}
        <SignInForm onSignedIn={() => router.replace("/runs")} />
      </div>
    </main>
  );
}
