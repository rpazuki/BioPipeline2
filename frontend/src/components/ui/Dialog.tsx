"use client";

/**
 * A modal that behaves like one.
 *
 * Built on `<dialog showModal()>` so the browser supplies the focus trap, the
 * inert background and the Escape handling rather than three hand-rolled
 * effects that each miss a case. `dismissable: false` is for the re-auth
 * dialog, where there is nothing behind it the user can usefully do.
 */

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

export function Dialog({
  open,
  title,
  onClose,
  dismissable = true,
  children,
}: {
  open: boolean;
  title: string;
  onClose?: () => void;
  dismissable?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-label={title}
      onCancel={(event) => {
        if (!dismissable) {
          event.preventDefault();
          return;
        }
        onClose?.();
      }}
      onClose={() => {
        if (dismissable) onClose?.();
      }}
    >
      {/*
        Rendered only while open. A closed `<dialog>` is hidden by the user
        agent stylesheet, so leaving the content mounted looks identical in a
        browser — and is a trap everywhere else: the content stays in the
        accessibility tree for anything that ignores that stylesheet, and any
        form inside it keeps whatever was typed the last time the dialog was
        open.
      */}
      {open ? (
        <div className="dialog__body">
          <h2 className="dialog__title">{title}</h2>
          {children}
        </div>
      ) : null}
    </dialog>
  );
}
