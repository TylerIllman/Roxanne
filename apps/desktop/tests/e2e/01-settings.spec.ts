import { test, expect } from "./fixtures";

test.describe("Settings panel — provider toggle + Unmute personas", () => {
  test("Speech tab shows Unmute persona list when provider is set", async ({ page }) => {
    // Open Settings, switch to Speech tab.
    await page.getByRole("button", { name: "Settings" }).click();
    await page.getByRole("button", { name: "Speech", exact: true }).click();

    // Provider toggle should default to Unmute (the fixture writes
    // tts_provider: "unmute" to config.json).
    const unmuteToggle = page.getByRole("button", { name: "Unmute (remote)" });
    await expect(unmuteToggle).toBeVisible();
    await expect(unmuteToggle).toHaveClass(/bg-white/);

    // Persona list should populate from the live Unmute server.
    // Use a long timeout — first fetch can take a few seconds.
    const personaItem = page.locator('div:has-text("Watercooler")').first();
    await expect(personaItem).toBeVisible({ timeout: 15_000 });

    // Investor Assistant (Anuba pitch persona) should be present.
    await expect(page.locator('div:has-text("Investor Assistant")').first()).toBeVisible();

    // Switching to Piper should re-render the Piper voice list.
    await page.getByRole("button", { name: "Piper (local)" }).click();
    // Default Piper voice present.
    const amyEntry = page.locator('div:has-text("en_US-amy-medium")').first();
    await expect(amyEntry).toBeVisible({ timeout: 5_000 });

    // Flip back to Unmute and pick Investor Assistant.
    await page.getByRole("button", { name: "Unmute (remote)" }).click();
    await page.locator('div:has-text("Investor Assistant")').first().click();

    // The picked persona should show the "Active" badge.
    await expect(
      page.locator('div:has-text("Investor Assistant")').first().getByText("Active"),
    ).toBeVisible({ timeout: 5_000 });
  });
});
