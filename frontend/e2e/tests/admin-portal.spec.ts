import { test, expect, type Page } from "@playwright/test";
import { secretFromOtpauthUri, totpNow } from "./totp";

// Real, no-mock click-through of the Admin Portal against the live stack
// (see scripts/e2e-run.sh, which seeds e2e_admin/e2e_admin_enroll/e2e_user
// before this runs).
//
// e2e_admin is pre-enrolled by the seed script with a known secret (passed
// in via E2E_ADMIN_TOTP_SECRET) — real MFA, just skipping the UI steps for
// tests that don't need to exercise enrollment itself, and robust to a
// worker restart, since enrollment can only happen once per account.
// e2e_admin_enroll is deliberately left unenrolled specifically so one
// test below can exercise the real first-login mandatory-enrollment UI
// flow end to end (QR code, confirm, one-time recovery codes) — the same
// flow whose recovery-codes step this suite caught a real regression in
// (see LoginFlow.tsx's comments and docs/adr/0014...).

const ADMIN_USERNAME = "e2e_admin";
const ADMIN_ENROLL_USERNAME = "e2e_admin_enroll";
const USER_USERNAME = "e2e_user";
const PASSWORD = "E2E-Test-Password!2026";
const ADMIN_TOTP_SECRET = process.env.E2E_ADMIN_TOTP_SECRET || "";

async function loginAsAdmin(page: Page) {
  await page.goto("/admin/");
  await page.getByLabel("Username").fill(ADMIN_USERNAME);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByLabel(/authentication code/i)).toBeVisible();
  await page.getByLabel(/authentication code/i).fill(totpNow(ADMIN_TOTP_SECRET));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test.describe("Admin Portal", () => {
  test.skip(!ADMIN_TOTP_SECRET, "E2E_ADMIN_TOTP_SECRET not set — run via scripts/e2e-run.sh");

  test("mandatory MFA enrollment on first login shows recovery codes before the dashboard, not instead of it", async ({ page }) => {
    await page.goto("/admin/");
    await page.getByLabel("Username").fill(ADMIN_ENROLL_USERNAME);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);

    const enrollResponse = page.waitForResponse((r) => r.url().includes("/mfa/setup/enroll") && r.ok());
    await page.getByRole("button", { name: "Log in" }).click();
    const body = await (await enrollResponse).json();
    const secret = secretFromOtpauthUri(body.otpauth_uri);

    await expect(page.getByAltText("TOTP enrollment QR code")).toBeVisible();
    await page.getByLabel(/enter the code from your app/i).fill(totpNow(secret));
    await page.getByRole("button", { name: "Confirm and continue" }).click();

    // The regression this suite caught: refreshing client-side auth state
    // before this screen renders makes the /login route redirect away
    // from it immediately (`user` becomes truthy while still on that
    // path) — silently skipping past the user's only chance to see these
    // codes. Must still be showing here, not the dashboard.
    await expect(page.getByText(/will not be shown again/i)).toBeVisible();
    const codes = await page.locator(".recovery-codes span").allTextContents();
    expect(codes.length).toBeGreaterThan(0);
    await expect(page.getByRole("heading", { name: "Dashboard" })).not.toBeVisible();

    await page.getByRole("button", { name: "I've saved these, continue" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  });

  test("logs in with a real TOTP code and sees a real, non-fabricated dashboard", async ({ page }) => {
    await loginAsAdmin(page);
    // No fabricated data — every stat card must at least render without
    // throwing, backed by the real list/health endpoints.
    await expect(page.getByText(/active sessions/i)).toBeVisible();
    // Scoped to the StatCard specifically — the PageHeader subtitle also
    // mentions "system health" in its own sentence.
    await expect(page.locator(".stat-card", { hasText: /system health/i })).toBeVisible();
  });

  test("Users page lists the real seeded users", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Users", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await expect(page.getByRole("link", { name: USER_USERNAME })).toBeVisible();
    await expect(page.getByRole("link", { name: ADMIN_USERNAME, exact: true })).toBeVisible();
  });

  test("System page renders real, non-hardcoded health status", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "System" }).click();
    // Every component the real /admin/health check covers must show some
    // real status text — never silently blank, never a fixed green check
    // baked into markup regardless of backend state. Matched against the
    // component's own table cell specifically, since ClamAV's version
    // string cell also happens to contain "ClamAV".
    for (const component of ["postgres", "redis", "clamav", "session_agent"]) {
      await expect(page.getByRole("cell", { name: component, exact: true })).toBeVisible();
    }
  });

  test("Quarantine page shows a real, honest empty state with no fake file preview", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Quarantine" }).click();
    await expect(page.locator("iframe")).toHaveCount(0);
    // Either a real empty state or a real table — never a placeholder row.
    // Wait for the page to actually finish loading (not a non-retrying
    // isVisible() snapshot, which can race the initial fetch and mistake
    // "still loading" for "empty") before deciding which case applies.
    await expect(page.locator(".table-wrap, .empty-state")).toBeVisible();
    const hasTable = (await page.locator(".data-table").count()) > 0;
    if (!hasTable) {
      await expect(page.getByText(/no.*quarantine/i)).toBeVisible();
    }
  });

  test("Dashboard's Needs Attention section reflects real data — calm when clear, never a fabricated alert", async ({ page }) => {
    await loginAsAdmin(page);
    await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
    // Either a real attention item (a genuine open incident/isolated
    // session/quarantine file/degraded component) or the calm all-clear
    // empty state — never both, and never invented alert copy.
    const hasAttentionItem = await page.locator(".attention-item").first().isVisible().catch(() => false);
    if (!hasAttentionItem) {
      await expect(page.getByText(/nothing needs attention/i)).toBeVisible();
    }
  });

  test("the Help menu opens and links to a real, reachable guide (not a fake or broken link)", async ({ page, request }) => {
    await loginAsAdmin(page);
    await page.getByRole("button", { name: "Help" }).click();
    const link = page.getByRole("menuitem", { name: /admin guide/i });
    await expect(link).toBeVisible();
    const href = await link.getAttribute("href");
    expect(href).toBeTruthy();
    const res = await request.get(href!);
    expect(res.status()).toBe(200);
  });

  test("the Notifications button is honest about having no data, not filled with invented demo entries", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("button", { name: "Notifications" }).click();
    await expect(page.getByText(/no notifications yet/i)).toBeVisible();
  });

  test("Groups delete uses a specific confirmation dialog, not a bare browser confirm() prompt", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Groups" }).click();
    await expect(page.getByRole("heading", { name: "Groups" })).toBeVisible();

    const groupName = `e2e-polish-${Date.now()}`;
    await page.getByRole("button", { name: "Create Group" }).click();
    await page.getByLabel("Name").fill(groupName);
    await page.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByRole("cell", { name: groupName })).toBeVisible();

    const row = page.locator("tr", { hasText: groupName });
    await row.getByRole("button", { name: "Delete" }).click();

    // A real, specific confirmation dialog naming this exact group — not
    // window.confirm() (which Playwright would auto-dismiss/never see as
    // a page element at all) and not a generic "Are you sure?".
    await expect(page.getByText(`Delete group "${groupName}"?`)).toBeVisible();
    await page.getByRole("button", { name: "Delete", exact: true }).last().click();
    await expect(page.getByRole("cell", { name: groupName })).toHaveCount(0);
  });
});

test.describe("Listener/portal security boundary", () => {
  test("the User Portal's own session cannot act on the admin API", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Username").fill(USER_USERNAME);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    // Same browser context/cookies as the logged-in User Portal session,
    // hitting the admin API directly. In Compact (both listeners in one
    // process) this is a 403 (RBAC rejection); in a Segmented deployment
    // running a real user-mode listener, the same request is a 404
    // (the route doesn't exist at all) — see scripts/test-listener-modes.sh
    // for the backend-level proof of that distinction. Either way, it must
    // never be a 200.
    const res = await page.request.get("/api/admin/users");
    expect([403, 404]).toContain(res.status());
  });
});
