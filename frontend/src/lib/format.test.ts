import { describe, expect, it } from "vitest";

import { formatBytes, formatDuration, formatTimestamp, shortId } from "@/lib/format";

describe("timestamps", () => {
  it("name their zone, because a run submitted elsewhere is ordinary here", () => {
    expect(formatTimestamp("2026-03-01T14:03:00Z")).toMatch(/\(.+\)$/);
  });

  it("render a missing time as a dash rather than Invalid Date", () => {
    expect(formatTimestamp(null)).toBe("—");
    expect(formatTimestamp("not a date")).toBe("—");
  });
});

describe("durations", () => {
  it("scale to the work, which here runs from seconds to days", () => {
    const start = "2026-03-01T00:00:00Z";
    expect(formatDuration(start, "2026-03-01T00:00:42Z")).toBe("42s");
    expect(formatDuration(start, "2026-03-01T00:07:30Z")).toBe("7m 30s");
    expect(formatDuration(start, "2026-03-01T05:20:00Z")).toBe("5h 20m");
    expect(formatDuration(start, "2026-03-02T06:00:00Z")).toBe("1d 6h");
  });

  it("measure an unfinished run against now rather than showing nothing", () => {
    const started = new Date(Date.now() - 90_000).toISOString();
    expect(formatDuration(started, null)).toMatch(/^1m/);
  });

  it("show a dash for a run that has not started", () => {
    expect(formatDuration(null, null)).toBe("—");
  });
});

describe("sizes", () => {
  it("stay readable across the range a genomics output spans", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 kB");
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
    expect(formatBytes(null)).toBe("—");
  });
});

describe("identifiers", () => {
  it("abbreviate for a table cell", () => {
    expect(shortId("0189ab34-0000-4000-8000-000000000000")).toBe("0189ab34");
  });
});
