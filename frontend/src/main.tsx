import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, ApiError, setAccess, uploadImport, downloadImportTemplate, importHistory, User } from "./api";
import "./style.css";
import { Documents } from './Documents';
import { Research } from './Research';
import { Chat } from './Chat';
import { StudentInput } from './StudentInput';
import { PersonalAcademics } from './PersonalAcademics';
import { AccountRegistration, PersonalOnboarding, AdminAccounts } from './Accounts';
import { PRODUCT_CONFIG, STUDENT_NAV, ADVISOR_NAV, ADMIN_NAV, NavItem } from './product-config';
import type { AcademicSummary } from "./api-types";

type Academic = AcademicSummary;
const fmt = (s: string | number | null | undefined, maxDigits = 3) =>
  s == null
    ? "—"
    : Number(s).toLocaleString("vi-VN", { maximumFractionDigits: maxDigits });

function App() {
  const [showPassword, setShowPassword] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [starting, setStarting] = useState(true);
  const [page, setPage] = useState("overview");
  const [academicsTab, setAcademicsTab] = useState<"official" | "personal" | "self_input">("official");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<any>(null);
  const [summary, setSummary] = useState<Academic | null>(null);
  const [semesters, setSemesters] = useState<any[]>([]);
  const [semester, setSemester] = useState("");
  const [result, setResult] = useState<any>(null);
  const [recommendation, setRecommendation] = useState<any>(null);
  const [students, setStudents] = useState<any[]>([]);
  const [capabilities, setCapabilities] = useState<any>(null);

  async function task(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function enter(data: any) {
    setAccess(data.access_token);
    setUser(data.user);
    setError('');
  }

  useEffect(() => {
    const expired = () => {
      setUser(null); setProfile(null); setSummary(null); setStudents([]);
      setResult(null); setRecommendation(null); setCapabilities(null); setPage('overview');
      setError('Phiên đã hết hạn. Vui lòng đăng nhập lại để tiếp tục.');
    };
    window.addEventListener('advisor:session-expired', expired);
    return () => window.removeEventListener('advisor:session-expired', expired);
  }, []);

  useEffect(() => {
    api("/auth/refresh", {})
      .then(enter)
      .catch(() => {})
      .finally(() => setStarting(false));
  }, []);

  useEffect(() => {
    if (!user) return;
    void task(async () => {
      const [terms, caps] = await Promise.all([
        api("/catalog/semesters"),
        api("/system/capabilities"),
      ]);
      setSemesters(terms.items);
      setSemester(
        terms.items.find((t: any) => t.code === "DEMO-T5")?.id ||
          terms.items[0]?.id ||
          "",
      );
      setCapabilities(caps);
      if (user.role === "student") {
        try {
          const p = await api("/students/me");
          setProfile(p);
          setSummary(await api("/students/" + p.id + "/academic-summary"));
        } catch (e) {
          if (e instanceof ApiError && e.code === "STUDENT_PROFILE_NOT_LINKED") {
            setProfile(null);
            setSummary(null);
            setAcademicsTab("personal");
          } else throw e;
        }
      } else {
        const advStudents = await api("/advisor/students");
        setStudents(advStudents.items);
      }
    });
  }, [user]);

  function navigate(next: string) {
    setPage(next);
    setResult(null);
    setError("");
  }

  async function signOut() {
    await api("/auth/logout", {});
    setAccess("");
    setUser(null);
    setProfile(null);
    setSummary(null);
    setStudents([]);
    setResult(null);
    setRecommendation(null);
    setCapabilities(null);
    setPage("overview");
  }

  if (starting) {
    return <main className="loading">Đang kết nối hệ thống {PRODUCT_CONFIG.BRAND_NAME}…</main>;
  }

  if (!user) {
    return (
      <main className="login">
        <section className="intro">
          <div className="brand">
            <span>AI</span> {PRODUCT_CONFIG.BRAND_NAME}
          </div>
          <p className="eyebrow">{PRODUCT_CONFIG.INSTITUTION_NAME.toUpperCase()}</p>
          <h1>
            Đồng hành học tập,
            <br />
            lập kế hoạch và
            <br />
            <em>tra cứu có dẫn nguồn.</em>
          </h1>
          <p>
            {PRODUCT_CONFIG.SHORT_DESCRIPTION}
          </p>
          <div className="demo-note">
            {PRODUCT_CONFIG.PILOT_BADGE}
            <br />
            {PRODUCT_CONFIG.PILOT_DISCLOSURE}
          </div>
        </section>
        <section className="login-form">
          <p className="eyebrow">CHÀO MỪNG BẠN</p>
          <h2>Đăng nhập {PRODUCT_CONFIG.BRAND_NAME}</h2>
          <p className="muted">
            Sử dụng tên đăng nhập hoặc email và mật khẩu của bạn. Tài khoản mới có thể kích hoạt bằng mã mời pilot.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void task(async () =>
                enter(
                  await api("/auth/login", {
                    email: String(f.get("email") || '').trim().toLowerCase(),
                    password: f.get("password"),
                  }),
                ),
              );
            }}
          >
            <label>
              Tên đăng nhập hoặc email
              <input
                name="email"
                type="text"
                required
                autoComplete="username"
                autoFocus
                disabled={busy}
                placeholder="student@demo.local"
              />
            </label>
            <label>
              Mật khẩu
              <input
                name="password"
                type={showPassword ? 'text' : 'password'}
                disabled={busy}
                maxLength={256}
                required
                autoComplete="current-password"
              />
            </label>
            <button type="button" className="quiet" aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)}>
              {showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
            </button>
            {error && (
              <div role="alert" className="error">
                {error}
              </div>
            )}
            <button disabled={busy}>
              {busy ? "Đang đăng nhập…" : "Vào không gian học tập →"}
            </button>
          </form>
          <AccountRegistration />
          <small>
            Chưa có tài khoản hoặc quên mật khẩu? Vui lòng liên hệ Quản trị viên để được cấp lại. Không gửi mật khẩu vào hội thoại chat.
          </small>
        </section>
      </main>
    );
  }

  const navItems: NavItem[] =
    user.role === "student"
      ? STUDENT_NAV
      : user.role === "advisor"
      ? ADVISOR_NAV
      : ADMIN_NAV;

  const currentNav = navItems.find((n) => n.id === page) || navItems[0];

  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <span>AI</span> Cố vấn học tập
        </div>
        <p className="eyebrow">NỀN TẢNG HỖ TRỢ HỌC TẬP</p>
        <nav>
          {navItems.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "active" : ""}
              onClick={() => navigate(item.id)}
            >
              <i>{item.icon}</i>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <span className="badge">{PRODUCT_CONFIG.PILOT_BADGE}</span>
          <p>
            Kho quy chế: {PRODUCT_CONFIG.CORPUS_NAME}
            <br />
            Hỗ trợ học vụ sinh viên
          </p>
          <button
            className="quiet"
            disabled={busy}
            onClick={() => void task(signOut)}
          >
            Đăng xuất ↗
          </button>
        </div>
      </aside>

      <div className="workspace">
        <header>
          <span>
            {PRODUCT_CONFIG.BRAND_NAME} / <b>{currentNav.label}</b>
          </span>
          <span className="identity">
            {user.email}{" "}
            <span className="avatar">{user.role[0].toUpperCase()}</span>
          </span>
        </header>

        <main className="content">
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
          {busy && (
            <p role="status" className="muted">
              Đang xử lý…
            </p>
          )}

          {/* PAGE: OVERVIEW */}
          {page === "overview" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">HÀNH TRÌNH HỌC TẬP</p>
                  <h1>
                    {user.role === "student"
                      ? "Nhìn rõ hiện tại. Đi xa hơn."
                      : user.role === "advisor"
                      ? "Không gian Cố vấn học tập"
                      : "Tổng quan quản trị hệ thống"}
                  </h1>
                  <p className="muted">
                    {profile?.student_code
                      ? `Mã sinh viên: ${profile.student_code} · ${profile.full_name || ''}`
                      : user.role === "student"
                      ? "Tài khoản sinh viên"
                      : "Quản lý và hỗ trợ hoạt động học tập."}
                    {summary && ` · Bản cập nhật ${summary.academic_revision}`}
                  </p>
                </div>
                <span className="pill">● {PRODUCT_CONFIG.PILOT_BADGE}</span>
              </div>

              {user.role === 'student' && !profile && !busy && (
                <section className="panel" role="status">
                  <h2>Bắt đầu với bảng điểm cá nhân</h2>
                  <p>{PRODUCT_CONFIG.ACCOUNTS.UNLINKED_NOTICE}</p>
                  <button onClick={() => { setAcademicsTab('personal'); navigate('academics'); }}>
                    Mở bảng điểm cá nhân (Tự khai báo) →
                  </button>
                  <PersonalOnboarding />
                </section>
              )}

              {user.role === 'student' && summary && (
                <>
                  <div className="metrics">
                    <Metric
                      title="GPA tích lũy"
                      value={fmt(summary.cumulative_gpa)}
                      suffix="/ 4"
                    />
                    <Metric
                      title="Tín chỉ đã đạt"
                      value={fmt(summary.earned_credits)}
                      suffix={`/ ${fmt(summary.required_credits)}`}
                    />
                    <Metric
                      title="Tín chỉ tính GPA"
                      value={fmt(summary.gpa_credits)}
                      suffix="tín chỉ"
                    />
                    <Metric
                      title="Còn trong chương trình"
                      value={fmt(summary.remaining_required_credits)}
                      suffix="tín chỉ"
                    />
                  </div>

                  <div className="grid-two">
                    <section className="panel feature">
                      <p className="eyebrow">KẾ HOẠCH HỌC TẬP</p>
                      <h2>
                        Mục tiêu rõ ràng,
                        <br />
                        chủ động tiến độ.
                      </h2>
                      <p>
                        Mô phỏng GPA mục tiêu, tính điểm thi cần đạt và dự kiến lộ trình học phần. Kết quả mô phỏng hoàn toàn độc lập với bảng điểm thật.
                      </p>
                      <button onClick={() => navigate("planning")}>
                        Lập kế hoạch học tập ↗
                      </button>
                    </section>
                    <section className="panel">
                      <h3>Tiến độ tích lũy tín chỉ</h3>
                      <div className="progress-number">
                        {fmt(summary.earned_credits)}{" "}
                        <small>/ {fmt(summary.required_credits)} tín chỉ</small>
                      </div>
                      <progress
                        value={Number(summary.earned_credits)}
                        max={Number(summary.required_credits)}
                      />
                      <p className="muted">
                        Tiến độ được tính theo chương trình đào tạo. Đây là công cụ hỗ trợ theo dõi, không thay thế quyết định xét tốt nghiệp chính thức.
                      </p>
                      <button
                        className="secondary"
                        onClick={() => { setAcademicsTab('official'); navigate("academics"); }}
                      >
                        Xem chi tiết bảng điểm →
                      </button>
                    </section>
                  </div>

                  <div className="grid-two" style={{ marginTop: '16px' }}>
                    <section className="panel">
                      <h3>Tra cứu tài liệu học vụ với AI</h3>
                      <p className="muted">
                        Đặt câu hỏi về quy định đào tạo tín chỉ, học bổng, chuẩn đầu ra và thủ tục học vụ trong kho tài liệu pilot đang chọn.
                      </p>
                      <button onClick={() => navigate("chat")}>
                        Trò chuyện cùng Cố vấn AI ↗
                      </button>
                    </section>
                    <section className="panel">
                      <h3>Kho tài liệu văn bản</h3>
                      <p className="muted">
                        Tìm kiếm và đọc trực tiếp các quyết định, quy định hiện hành trong kho {PRODUCT_CONFIG.CORPUS_NAME}.
                      </p>
                      <button onClick={() => navigate("documents")}>
                        Mở kho tài liệu ↗
                      </button>
                    </section>
                  </div>
                </>
              )}

              {user.role === "advisor" && (
                <section className="panel">
                  <h3>Sinh viên được phân công</h3>
                  {students.map((s) => (
                    <button
                      className="student-row"
                      key={s.id}
                      onClick={() =>
                        void task(async () => {
                          setSummary(
                            await api(
                              "/students/" + s.id + "/academic-summary",
                            ),
                          );
                          setPage("academics");
                        })
                      }
                    >
                      {s.student_code} · {s.full_name}
                      <span>Xem tóm tắt học vụ →</span>
                    </button>
                  ))}
                  {students.length === 0 && (
                    <p className="muted">Chưa có sinh viên nào được phân công cho tài khoản này.</p>
                  )}
                </section>
              )}

              {user.role === "admin" && (
                <>
                  <AdminImport />
                  <AdminAccounts />
                </>
              )}
            </>
          )}

          {/* PAGE: ACADEMICS (HỒ SƠ HỌC TẬP - CONSOLIDATED) */}
          {(page === "academics" || page === "transcript" || page === "self-input" || page === "personal-academics") && (
            <>
              {user.role === "student" && (
                <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    style={{ background: academicsTab === 'official' ? '#174d3b' : '#e2e8f0', color: academicsTab === 'official' ? '#fff' : '#334155' }}
                    onClick={() => setAcademicsTab('official')}
                  >
                    Bảng điểm của bạn
                  </button>
                  <button
                    type="button"
                    style={{ background: academicsTab === 'personal' ? '#174d3b' : '#e2e8f0', color: academicsTab === 'personal' ? '#fff' : '#334155' }}
                    onClick={() => setAcademicsTab('personal')}
                  >
                    Bảng điểm cá nhân (Tự khai báo)
                  </button>
                  <button
                    type="button"
                    style={{ background: academicsTab === 'self_input' ? '#174d3b' : '#e2e8f0', color: academicsTab === 'self_input' ? '#fff' : '#334155' }}
                    onClick={() => setAcademicsTab('self_input')}
                  >
                    + Tự nhập điểm & tín chỉ
                  </button>
                </div>
              )}

              {/* Subview: Official Transcript */}
              {academicsTab === 'official' && (
                <>
                  <h1>Bảng điểm của bạn</h1>
                  <p className="muted">
                    Điểm thang 10 · GPA và cách xử lý học lại theo quy chế đào tạo gắn với hồ sơ học vụ.
                  </p>

                  {summary?.transcript && summary.transcript.length > 0 ? (
                    <>
                      <section className="panel table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Học phần</th>
                              <th>Tín chỉ</th>
                              <th>Lần học</th>
                              <th>Điểm</th>
                              <th>Trạng thái</th>
                            </tr>
                          </thead>
                          <tbody>
                            {summary.transcript.map((r: any) => (
                              <tr key={r.id}>
                                <td>
                                  <b>{r.code}</b>
                                  <small>{r.title}</small>
                                </td>
                                <td>{fmt(r.credits)}</td>
                                <td>{r.attempt_no}</td>
                                <td>{fmt(r.final_score)}</td>
                                <td>
                                  <span className="pill">
                                    {r.status === "graded" ? "Đã có điểm" : r.status === "pending" ? "Đang học" : r.status}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </section>

                      <section className="panel table-wrap">
                        <h2>Lịch sử & xu hướng GPA</h2>
                        <p className="muted">
                          Mỗi học kỳ phản ánh kết quả tích lũy tại thời điểm kết thúc kỳ; điểm học lại các kỳ sau được cập nhật theo quy tắc cao nhất.
                        </p>
                        <table>
                          <thead>
                            <tr>
                              <th>Học kỳ</th>
                              <th>GPA học kỳ</th>
                              <th>GPA tích lũy</th>
                              <th>Tín chỉ GPA học kỳ</th>
                            </tr>
                          </thead>
                          <tbody>
                            {summary.semester_history.map((term: any) => (
                              <tr key={term.semester_id}>
                                <td>{semesters.find((s) => s.id === term.semester_id)?.code || term.semester_id}</td>
                                <td>{fmt(term.term_gpa)}</td>
                                <td>{fmt(term.cumulative_gpa)}</td>
                                <td>{fmt(term.term_credits)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!summary.semester_history.length && <p className="muted">Chưa có dữ liệu học kỳ trước đó.</p>}
                        {summary.trend && (
                          <p style={{ marginTop: '12px', fontSize: '13px' }}>
                            Biến động GPA tích lũy so với kỳ trước: <strong>{fmt(summary.trend.delta)}</strong>
                          </p>
                        )}
                      </section>
                    </>
                  ) : (
                    <section className="panel">
                      <h3>Chưa có dữ liệu bảng điểm chính thức</h3>
                      <p className="muted">
                        Tài khoản của bạn chưa có dữ liệu bảng điểm liên kết từ hệ thống. Bạn có thể sử dụng chức năng <strong>Bảng điểm cá nhân (Tự khai báo)</strong> để tính điểm và mô phỏng GPA.
                      </p>
                      <button onClick={() => setAcademicsTab('personal')}>
                        Chuyển sang Bảng điểm cá nhân →
                      </button>
                    </section>
                  )}
                </>
              )}

              {/* Subview: Personal Academics */}
              {academicsTab === 'personal' && (
                <PersonalAcademics key={user.id} />
              )}

              {/* Subview: Student Input */}
              {academicsTab === 'self_input' && (
                <StudentInput />
              )}
            </>
          )}

          {/* PAGE: PLANNING (KẾ HOẠCH HỌC TẬP / WHAT-IF) */}
          {(page === "planning" || page === "courses") && (
            <>
              <h1>Kế hoạch học tập</h1>
              <div style={{ padding: '8px 12px', background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '6px', marginBottom: '16px', fontSize: '13px', color: '#0369a1' }}>
                ℹ️ {PRODUCT_CONFIG.ACADEMICS.WHAT_IF_DISCLOSURE}
              </div>

              <div className="grid-two">
                <Calculator
                  title="GPA cần đạt"
                  fields={[
                    ["target_gpa", "GPA mục tiêu", "3.2", "4"],
                    ["future_gpa_credits", "Tín chỉ GPA mới", "54", "126"],
                  ]}
                  busy={busy}
                  onRun={(body) =>
                    task(async () =>
                      setResult(await api("/academic/required-gpa", body)),
                    )
                  }
                />
                <Calculator
                  title="Mô phỏng GPA học kỳ"
                  fields={[
                    ["assumed_gpa", "GPA giả định", "3.5", "4"],
                    ["gpa_credits", "Tín chỉ mới", "18", "126"],
                  ]}
                  busy={busy}
                  onRun={(body) =>
                    task(async () =>
                      setResult(
                        await api("/academic/simulations", {
                          mode: "semester_average",
                          ...body,
                        }),
                      ),
                    )
                  }
                />
                <section className="panel">
                  <h3>Mô phỏng điểm từng học phần</h3>
                  <p className="muted">Chọn một hoặc nhiều học phần trong danh sách để giả định điểm số mới.</p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const form = new FormData(e.currentTarget);
                      const items = (summary?.transcript || [])
                        .filter((row: any) => form.get("pick-" + row.offering_id))
                        .map((row: any) => ({
                          offering_id: row.offering_id,
                          assumed_final_score: form.get("score-" + row.offering_id),
                        }));
                      if (!items.length) return;
                      void task(async () =>
                        setResult(
                          await api("/academic/simulations", {
                            mode: "course_scores",
                            items,
                          }),
                        ),
                      );
                    }}
                  >
                    {(summary?.transcript || [])
                      .filter((row: any) => row.status !== "withdrawn")
                      .map((row: any) => (
                        <div key={row.offering_id} className="status-row">
                          <label>
                            <input name={"pick-" + row.offering_id} type="checkbox" /> {row.code} · lần {row.attempt_no}
                          </label>
                          <input
                            aria-label={"Điểm giả định " + row.code}
                            name={"score-" + row.offering_id}
                            type="number"
                            min="0"
                            max="10"
                            step="0.000001"
                            defaultValue={row.final_score || "7"}
                          />
                        </div>
                      ))}
                    <button disabled={busy}>Mô phỏng điểm học phần</button>
                  </form>
                </section>
                <section className="panel">
                  <h3>Điểm thành phần cần đạt</h3>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const f = new FormData(e.currentTarget);
                      void task(async () =>
                        setResult(
                          await api("/academic/target-score", {
                            enrollment_id: f.get("enrollment"),
                            target_total_score: f.get("score"),
                            unknown_component_code: "final",
                          }),
                        ),
                      );
                    }}
                  >
                    <label>
                      Học phần chưa hoàn tất
                      <select name="enrollment" required>
                        {summary?.transcript
                          .filter((r: any) => r.status === "pending")
                          .map((r: any) => (
                            <option key={r.id} value={r.id}>
                              {r.code}
                            </option>
                          ))}
                      </select>
                    </label>
                    <label>
                      Điểm tổng kết mục tiêu
                      <input
                        name="score"
                        type="number"
                        min="0"
                        max="10"
                        step="0.000001"
                        defaultValue="8"
                        required
                      />
                    </label>
                    <p className="muted">
                      Áp dụng khi chỉ còn thiếu điểm thi kết thúc học phần (final).
                    </p>
                    <button disabled={busy}>Tính điểm cần đạt</button>
                  </form>
                </section>
                <Calculator
                  title="Lưu mục tiêu cá nhân"
                  fields={[["target_gpa", "GPA mục tiêu", "3.2", "4"]]}
                  busy={busy}
                  onRun={(body) =>
                    task(async () => {
                      await api("/students/me/goal", body, "PATCH");
                      setResult({
                        message: "Đã lưu mục tiêu cá nhân. Bảng điểm thật không bị ảnh hưởng.",
                      });
                    })
                  }
                />
              </div>

              {result && <Result data={result} />}

              {/* Course planning section */}
              <section className="panel" style={{ marginTop: '20px' }}>
                <h2>Đề xuất học phần học kỳ tới</h2>
                <p className="muted">
                  Hệ thống tự động kiểm tra điều kiện tiên quyết, ưu tiên các môn bắt buộc chưa đạt. Giới hạn tối đa 18 tín chỉ/kỳ.
                </p>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '12px' }}>
                  <label style={{ margin: 0, flex: 1 }}>
                    Học kỳ đăng ký:
                    <select
                      value={semester}
                      onChange={(e) => setSemester(e.target.value)}
                    >
                      {semesters.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.code}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    disabled={busy || !semester}
                    onClick={() =>
                      void task(async () =>
                        setRecommendation(
                          await api(
                            "/recommendations/courses?semester_id=" + semester,
                          ),
                        ),
                      )
                    }
                  >
                    Xem gợi ý học phần →
                  </button>
                </div>

                {recommendation && (
                  <div style={{ marginTop: '16px' }}>
                    <h3>Gợi ý đăng ký {fmt(recommendation.total_credits)} tín chỉ</h3>
                    <div className="course-grid">
                      {recommendation.selected.map((c: any) => (
                        <article key={c.id}>
                          <span className="badge">{c.code}</span>
                          <h3>{c.title}</h3>
                          <p>
                            {fmt(c.credits)} tín chỉ ·{" "}
                            {c.retake ? "Học lại" : "Môn bắt buộc"}
                          </p>
                        </article>
                      ))}
                    </div>
                    {recommendation.excluded.length > 0 && (
                      <details style={{ marginTop: '12px' }}>
                        <summary>
                          Các môn chưa đủ điều kiện mở kỳ này ({recommendation.excluded.length})
                        </summary>
                        {recommendation.excluded.map((c: any) => (
                          <p key={c.offering_id} className="muted" style={{ margin: '4px 0' }}>
                            <strong>{c.code}</strong>: {c.reason}
                          </p>
                        ))}
                      </details>
                    )}
                  </div>
                )}
              </section>
            </>
          )}

          {/* PAGE: CHAT (HỎI CỐ VẤN AI) */}
          {page === "chat" && (
            <>
              <Chat
                isAdmin={user.role === 'admin'}
                isStudent={user.role === 'student'}
                studentProfileLinked={!!profile}
              />
            </>
          )}

          {/* PAGE: DOCUMENTS */}
          {page === "documents" && (
            <Documents
              isAdmin={user.role === 'admin'}
            />
          )}

          {/* PAGE: RESEARCH (ADMIN ONLY) */}
          {page === "research" && user.role === "admin" && (
            <>
              <h1>{PRODUCT_CONFIG.RESEARCH.TITLE}</h1>
              <div style={{ padding: '8px 12px', background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px', marginBottom: '16px', fontSize: '13px', color: '#92400e' }}>
                ⚠️ {PRODUCT_CONFIG.RESEARCH.SYNTHETIC_WARNING}
              </div>
              <Research isAdmin={true} />
            </>
          )}

          {/* PAGE: ACCOUNTS (ADMIN ONLY) */}
          {page === "accounts" && user.role === "admin" && (
            <>
              <h1>Tài khoản & Phân quyền — Admin</h1>
              <AdminAccounts />
            </>
          )}

          {/* PAGE: ASSIGNED STUDENTS (ADVISOR ONLY) */}
          {page === "assigned_students" && user.role === "advisor" && (
            <section className="panel">
              <h1>Danh sách sinh viên được phân công</h1>
              <p className="muted">Theo dõi kết quả học tập và hỗ trợ các sinh viên thuộc quyền phụ trách của bạn.</p>
              {students.map((s) => (
                <div key={s.id} className="status-row">
                  <div>
                    <strong>{s.student_code}</strong> · {s.full_name}
                    <br />
                    <small className="muted">Email: {s.email || 'Chưa cập nhật'}</small>
                  </div>
                  <button
                    onClick={() =>
                      void task(async () => {
                        setSummary(
                          await api(
                            "/students/" + s.id + "/academic-summary",
                          ),
                        );
                        navigate("academics");
                      })
                    }
                  >
                    Xem hồ sơ chi tiết →
                  </button>
                </div>
              ))}
              {students.length === 0 && (
                <p className="muted">Hiện tại chưa có sinh viên nào được phân công.</p>
              )}
            </section>
          )}
        </main>

        <footer>
          {PRODUCT_CONFIG.BRAND_NAME} · {PRODUCT_CONFIG.INSTITUTION_NAME}
          <span>{PRODUCT_CONFIG.TAGLINE}</span>
        </footer>
      </div>
    </div>
  );
}

function Metric({
  title,
  value,
  suffix,
}: {
  title: string;
  value: string;
  suffix: string;
}) {
  return (
    <section className="metric">
      <p>{title}</p>
      <strong>{value}</strong>
      <small>{suffix}</small>
    </section>
  );
}

function Calculator({
  title,
  fields,
  busy,
  onRun,
}: {
  title: string;
  fields: string[][];
  busy: boolean;
  onRun: (body: Record<string, string>) => Promise<void>;
}) {
  return (
    <section className="panel">
      <h3>{title}</h3>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void onRun(
            Object.fromEntries(
              new FormData(e.currentTarget).entries(),
            ) as Record<string, string>,
          );
        }}
      >
        {fields.map(([id, label, value, max]) => (
          <label key={id}>
            {label}
            <input
              name={id}
              type="number"
              min="0"
              max={max}
              step="0.000001"
              defaultValue={value}
              required
            />
          </label>
        ))}
        <button disabled={busy}>Thực hiện →</button>
      </form>
    </section>
  );
}

function Result({ data }: { data: any }) {
  const labels: Record<string, string> = {
    current_gpa: "GPA hiện tại",
    target_gpa: "GPA mục tiêu",
    required_future_gpa: "GPA cần đạt",
    required_score: "Điểm cần đạt",
    feasibility: "Khả thi",
    message: "Thông báo",
  };
  return (
    <section className="panel result" role="status">
      <h3>Kết quả tính toán mô phỏng</h3>
      {data.after && (
        <p className="result-number">
          {fmt(data.before.cumulative_gpa)} → {fmt(data.after.cumulative_gpa)}{" "}
          <small>GPA</small>
        </p>
      )}
      {Object.entries(labels)
        .filter(([k]) => k in data)
        .map(([k, label]) => {
          let val = data[k];
          if (val == null) {
            val = "Chưa đủ dữ liệu";
          } else if (k !== "feasibility" && k !== "message" && !isNaN(Number(val))) {
            val = fmt(val);
          }
          return (
            <div className="status-row" key={k}>
              <span>{label}</span>
              <strong>{val}</strong>
            </div>
          );
        })}
      <p className="muted" style={{ marginTop: '10px', fontSize: '12px' }}>
        {PRODUCT_CONFIG.ACADEMICS.WHAT_IF_DISCLOSURE}
      </p>
    </section>
  );
}

function AdminImport() {
  const [file, setFile] = useState<File | null>(null);
  const [importType, setImportType] = useState("enrollments");
  const [validated, setValidated] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [majors, setMajors] = useState<any[]>([]);
  const types = ["curricula", "cohorts", "semesters", "students", "courses", "curriculum_courses", "prerequisites", "offerings", "grade_components", "enrollments", "grade_component_scores"];

  async function refreshHistory() {
    try {
      setHistory(await importHistory());
    } catch {
      /* supplementary */
    }
  }

  async function refreshMajors() {
    try {
      const data = await api('/catalog/curricula');
      setMajors(data.items || []);
    } catch {
      /* optional — không block UI nếu lỗi */
    }
  }

  useEffect(() => {
    void refreshHistory();
    void refreshMajors();
  }, []);

  async function submit(dry: boolean) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const r = await uploadImport(importType, file, dry);
      setResult(r);
      setValidated(dry && r.status === "validated");
      if (!dry) void refreshHistory();
    } catch (e) {
      setError((e as Error).message);
      setValidated(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h3>Nhập dữ liệu học vụ CSV — Admin</h3>
      <p className="muted">
        CSV UTF-8 tối đa 1.000 dòng / 512 KB. Chế độ kiểm tra (dry-run) luôn chạy trước khi ghi dữ liệu chính thức.
      </p>
      <label>
        Loại danh mục import
        <select
          value={importType}
          onChange={(e) => {
            setImportType(e.target.value);
            setValidated(false);
            setResult(null);
          }}
        >
          {types.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </label>
      {(importType === 'curricula' || importType === 'students' || importType === 'cohorts') && majors.length > 0 && (
        <div style={{ background: 'var(--surface-2, #f0f4f8)', borderRadius: 8, padding: '10px 14px', marginTop: 4, marginBottom: 8 }}>
          <p style={{ margin: '0 0 6px', fontWeight: 600, fontSize: 13 }}>📋 Ngành đã có trong hệ thống:</p>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #ddd' }}>
                <th style={{ textAlign: 'left', padding: '3px 8px', fontWeight: 600 }}>Ngành</th>
                <th style={{ textAlign: 'left', padding: '3px 8px', fontWeight: 600 }}>Mã CT</th>
                <th style={{ textAlign: 'left', padding: '3px 8px', fontWeight: 600 }}>Phiên bản</th>
                <th style={{ textAlign: 'right', padding: '3px 8px', fontWeight: 600 }}>Tín chỉ</th>
              </tr>
            </thead>
            <tbody>
              {majors.map((m: any, i: number) => (
                <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: '3px 8px' }}>{m.major}{m.faculty ? ` — ${m.faculty}` : ''}</td>
                  <td style={{ padding: '3px 8px', fontFamily: 'monospace' }}>{m.code}</td>
                  <td style={{ padding: '3px 8px', fontFamily: 'monospace' }}>{m.version}</td>
                  <td style={{ padding: '3px 8px', textAlign: 'right' }}>{m.total_required_credits}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ margin: '6px 0 0', fontSize: 11 }}>Dùng mã CT và phiên bản này khi điền CSV (curriculum_code, curriculum_version).</p>
        </div>
      )}
      <button
        type="button"
        disabled={busy}
        onClick={() => void downloadImportTemplate(importType)}
      >
        Tải CSV template mẫu
      </button>
      <label>
        Tập tin CSV (UTF-8)
        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => {
            setFile(e.target.files?.[0] || null);
            setValidated(false);
            setResult(null);
          }}
        />
      </label>
      <div style={{ display: "flex", gap: 12 }}>
        <button disabled={!file || busy} onClick={() => void submit(true)}>
          1. Kiểm tra cấu trúc (Dry-run)
        </button>
        <button
          disabled={!validated || busy}
          onClick={() => void submit(false)}
        >
          2. Ghi dữ liệu đã thẩm định
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {result && (
        <div role="status" style={{ marginTop: '12px' }}>
          <p>
            Trạng thái: <strong>{result.status}</strong>{" "}
            {result.idempotent_replay
              ? "· Đã nạp trước đó, không ghi trùng"
              : ""}
          </p>
          {result.errors?.map((r: any) => (
            <p key={r.line} className="error">
              Dòng {r.line}: {r.code}
            </p>
          ))}
        </div>
      )}
      <h4>Lịch sử các đợt import gần đây</h4>
      {history.length === 0 ? (
        <p className="muted">Chưa có bản ghi import nào được lưu.</p>
      ) : (
        history.slice(0, 10).map((job) => (
          <p key={job.id} className="muted" style={{ margin: '4px 0' }}>
            {job.import_type}: <strong>{job.status}</strong> · {new Date(job.created_at).toLocaleString("vi-VN")}
          </p>
        ))
      )}
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
