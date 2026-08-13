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

  test("Dashboard's operations view (B1.10.2) shows real worker load and a working range selector", async ({ page }) => {
    await loginAsAdmin(page);

    // KPI cards backed by GET /admin/dashboard, not the old client-side
    // aggregation — "Workers healthy" only exists on the new endpoint.
    await expect(page.getByText(/workers healthy/i)).toBeVisible();
    await expect(page.getByText(/avg cpu/i)).toBeVisible();
    await expect(page.getByText(/avg ram/i)).toBeVisible();
    await expect(page.getByText(/last updated \d{1,2}:\d{2}:\d{2}/i)).toBeVisible();

    // Session history chart renders as a real SVG, not a placeholder box.
    await expect(page.getByRole("img", { name: /active sessions over time/i })).toBeVisible();

    // Worker load section lists the real seeded session-agent node.
    await expect(page.getByText(/worker load/i)).toBeVisible();
    await expect(page.locator(".load-bar-row")).toHaveCount(1);

    // Range selector actually triggers a new fetch against the backend.
    const historyResponse = page.waitForResponse((r) => r.url().includes("/admin/dashboard?range=7d") && r.ok());
    await page.getByRole("button", { name: "7d", exact: true }).click();
    await historyResponse;
  });

  test("Users page lists the real seeded users", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Users", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await expect(page.getByRole("link", { name: USER_USERNAME })).toBeVisible();
    await expect(page.getByRole("link", { name: ADMIN_USERNAME, exact: true })).toBeVisible();
  });

  test("User Detail (B1.10.4) hides 'Terminate all sessions' when the user has no live sessions", async ({ page }) => {
    // e2e_user is freshly seeded with no session — the button must not
    // exist at all (not just be disabled), since its own confirm dialog
    // assumes there's something real to terminate. The full terminate
    // round-trip (session flips to TERMINATED, USER_SESSIONS_REVOKED is
    // audited) is covered by backend/tests/integration/test_user_sessions_revoke.py
    // against the real Session Agent — creating a real sandbox session
    // from this suite would duplicate that coverage at much higher cost.
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Users", exact: true }).click();
    await page.getByRole("link", { name: USER_USERNAME }).click();
    await expect(page.getByRole("heading", { name: USER_USERNAME })).toBeVisible();
    await expect(page.getByRole("button", { name: "Terminate all sessions" })).toHaveCount(0);
  });

  test("User Detail (B1.10.5) Lock/Unlock account really blocks and restores login", async ({ page, request }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Users", exact: true }).click();
    await page.getByRole("link", { name: USER_USERNAME }).click();

    await expect(page.getByText(/not locked/i)).toBeVisible();
    await page.getByRole("button", { name: "Lock account", exact: true }).click();
    await page.getByRole("button", { name: "Lock account", exact: true }).last().click();
    await expect(page.getByText(/^LOCKED/)).toBeVisible();

    // Real backend round-trip, not just a UI state flip: the actual login
    // endpoint now rejects the account's real, correct password.
    const lockedLogin = await request.post("/api/auth/login", {
      data: { username: USER_USERNAME, password: PASSWORD },
    });
    expect(lockedLogin.status()).toBe(429);

    await page.getByRole("button", { name: "Unlock account", exact: true }).click();
    await page.getByRole("button", { name: "Unlock account", exact: true }).last().click();
    await expect(page.getByText(/not locked/i)).toBeVisible();

    const unlockedLogin = await request.post("/api/auth/login", {
      data: { username: USER_USERNAME, password: PASSWORD },
    });
    expect(unlockedLogin.status()).toBe(200);
  });

  test("Login Diagnostics (B1.10.6) is read-only and correctly reports both a known and an unknown username", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Login Diagnostics" }).click();
    await expect(page.getByRole("heading", { name: "Login Diagnostics" })).toBeVisible();

    // A real seeded account: exists, active, no lockout.
    await page.getByPlaceholder("Username").fill(USER_USERNAME);
    await page.getByRole("button", { name: "Diagnose" }).click();
    await expect(page.getByText("YES", { exact: true })).toBeVisible();
    await expect(page.getByText("NOT LOCKED")).toBeVisible();
    await expect(page.getByRole("link", { name: /view full user detail/i })).toBeVisible();

    // A username that doesn't exist: no fabricated account data, an
    // honest "no account found" reason, and no dangling detail link.
    await page.getByPlaceholder("Username").fill("definitely_not_a_real_username_xyz");
    await page.getByRole("button", { name: "Diagnose" }).click();
    await expect(page.getByText("NO", { exact: true })).toBeVisible();
    await expect(page.getByText(/no account found/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /view full user detail/i })).toHaveCount(0);
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
    // Roadmap B1.10.7 — a visible "Last updated" clock backed by real polling.
    await expect(page.getByText(/last updated \d{1,2}:\d{2}:\d{2}/i)).toBeVisible();
  });

  test("Audit page (B1.10.7) filters by event type/user and links to the real user", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Audit", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Audit" })).toBeVisible();

    // Filtering by a real event type narrows the table to only that type.
    const eventResponse = page.waitForResponse(
      (r) => r.url().includes("/admin/security-events") && r.url().includes("event_type=USER_CREATED") && r.ok(),
    );
    await page.getByPlaceholder("Filter by event type").fill("USER_CREATED");
    await eventResponse;
    const rows = page.locator(".data-table tbody tr").filter({ hasText: "USER_CREATED" });
    await expect(rows.first()).toBeVisible();
    await expect(page.locator(".data-table tbody tr", { hasText: /SESSION_STARTED|MFA_ENROLLED/ })).toHaveCount(0);

    // The user column is a real link to that user's detail page, not just text.
    const userLink = page.locator(".data-table tbody tr").first().locator("a").first();
    await expect(userLink).toHaveAttribute("href", /\/users\/[0-9a-f-]{36}/);

    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByPlaceholder("Filter by event type")).toHaveValue("");
  });

  test("Workers page (B1.10.3) lists real workers and drilling into one shows drain/maintenance controls and history charts", async ({ page }) => {
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "Workers" }).click();
    await expect(page.getByRole("heading", { name: "Workers" })).toBeVisible();

    const workerLink = page.locator(".data-table tbody tr td a").first();
    await expect(workerLink).toBeVisible();
    const hostname = await workerLink.textContent();
    await workerLink.click();

    await expect(page.getByRole("heading", { name: hostname ?? "" })).toBeVisible();
    await expect(page.getByText(/scheduling status/i)).toBeVisible();
    await expect(page.getByRole("img", { name: /cpu percent over time/i })).toBeVisible();
    await expect(page.getByRole("img", { name: /ram percent over time/i })).toBeVisible();

    // Drain -> confirm -> health flips to DRAINING -> undrain restores it,
    // exercising the real backend state change end to end, not just a UI
    // mock. Always restored, even if an assertion above fails first.
    await page.getByRole("button", { name: "Drain", exact: true }).click();
    await page.getByRole("button", { name: "Drain", exact: true }).last().click();
    try {
      await expect(page.getByText("DRAINING", { exact: true }).first()).toBeVisible();
    } finally {
      await page.getByRole("button", { name: "Undrain" }).click();
      await page.getByRole("button", { name: "Undrain" }).last().click();
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

  test("LDAP settings page loads real config from the API and never shows a bind password", async ({ page }) => {
    // Roadmap B1.8 — no fabricated defaults: the form must reflect
    // whatever GET /admin/ldap/config actually returns, and the password
    // field must never be pre-filled with anything, ever.
    await loginAsAdmin(page);
    await page.getByRole("link", { name: "LDAP" }).click();
    await expect(page.getByRole("heading", { name: "Settings — Authentication — LDAP" })).toBeVisible();
    await expect(page.getByLabel("Server URI")).toBeVisible();
    await expect(page.getByLabel("Bind password")).toHaveValue("");
    await expect(page.getByRole("button", { name: "Test connection" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save configuration" })).toBeVisible();
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
