"""
Seed script: Nhập catalog học phần ngành Hệ thống thông tin (HTTT)
Khoa Công nghệ thông tin, Trường Đại học Công nghệ Giao thông vận tải (UTT).

Nguồn do owner cung cấp: DS HP HTTT.docx.

Sử dụng:
  python -m app.seed_httt_curriculum             # dry-run (mặc định, không ghi DB)
  python -m app.seed_httt_curriculum --confirm SEED_HTTT_CURRICULUM   # ghi thật

Bất biến an toàn:
  - Chỉ UPSERT catalog và prerequisite — KHÔNG tạo enrollment, student, transcript.
  - Idempotent: chạy lại sẽ sửa metadata catalog HTTT về đúng dữ liệu đã duyệt.
  - Không xóa dữ liệu mô phỏng hiện có (DEMO-C*, DEMO-CS, ...).
  - Mã môn HTTT thật (DC1*, DC2*, DC3*, DC4*) không xung đột với mô phỏng.
"""
from __future__ import annotations
import argparse
import sys
from app.store import transaction, one, rows, run


# ---------------------------------------------------------------------------
# Dữ liệu học phần ngành HTTT — trích từ DS HP HTTT.docx
# Cột: (code, title, credits, group_name)
# group_name dùng để gán recommended_term_no ước tính
# ---------------------------------------------------------------------------
HTTT_COURSES = [
    # I. Kiến thức giáo dục đại cương — Lý luận chính trị (bắt buộc)
    ("DC1LL06", "Triết học Mác - Lênin", 3, 1),
    ("DC1LL07", "Kinh tế chính trị Mác - Lênin", 2, 1),
    ("DC1LL08", "Chủ nghĩa xã hội khoa học", 2, 2),
    ("DC1LL03", "Tư tưởng Hồ Chí Minh", 2, 2),
    ("DC1LL09", "Lịch sử Đảng Cộng sản Việt Nam", 2, 3),
    ("DC1LL05", "Pháp luật Việt Nam đại cương", 2, 3),

    # I. Kiến thức giáo dục đại cương — Toán, KHTN, Tin học, Ngoại ngữ, Kỹ năng mềm (bắt buộc)
    ("DC1CB11", "Toán 1", 4, 1),
    ("DC1CB41", "Toán 2", 2, 2),
    ("DC1TT21", "Vật lý đại cương 1", 2, 1),
    ("DC1TT22", "Vật lý đại cương 2", 2, 2),
    ("DC1TT44", "Tin học cơ sở", 3, 1),
    ("DC1CB35", "Tiếng Anh", 3, 2),
    ("DC1TT77", "Kỹ năng mềm", 3, 2),

    # I. Kiến thức giáo dục đại cương — Tự chọn (nhóm Toán/KHTN/Ngoại ngữ)
    ("DC1CB98", "Làm việc nhóm và kỹ năng giao tiếp", 2, 3),
    ("DC1TT31", "Kỹ thuật xây dựng và trình bày báo cáo", 2, 3),
    ("DC1CB20", "Lý thuyết xác suất – thống kê", 2, 4),
    ("DC1CB99", "Phương pháp nghiên cứu khoa học", 2, 4),

    # I. Giáo dục thể chất
    ("DC1TD21", "Điền kinh", 2, 1),
    ("DC1TD31", "Bóng chuyền", 2, 2),
    ("DC1TD32", "Cầu lông", 2, 2),
    ("DC1TD33", "Aerobic", 2, 2),

    # I. Giáo dục Quốc phòng – An ninh
    ("DC1QP05", "Đường lối quốc phòng và an ninh của Đảng Cộng sản Việt Nam", 3, 1),
    ("DC1QP06", "Công tác quốc phòng và an ninh", 2, 1),
    ("DC1QP07", "Quân sự chung", 2, 1),
    ("DC1QP08", "Kỹ thuật chiến đấu bộ binh và chiến thuật", 2, 2),

    # II. Kiến thức giáo dục chuyên nghiệp — Cơ sở ngành (bắt buộc)
    ("DC2HT42", "Toán học rời rạc", 4, 2),
    ("DC2TT23", "Ngôn ngữ lập trình C", 3, 2),
    ("DC2TT22", "Nhập môn Cơ sở dữ liệu", 3, 3),
    ("DC2HT12", "Nguyên lý Hệ điều hành", 3, 3),
    ("DC2HT13", "Nhập môn Mạng máy tính", 3, 3),
    ("DC2TT35", "Lập trình hướng đối tượng C++", 3, 3),
    ("DC2HT34", "Lập trình trực quan C#", 3, 4),
    ("DC2HT26", "Cấu trúc dữ liệu và giải thuật", 4, 3),
    ("DC2TT11", "Kiến trúc máy tính", 3, 2),
    ("DC3HT60", "Phân tích và thiết kế hệ thống thông tin", 4, 4),
    ("DC2HT27", "Lập trình Java cơ bản", 3, 4),
    ("DC2TT24", "Thương mại điện tử", 3, 5),
    ("DC3HT31", "Lập trình di động", 3, 5),
    ("DC3HT51", "An toàn và bảo mật hệ thống thông tin", 2, 6),
    ("DC2HT36", "Lập trình trên môi trường Web", 3, 4),
    ("DC3HT12", "Trí tuệ nhân tạo", 3, 5),
    ("DC2TT32", "Điện toán đám mây", 2, 6),

    # II. Kiến thức cơ sở ngành — Tự chọn
    ("DC2TT31", "Phần mềm mã nguồn mở", 2, 5),
    ("DC3TT34", "Giao thông thông minh - ITS", 2, 5),
    ("DC2TH33", "Automat và ngôn ngữ hình thức", 2, 5),
    ("DC2HT41", "Kỹ thuật đồ họa máy tính", 2, 5),
    ("DC2TH34", "Nhập môn Chương trình dịch", 2, 5),

    # II. Kiến thức ngành (bắt buộc)
    ("DC3HT21", "Hệ quản trị cơ sở dữ liệu", 3, 4),
    ("DC3HT25", "Lập trình Java nâng cao", 3, 5),
    ("DC2HT38", "Công nghệ phần mềm", 3, 4),
    ("DC3TT12", "Kiến trúc và thiết kế phần mềm", 3, 5),
    ("DC3HT16", "Nhập môn Xử lý ảnh", 3, 5),
    ("DC3TH17", "Nhập môn Tương tác người - máy", 2, 5),
    ("DC3HT32", "Quản lý dự án phần mềm", 3, 6),
    ("DC3HT18", "Tiếng Anh chuyên ngành", 3, 6),
    ("DC3HT41", "Kiểm thử phần mềm", 3, 6),
    ("DC3HT22", "Hệ trợ giúp quyết định", 3, 6),
    ("DC3HT23", "Hệ cơ sở tri thức", 3, 7),
    ("DC3HT42", "Hệ thống hoạch định nguồn lực doanh nghiệp - ERP", 3, 7),
    ("DC3HT52", "Đồ án Hệ thống thông tin", 3, 7),

    # II. Kiến thức ngành — Tự chọn
    ("DC3HT43", "Hệ thống thông tin địa lý - GIS", 3, 7),
    ("DC3HT44", "Kiến trúc của hệ thống quản lý, giám sát phương tiện giao thông", 3, 7),
    ("DC3HT46", "Thiết kế mạng máy tính", 3, 6),
    ("DC3TT47", "Quản trị mạng", 3, 6),
    ("DC3TT17", "Big Data", 3, 7),
    ("DC3HT47", "Cơ sở dữ liệu phân tán", 3, 7),
    ("DC3HT45", "Kiến trúc của hệ thống cảnh báo ùn tắc, an toàn giao thông", 3, 7),

    # II. Thực hành, thực tập nghề nghiệp
    ("DC4HT23", "Thực tập chuyên ngành", 3, 7),
    ("DC4HT24", "Thực tập hệ thống thông tin", 3, 7),
    ("DC4HT25", "Thực tập doanh nghiệp", 3, 8),

    # II. Thực tập tốt nghiệp + Đồ án
    ("DC4TH70", "Thực tập tốt nghiệp", 4, 8),
    ("DC4TH80", "Đồ án tốt nghiệp", 8, 8),
]

CURRICULUM_CODE = "HTTT-UTT"
CURRICULUM_VERSION = "2024"
CURRICULUM_MAJOR = "Hệ thống thông tin"
CURRICULUM_FACULTY = "Công nghệ thông tin"
CURRICULUM_CREDITS = 157
DOMAIN_ID = "demo_academic"
SOURCE_NAME = "DS HP HTTT.docx"
SOURCE_SHA256 = "974855dbef253e24fe82c85a01866f0665e1b95a5768bd2651203b3515e4151c"
POLICY_CODE = "ACADEMIC-DEMO-2"
POLICY_VERSION = "2.0.0"
CONFIRM_PHRASE = "SEED_HTTT_CURRICULUM"

# 72 mã học phần gồm 53 bắt buộc và 19 lựa chọn tự chọn. Tổng 199 tín chỉ
# là tổng mọi lựa chọn, không phải số tín chỉ sinh viên phải hoàn thành.
ELECTIVE_CODES = frozenset({
    "DC1CB98", "DC1TT31", "DC1CB20", "DC1CB99",
    "DC1TD31", "DC1TD32", "DC1TD33",
    "DC2TT31", "DC3TT34", "DC2TH33", "DC2HT41", "DC2TH34",
    "DC3HT43", "DC3HT44", "DC3HT46", "DC3TT47", "DC3TT17",
    "DC3HT47", "DC3HT45",
})
NON_GPA_CODES = frozenset({
    "DC1TD21", "DC1TD31", "DC1TD32", "DC1TD33",
    "DC1QP05", "DC1QP06", "DC1QP07", "DC1QP08",
})

# Điều kiện tiên quyết được chép nguyên từ cột cuối của DOCX. Ngưỡng 1.0/4
# là mức đạt của policy ACADEMIC-DEMO-2; đây không phải một ngưỡng trích từ DOCX.
PREREQUISITES = (
    ("DC1LL07", "DC1LL06"), ("DC1LL08", "DC1LL06"),
    ("DC1LL03", "DC1LL08"), ("DC1LL09", "DC1LL08"),
    ("DC1TT22", "DC1TT21"), ("DC1CB20", "DC1CB41"),
    ("DC2HT42", "DC1TT44"), ("DC2TT23", "DC1TT44"),
    ("DC2TT22", "DC1TT44"), ("DC2HT12", "DC1TT44"),
    ("DC2HT13", "DC1TT44"), ("DC2TT35", "DC2TT23"),
    ("DC2HT34", "DC2TT23"), ("DC2HT26", "DC2TT23"),
    ("DC2TT11", "DC1TT44"), ("DC3HT60", "DC2TT35"),
    ("DC3HT60", "DC2TT22"), ("DC2HT27", "DC2TT35"),
    ("DC3HT31", "DC2HT27"), ("DC3HT51", "DC2HT12"),
    ("DC2HT36", "DC2HT27"), ("DC3HT12", "DC2TT23"),
    ("DC3TT34", "DC3HT60"), ("DC3HT21", "DC2TT22"),
    ("DC3HT25", "DC2HT27"), ("DC2HT38", "DC1TT44"),
    ("DC3TT12", "DC2HT38"), ("DC3HT16", "DC2TT23"),
    ("DC3HT32", "DC2HT38"), ("DC3HT41", "DC2TT23"),
    ("DC3HT22", "DC3HT21"), ("DC3HT23", "DC3HT12"),
    ("DC3HT42", "DC3HT60"), ("DC3HT52", "DC2HT36"),
    ("DC3HT52", "DC3HT60"), ("DC3HT52", "DC2HT38"),
    ("DC3HT43", "DC3HT60"), ("DC3HT43", "DC3HT21"),
    ("DC3HT46", "DC2HT13"), ("DC3TT47", "DC2HT13"),
    ("DC3HT47", "DC3HT21"), ("DC4HT24", "DC4HT23"),
    ("DC4HT25", "DC4HT24"), ("DC4TH70", "DC4HT25"),
    ("DC4TH80", "DC4TH70"),
)


def seed_httt(dry_run: bool = True) -> dict:
    """
    Seed học phần HTTT vào DB. Trả về dict với stats.
    dry_run=True: chỉ validate, không ghi.
    """
    stats = {
        "curriculum": False,
        "courses_new": 0,
        "courses_skipped": 0,
        "curriculum_courses_new": 0,
        "curriculum_courses_skipped": 0,
        "prerequisites_new": 0,
        "prerequisites_skipped": 0,
        "dry_run": dry_run,
    }

    with transaction() as db:
        policy = one(
            db,
            "SELECT id FROM app.grading_policies WHERE code=:code AND version=:version",
            code=POLICY_CODE,
            version=POLICY_VERSION,
        )
        if not policy:
            raise RuntimeError(
                f"POLICY_MISSING: Grading policy {POLICY_CODE}/{POLICY_VERSION} chưa tồn tại."
            )

        if dry_run:
            # Validate: check policy tồn tại, preview stats
            existing_curriculum = one(
                db,
                "SELECT id FROM app.curricula WHERE code=:code AND version=:version",
                code=CURRICULUM_CODE, version=CURRICULUM_VERSION,
            )
            stats["curriculum"] = bool(existing_curriculum)
            for code, title, credits, _ in HTTT_COURSES:
                existing = one(
                    db,
                    "SELECT id FROM app.courses WHERE code=:code AND domain_id=:domain",
                    code=code, domain=DOMAIN_ID,
                )
                if existing:
                    stats["courses_skipped"] += 1
                else:
                    stats["courses_new"] += 1
            print(f"[DRY-RUN] Preview:")
            print(f"  Curriculum HTTT-UTT/2024: {'đã tồn tại' if stats['curriculum'] else 'sẽ tạo mới'}")
            print(f"  Courses mới: {stats['courses_new']}, bỏ qua (đã có): {stats['courses_skipped']}")
            print(f"  Tổng học phần trong file: {len(HTTT_COURSES)}")
            print(f"  Bắt buộc/tự chọn: {len(HTTT_COURSES)-len(ELECTIVE_CODES)}/{len(ELECTIVE_CODES)}")
            print(f"  Quan hệ tiên quyết: {len(PREREQUISITES)}")
            print("  => Không ghi DB. Dùng --confirm SEED_HTTT_CURRICULUM để chạy thật.")
            return stats

        # ----- LIVE RUN -----

        # 1. Tạo curriculum HTTT-UTT/2024
        run(
            db,
            """INSERT INTO app.curricula(
                   code,version,major,total_required_credits,policy_id,status,
                   faculty,source_name,source_sha256)
               VALUES(:code,:version,:major,:credits,:policy,'demo',:faculty,:source,:source_hash)
               ON CONFLICT(code,version) DO UPDATE SET
                 major=excluded.major,total_required_credits=excluded.total_required_credits,
                 policy_id=excluded.policy_id,faculty=excluded.faculty,
                 source_name=excluded.source_name,source_sha256=excluded.source_sha256""",
            code=CURRICULUM_CODE,
            version=CURRICULUM_VERSION,
            major=CURRICULUM_MAJOR,
            credits=CURRICULUM_CREDITS,
            policy=policy["id"],
            faculty=CURRICULUM_FACULTY,
            source=SOURCE_NAME,
            source_hash=SOURCE_SHA256,
        )
        curriculum = one(
            db,
            "SELECT id FROM app.curricula WHERE code=:code AND version=:version",
            code=CURRICULUM_CODE, version=CURRICULUM_VERSION,
        )
        stats["curriculum"] = True

        # 2. Tạo/cập nhật từng môn học
        for code, title, credits, term_no in HTTT_COURSES:
            existing = one(
                db,
                "SELECT id FROM app.courses WHERE code=:code AND domain_id=:domain",
                code=code, domain=DOMAIN_ID,
            )
            if existing:
                # Cập nhật title nếu đã có (idempotent)
                run(
                    db,
                    "UPDATE app.courses SET title=:title WHERE id=:id",
                    title=title, id=existing["id"],
                )
                course_id = existing["id"]
                stats["courses_skipped"] += 1
            else:
                run(
                    db,
                    """INSERT INTO app.courses(code, title, domain_id)
                       VALUES(:code, :title, :domain)""",
                    code=code, title=title, domain=DOMAIN_ID,
                )
                course = one(
                    db,
                    "SELECT id FROM app.courses WHERE code=:code AND domain_id=:domain",
                    code=code, domain=DOMAIN_ID,
                )
                course_id = course["id"]
                stats["courses_new"] += 1

            # 3. Gắn vào curriculum. DOCX không chứa học kỳ khuyến nghị nên
            # không được biến term_no ước lượng thành dữ liệu chính thức.
            existing_cc = one(
                db,
                "SELECT id FROM app.curriculum_courses WHERE curriculum_id=:cid AND course_id=:course",
                cid=curriculum["id"], course=course_id,
            )
            if existing_cc:
                run(
                    db,
                    """UPDATE app.curriculum_courses
                       SET credits=:credits,required=:required,recommended_term_no=NULL,
                           counts_for_gpa=:counts_for_gpa
                       WHERE id=:id""",
                    credits=credits,
                    required=code not in ELECTIVE_CODES,
                    counts_for_gpa=code not in NON_GPA_CODES,
                    id=existing_cc["id"],
                )
                stats["curriculum_courses_skipped"] += 1
            else:
                run(
                    db,
                    """INSERT INTO app.curriculum_courses(
                           curriculum_id,course_id,credits,required,recommended_term_no,counts_for_gpa)
                       VALUES(:cid,:course,:credits,:required,NULL,:counts_for_gpa)""",
                    cid=curriculum["id"],
                    course=course_id,
                    credits=credits,
                    required=code not in ELECTIVE_CODES,
                    counts_for_gpa=code not in NON_GPA_CODES,
                )
                stats["curriculum_courses_new"] += 1

        # 4. Tiên quyết theo DOCX. Numeric threshold follows the selected demo
        # policy and is deliberately recorded as such in this module.
        course_ids = {row["code"]: row["id"] for row in rows(
            db, "SELECT id,code FROM app.courses WHERE domain_id=:domain", domain=DOMAIN_ID
        )}
        for course_code, prerequisite_code in PREREQUISITES:
            existing = one(
                db,
                """SELECT id FROM app.prerequisites
                   WHERE curriculum_id=:curriculum AND course_id=:course
                     AND prerequisite_course_id=:prerequisite""",
                curriculum=curriculum["id"],
                course=course_ids[course_code],
                prerequisite=course_ids[prerequisite_code],
            )
            if existing:
                run(db, "UPDATE app.prerequisites SET min_grade_point=1 WHERE id=:id", id=existing["id"])
                stats["prerequisites_skipped"] += 1
            else:
                run(
                    db,
                    """INSERT INTO app.prerequisites(
                           curriculum_id,course_id,prerequisite_course_id,min_grade_point)
                       VALUES(:curriculum,:course,:prerequisite,1)""",
                    curriculum=curriculum["id"],
                    course=course_ids[course_code],
                    prerequisite=course_ids[prerequisite_code],
                )
                stats["prerequisites_new"] += 1

        # 5. Ghi audit log
        run(
            db,
            """INSERT INTO app.audit_logs(actor_id, action, entity_type, entity_id, status, request_id)
               SELECT id, 'seed_httt_curriculum', 'curriculum', :curriculum_code, 'completed', 'seed_httt_curriculum'
               FROM app.users WHERE email='admin@demo.local' LIMIT 1""",
            curriculum_code=CURRICULUM_CODE,
        )

    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        metavar="PHRASE",
        help=f"Nhập '{CONFIRM_PHRASE}' để ghi thật vào DB. Mặc định: dry-run.",
    )
    args = parser.parse_args()

    dry_run = True
    if args.confirm:
        if args.confirm != CONFIRM_PHRASE:
            print(f"[ERROR] Cụm xác nhận sai. Phải là: {CONFIRM_PHRASE}", file=sys.stderr)
            sys.exit(1)
        dry_run = False

    print(f"=== Seed HTTT Curriculum ({'DRY-RUN' if dry_run else 'LIVE'}) ===")
    stats = seed_httt(dry_run=dry_run)

    if not dry_run:
        print("\n[COMPLETED] Kết quả:")
        print(f"  Curriculum HTTT-UTT/2024: {'tạo mới' if stats['curriculum'] else 'đã có'}")
        print(f"  Courses tạo mới   : {stats['courses_new']}")
        print(f"  Courses bỏ qua    : {stats['courses_skipped']}")
        print(f"  Curriculum_courses mới  : {stats['curriculum_courses_new']}")
        print(f"  Curriculum_courses bỏ qua: {stats['curriculum_courses_skipped']}")
        print(f"  Prerequisites mới/bỏ qua: {stats['prerequisites_new']}/{stats['prerequisites_skipped']}")
        print("\nKhông có enrollment/transcript nào bị ảnh hưởng.")
        print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()
