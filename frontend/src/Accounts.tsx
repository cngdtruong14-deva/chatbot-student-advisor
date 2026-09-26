import React, { useEffect, useState } from 'react';
import { api } from './api';
import type { CohortCatalog, CurriculumCatalog, OneTimeAccountCode, PersonalAccountProfile, ProfileSaveResult, RecoveryResult, RegistrationResult } from './generated-api';

export function AccountRegistration() {
  const [mode, setMode] = useState('register');
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  return <details><summary>Đăng ký pilot / Khôi phục mật khẩu</summary>
    <button type="button" onClick={() => { setMode(mode === 'register' ? 'recover' : 'register'); setMessage(''); }} disabled={busy}>
      {mode === 'register' ? 'Tôi có mã khôi phục' : 'Đăng ký bằng mã mời'}</button>
    <p>Không cần email. Mật khẩu 12–256 ký tự. Liên hệ admin để nhận mã mời hoặc xác minh yêu cầu khôi phục; không gửi mật khẩu vào chat.</p>
    <form key={mode} onSubmit={async e => {
      e.preventDefault(); const form = e.currentTarget, f = new FormData(form);
      if (f.get('password') !== f.get('confirm')) { setMessage('Hai mật khẩu không khớp'); return; }
      setBusy(true); setMessage('');
      try {
        await api<RegistrationResult | RecoveryResult>('/auth/' + mode, mode === 'register'
          ? { username: f.get('username'), password: f.get('password'), invite_code: f.get('code') }
          : { code: f.get('code'), password: f.get('password') });
        form.reset(); setMessage('Thành công. Hãy đăng nhập bằng mật khẩu mới.');
      } catch (err) { setMessage((err as Error).message); } finally { setBusy(false); }
    }}>
      {mode === 'register' && <label>Tên đăng nhập<input name="username" required pattern="[a-zA-Z0-9_]{3,32}" autoComplete="username" /></label>}
      <label>{mode === 'register' ? 'Mã mời' : 'Mã khôi phục'}<input name="code" required autoComplete="off" /></label>
      <label>Mật khẩu mới<input name="password" type="password" minLength={12} maxLength={256} required autoComplete="new-password" /></label>
      <label>Nhập lại mật khẩu<input name="confirm" type="password" required autoComplete="new-password" /></label>
      <button disabled={busy}>{busy ? 'Đang xử lý…' : 'Xác nhận'}</button>
    </form><p role="status">{message}</p>
  </details>;
}

export function PersonalOnboarding() {
  const [values, setValues] = useState({ display_name: '', major: '', cohort: '' });
  const [curricula, setCurricula] = useState<CurriculumCatalog['items']>([]);
  const [cohorts, setCohorts] = useState<CohortCatalog['items']>([]);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  useEffect(() => { let active = true; api<PersonalAccountProfile | null>('/account/profile').then(p => {
    if (active && p) setValues({ display_name: p.display_name, major: p.major, cohort: p.cohort });
  }).catch(e => { if (active) setMessage(e.message); }); return () => { active = false; }; }, []);
  useEffect(() => { let active = true; Promise.all([
    api<CurriculumCatalog>('/catalog/curricula'), api<CohortCatalog>('/catalog/cohorts'),
  ]).then(([curriculumResult, cohortResult]) => {
    if (active) { setCurricula(curriculumResult.items); setCohorts(cohortResult.items); }
  }).catch(e => { if (active) setMessage(e.message); }); return () => { active = false; }; }, []);
  const knownMajor = !values.major || curricula.some(item => item.major === values.major);
  const selectedCurriculumIds = new Set(curricula.filter(item => item.major === values.major).map(item => item.id));
  const compatibleCohorts = cohorts.filter(item => selectedCurriculumIds.has(item.curriculum_id));
  const normalizedCohort = values.cohort.toUpperCase();
  const knownCohort = !normalizedCohort || compatibleCohorts.some(item => item.code === normalizedCohort);
  return <section className="panel"><h2>Hồ sơ cá nhân</h2>
    <p>Thông tin tự khai, chưa được trường xác minh. Sau khi lưu, bạn có thể nhập bảng điểm cá nhân để tính GPA và mô phỏng mục tiêu.</p>
    <form onSubmit={async e => { e.preventDefault(); setBusy(true); try {
      await api<ProfileSaveResult>('/account/profile', values, 'PUT'); setMessage('Đã lưu hồ sơ cá nhân.');
    } catch (err) { setMessage((err as Error).message); } finally { setBusy(false); } }}>
      <label>Tên hiển thị<input required maxLength={120} value={values.display_name} onChange={e => setValues({...values, display_name: e.target.value})} /></label>
      <label>Ngành
        <select value={values.major} onChange={e => setValues({...values, major: e.target.value, cohort: ''})}>
          <option value="">Chọn ngành trong danh mục</option>
          {!knownMajor && <option value={values.major}>{values.major} (giá trị hồ sơ cũ)</option>}
          {curricula.map(item => <option key={item.id} value={item.major}>
            {item.major}{item.faculty ? ` — Khoa ${item.faculty}` : ''} — {item.code}/{item.version}
          </option>)}
        </select>
      </label>
      {!knownMajor && <p className="muted">Ngành đã lưu không còn trong danh mục. Hãy chọn lại trước khi cập nhật hồ sơ.</p>}
      <label>Khóa (tự khai, chờ admin xác nhận)
        <select required={Boolean(values.major)} disabled={!values.major} value={normalizedCohort} onChange={e => setValues({...values, cohort: e.target.value})}>
          <option value="">{values.major ? 'Chọn khóa thuộc chương trình' : 'Chọn ngành trước'}</option>
          {!knownCohort && <option value={normalizedCohort}>{values.cohort} (giá trị cũ — cần chọn lại)</option>}
          {compatibleCohorts.map(item => <option key={item.id} value={item.code}>{item.code}</option>)}
        </select>
      </label>
      {values.major && !compatibleCohorts.length && <p className="error">Chương trình chưa có khóa được quản trị viên công bố.</p>}
      <p className="muted">Khóa tự khai sẽ hiển thị cho admin đối chiếu; chưa tự tạo hồ sơ học vụ hoặc xác minh điểm.</p>
      <button disabled={busy}>Lưu hồ sơ</button>
    </form><p role="status">{message}</p></section>;
}

export function AdminAccounts() {
  type AdminAccount = {
    id: string; username: string | null; email: string; role: 'student' | 'advisor' | 'admin'; is_active: boolean;
    display_name: string | null; self_reported_major: string | null; self_reported_cohort: string | null;
    personal_transcript_revision: number; student_id: string | null; student_code: string | null; full_name: string | null;
    curriculum_id: string | null; curriculum_code: string | null; curriculum_version: string | null;
    curriculum_major: string | null; cohort_id: string | null; cohort_code: string | null; advisor_count: number;
  };
  type Cohort = { id: string; code: string; curriculum_id: string; curriculum_code: string; curriculum_version: string; major: string };
  type Assignment = { advisor_user_id: string; advisor_name: string; student_id: string; student_code: string; student_name: string };
  type AuditItem = { id: string; action: string; created_at: string; actor: string | null; subject: string | null };
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const [secret, setSecret] = useState(''), [query, setQuery] = useState('');
  const [accounts, setAccounts] = useState<AdminAccount[]>([]), [cohorts, setCohorts] = useState<Cohort[]>([]);
  const [curricula, setCurricula] = useState<CurriculumCatalog['items']>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]), [auditItems, setAuditItems] = useState<AuditItem[]>([]);
  const [selectedId, setSelectedId] = useState(''), [advisorId, setAdvisorId] = useState(''), [studentId, setStudentId] = useState('');
  const [link, setLink] = useState({ student_code: '', full_name: '', curriculum_id: '', cohort_id: '', confirmed: false });
  async function refresh() {
    const [a, c, cur, assigned, audit] = await Promise.all([
      api<{items: AdminAccount[]}>('/admin/accounts'), api<{items: Cohort[]}>('/admin/cohorts'),
      api<CurriculumCatalog>('/catalog/curricula'), api<{items: Assignment[]}>('/admin/advisor-assignments'),
      api<{items: AuditItem[]}>('/admin/account-audit?limit=30'),
    ]);
    setAccounts(a.items); setCohorts(c.items); setCurricula(cur.items); setAssignments(assigned.items); setAuditItems(audit.items);
  }
  useEffect(() => { refresh().catch(e => setMessage(e.message)); }, []);
  const selected = accounts.find(item => item.id === selectedId) || null;
  const students = accounts.filter(item => item.role === 'student');
  const advisors = accounts.filter(item => item.role === 'advisor' && item.is_active);
  const visible = accounts.filter(item => {
    const text = [item.username, item.email, item.display_name, item.student_code, item.full_name].filter(Boolean).join(' ').toLowerCase();
    return text.includes(query.trim().toLowerCase());
  });
  const compatibleCohorts = cohorts.filter(item => item.curriculum_id === link.curriculum_id);
  const selectedCatalogCohort = cohorts.find(item => item.id === link.cohort_id);
  const linkBlockingReason = !link.student_code.trim() ? 'Nhập mã sinh viên.'
    : !link.full_name.trim() ? 'Nhập họ tên hồ sơ học vụ.'
    : !link.curriculum_id ? 'Chọn chương trình.'
    : !compatibleCohorts.length ? 'Chương trình chưa có khóa hợp lệ trong catalog.'
    : !link.cohort_id ? 'Chọn khóa cần xác nhận.'
    : selectedCatalogCohort?.curriculum_id !== link.curriculum_id ? 'Khóa không thuộc chương trình đã chọn.'
    : !link.confirmed ? 'Đánh dấu xác nhận sau khi đã đối chiếu thông tin.' : '';
  useEffect(() => {
    if (!selected || selected.role !== 'student') return;
    const reportedCohort = (selected.self_reported_cohort || '').trim().toUpperCase();
    // Cohort codes are globally unique in the reviewed catalog. Let the cohort
    // row identify its owning curriculum; the self-reported major is display
    // text and may differ in whitespace/normalisation from catalog metadata.
    const reportedCatalogCohort = cohorts.find(item => item.code.toUpperCase() === reportedCohort);
    const preferredCurriculum = selected.curriculum_id || reportedCatalogCohort?.curriculum_id
      || curricula.find(item => item.major === selected.self_reported_major)?.id || curricula[0]?.id || '';
    const preferredCohort = selected.cohort_id || cohorts.find(item => item.curriculum_id === preferredCurriculum && item.code.toUpperCase() === reportedCohort)?.id || '';
    setLink({ student_code: selected.student_code || '', full_name: selected.full_name || selected.display_name || '',
      curriculum_id: preferredCurriculum, cohort_id: preferredCohort, confirmed: false });
  }, [selectedId, accounts.length, cohorts.length, curricula.length]);
  async function perform(path: string) {
    setBusy(true); setSecret(''); setMessage('');
    try { const r = await api<OneTimeAccountCode>(path, {}); setSecret(r.code); setMessage('Hết hạn: ' + r.expires_at); }
    catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  async function mutate(action: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage('');
    try { await action(); await refresh(); setMessage(success); }
    catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  const actionLabel: Record<string,string> = {
    registered: 'Đăng ký tài khoản', profile_updated: 'Cập nhật hồ sơ tự khai', personal_transcript_saved: 'Lưu bảng điểm tự khai',
    recovery_issued: 'Cấp mã khôi phục', academic_profile_linked: 'Liên kết hồ sơ học vụ',
    advisor_assigned: 'Phân công cố vấn', advisor_unassigned: 'Hủy phân công cố vấn', invite_created: 'Tạo mã mời',
  };
  return <div className="admin-account-workspace">
    <section className="panel"><h2>Phạm vi quyền quản trị</h2>
      <div className="permission-grid">
        <div><strong>Admin</strong><span>Tạo tài khoản, khôi phục, liên kết hồ sơ, phân công cố vấn, quản trị tài liệu.</span></div>
        <div><strong>Cố vấn</strong><span>Chỉ xem sinh viên được phân công; không liên kết tài khoản hoặc sửa bảng điểm.</span></div>
        <div><strong>Sinh viên</strong><span>Chỉ xem dữ liệu của mình; dữ liệu tự khai tách biệt dữ liệu trường.</span></div>
      </div>
      <p className="muted">Liên kết chỉ tạo hồ sơ pilot synthetic cho đúng tài khoản. Hệ thống không chuyển hồ sơ đã thuộc tài khoản khác và không nâng điểm tự khai thành điểm trường xác minh.</p>
    </section>

    <section className="panel"><h2>Cấp quyền truy cập pilot</h2>
      <button disabled={busy} onClick={() => void perform('/admin/account-invites')}>Tạo mã mời một lần (7 ngày)</button>
      {secret && <div className="one-time-secret"><p>Mã chỉ hiển thị lần này, gửi qua kênh riêng; không lưu vào log hoặc chat:</p><code>{secret}</code><button onClick={() => setSecret('')}>Ẩn mã</button></div>}
    </section>

    <section className="panel"><div className="section-heading"><div><h2>Tài khoản và trạng thái hồ sơ</h2><p className="muted">Chọn một tài khoản sinh viên để khôi phục hoặc liên kết hồ sơ học vụ.</p></div>
      <button disabled={busy} onClick={() => void refresh().catch(e => setMessage(e.message))}>Làm mới</button></div>
      <label>Tìm theo tên đăng nhập, tên, email hoặc mã sinh viên<input value={query} onChange={e => setQuery(e.target.value)} placeholder="Nhập từ khóa…" /></label>
      <div className="table-wrap"><table><thead><tr><th>Tài khoản</th><th>Vai trò</th><th>Hồ sơ tự khai</th><th>Hồ sơ học vụ</th><th></th></tr></thead><tbody>
        {visible.map(item => <tr key={item.id}><td><strong>{item.username || item.email}</strong><small>{item.display_name || item.email}</small></td>
          <td><span className="pill">{item.role}</span>{!item.is_active && <small>Đã khóa</small>}</td>
          <td>{item.role === 'student' ? <>{item.personal_transcript_revision > 0 ? `Đã lưu · rev ${item.personal_transcript_revision}` : item.display_name ? 'Có hồ sơ, chưa có bảng điểm' : 'Chưa có'}</> : '—'}</td>
          <td>{item.student_id ? <><strong>{item.student_code}</strong><small>{item.curriculum_code}/{item.curriculum_version} · {item.cohort_code}</small></> : item.role === 'student' ? 'Chưa liên kết' : '—'}</td>
          <td>{item.role === 'student' && <button type="button" className="secondary" onClick={() => setSelectedId(item.id)}>Quản lý</button>}</td></tr>)}
      </tbody></table></div>
    </section>

    {selected && <section className="panel"><h2>Quản lý sinh viên: {selected.username || selected.email}</h2>
      <div className="status-strip"><div><span>Hồ sơ tự khai</span><strong>{selected.display_name || 'Chưa có'}</strong><small>{selected.self_reported_major || 'Chưa chọn ngành'} · {selected.self_reported_cohort || 'Chưa khai khóa'}</small></div>
        <div><span>Bảng điểm tự khai</span><strong>{selected.personal_transcript_revision > 0 ? `Phiên bản ${selected.personal_transcript_revision}` : 'Chưa lưu'}</strong><small>Không tự động chuyển thành dữ liệu trường</small></div>
        <div><span>Liên kết học vụ</span><strong>{selected.student_code || 'Chưa liên kết'}</strong><small>{selected.curriculum_major || 'Chưa có chương trình'}</small></div></div>
      <details><summary>Khôi phục mật khẩu</summary><p>Chỉ thực hiện sau khi xác minh chủ tài khoản qua kênh riêng. Tất cả phiên hiện tại sẽ bị thu hồi.</p>
        <form onSubmit={e => { e.preventDefault(); void perform('/admin/accounts/' + encodeURIComponent(selected.id) + '/recovery'); }}>
          <label><input type="checkbox" required /> Tôi đã xác minh đúng chủ tài khoản.</label><button disabled={busy}>Cấp mã khôi phục (30 phút)</button></form></details>
      {!selected.student_id ? <form onSubmit={e => { e.preventDefault(); void mutate(() => api('/admin/accounts/' + encodeURIComponent(selected.id) + '/academic-profile', {
          student_code: link.student_code, full_name: link.full_name, curriculum_id: link.curriculum_id, cohort_id: link.cohort_id,
          confirmation: 'LINK_ACADEMIC_PROFILE',
        }), 'Đã liên kết hồ sơ học vụ. Sinh viên có thể dùng dữ liệu trường sau khi đăng nhập lại/làm mới.'); }}>
        <h3>Liên kết hồ sơ học vụ pilot</h3>
        <p className="muted">Sinh viên tự khai: <strong>{selected.self_reported_major || 'chưa chọn ngành'} · {selected.self_reported_cohort || 'chưa chọn khóa'}</strong>. Admin phải đối chiếu rồi mới tạo hồ sơ học vụ synthetic.</p>
        <label>Mã sinh viên<input required pattern="[A-Za-z0-9_-]+" value={link.student_code} onChange={e => setLink({...link, student_code: e.target.value.toUpperCase()})} /></label>
        <label>Họ tên hồ sơ học vụ<input required value={link.full_name} onChange={e => setLink({...link, full_name: e.target.value})} /></label>
        <label>Chương trình<select required value={link.curriculum_id} onChange={e => setLink({...link, curriculum_id: e.target.value, cohort_id: ''})}>
          <option value="">Chọn chương trình</option>{curricula.map(item => <option key={item.id} value={item.id}>{item.major} — {item.code}/{item.version}</option>)}</select></label>
        <label>Khóa thuộc chương trình<select required value={link.cohort_id} onChange={e => {
          const cohort = cohorts.find(item => item.id === e.target.value);
          setLink({...link, cohort_id: e.target.value, curriculum_id: cohort?.curriculum_id || link.curriculum_id});
        }}>
          <option value="">Chọn khóa</option>{cohorts.map(item => <option key={item.id} value={item.id}>{item.code}</option>)}</select></label>
        {link.curriculum_id && !compatibleCohorts.length && <p className="error">Chương trình này chưa có khóa hợp lệ trong catalog. Hãy import/tạo cohort trước khi liên kết.</p>}
        <label><input type="checkbox" checked={link.confirmed} onChange={e => setLink({...link, confirmed: e.target.checked})} required /> Tôi đã đối chiếu tài khoản, mã sinh viên, chương trình và khóa.</label>
        {linkBlockingReason && <p className="muted" role="status">Để liên kết: {linkBlockingReason}</p>}
        <button disabled={busy || Boolean(linkBlockingReason)}>Liên kết hồ sơ</button>
      </form> : <p className="success"><strong>Đã liên kết:</strong> {selected.student_code} · {selected.full_name} · {selected.curriculum_code}/{selected.curriculum_version} · {selected.cohort_code}. Không cho phép ghi đè hoặc chuyển quyền tự động.</p>}
    </section>}

    <section className="panel"><h2>Phân công cố vấn</h2><p className="muted">Cố vấn chỉ xem được hồ sơ chính thức của sinh viên đã được phân công.</p>
      <form className="inline-admin-form" onSubmit={e => { e.preventDefault(); void mutate(() => api('/admin/advisor-assignments', { advisor_user_id: advisorId, student_id: studentId }), 'Đã phân công cố vấn.'); }}>
        <label>Cố vấn<select required value={advisorId} onChange={e => setAdvisorId(e.target.value)}><option value="">Chọn cố vấn</option>{advisors.map(a => <option key={a.id} value={a.id}>{a.username || a.email}</option>)}</select></label>
        <label>Sinh viên đã liên kết<select required value={studentId} onChange={e => setStudentId(e.target.value)}><option value="">Chọn sinh viên</option>{students.filter(s => s.student_id).map(s => <option key={s.student_id!} value={s.student_id!}>{s.student_code} — {s.full_name}</option>)}</select></label>
        <button disabled={busy}>Phân công</button>
      </form>
      <div className="table-wrap"><table><thead><tr><th>Cố vấn</th><th>Sinh viên</th><th></th></tr></thead><tbody>{assignments.map(item => <tr key={item.advisor_user_id + item.student_id}>
        <td>{item.advisor_name}</td><td><strong>{item.student_code}</strong><small>{item.student_name}</small></td><td><button className="secondary" disabled={busy} onClick={() => void mutate(() => api('/admin/advisor-assignments/' + item.advisor_user_id + '/' + item.student_id, undefined, 'DELETE'), 'Đã hủy phân công.')}>Hủy phân công</button></td>
      </tr>)}</tbody></table></div>
    </section>

    <section className="panel"><h2>Nhật ký quản trị tài khoản gần đây</h2><div className="table-wrap"><table><thead><tr><th>Thời gian</th><th>Thao tác</th><th>Admin/actor</th><th>Đối tượng</th></tr></thead><tbody>
      {auditItems.map(item => <tr key={item.id}><td>{new Date(item.created_at).toLocaleString('vi-VN')}</td><td>{actionLabel[item.action] || item.action}</td><td>{item.actor || 'Hệ thống'}</td><td>{item.subject || '—'}</td></tr>)}
    </tbody></table></div></section>
    <p role="status" className={message.startsWith('Đã') ? 'success' : ''}>{message}</p>
  </div>;
}
