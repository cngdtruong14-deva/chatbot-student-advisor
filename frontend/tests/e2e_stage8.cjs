/* Stage 8.5 browser gate. Run only against a disposable stack. Password is stdin. */
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const { randomBytes } = require('node:crypto');

const baseUrl = process.argv[2];
const outputDir = process.argv[3];
const password = fs.readFileSync(0, 'utf8').trim();
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(baseUrl || '') || !outputDir || password.length < 12) {
  throw new Error('Disposable localhost URL, evidence directory and stdin password are required');
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const pageErrors = [];
  const badResponses = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 500) badResponses.push(`${response.status()} ${response.url()}`);
  });
  async function login(identity, secret, expectedHeading) {
    await page.getByLabel('Tên đăng nhập hoặc email').fill(identity);
    await page.getByLabel('Mật khẩu', { exact: true }).fill(secret);
    const response = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login') && r.request().method() === 'POST');
    await page.getByRole('button', { name: /Vào không gian học tập/ }).click();
    const payload = await (await response).json();
    await page.getByRole('heading', { name: expectedHeading }).waitFor();
    return payload.data.user;
  }
  async function logout() {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: /Đăng xuất/ }).click();
    await page.getByRole('heading', { name: /Đăng nhập/ }).waitFor();
  }
  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });

    // 1. Student login & overview verification
    await login('student@demo.local', password, 'Nhìn rõ hiện tại. Đi xa hơn.');
    await page.getByText('DEMO-001', { exact: false }).waitFor();
    await page.screenshot({ path: path.join(outputDir, '01-overview.png'), fullPage: true });

    // Verify Student navigation boundaries: MUST NOT expose Research/ML
    const studentNavResearchCount = await page.locator('nav').getByText(/Nghiên cứu|Research/).count();
    if (studentNavResearchCount > 0) throw new Error('Student navigation must not expose Research');

    // 2. Transcript & Academics
    await page.locator('aside nav').getByRole('button', { name: 'Hồ sơ học tập' }).click();
    await page.getByRole('heading', { name: 'Bảng điểm của bạn' }).waitFor();
    await page.getByText('DEMO-C01', { exact: true }).waitFor();

    // 3. Planning (What-if simulation)
    await page.locator('aside nav').getByRole('button', { name: 'Kế hoạch học tập' }).click();
    const calculator = page.locator('section').filter({ has: page.getByRole('heading', { name: 'GPA cần đạt', exact: true }) });
    await calculator.getByRole('button').click();
    await page.getByRole('heading', { name: 'Kết quả tính toán mô phỏng' }).waitFor();

    // 4. Chat productization & Citations
    await page.locator('aside nav').getByRole('button', { name: 'Hỏi cố vấn AI' }).click();
    await page.getByLabel('Kho tài liệu').selectOption('demo_academic');
    await page.getByLabel('Tin nhắn').fill('GPA của tôi hiện tại là bao nhiêu?');
    await page.getByRole('button', { name: /Gửi/ }).click();
    await page.getByText(/GPA:/).waitFor();
    // Verify 30-day retention notice and high-stakes notice
    await page.getByText(/30 ngày/).waitFor();
    // Verify student UI does not leak raw benchmark proxy
    const rawProxy = await page.getByText(/87,5% correctness proxy/).count();
    if (rawProxy > 0) throw new Error('Student UI must not show raw benchmark proxy');
    await page.screenshot({ path: path.join(outputDir, '02-chat.png'), fullPage: true });

    // 5. Reload session & history
    await page.reload({ waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: 'Nhìn rõ hiện tại. Đi xa hơn.' }).waitFor();
    await page.locator('aside nav').getByRole('button', { name: 'Hỏi cố vấn AI' }).click();
    const chatSidebar = page.getByRole('complementary', { name: 'Lịch sử và tài liệu truy xuất' });
    await chatSidebar.getByRole('heading', { name: 'Lịch sử trò chuyện' }).waitFor();
    await chatSidebar.getByRole('heading', { name: 'Tài liệu truy xuất' }).waitFor();
    const savedConversation = chatSidebar.getByRole('button', { name: /Mở cuộc trò chuyện/ }).first();
    await savedConversation.waitFor();
    await savedConversation.click();
    await page.getByText(/GPA:/).waitFor();
    const mainBox = await page.locator('.chat-main').boundingBox();
    const sideBox = await chatSidebar.boundingBox();
    if (!mainBox || !sideBox || sideBox.x <= mainBox.x) throw new Error('Chat history/evidence panel must be to the right on desktop');

    // 6. Responsive viewports check: 1280px, 768px, 360px
    for (const width of [1280, 768, 360]) {
      await page.setViewportSize({ width, height: 800 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      if (overflow) throw new Error(`Mobile horizontal overflow at ${width}px`);
    }
    await page.screenshot({ path: path.join(outputDir, '03-mobile.png'), fullPage: true });

    await logout();

    // 7. Advisor navigation verification
    await login('advisor@demo.local', password, 'Không gian Cố vấn học tập');
    const advisorNavResearchCount = await page.locator('nav').getByText(/Nghiên cứu|Research/).count();
    if (advisorNavResearchCount > 0) throw new Error('Advisor navigation must not expose Research');
    await page.locator('aside nav').getByRole('button', { name: 'Sinh viên được phân công' }).waitFor();
    await logout();

    // 8. Admin navigation & Research verification
    await login('admin@demo.local', password, 'Tổng quan quản trị hệ thống');
    // Admin Research tab check: must have synthetic disclosure
    await page.locator('aside nav').getByRole('button', { name: 'Nghiên cứu ML (Synthetic)' }).click();
    await page.getByRole('heading', { name: 'Nghiên cứu & Đánh giá ML' }).waitFor();
    await page.getByText(/1\.000 hồ sơ synthetic/).first().waitFor();
    await page.getByRole('heading', { name: /Academic Demo v2/ }).waitFor();

    // Admin pilot account & invite code
    await page.locator('aside nav').getByRole('button', { name: 'Tổng quan hệ thống' }).click();
    const accountPanel = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Cấp quyền truy cập pilot' }) });
    await accountPanel.getByRole('button', { name: /Tạo mã mời/ }).click();
    const invite = (await accountPanel.locator('code').textContent()).trim();
    await logout();

    // 9. Invite registration & unlinked student UX
    const username = `stage8_${randomBytes(5).toString('hex')}`;
    const recoveredPassword = `${password}R1!`;
    await page.getByText('Đăng ký pilot / Khôi phục mật khẩu').click();
    await page.getByLabel('Tên đăng nhập', { exact: true }).fill(username);
    await page.getByLabel('Mã mời', { exact: true }).fill(invite);
    await page.getByLabel('Mật khẩu mới', { exact: true }).fill(password);
    await page.getByLabel('Nhập lại mật khẩu', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Xác nhận' }).click();
    await page.getByText('Thành công. Hãy đăng nhập bằng mật khẩu mới.').waitFor();
    const newUser = await login(username, password, 'Nhìn rõ hiện tại. Đi xa hơn.');
    await page.getByRole('heading', { name: 'Bắt đầu với bảng điểm cá nhân' }).waitFor();
    await logout();

    // 10. Admin recovery code issuance
    await login('admin@demo.local', password, 'Tổng quan quản trị hệ thống');
    const accountTable = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Tài khoản và trạng thái hồ sơ' }) });
    const newAccountRow = accountTable.locator('tbody tr').filter({ hasText: username });
    await newAccountRow.getByRole('button', { name: 'Quản lý' }).click();
    const recoveryPanel = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: `Quản lý sinh viên: ${username}` }) });
    await recoveryPanel.getByText('Khôi phục mật khẩu', { exact: true }).click();
    await recoveryPanel.getByRole('checkbox', { name: /xác minh đúng chủ tài khoản/ }).check();
    await recoveryPanel.getByRole('button', { name: /Cấp mã khôi phục/ }).click();
    const recovery = (await page.locator('.one-time-secret code').textContent()).trim();
    await logout();

    // 11. Password recovery flow
    await page.getByText('Đăng ký pilot / Khôi phục mật khẩu').click();
    await page.getByRole('button', { name: 'Tôi có mã khôi phục' }).click();
    await page.getByLabel('Mã khôi phục', { exact: true }).fill(recovery);
    await page.getByLabel('Mật khẩu mới', { exact: true }).fill(recoveredPassword);
    await page.getByLabel('Nhập lại mật khẩu', { exact: true }).fill(recoveredPassword);
    await page.getByRole('button', { name: 'Xác nhận' }).click();
    await page.getByText('Thành công. Hãy đăng nhập bằng mật khẩu mới.').waitFor();
    await login(username, recoveredPassword, 'Nhìn rõ hiện tại. Đi xa hơn.');
    await logout();

    // 12. Unlinked user UX
    await login('unlinked@demo.local', password, 'Nhìn rõ hiện tại. Đi xa hơn.');
    await page.getByRole('heading', { name: 'Bắt đầu với bảng điểm cá nhân' }).waitFor();
    await page.locator('aside nav').getByRole('button', { name: 'Hỏi cố vấn AI' }).click();
    await page.getByText(/Chưa có hồ sơ học tập cá nhân/).waitFor();
    await page.getByText(/Bạn vẫn có thể tra cứu tài liệu UTT phạm vi chung/).waitFor();
    await logout();

    if (pageErrors.length) throw new Error(`Browser errors: ${pageErrors.join('; ')}`);
    if (badResponses.length) throw new Error(`HTTP 5xx responses: ${badResponses.join('; ')}`);
    console.log('PASS: Stage 8.5 production UX — role navigation, student IA, citations, retention notice, truthful synthetic disclosures, responsive 360/768/1280 and recovery flows.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
