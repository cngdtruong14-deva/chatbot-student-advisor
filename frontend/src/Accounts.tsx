import React, { useEffect, useState } from 'react';
import { api } from './api';
import type { CurriculumCatalog, OneTimeAccountCode, PersonalAccountProfile, ProfileSaveResult, RecoveryResult, RegistrationResult } from './generated-api';

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
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  useEffect(() => { let active = true; api<PersonalAccountProfile | null>('/account/profile').then(p => {
    if (active && p) setValues({ display_name: p.display_name, major: p.major, cohort: p.cohort });
  }).catch(e => { if (active) setMessage(e.message); }); return () => { active = false; }; }, []);
  useEffect(() => { let active = true; api<CurriculumCatalog>('/catalog/curricula').then(result => {
    if (active) setCurricula(result.items);
  }).catch(e => { if (active) setMessage(e.message); }); return () => { active = false; }; }, []);
  const knownMajor = !values.major || curricula.some(item => item.major === values.major);
  return <section className="panel"><h2>Hồ sơ cá nhân</h2>
    <p>Thông tin tự khai, chưa được trường xác minh. Sau khi lưu, bạn có thể nhập bảng điểm cá nhân để tính GPA và mô phỏng mục tiêu.</p>
    <form onSubmit={async e => { e.preventDefault(); setBusy(true); try {
      await api<ProfileSaveResult>('/account/profile', values, 'PUT'); setMessage('Đã lưu hồ sơ cá nhân.');
    } catch (err) { setMessage((err as Error).message); } finally { setBusy(false); } }}>
      <label>Tên hiển thị<input required maxLength={120} value={values.display_name} onChange={e => setValues({...values, display_name: e.target.value})} /></label>
      <label>Ngành
        <select value={values.major} onChange={e => setValues({...values, major: e.target.value})}>
          <option value="">Chọn ngành trong danh mục</option>
          {!knownMajor && <option value={values.major}>{values.major} (giá trị hồ sơ cũ)</option>}
          {curricula.map(item => <option key={item.id} value={item.major}>
            {item.major}{item.faculty ? ` — Khoa ${item.faculty}` : ''} — {item.code}/{item.version}
          </option>)}
        </select>
      </label>
      {!knownMajor && <p className="muted">Ngành đã lưu không còn trong danh mục. Hãy chọn lại trước khi cập nhật hồ sơ.</p>}
      <label>Khóa (tự khai)<input maxLength={60} value={values.cohort} onChange={e => setValues({...values, cohort: e.target.value})} /></label>
      <button disabled={busy}>Lưu hồ sơ</button>
    </form><p role="status">{message}</p></section>;
}

export function AdminAccounts() {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const [secret, setSecret] = useState('');
  async function perform(path: string) {
    setBusy(true); setSecret(''); setMessage('');
    try { const r = await api<OneTimeAccountCode>(path, {}); setSecret(r.code); setMessage('Hết hạn: ' + r.expires_at); }
    catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel"><h2>Tài khoản pilot</h2>
    <button disabled={busy} onClick={() => void perform('/admin/account-invites')}>Tạo mã mời một lần (7 ngày)</button>
    <form onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget);
      void perform('/admin/accounts/' + encodeURIComponent(String(f.get('user_id'))) + '/recovery'); }}>
      <label>User UUID của sinh viên<input name="user_id" required /></label>
      <label><input type="checkbox" required /> Tôi đã xác minh chủ tài khoản qua kênh riêng; thao tác sẽ thu hồi phiên hiện tại.</label>
      <button disabled={busy}>Cấp mã khôi phục (30 phút)</button>
    </form>
    {secret && <div><p>Mã chỉ hiển thị lần này, gửi qua kênh riêng; không lưu vào log hoặc chat:</p><code>{secret}</code><button onClick={() => setSecret('')}>Ẩn mã</button></div>}
    <p role="status">{message}</p></section>;
}
