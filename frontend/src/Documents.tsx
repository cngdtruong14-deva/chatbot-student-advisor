import React, { useEffect, useState } from 'react';
import { api, extractDocument } from './api';
import { PRODUCT_CONFIG } from './product-config';

const TOPIC_SUGGESTIONS = [
  'Điều kiện để sinh viên được xét công nhận tốt nghiệp',
  'Học bổng khuyến khích học tập cho sinh viên',
  'Chuẩn đầu ra tin học và ngoại ngữ',
  'Đánh giá kết quả rèn luyện sinh viên',
  'Nghỉ học tạm thời và bảo lưu kết quả học tập',
  'Quy định về học lại và đăng ký học phần',
];

export function Documents({ isAdmin = false }: { isAdmin?: boolean }) {
  // Admin state
  const [items, setItems] = useState<any[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [content, setContent] = useState('');
  const [notice, setNotice] = useState('');

  // Student / Reader state
  const [query, setQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searched, setSearched] = useState(false);

  async function refreshAdmin() {
    if (!isAdmin) return;
    try {
      const res = await api('/admin/documents');
      setItems(res.items);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    if (isAdmin) {
      void refreshAdmin();
    }
  }, [isAdmin]);

  async function handleAdminAction(id: string, name: 'ingest' | 'activate') {
    setBusy(true);
    setError('');
    try {
      const r = await api(`/admin/documents/${id}/${name}`, {}, 'POST');
      setNotice(`${name === 'ingest' ? 'Đã xử lý cấu trúc' : 'Đã kích hoạt vào kho'} bản ${r.id}. Trạng thái: ${r.status}.`);
      await refreshAdmin();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleSearch(searchTerm?: string) {
    const text = (searchTerm || query).trim();
    if (!text) return;
    setBusy(true);
    setError('');
    setSearched(true);
    try {
      const res = await api('/knowledge/search', {
        query: text,
        corpus_scope: 'utt_corpus',
      });
      setSearchResults(res.citations || []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin) {
    return (
      <section className="panel">
        <div style={{ marginBottom: '16px' }}>
          <h1 style={{ marginBottom: '4px' }}>Kho tài liệu pilot</h1>
          <p className="muted" style={{ margin: 0 }}>
            {PRODUCT_CONFIG.CORPUS_DISCLOSURE} Tra cứu nhanh các văn bản quy chế, biểu mẫu và hướng dẫn học vụ thuộc kho {PRODUCT_CONFIG.CORPUS_NAME}.
          </p>
          <p className="muted" style={{ margin: '6px 0 0' }}>{PRODUCT_CONFIG.PILOT_DISCLOSURE}</p>
        </div>

        <form onSubmit={e => { e.preventDefault(); void handleSearch(); }} style={{ marginBottom: '16px' }}>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Nhập từ khóa hoặc câu hỏi cần tra cứu quy chế..."
              disabled={busy}
              style={{ flex: 1 }}
            />
            <button disabled={busy || !query.trim()}>
              {busy ? 'Đang tìm…' : 'Tra cứu ↗'}
            </button>
          </div>
        </form>

        <div style={{ marginBottom: '20px' }}>
          <small style={{ display: 'block', marginBottom: '8px', color: '#64748b', fontWeight: 600 }}>Chủ đề quy chế thường gặp:</small>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {TOPIC_SUGGESTIONS.map((topic, i) => (
              <button
                key={i}
                type="button"
                className="chip-btn"
                disabled={busy}
                onClick={() => { setQuery(topic); void handleSearch(topic); }}
              >
                {topic}
              </button>
            ))}
          </div>
        </div>

        {error && <p role="alert" className="error">{error}</p>}

        {searched && (
          <div>
            <h3>Kết quả tra cứu ({searchResults.length} trích đoạn phù hợp)</h3>
            {searchResults.length === 0 && (
              <p className="muted">Không tìm thấy tài liệu phù hợp với từ khóa đã nhập. Bạn hãy thử từ khóa ngắn gọn hơn hoặc chọn các chủ đề gợi ý phía trên.</p>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {searchResults.map((c: any, i: number) => {
                const sourceUrl = /^https?:\/\//i.test(c.source)
                  ? c.source
                  : (typeof c.source === 'string' && c.source.startsWith('gdrive:') ? `https://drive.google.com/file/d/${c.source.slice(7)}/view` : null);
                const effectivity = c.is_effective_date_verified
                  ? `Hiệu lực: ${c.effective_from || '—'} đến ${c.effective_until || '—'}`
                  : 'Đang áp dụng trong kho quy chế hiện hành';
                return (
                  <article key={c.chunk_id || i} style={{ padding: '12px 14px', border: '1px solid #e2e8f0', borderRadius: '8px', background: '#f8fafc' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
                      <h4 style={{ margin: 0, color: '#0f172a' }}>{c.title || 'Văn bản trong kho pilot'}</h4>
                      {c.section && <span className="pill">{c.section}</span>}
                    </div>
                    <p style={{ margin: '6px 0', fontSize: '0.94em', color: '#334155', whiteSpace: 'pre-wrap' }}>{c.excerpt}</p>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px', fontSize: '0.85em', color: '#64748b', flexWrap: 'wrap', gap: '8px' }}>
                      <span>{effectivity}</span>
                      {sourceUrl ? (
                        <a href={sourceUrl} target="_blank" rel="noopener noreferrer" style={{ color: '#0284c7', textDecoration: 'underline', fontWeight: 500 }}>
                          Mở văn bản gốc ↗
                        </a>
                      ) : (
                        <span>Nguồn: {c.source}</span>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        )}

        <div style={{ marginTop: '24px', padding: '12px 16px', background: '#eff6ff', borderRadius: '8px', border: '1px solid #bfdbfe', fontSize: '13px', color: '#1e40af' }}>
          <strong>Lưu ý quan trọng:</strong> {PRODUCT_CONFIG.CHAT.HIGH_STAKES_WARNING}
        </div>
      </section>
    );
  }

  // Admin view
  return (
    <section className="panel">
      <h1>Quản lý kho tài liệu & Ingestion — Admin</h1>
      <p className="muted">
        Quản lý tài liệu và các bản phát hành kho tri thức. Kho pilot hiện tại: <strong>{PRODUCT_CONFIG.CORPUS_NAME}</strong>.
      </p>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status">{notice}</p>}

      <form onSubmit={async e => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        setBusy(true);
        setError('');
        try {
          const r = await api('/admin/documents', {
            title: f.get('title'),
            source: f.get('source'),
            version: f.get('version'),
            document_type: f.get('document_type'),
            content,
            valid_from: f.get('valid_from'),
            valid_until: f.get('valid_until'),
            corpus_scope: f.get('corpus_scope'),
            ...(f.get('document_id') ? { document_id: f.get('document_id') } : {})
          });
          setNotice(`Đã lưu bản ${r.id}. Trạng thái: ${r.status}.`);
          await refreshAdmin();
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}>
        <label>Tài liệu
          <select name="document_id">
            <option value="">Tài liệu mới</option>
            {Array.from(new Map(items.map(i => [i.document_id, i])).values()).map(i => (
              <option key={i.document_id} value={i.document_id}>{i.title}</option>
            ))}
          </select>
        </label>
        <label>Tiêu đề<input name="title" required maxLength={200} /></label>
        <label>Nguồn<input name="source" required maxLength={500} placeholder="Ví dụ: Quyết định số 123/QĐ-ĐHCNGTVT" /></label>
        <label>Kho tài liệu
          <select name="corpus_scope" defaultValue="demo_academic">
            <option value="demo_academic">Học vụ mẫu (demo_academic) · synthetic</option>
            <option value="utt_test">UTT-test · tài liệu thử nghiệm</option>
          </select>
        </label>
        <label>Phiên bản<input name="version" required defaultValue="1" maxLength={80} /></label>
        <label>Loại
          <select name="document_type">
            <option value="policy">Chính sách</option>
            <option value="procedure">Thủ tục</option>
            <option value="guide">Hướng dẫn</option>
          </select>
        </label>
        <label>Hiệu lực từ<input name="valid_from" type="date" required defaultValue={new Date().toISOString().slice(0, 10)} /></label>
        <label>Hiệu lực đến (không bao gồm)<input name="valid_until" type="date" required defaultValue="9999-12-31" /></label>
        <label>Nạp TXT, Markdown, PDF, DOCX hoặc ảnh scan (PNG, JPG)
          <input
            type="file"
            accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/png,image/jpeg"
            onChange={async e => {
              const file = e.target.files?.[0];
              if (!file) return;
              setBusy(true);
              setError('');
              setNotice('');
              try {
                if (/\.(txt|md)$/i.test(file.name)) {
                  if (file.size > 400000) throw new Error('TXT/MD tối đa 400 KB.');
                  const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
                  if (text.length > 100000) throw new Error('Giới hạn 100.000 ký tự.');
                  setContent(text);
                  setNotice(`Đã đọc ${file.name}. Hãy kiểm tra nội dung trước khi lưu.`);
                } else if (/\.(pdf|docx|png|jpe?g)$/i.test(file.name)) {
                  if (file.size > 5 * 1024 * 1024) throw new Error('Tài liệu hoặc ảnh tối đa 5 MB.');
                  const extracted = await extractDocument(file);
                  setContent(extracted.content);
                  setNotice(`Đã trích xuất ${extracted.character_count} ký tự từ ${file.name}. Hãy kiểm tra nội dung trước khi lưu.${extracted.warnings?.length ? ' ' + extracted.warnings.join(' ') : ''}`);
                } else {
                  throw new Error('Chỉ hỗ trợ TXT, MD, PDF, DOCX và hình ảnh (PNG, JPG).');
                }
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          />
        </label>
        <label>Nội dung / xem trước
          <textarea rows={10} required maxLength={100000} value={content} onChange={e => setContent(e.target.value)} />
        </label>
        <button disabled={busy}>Lưu bản nháp</button>
      </form>

      <h2>Tài liệu đã đăng ký trong kho</h2>
      <button disabled={busy} onClick={() => void refreshAdmin()}>Cập nhật danh sách</button>
      {items.map(i => (
        <article key={i.id} style={{ marginTop: '12px', padding: '12px', border: '1px solid #e2e8f0', borderRadius: '6px' }}>
          <h3>{i.title} · Phiên bản {i.version}</h3>
          <p>
            <span className="badge">{i.corpus_label || i.scope_key}</span> Trạng thái: {i.status} · {i.chunk_count} đoạn trích · Hiệu lực: {i.valid_from} → {i.valid_until}
          </p>
          {i.review_state === 'test_only' && (
            <p className="error">UTT-test: tài liệu thử nghiệm người dùng cung cấp; kiểm tra hiệu lực trước khi sử dụng.</p>
          )}
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            {(i.status === 'pending' || i.status === 'failed') && (
              <button disabled={busy} onClick={() => void handleAdminAction(i.id, 'ingest')}>
                1. Xử lý thành đoạn trích
              </button>
            )}
            {i.status === 'ready' && (
              <button disabled={busy} onClick={() => void handleAdminAction(i.id, 'activate')}>
                2. Kích hoạt vào kho tri thức
              </button>
            )}
          </div>
        </article>
      ))}
    </section>
  );
}
