import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MusicForm } from "./MusicForm";
import { VideoServerForm } from "./VideoServerForm";

describe("MusicForm", () => {
  it("shows 'saved' placeholder and sends blank password to keep it", async () => {
    const onSave = vi.fn().mockResolvedValue({ ok: true });
    render(<MusicForm initial={{ url: "https://m", username: "bb" }} passwordSet
      onTest={vi.fn()} onSave={onSave} />);
    expect(screen.getByPlaceholderText(/saved — leave blank to keep/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(
      { url: "https://m", username: "bb", password: "" }));
  });

  it("renders a test failure", async () => {
    const onTest = vi.fn().mockResolvedValue({ ok: false, error: "401 bad creds" });
    render(<MusicForm initial={{ url: "https://m", username: "bb" }} passwordSet={false}
      onTest={onTest} onSave={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /test/i }));
    expect(await screen.findByText(/401 bad creds/)).toBeTruthy();
  });

  it("renders a save failure and accepts extra fields in initial", async () => {
    const onSave = vi.fn().mockResolvedValue({ ok: false, error: "nope" });
    const initial = { url: "https://m", username: "bb", configured: true };
    render(<MusicForm initial={initial} passwordSet onTest={vi.fn()} onSave={onSave}
      saveLabel="Apply" />);
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    expect(await screen.findByText(/nope/)).toBeTruthy();
  });
});

describe("MusicForm strict", () => {
  const setUp = (passwordSet: boolean) => {
    render(<MusicForm strict initial={{ url: "", username: "" }} passwordSet={passwordSet}
      onTest={vi.fn()} onSave={vi.fn()} />);
    const save = screen.getByRole("button", { name: /save/i }) as HTMLButtonElement;
    const test = screen.getByRole("button", { name: /^test$/i }) as HTMLButtonElement;
    const set = (label: string, value: string) =>
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    return { save, test, set };
  };

  it("requires an http(s) URL, a username and a password", () => {
    const { save, test, set } = setUp(false);
    set("Server URL", "m.local:4533");
    set("Username", "bb");
    set("Password", "pw");
    expect(save.disabled).toBe(true);
    expect(test.disabled).toBe(true);
    set("Server URL", "http://m.local:4533");
    expect(save.disabled).toBe(false);
    expect(test.disabled).toBe(false);
    set("Password", "");
    expect(save.disabled).toBe(true);
    set("Password", "pw");
    set("Username", "  ");
    expect(save.disabled).toBe(true);
  });

  it("accepts a blank password when one is stored", () => {
    const { save, set } = setUp(true);
    set("Server URL", "https://m");
    set("Username", "bb");
    expect(save.disabled).toBe(false);
  });

  it("is lenient without strict (wizard behaviour)", () => {
    render(<MusicForm initial={{ url: "m.local", username: "bb" }} passwordSet={false}
      onTest={vi.fn()} onSave={vi.fn()} />);
    expect((screen.getByRole("button", { name: /save/i }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("VideoServerForm", () => {
  it("requires an http(s) base for remote mode", () => {
    render(<VideoServerForm initial={{ mode: "remote", base: "ftp://x" }} keySet
      onSave={vi.fn()} />);
    expect((screen.getByRole("button", { name: /save/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("sends blank api_key to keep the stored key", async () => {
    const onSave = vi.fn().mockResolvedValue({ ok: true });
    render(<VideoServerForm initial={{ mode: "remote", base: "https://v" }} keySet
      onSave={onSave} />);
    expect(screen.getByPlaceholderText(/saved — leave blank to keep/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(
      { mode: "remote", base: "https://v", api_key: "" }));
  });

  it("shows the server's error and a Test result when onTest is given", async () => {
    const onSave = vi.fn().mockResolvedValue({ ok: false, error: "unreachable", can_force: true });
    const onTest = vi.fn().mockResolvedValue({ ok: true, server_name: "Den" });
    render(<VideoServerForm initial={{ mode: "remote", base: "https://v" }} keySet={false}
      onTest={onTest} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: /^test$/i }));
    expect(await screen.findByText(/Connected to Den/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(await screen.findByText(/unreachable/)).toBeTruthy();
  });

  it("hides the Test button without onTest", () => {
    render(<VideoServerForm initial={{ mode: "builtin", base: "" }} keySet={false}
      onSave={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /^test$/i })).toBeNull();
  });
});
