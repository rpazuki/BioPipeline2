import "@testing-library/jest-dom/vitest";

/**
 * jsdom does not implement `<dialog>`'s modal methods, and every dialog in
 * this app relies on the browser for its focus trap. Stubbing them keeps the
 * component tests honest about *what* is rendered without pretending to test
 * modality, which only a real browser can exercise — that is Playwright's job.
 */
if (typeof HTMLDialogElement !== "undefined") {
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.open = false;
    this.dispatchEvent(new Event("close"));
  };
}

if (!globalThis.crypto?.randomUUID) {
  Object.defineProperty(globalThis, "crypto", {
    value: { ...globalThis.crypto, randomUUID: () => "00000000-0000-4000-8000-000000000000" },
  });
}
