import { test, expect } from "./fixtures";

test.describe("Voice button — dispatches to Unmute and opens WebSocket", () => {
  test("clicking Voice chat with provider=unmute opens a realtime WebSocket session", async ({
    page,
  }) => {
    // Watch console + WebSocket frames before we click.
    const consoleLogs: string[] = [];
    page.on("console", (msg) => {
      const txt = msg.text();
      if (
        txt.includes("[unmute-voice]") ||
        txt.includes("[voice-button]") ||
        txt.toLowerCase().includes("error")
      ) {
        consoleLogs.push(`${msg.type()}: ${txt}`);
      }
    });

    const wsFramesSent: string[] = [];
    const wsFramesReceived: string[] = [];
    page.on("websocket", (ws) => {
      if (!ws.url().includes("/v1/realtime")) return;
      ws.on("framesent", (f) => {
        if (typeof f.payload === "string") wsFramesSent.push(f.payload);
      });
      ws.on("framereceived", (f) => {
        if (typeof f.payload === "string") wsFramesReceived.push(f.payload);
      });
    });

    // Click Voice chat — fixture's config.json already has tts_provider=unmute.
    await page.getByRole("button", { name: /Voice chat/i }).click();

    // Status messages render into the chat.
    await expect(page.getByText(/Starting voice \(provider: unmute\)/)).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/Connecting to Unmute/)).toBeVisible({ timeout: 10_000 });

    // session.update should be sent and session.updated received.
    await expect
      .poll(() => wsFramesSent.find((f) => f.includes('"session.update"')), { timeout: 15_000 })
      .toBeTruthy();
    await expect
      .poll(() => wsFramesReceived.find((f) => f.includes('"session.updated"')), { timeout: 15_000 })
      .toBeTruthy();

    // Voice mode UI flips to the listening state.
    await expect(page.getByRole("button", { name: /Listening|Say "Roxanne"/ })).toBeVisible({
      timeout: 10_000,
    });

    // Verify the session.update payload included the persona's instructions and voice.
    const sessionUpdate = wsFramesSent.find((f) => f.includes('"session.update"'));
    expect(sessionUpdate).toBeDefined();
    const parsed = JSON.parse(sessionUpdate!);
    expect(parsed.session).toMatchObject({
      voice: expect.any(String),
      allow_recording: false,
    });
    expect(parsed.session.voice.length).toBeGreaterThan(0);
    expect(parsed.session.instructions).toBeTruthy();

    // Surface diagnostics for triage if any later assertion misses.
    if (process.env.E2E_VERBOSE) {
      console.log("Sent frames:", wsFramesSent.length);
      console.log("Received frames:", wsFramesReceived.length);
      console.log("Console logs:", consoleLogs);
    }

    // Click the button again to close the session cleanly.
    await page.getByRole("button", { name: /Listening|Say "Roxanne"/ }).click();
    await expect(page.getByRole("button", { name: /Voice chat/i })).toBeVisible({ timeout: 5_000 });
  });
});
