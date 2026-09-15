"use client";

/**
 * The sign-in form, used twice: on the login page, and inside the dialog that
 * appears when a session expires under someone. Sharing it is why re-auth
 * behaves identically to a fresh sign-in, including lockout messages.
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Field } from "@/components/ui/Field";
import { useSession } from "@/features/auth/session";
import { auth, type SessionResponse } from "@/lib/api";
import { fieldErrors } from "@/lib/form";

const FIELDS = ["email", "password"] as const;

export function SignInForm({
  submitLabel = "Sign in",
  lockEmail,
  onSignedIn,
}: {
  submitLabel?: string;
  /** Re-auth knows who it is asking for; the login page does not. */
  lockEmail?: string;
  onSignedIn?: (user: SessionResponse) => void;
}) {
  const { client, signedIn } = useSession();
  const [email, setEmail] = useState(lockEmail ?? "");
  const [password, setPassword] = useState("");

  const signIn = useMutation({
    mutationFn: () => auth.login(client, email, password),
    onSuccess: (user) => {
      setPassword("");
      signedIn(user);
      onSignedIn?.(user);
    },
  });

  const problems = fieldErrors(signIn.error, FIELDS);

  return (
    <form
      className="form"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        signIn.mutate();
      }}
    >
      <Field id="email" label="Email" error={problems.for("email")}>
        {(props) => (
          <input
            {...props}
            type="email"
            name="email"
            autoComplete="username"
            value={email}
            readOnly={Boolean(lockEmail)}
            required
            onChange={(event) => setEmail(event.target.value)}
          />
        )}
      </Field>

      <Field id="password" label="Password" error={problems.for("password")}>
        {(props) => (
          <input
            {...props}
            type="password"
            name="password"
            autoComplete="current-password"
            value={password}
            required
            onChange={(event) => setPassword(event.target.value)}
          />
        )}
      </Field>

      {problems.unattached.length > 0 ? (
        <div className="form__error" role="alert">
          {problems.unattached.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      ) : null}

      <button type="submit" className="button button--primary" disabled={signIn.isPending}>
        {signIn.isPending ? "Signing in…" : submitLabel}
      </button>
    </form>
  );
}
