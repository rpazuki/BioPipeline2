"use client";

/**
 * What happens when a session expires while somebody is working.
 *
 * Not a redirect. The page underneath keeps its state — a half-written
 * pipeline document, a submission form with thirty values in it — and the user
 * signs in over the top of it and carries on. Sessions here last a week and
 * tasks run for a day, so this fires rarely and always at the worst moment.
 */

import { Dialog } from "@/components/ui/Dialog";
import { SignInForm } from "@/features/auth/SignInForm";
import { useSession } from "@/features/auth/session";

export function ReauthDialog() {
  const { expired, user, signOut } = useSession();

  return (
    <Dialog open={expired} title="Your session has expired" dismissable={false}>
      <p>Sign in again to carry on. Nothing on this page has been lost.</p>
      <SignInForm submitLabel="Continue" lockEmail={user?.email} />
      <button type="button" className="button button--quiet" onClick={() => void signOut()}>
        Sign out instead
      </button>
    </Dialog>
  );
}
