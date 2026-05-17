import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { LibraryPanel } from "../LibraryPanel";
import * as api from "../libraryApi";
import { _resetForTests } from "../homeLibrary";

beforeEach(() => {
  _resetForTests();
  vi.spyOn(api, "getHealth").mockResolvedValue({
    service_version: "0.1", navidrome_reachable: true, cache_present: false,
    cache_mount: null, last_sync_ts: 0, syncing: false,
  });
  vi.spyOn(api, "getCacheStats").mockResolvedValue({
    present: false, mount_path: null, capacity: 0, free: 0,
    pinned_bytes: 0, streamed_bytes: 0, reserved: 0,
  });
  vi.spyOn(api, "getSource").mockResolvedValue({ url: "http://nav:4533", username: "u" });
  vi.spyOn(api, "putSource").mockResolvedValue({ ok: true });
  vi.spyOn(api, "testSource").mockResolvedValue({ ok: true });
  vi.spyOn(api, "runSync").mockResolvedValue(undefined);
});
afterEach(() => { vi.restoreAllMocks(); });

describe("LibraryPanel", () => {
  it("renders source form populated from GET /source (no password)", async () => {
    const { findByDisplayValue, queryByDisplayValue } = render(<LibraryPanel />);
    await findByDisplayValue("http://nav:4533");
    await findByDisplayValue("u");
    // Password field is empty (never echoed back)
    expect(queryByDisplayValue(/secret/i)).toBeNull();
  });

  it("Save calls putSource with form values", async () => {
    const { findByText, container } = render(<LibraryPanel />);
    await findByText(/Save/i);
    const url = container.querySelector('input[type="url"]') as HTMLInputElement;
    const user = container.querySelector('input[name="username"]') as HTMLInputElement;
    const pw = container.querySelector('input[type="password"]') as HTMLInputElement;
    fireEvent.change(url, { target: { value: "http://nav:4533" } });
    fireEvent.change(user, { target: { value: "u" } });
    fireEvent.change(pw, { target: { value: "p" } });
    fireEvent.click(await findByText(/Save/i));
    await waitFor(() => expect(api.putSource).toHaveBeenCalledWith({
      url: "http://nav:4533", username: "u", password: "p",
    }));
  });

  it("Test button surfaces backend error", async () => {
    (api.testSource as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false, error: "auth: wrong password",
    });
    const { findByText, getByText } = render(<LibraryPanel />);
    fireEvent.click(await findByText(/Test/i));
    await waitFor(() => getByText(/wrong password/i));
  });

  it("Sync now calls runSync", async () => {
    const { findByText } = render(<LibraryPanel />);
    fireEvent.click(await findByText(/Sync now/i));
    await waitFor(() => expect(api.runSync).toHaveBeenCalled());
  });
});
