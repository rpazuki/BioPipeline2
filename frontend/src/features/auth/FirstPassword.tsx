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
  const [done, setDone] = useState(false);

  const change = useMutation({
    mutationFn: () => auth.changePassword(client, current, replacement),
    onSuccess: () => setDone(true),
  });

  if (done) {
    return (
      <div className="login">
        <h1>Password changed</h1>
        <p className="muted">
          Every session that password opened has ended, including this one. Sign in again with
          the one you just chose.
        </p>
        <button type="button" className="button button--primary" onClick={() => void signOut()}>
          Sign in again
        </button>
      </div>
    );
  }

  return (
    <form
      className="login"
      onSubmit={(event) => {
        event.preventDefault();
        change.mutate();
      }}
    >
      <h1>Choose your own password</h1>
      <p className="muted">
        This account is still using the password it was created with, which means somebody else
        knows it. Nothing else can be done with {user?.email} until it is replaced.
      </p>
      <Field id="current" label="The password you were given">
        {(props) => (
          <input
            {...props}
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        )}
      </Field>
      <Field id="replacement" label="Your new password" hint="At least 12 characters.">
        {(props) => (
          <input
            {...props}
            type="password"
            autoComplete="new-password"
            value={replacement}
            onChange={(event) => setReplacement(event.target.value)}
          />
        )}
      </Field>
      {change.isError ? <Failure error={change.error} /> : null}
      <button
        type="submit"
        className="button button--primary"
        disabled={change.isPending || replacement.length < 12}
      >
        {change.isPending ? "Changing…" : "Change it"}
      </button>
    </form>
  );
}
