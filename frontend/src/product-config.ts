/**
 * Cấu hình tập trung cho giao diện nền tảng cố vấn học tập thông minh.
 * Tuân thủ nghiêm ngặt các ranh giới:
 * - UTT là phạm vi pilot đầu tiên; corpus UTT luôn giữ nhãn nguồn rõ ràng
 * - Dữ liệu tự khai báo có nhãn chưa xác minh
 * - Chính sách ACADEMIC-DEMO-2.0.0 và 1.000 hồ sơ ML là mô phỏng nghiên cứu (synthetic)
 * - Thông báo lưu trữ hội thoại 30 ngày
 * - Khuyến cáo đối chiếu văn bản cho các chủ đề high-stakes
 */

export const PRODUCT_CONFIG = {
  BRAND_NAME: 'Cố vấn học tập thông minh',
  TAGLINE: 'Theo dõi học tập, lập kế hoạch và tra cứu tài liệu có dẫn nguồn.',
  SHORT_DESCRIPTION: 'Nền tảng hỗ trợ sinh viên theo dõi kết quả học tập, mô phỏng kế hoạch tích lũy tín chỉ và tra cứu tài liệu có dẫn nguồn.',
  INSTITUTION_NAME: 'Pilot tại Trường Đại học Công nghệ Giao thông vận tải (UTT)',
  PILOT_BADGE: 'PILOT TẠI UTT',
  PILOT_DISCLOSURE: 'UTT là phạm vi triển khai pilot đầu tiên. Sản phẩm không phải cổng thông tin chính thức của UTT và có thể cấu hình cho cơ sở đào tạo khác.',
  CORPUS_NAME: 'UTT-CORPUS-2026-V2',
  CORPUS_DISCLOSURE: 'Kho pilot hiện sử dụng tài liệu UTT và luôn kèm nguồn để đối chiếu.',

  CHAT: {
    TITLE: 'Hỏi cố vấn AI',
    RETENTION_NOTICE: 'Hội thoại được lưu tối đa 30 ngày để duy trì lịch sử và cải thiện chất lượng. Bạn có thể xóa sớm hơn.',
    SOURCE_TITLE: 'Trả lời từ kho tài liệu pilot',
    ANSWER_FALLBACK_LABEL: 'Câu trả lời tham khảo',
    INSUFFICIENT_EVIDENCE_LABEL: 'Chưa tìm thấy đủ thông tin trong tài liệu hiện có',
    HIGH_STAKES_WARNING: 'Lưu ý: Đối với các nội dung học vụ quan trọng (đình chỉ, buộc thôi học, học phí, học bổng, điều kiện tốt nghiệp), bạn nên đối chiếu văn bản chính thức và liên hệ phòng Đào tạo hoặc Cố vấn học tập.',
    PROVIDER_OFFLINE_NOTICE: 'Trợ lý AI đang tạm thời gián đoạn kết nối sinh câu trả lời. Hệ thống chuyển sang chế độ tra cứu trích dẫn trực tiếp từ kho tài liệu đang chọn.',
  },

  ACADEMICS: {
    SELF_REPORTED_DISCLOSURE: 'Dữ liệu do bạn tự khai báo, chưa được cơ sở đào tạo xác minh.',
    OFFICIAL_DISCLOSURE: 'Dữ liệu học vụ từ hồ sơ hệ thống đã liên kết.',
    WHAT_IF_DISCLOSURE: 'Các kết quả tính toán mô phỏng (What-if) không làm thay đổi bảng điểm thật của bạn.',
    POLICY_DEMO_DISCLOSURE: 'Mô hình tính toán học vụ dựa trên chính sách thử nghiệm ACADEMIC-DEMO-2.0.0.',
  },

  RESEARCH: {
    TITLE: 'Nghiên cứu & Đánh giá ML',
    SYNTHETIC_WARNING: 'Dữ liệu thử nghiệm ML bao gồm 1.000 hồ sơ synthetic (ACADEMIC-DEMO-2.0.0) và 20 ca công khai (OULAD). Đây là dữ liệu nghiên cứu mô phỏng, không phản ánh hồ sơ sinh viên thực tế.',
  },

  ACCOUNTS: {
    DEMO_BADGE: 'Tài khoản minh họa',
    UNLINKED_NOTICE: 'Tài khoản của bạn chưa được liên kết với hồ sơ sinh viên trong hệ thống. Bạn có thể sử dụng chức năng tự khai báo bảng điểm hoặc liên hệ quản trị viên để được cấp mã liên kết.',
  }
} as const;

export interface NavItem {
  id: string;
  label: string;
  icon?: string;
  badge?: string;
}

export const STUDENT_NAV: NavItem[] = [
  { id: 'overview', label: 'Tổng quan', icon: '🏠' },
  { id: 'academics', label: 'Hồ sơ học tập', icon: '📊' },
  { id: 'planning', label: 'Kế hoạch học tập', icon: '🎯' },
  { id: 'chat', label: 'Hỏi cố vấn AI', icon: '💬' },
  { id: 'documents', label: 'Kho tài liệu', icon: '📚' },
];

export const ADVISOR_NAV: NavItem[] = [
  { id: 'overview', label: 'Tổng quan', icon: '🏠' },
  { id: 'assigned_students', label: 'Sinh viên được phân công', icon: '👥' },
  { id: 'academics', label: 'Theo dõi học tập', icon: '📊' },
  { id: 'chat', label: 'Hỏi cố vấn AI', icon: '💬' },
  { id: 'documents', label: 'Kho tài liệu', icon: '📚' },
];

export const ADMIN_NAV: NavItem[] = [
  { id: 'overview', label: 'Tổng quan hệ thống', icon: '⚙️' },
  { id: 'accounts', label: 'Tài khoản & Phân quyền', icon: '👤' },
  { id: 'documents', label: 'Kho tài liệu & Ingestion', icon: '📚' },
  { id: 'research', label: 'Nghiên cứu ML (Synthetic)', icon: '🔬' },
];
