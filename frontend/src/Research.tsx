import React, { useEffect, useState } from 'react';
import { api, ApiError } from './api';

type ResearchCase = {
  id: string;
  source_case_key: string;
  domain_id: 'oulad' | 'academic_demo_v2';
  data_origin: 'public_dataset' | 'synthetic';
};

type Dashboard = {
  expected_case_count: number;
  case_count: number;
  snapshot_count: number;
  prediction_count: number;
  at_risk_count: number;
  not_at_risk_count: number;
  average_probability: number | null;
  coverage_status: 'complete' | 'partial' | 'empty';
  model_versions: Array<{ model_id: string; model_version: string; manifest_sha256: string; prediction_count: number }>;
  limitations: string[];
};

const domainLabel = (item: ResearchCase) => item.domain_id === 'academic_demo_v2'
  ? 'Academic Demo v2 · synthetic research model'
  : 'OULAD · public research dataset';

export function Research({ isAdmin = false }: { isAdmin?: boolean }) {
  const [cases, setCases] = useState<ResearchCase[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [result, setResult] = useState<any>(null);
  const [explanation, setExplanation] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api('/research-cases?limit=100').then(r => setCases(r.items)).catch(e => setError(e.message));
    if (isAdmin) api('/admin/research/dashboard').then(setDashboard).catch(e => setError(e.message));
  }, [isAdmin]);
  useEffect(() => { setExplanation(null); }, [result]);

  async function predict(item: ResearchCase) {
    setBusy(true); setError(''); setResult(null);
    try {
      setResult(await api(`/research-cases/${item.id}/predictions`, {}));
    } catch (e) {
      if (e instanceof ApiError && e.code === 'NOT_APPLICABLE') {
        setError('Research case này không tương thích với model đang hoạt động. Không có dự đoán được tạo.');
      } else setError((e as Error).message);
    } finally { setBusy(false); }
  }

  return <section className="panel">
    <h2>Mô hình nghiên cứu tách biệt</h2>
    <p>Inference chỉ chạy cho research case khớp domain, schema, cutoff và feature order. Hồ sơ sinh viên thật không được tự động chấm rủi ro.</p>
    {error && <p role="alert" className="error">{error}</p>}

    {dashboard && <section aria-label="Tổng hợp Academic Demo v2" className="numeric-card">
      <span className="badge">SYNTHETIC RESEARCH MODEL</span>
      <h3>Academic Demo v2 · mức bao phủ {dashboard.coverage_status}</h3>
      <p>{dashboard.case_count}/{dashboard.expected_case_count} research cases · {dashboard.snapshot_count} snapshots · {dashboard.prediction_count} predictions</p>
      <p>At risk: {dashboard.at_risk_count} · Not at risk: {dashboard.not_at_risk_count} · Xác suất trung bình: {dashboard.average_probability == null ? '—' : `${(dashboard.average_probability * 100).toFixed(1)}%`}</p>
      {dashboard.model_versions.map(m => <p key={`${m.model_id}:${m.model_version}`}><strong>{m.model_id}</strong> · {m.model_version} · {m.prediction_count} dự đoán<br/><small>Manifest {m.manifest_sha256}</small></p>)}
      <ul>{dashboard.limitations.map(item => <li key={item}>{item}</li>)}</ul>
    </section>}

    {!cases.length && <p>Chưa có research case được gán cho tài khoản này.</p>}
    {cases.map(item => <div className="status-row" key={item.id}>
      <span><strong>{item.source_case_key}</strong><br/><small>{domainLabel(item)} · cutoff ngày 28</small></span>
      <button disabled={busy} onClick={() => void predict(item)}>Dự đoán nghiên cứu</button>
    </div>)}

    {result && <div role="status">
      <span className="badge">{result.domain_id === 'academic_demo_v2' ? 'SYNTHETIC RESEARCH MODEL' : 'PUBLIC RESEARCH MODEL'}</span>
      <h3>Nguy cơ: {(result.probability * 100).toFixed(1)}%</h3>
      <p>Ngưỡng cảnh báo: {(result.threshold * 100).toFixed(1)}% · {result.model_id} · {result.model_version}</p>
      <p>{result.disclaimer}</p>
      <small>Mã dự đoán: {result.id}</small>
      <button onClick={() => api(`/predictions/${result.id}/explanation`).then(setExplanation).catch(e => setError(e.message))}>Xem giải thích</button>
    </div>}
    {explanation && <div><p>{explanation.note}</p>{(explanation.contributions || []).map((c: any) => <p key={c.feature}>{c.feature}: {Number(c.value).toFixed(3)}</p>)}</div>}
  </section>;
}
