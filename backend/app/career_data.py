"""Reviewed demo reference data for HTTT career and skill-gap features."""
from __future__ import annotations

import csv
import hashlib
from decimal import Decimal
from pathlib import Path


MAPPING_VERSION = "HTTT-CAREER-SKILLS-1.0.0"
CURRICULUM_CODE = "HTTT-UTT"
CURRICULUM_VERSION = "2024"
CURATION_STATUS = "owner_approved_demo"
COURSE_SKILLS_SOURCE = "course_skills_HTTT.csv"
COURSE_SKILLS_SHA256 = "8b01a3fb7921aee10ebb983c338656c845254f2969b9e21eccf089e124d3bb3c"

SKILLS = (
    ("SK01", "Phân tích yêu cầu nghiệp vụ (Requirements Analysis)", "Business"),
    ("SK02", "Mô hình hóa quy trình nghiệp vụ (BPMN)", "Business"),
    ("SK03", "Tư duy hệ thống (Systems Thinking)", "Business"),
    ("SK04", "Phân tích thiết kế hệ thống (UML/SA&D)", "Technical"),
    ("SK05", "Quản lý dự án CNTT", "Business"),
    ("SK06", "Kiến thức ERP (SAP/Oracle/Odoo)", "Business"),
    ("SK07", "Kiểm toán CNTT & Tuân thủ", "Business"),
    ("SK08", "Quản trị thay đổi (Change Management)", "Business"),
    ("SK09", "SQL", "Technical"),
    ("SK10", "Thiết kế cơ sở dữ liệu", "Technical"),
    ("SK11", "Quản trị CSDL (backup/tuning/security)", "Technical"),
    ("SK12", "Phân tích dữ liệu", "Technical"),
    ("SK13", "Trực quan hóa dữ liệu (Power BI/Tableau)", "Tool"),
    ("SK14", "Thống kê", "Technical"),
    ("SK15", "Excel nâng cao", "Tool"),
    ("SK16", "ETL / Data Warehouse", "Technical"),
    ("SK17", "Lập trình cơ bản (Python/Java/C#)", "Technical"),
    ("SK18", "Phát triển Web cơ bản", "Technical"),
    ("SK19", "Mạng máy tính", "Technical"),
    ("SK20", "An toàn thông tin", "Technical"),
    ("SK21", "Điện toán đám mây", "Technical"),
    ("SK22", "Giao tiếp", "Soft"),
    ("SK23", "Thuyết trình", "Soft"),
    ("SK24", "Làm việc nhóm", "Soft"),
    ("SK25", "Giải quyết vấn đề", "Soft"),
    ("SK26", "Tiếng Anh chuyên ngành", "Soft"),
    ("SK27", "Quản lý thời gian", "Soft"),
)

CAREERS = (
    ("CR01", "Business Analyst", "Cầu nối giữa nghiệp vụ và IT, thu thập/phân tích yêu cầu, đề xuất giải pháp hệ thống"),
    ("CR02", "Systems Analyst", "Phân tích thiết kế hệ thống thông tin, chuyển yêu cầu nghiệp vụ thành đặc tả kỹ thuật"),
    ("CR03", "ERP Functional Consultant", "Tư vấn, cấu hình, triển khai hệ thống ERP cho doanh nghiệp"),
    ("CR04", "Data Analyst", "Phân tích dữ liệu kinh doanh, trực quan hóa và hỗ trợ ra quyết định"),
    ("CR05", "Database Administrator", "Quản trị, vận hành và bảo mật hệ thống cơ sở dữ liệu doanh nghiệp"),
    ("CR06", "IT Project Coordinator", "Điều phối tiến độ, tài nguyên và giao tiếp giữa các bên trong dự án CNTT"),
)

# required_level is intentionally absent in v1. Match is evidence coverage, not
# an employability probability. A later sourced review may introduce levels.
CAREER_SKILLS = (
    ("CR01", "SK01", ".25"), ("CR01", "SK02", ".20"), ("CR01", "SK22", ".15"),
    ("CR01", "SK04", ".15"), ("CR01", "SK25", ".10"), ("CR01", "SK15", ".08"), ("CR01", "SK23", ".07"),
    ("CR02", "SK04", ".25"), ("CR02", "SK01", ".20"), ("CR02", "SK09", ".15"),
    ("CR02", "SK17", ".15"), ("CR02", "SK03", ".15"), ("CR02", "SK25", ".10"),
    ("CR03", "SK06", ".30"), ("CR03", "SK02", ".20"), ("CR03", "SK01", ".15"),
    ("CR03", "SK08", ".10"), ("CR03", "SK22", ".10"), ("CR03", "SK26", ".10"), ("CR03", "SK23", ".05"),
    ("CR04", "SK09", ".20"), ("CR04", "SK12", ".20"), ("CR04", "SK13", ".18"),
    ("CR04", "SK14", ".17"), ("CR04", "SK17", ".15"), ("CR04", "SK15", ".10"),
    ("CR05", "SK11", ".30"), ("CR05", "SK10", ".20"), ("CR05", "SK09", ".20"),
    ("CR05", "SK20", ".15"), ("CR05", "SK19", ".10"), ("CR05", "SK21", ".05"),
    ("CR06", "SK05", ".25"), ("CR06", "SK22", ".18"), ("CR06", "SK24", ".15"),
    ("CR06", "SK27", ".15"), ("CR06", "SK01", ".12"), ("CR06", "SK04", ".08"), ("CR06", "SK26", ".07"),
)

CERTIFICATIONS = (
    ("CERT01", "CBAP (Certified Business Analysis Professional)", "SK01"),
    ("CERT02", "PMI-PBA", "SK01"), ("CERT03", "PMP", "SK05"),
    ("CERT04", "ITIL Foundation", "SK05"),
    ("CERT05", "SAP Certified Application Associate", "SK06"),
    ("CERT06", "Oracle Database Certified Associate", "SK11"),
    ("CERT07", "Microsoft PL-300 (Power BI Data Analyst)", "SK13"),
    ("CERT08", "Google Data Analytics Certificate", "SK12"),
)

EXCLUDED_COURSES = {
    "DC1LL06", "DC1LL07", "DC1LL08", "DC1LL03", "DC1LL09", "DC1LL05",
    "DC1CB11", "DC1CB41", "DC1TT21", "DC1TT22", "DC1TD21", "DC1TD31",
    "DC1TD32", "DC1TD33", "DC1QP05", "DC1QP06", "DC1QP07", "DC1QP08",
    "DC2TT11", "DC3TT34", "DC2TH33", "DC2HT41", "DC2TH34", "DC3HT44", "DC3HT45",
}
TECHNICAL_SCOPE_EXCLUSIONS = {"DC2TT11", "DC3TT34", "DC2TH33", "DC2HT41", "DC2TH34", "DC3HT44", "DC3HT45"}


def load_course_skills() -> tuple[dict, ...]:
    path = Path(__file__).with_name("resources") / "career" / COURSE_SKILLS_SOURCE
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != COURSE_SKILLS_SHA256:
        raise RuntimeError("COURSE_SKILLS_SOURCE_HASH_MISMATCH")
    skill_names = {code: name for code, name, _ in SKILLS}
    result = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["course_code", "course_title", "skill_id", "skill_name", "weight"]:
            raise RuntimeError("COURSE_SKILLS_HEADER_INVALID")
        for line, row in enumerate(reader, 2):
            weight = Decimal(row["weight"])
            if row["skill_id"] not in skill_names or row["skill_name"] != skill_names[row["skill_id"]]:
                raise RuntimeError(f"COURSE_SKILLS_SKILL_INVALID:{line}")
            if not Decimal("0") < weight <= Decimal("1"):
                raise RuntimeError(f"COURSE_SKILLS_WEIGHT_INVALID:{line}")
            result.append({**row, "weight": weight})
    keys = {(row["course_code"], row["skill_id"]) for row in result}
    if len(result) != 91 or len(keys) != len(result):
        raise RuntimeError("COURSE_SKILLS_CARDINALITY_INVALID")
    return tuple(result)


def validate_reference_data(catalog_codes: set[str]) -> None:
    rows = load_course_skills()
    skill_codes = {row[0] for row in SKILLS}
    career_codes = {row[0] for row in CAREERS}
    mapped_courses = {row["course_code"] for row in rows}
    if len(SKILLS) != 27 or len(CAREERS) != 6 or len(CAREER_SKILLS) != 39 or len(CERTIFICATIONS) != 8:
        raise RuntimeError("CAREER_REFERENCE_CARDINALITY_INVALID")
    if any(career not in career_codes or skill not in skill_codes for career, skill, _ in CAREER_SKILLS):
        raise RuntimeError("CAREER_SKILL_REFERENCE_INVALID")
    totals = {career: sum(Decimal(weight) for c, _, weight in CAREER_SKILLS if c == career)
              for career in career_codes}
    if any(total != Decimal("1") for total in totals.values()):
        raise RuntimeError("CAREER_SKILL_WEIGHT_SUM_INVALID")
    if mapped_courses & EXCLUDED_COURSES or mapped_courses | EXCLUDED_COURSES != catalog_codes:
        raise RuntimeError("COURSE_SKILL_CATALOG_COVERAGE_INVALID")
