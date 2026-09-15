import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DeliveryStatusBadge,
  RunStatusBadge,
  TaskStatusBadge,
} from "@/components/ui/StatusBadge";
import type { DeliveryStatus, RunStatus, TaskStatus } from "@/lib/api";

const RUN: RunStatus[] = [
  "queued",
  "running",
  "blocked",
  "cancel_requested",
  "succeeded",
  "failed",
  "cancelled",
];

const TASK: TaskStatus[] = [
  "created",
  "queued",
  "claimed",
  "running",
  "retry_wait",
  "succeeded",
  "failed",
  "cancelled",
  "skipped",
];

const DELIVERY: DeliveryStatus[] = ["pending", "delivered", "failed", "skipped"];

describe("every status has a tone", () => {
  it.each(RUN)("run: %s", (status) => {
    const { container } = render(<RunStatusBadge status={status} />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).not.toContain("badge--undefined");
  });

  it.each(TASK)("task: %s", (status) => {
    const { container } = render(<TaskStatusBadge status={status} />);
    expect(container.querySelector(".badge")?.className).not.toContain("badge--undefined");
  });

  it.each(DELIVERY)("delivery: %s", (status) => {
    const { container } = render(<DeliveryStatusBadge status={status} />);
    expect(container.querySelector(".badge")?.className).not.toContain("badge--undefined");
  });
});

describe("wording", () => {
  it("renders the machine value as something readable", () => {
    render(<RunStatusBadge status="cancel_requested" />);
    expect(screen.getByText("cancelling")).toBeInTheDocument();
  });

  it("keeps the raw value available for anything matching on it", () => {
    const { container } = render(<TaskStatusBadge status="retry_wait" />);
    expect(container.querySelector('[data-status="retry_wait"]')).toBeInTheDocument();
    expect(screen.getByText("waiting to retry")).toBeInTheDocument();
  });
});
