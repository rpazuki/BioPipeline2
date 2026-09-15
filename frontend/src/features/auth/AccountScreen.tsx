"use client";

/**
 * The account page.
 *
 * Changing a password signs every session out, including this one — that is
 * the backend's behaviour and the reason it is worth saying so before the
 * button is pressed rather than after the screen empties.
 */

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field } from "@/components/ui/Field";
import { useSession } from "@/features/auth/session";
import { auth } from "@/lib/api";
import { fieldErrors } from "@/lib/form";

const FIELDS = ["current_password", "new_password"] as const;

export function AccountScreen() {
  const router = useRouter();
  const { client, user, signOut } = useSession();
  const [current, setCurrent] = useState("");
  const [replacement, setReplacement] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const mismatch = confirmation.length > 0 && confirmation !== replacement;

  const change = useMutation({
    mutationFn: () => auth.changePassword(client, current, replacement),
    onSuccess: async () => {
      await signOut();
      router.replace("/login");
    },
  });

  const problems = fieldErrors(change.error, FIELDS);

  return (
    <div className="stack">
      <header className="page-header">
        <h1>Account</h1>
      </header>

      <section className="panel">
        <dl className="detail-list">
          <dt>Name</dt>
          <dd>{user?.display_name}</dd>
          <dt>Email</dt>
          <dd>{user?.email}</dd>
          <dt>Role</dt>
          <dd>{user?.role}</dd>
        </dl>
      </section>

      <section className="panel">
        <h2>Change password</h2>
        <p className="muted">
          This signs out every session, including this one. You will be asked to sign in again.
        </p>
        <form
          className="form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!mismatch) change.mutate();
          }}
        >
          <Field
            id="current_password"
            label="Current password"
            error={problems.for("current_password")}
          >
            {(props) => (
              <input
                {...props}
                type="password"
                autoComplete="current-password"
                value={current}
                required
                onChange={(event) => setCurrent(event.target.value)}
              />
            )}
          </Field>

          <Field
            id="new_password"
            label="New password"
            hint="At least 12 characters."
            error={problems.for("new_password")}
          >
            {(props) => (
              <input
                {...props}
                type="password"
                autoComplete="new-password"
                minLength={12}
                value={replacement}
                required
                onChange={(event) => setReplacement(event.target.value)}
              />
            )}
          </Field>

          <Field
            id="confirm_password"
            label="Repeat new password"
            error={mismatch ? "The two passwords do not match." : undefined}
          >
            {(props) => (
              <input
                {...props}
                type="password"
                autoComplete="new-password"
                value={confirmation}
                required
                onChange={(event) => setConfirmation(event.target.value)}
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

          <button
            type="submit"
            className="button button--primary"
            disabled={change.isPending || mismatch}
          >
            {change.isPending ? "Changing…" : "Change password"}
          </button>
        </form>
      </section>
    </div>
  );
}
