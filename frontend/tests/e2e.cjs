/* Run against the isolated audit stack only. Password travels over stdin, never logs. */
const { createRequire } = require("node:module");
const { execFileSync } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const path = require("node:path");
const fs = require("node:fs");
const [auditDirectory, moduleDirectory, outputDirectory] =
  process.argv.slice(2);
if (
  !auditDirectory ||
  path.basename(auditDirectory) !== "advisor-app-audit-0906" ||
  !moduleDirectory ||
  !outputDirectory
)
  throw new Error(
    "Explicit isolated audit directory, Playwright module directory and screenshot output are required",
  );
const { chromium } = createRequire(path.join(moduleDirectory, "package.json"))(
  "playwright",
);
const password = randomBytes(30).toString("base64url");
execFileSync(
  "docker",
  [
    "compose",
    "exec",
    "-T",
    "api",
    "python",
    "-c",
    "import sys; from app.security import password_hash; from app.store import transaction,run; p=sys.stdin.read();\nwith transaction() as db: run(db, 'UPDATE app.users SET password_hash=:hash WHERE email IN (:student,:admin)', hash=password_hash(p), student='student@demo.local', admin='admin@demo.local')",
  ],
  { cwd: auditDirectory, input: password, stdio: ["pipe", "pipe", "pipe"] },
);
(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://localhost:13010");
    await page.getByLabel("Email", { exact: true }).fill("student@demo.local");
    await page.getByLabel("Mật khẩu", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Vào không gian học tập" }).click();
    await page.getByText("Nhìn rõ hiện tại. Đi xa hơn.").waitFor();
    await page.getByText("2,96", { exact: true }).waitFor();
    fs.mkdirSync(outputDirectory, { recursive: true });
    await page.screenshot({
      path: path.join(outputDirectory, "overview-desktop.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Mục tiêu & mô phỏng" }).click();
    await page
      .locator("section")
      .filter({
        has: page.getByRole("heading", { name: "GPA cần đạt", exact: true }),
      })
      .getByRole("button")
      .click();
    await page.getByText("3,52", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Trợ lý học tập" }).click();
    await page.getByRole("textbox", { name: "Tin nhắn" }).fill("GPA");
    await page.getByRole("button", { name: "Gửi" }).click();
    await page.getByText("GPA 2,96 / 4 · Đã đạt 72 tín chỉ").waitFor();
    await page.screenshot({
      path: path.join(outputDirectory, "chat-desktop.png"),
      fullPage: true,
    });
    await page.reload();
    await page.getByText("Nhìn rõ hiện tại. Đi xa hơn.").waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(outputDirectory, "overview-mobile.png"),
      fullPage: true,
    });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    if (overflow) throw new Error("Mobile horizontal overflow");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole("button", { name: "Đăng xuất" }).click();
    await page.getByRole("heading", { name: "Đăng nhập Advisor" }).waitFor();
    if (errors.length) throw new Error(errors.join("\n"));
    console.log(
      "PASS: browser login, live GPA, calculator, chat service card, reload/refresh, mobile overflow, logout; no page errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.message);
  process.exitCode = 1;
});
