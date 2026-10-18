"use client";

/**
 * The screen an account created by an administrator lands on.
 *
 * Its password is one somebody else generated and read out, so the server
 * accepts exactly one request from this session: the one that replaces it.
 * Showing anything else would be showing a page whose every button returns a
 * 403 — the frame is here instead, in front of everything, saying why.
 *
 * Changing it ends this session, which is the point: whoever passed the
 * password on cannot go on using it.
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Field } from "@/components/ui/Field";
import { Failure } from "@/components/ui/states";
import { useApi, useSession } from "@/features/auth/session";
import { auth } from "@/lib/api";

export function FirstPassword() {
  const client = useApi();
  const { user, signOut } = useSession();
  const [current, setCurrent] = useState("");
  const [replacement, setReplacement] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const mismatch = confirmation.length > 0 && confirmation !== replacement;
  const canSubmit =
    current.length > 0 && replacement.length >= 12 && confirmation === replacement;
  const [done, setDone] = useState(false);

  const change = useMutation({
    mutationFn: () => auth.changePassword(client, current, replacement),
    onSuccess: () => setDone(true),
  });

  if (done) {
    return (
      <div className="login">
        <div className="login__card">
          <h1>Password changed</h1>
          <p className="muted">
            Every session that password opened has ended, including this one. Sign in again with
            the one you just chose.
          </p>
          <button
            type="button"
            className="button button--primary"
            onClick={() => void signOut()}
          >
            Sign in again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="login">
      <form
        className="login__card"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSubmit && !change.isPending) change.mutate();
        }}
      >
        <h1>Choose your own password</h1>
        <p className="muted">
          This account is still using the password it was created with, which means somebody
          else knows it. Nothing else can be done with {user?.email} until it is replaced.
        </p>
        <Field
          id="current"
          label="The password you were given"
          hint="Enter the temporary password you used to sign in."
        >
          {(props) => (
            <input
              {...props}
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          )}
        </Field>
        <Field id="replacement" label="Your new password">
          {(props) => (
            <input
              {...props}
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              aria-describedby="password-length"
              value={replacement}
              onChange={(event) => setReplacement(event.target.value)}
            />
          )}
        </Field>
        <Field
          id="confirmation"
          label="Confirm new password"
          error={mismatch ? "The two passwords do not match." : undefined}
        >
          {(props) => (
            <input
              {...props}
              type="password"
              autoComplete="new-password"
              required
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          )}
        </Field>
        {change.isError ? <Failure error={change.error} /> : null}
        <div className="password-form__actions">
          <p id="password-length" className="field__hint">
            At least 12 characters.
          </p>
          <button
            type="submit"
            className="button button--primary"
            disabled={change.isPending || !canSubmit}
          >
            {change.isPending ? "Changing…" : "Change it"}
          </button>
        </div>
      </form>
    </div>
  );
}
