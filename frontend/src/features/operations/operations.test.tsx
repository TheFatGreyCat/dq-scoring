import { render, screen } from "@testing-library/react";
import { I18nProvider } from "../../lib/i18n";
import "../../lib/surfaceTranslations";
import { AdapterPanel } from "./AdapterPanel";
import type { AdapterObservation } from "./operationsApi";

const base: AdapterObservation = { name: "advisory_gateway", state: "off", source: "configuration", checked_at: null, last_success_at: null, stale: false, timeout_seconds: null };

describe("adapter observations", () => {
  it("distinguishes off, unknown and stale without inferring health", () => {
    localStorage.setItem("dq_language", "en");
    render(<I18nProvider><AdapterPanel adapters={[
      base,
      { ...base, name: "spark_compute", state: "unknown", source: "worker_heartbeat", stale: true, checked_at: "2026-10-07T10:00:00Z" },
    ]} /></I18nProvider>);
    expect(screen.getByText("Off")).toBeInTheDocument();
    expect(screen.getByText(/Unknown · Stale/)).toBeInTheDocument();
    expect(screen.queryByText("Up")).not.toBeInTheDocument();
    expect(screen.queryByText("Down")).not.toBeInTheDocument();
  });
});
