import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/errors";
import { fieldErrors } from "@/lib/form";

function invalid(errors: { path: string; message: string }[]): ApiError {
  return new ApiError({
    status: 400,
    code: "request.invalid",
    message: "The request could not be understood.",
    details: { errors },
  });
}

describe("mapping a failure onto a form", () => {
  it("puts each message on the field that caused it", () => {
    const problems = fieldErrors(
      invalid([{ path: "email", message: "not an email address" }]),
      ["email", "password"],
    );
    expect(problems.for("email")).toBe("not an email address");
    expect(problems.for("password")).toBeUndefined();
  });

  it("strips the body prefix FastAPI puts on request-validation paths", () => {
    const problems = fieldErrors(
      invalid([{ path: "body.new_password", message: "too short" }]),
      ["new_password"],
    );
    expect(problems.for("new_password")).toBe("too short");
  });

  it("keeps a problem naming a field this form does not render, rather than losing it", () => {
    // Silently dropping it would leave the user with a form that refuses to
    // submit and says nothing.
    const problems = fieldErrors(invalid([{ path: "values.sample_id", message: "unknown" }]), [
      "email",
    ]);
    expect(problems.unattached).toEqual(["values.sample_id: unknown"]);
  });

  it("falls back to the message when the failure named no field at all", () => {
    const problems = fieldErrors(
      new ApiError({
        status: 401,
        code: "auth.failed",
        message: "Incorrect email or password.",
      }),
      ["email", "password"],
    );
    expect(problems.unattached).toEqual(["Incorrect email or password."]);
  });

  it("reports nothing for a failure that is not from the API", () => {
    const problems = fieldErrors(new Error("boom"), ["email"]);
    expect(problems.any).toBe(false);
  });
});
