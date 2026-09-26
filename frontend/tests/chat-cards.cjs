/* Component-level SSR regression; no browser, credentials, network, or app writes. */
const path = require('node:path');
const assert = require('node:assert/strict');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
(async () => {
const { createServer } = await import('vite');
const server = await createServer({ root: path.join(__dirname, '..'), configFile: false, server: { middlewareMode: true }, appType: 'custom' });
try {
const chatSource = require('node:fs').readFileSync(path.join(__dirname, '..', 'src', 'Chat.tsx'), 'utf8');
const mainSource = require('node:fs').readFileSync(path.join(__dirname, '..', 'src', 'main.tsx'), 'utf8');
assert.match(chatSource, /className="chat-workspace"/);
assert.match(chatSource, /className="chat-sidebar"/);
assert.match(chatSource, /Lịch sử trò chuyện/);
assert.match(chatSource, /Tài liệu truy xuất/);
assert.match(chatSource, /Nguồn hiện tại: tài liệu UTT/);
assert.match(chatSource, /Hồ sơ tự khai đang hoạt động/);
const accountsSource = require('node:fs').readFileSync(path.join(__dirname, '..', 'src', 'Accounts.tsx'), 'utf8');
assert.match(accountsSource, /Liên kết hồ sơ học vụ pilot/);
assert.match(accountsSource, /\/catalog\/cohorts/);
assert.match(accountsSource, /Sinh viên tự khai:/);
assert.match(accountsSource, /Để liên kết:/);
assert.match(accountsSource, /\/admin\/accounts\/.*\/academic-profile/);
assert.match(accountsSource, /\/admin\/advisor-assignments/);
assert.match(accountsSource, /Nhật ký quản trị tài khoản gần đây/);
assert.match(chatSource, /Chatbot có thể đọc bảng điểm đã lưu, tính GPA và mô phỏng/);
assert.match(mainSource, /Kế hoạch từ hồ sơ tự khai/);
assert.match(mainSource, /\/account\/required-gpa/);
assert.match(mainSource, /chưa thể xác nhận môn được phép đăng ký, tiên quyết hoặc lớp đang mở/);
assert.doesNotMatch(chatSource, /Trả lời từ tài liệu UTT/);
assert.match(chatSource, /cards\.filter\(card => card\.type !== 'evidence'\)/);
const { ChatCard } = await server.ssrLoadModule('/src/Chat.tsx');
const render = (type, data) => renderToStaticMarkup(React.createElement(ChatCard, { card: { type, data } }));
assert.match(render('academic_summary', { cumulative_gpa: null, earned_credits: '0', remaining_required_credits: '126' }), /Chưa có dữ liệu/);
assert.match(render('goal_analysis', { required_score: '8.5', feasibility: 'achievable' }), /8,5/);
assert.doesNotMatch(render('goal_analysis', { required_score: '8.5', feasibility: 'achievable' }), /Đã đạt.*tín chỉ/);
assert.match(render('goal_analysis', { required_future_gpa: null, feasibility: 'completed_target_not_met' }), /không còn tín chỉ/);
assert.match(render('simulation', { before: { cumulative_gpa: '2.96' }, after: { cumulative_gpa: '3.068' } }), /3,068/);
assert.match(render('course_recommendations', { selected: [], excluded: [], total_credits: '0' }), /Không có môn đủ điều kiện/);
assert.match(render('semester_history', [{ semester_id: '1', semester_code: 'DEMO-T1', term_gpa: null, cumulative_gpa: null, term_earned_credits: '0' }]), /DEMO-T1/);
assert.match(render('career_requirements', { career: { title: 'Data Analyst', description: 'Phân tích dữ liệu' }, skills: [{ skill_id: 'SK09', skill_name: 'SQL', importance_weight: '.2', courses: [] }], mapping_version: 'HTTT-CAREER-SKILLS-1.0.0' }), /SQL/);
assert.match(render('career_skill_gap', { career: { title: 'Data Analyst' }, match_score: '60', data_status: 'sufficient_for_demo', strong_skills: [{ skill_id: 'SK09', skill_name: 'SQL', proficiency_5: '3.5' }], missing_skills: [{ skill_id: 'SK13', skill_name: 'Power BI' }], recommended_courses: [], recommended_certifications: [], mapping_version: 'HTTT-CAREER-SKILLS-1.0.0' }), /60%/);
assert.match(render('career_matches', { data_status: 'sufficient_for_demo', matches: [{ career: { career_code: 'CR04', title: 'Data Analyst' }, match_score: '75' }] }), /Data Analyst: 75%/);
const evidence = render('evidence', { citations: [{ chunk_id: '1', title: 'Demo', section: '1', excerpt: '<script>alert(1)</script>', source: 'demo', version_id: 'v1' }] });
assert.doesNotMatch(evidence, /<script>/);
assert.match(evidence, /&lt;script&gt;/);
const controlledEvidence = renderToStaticMarkup(React.createElement(ChatCard, {
  card: {
    type: 'evidence',
    data: {
      response_mode: 'controlled_retrieval',
      controlled_reason: 'high_stakes',
      release_id: 'UTT-CORPUS-2026-V2',
      corpus_version: 'v2',
      retrieval_method: 'dense',
      retrieval_status: 'candidates_found',
      citations: [{ chunk_id: 'controlled-1', title: 'Quy chế', section: 'Điều 1', excerpt: 'Nội dung để đối chiếu', source: 'gdrive:file-id', version_id: 'v2' }],
    },
  },
  feedback: { onSubmit: () => {} },
}));
assert.match(controlledEvidence, /Trả lời từ kho tài liệu pilot/);
assert.match(controlledEvidence, /Top 1 trích đoạn/);
assert.match(controlledEvidence, /Bản phát hành: UTT-CORPUS-2026-V2/);
assert.match(controlledEvidence, /Hữu ích/);
const capstoneEvidence = render('evidence', {
  rag_mode: 'approved_grounded_capstone',
  response_mode: 'grounded_generation',
  claims: [],
  citations: [{ chunk_id: 'capstone-1', title: 'Lịch học', section: 'Điều 1', excerpt: 'Nội dung', source: 'gdrive:file-id', version_id: 'v2' }],
});
assert.match(capstoneEvidence, /Câu trả lời tham khảo/);
assert.doesNotMatch(capstoneEvidence, /87,5% correctness proxy/);
assert.match(capstoneEvidence, /kho tài liệu đang chọn/);
console.log('PASS: 24 chat/sidebar assertions (career cards, right-column history/evidence, no inline evidence duplication, numeric cards, escaped citations and product copy)');
const { StudentInput } = await server.ssrLoadModule('/src/StudentInput.tsx');
const input = renderToStaticMarkup(React.createElement(StudentInput));
assert.match(input, /Không ghi vào bảng điểm chính thức/);
assert.match(input, /Tín chỉ/);
assert.match(input, /Điểm tổng kết/);
console.log('PASS: 3 student input rendering assertions');
} finally { await server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
