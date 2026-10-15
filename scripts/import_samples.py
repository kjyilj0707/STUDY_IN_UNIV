"""로컬에서 만든 샘플 노트(data/courses/...)를 Supabase의 특정 사용자 계정으로 옮긴다. API 호출(비용) 없음.

사용: python -X utf8 scripts/import_samples.py <가입한 이메일>
같은 과목명이 이미 있으면 그 과목은 건너뛴다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import engine, store  # noqa: E402

COURSES = engine.ROOT / "data" / "courses"
SAMPLES = [
    {
        "dir": "A_고전문학의이해", "course_name": "고전문학의 이해", "professor": "", "semester": "2026-2",
        "primary_type": "A", "secondary_types": ["E"],
        "evaluation": "기말 40 / 중간 대체과제 15 / 조별발표 20 / 개별보고서 15",
        "lectures": [
            ("4강 신라인의 낭만과 비애, 향가의 세계", '5~6주차 "신라인의 낭만과 비애, 향가의 세계"',
             "2_강의자료/4강 신라인의 낭만과 비애, 향가의 세계 (5).pdf", "6_생성결과/auto/A1_4강_강의노트_auto.md"),
            ("5강 사물에 빗댄 중세 지성의 사유, 가전", '7주차 "사물에 빗댄 중세 지성의 사유, 가전"',
             "2_강의자료/5강 사물에 빗댄 중세 지성의 사유, 가전.pdf", "6_생성결과/auto/A1_5강_강의노트_auto.md"),
        ],
    },
    {
        "dir": "B_통계와사회", "course_name": "통계와사회", "professor": "", "semester": "2026-2",
        "primary_type": "B", "secondary_types": [], "evaluation": "중간 35 / 기말 45 / 연습문제 과제 10",
        "lectures": [
            ("4장 확률변수와 확률분포", '5주차 "확률변수와 확률분포1", 6주차 "확률변수와 확률분포2"',
             "2_강의자료/통계사회_제4장 (3).pdf", "6_생성결과/auto/B1_4장_장별노트_auto.md"),
        ],
    },
]


def main():
    email = sys.argv[1].strip().lower()
    profiles = store.service().table("profiles").select("id,email").execute().data
    uid = next((p["id"] for p in profiles if p["email"].lower() == email), None)
    if not uid:
        sys.exit(f"{email} 로 가입한 계정이 없습니다. 웹에서 먼저 가입하세요.")
    existing = {c["course_name"] for c in store.list_courses(uid)}
    for s in SAMPLES:
        if s["course_name"] in existing:
            print(f"건너뜀 (이미 있음): {s['course_name']}")
            continue
        src = COURSES / s["dir"]
        syllabus = src / "1_수업계획서" / "수업계획서.txt"
        course = store.create_course(uid, {
            **{k: s[k] for k in ("course_name", "professor", "semester", "primary_type", "secondary_types", "evaluation")},
            "syllabus_text": syllabus.read_text(encoding="utf-8") if syllabus.exists() else "",
        })
        for title, week, pdf, note in s["lectures"]:
            pdf_path, note_path = src / pdf, src / note
            if not pdf_path.exists() or not note_path.exists():
                print(f"  파일 없음, 건너뜀: {title}")
                continue
            lec = store.create_lecture(uid, {
                "course_id": course["id"], "title": title, "week": week, "stage": s["primary_type"] + "1",
                "pages": engine.pdf_profile(pdf_path)["pages"], "status": "done",
                "note": note_path.read_text(encoding="utf-8"), "omissions": [], "finished_at": store.now_iso(),
            }, pdf_path.read_bytes())
            print(f"  옮김: {title} ({lec['id']})")
        print(f"과목 완료: {s['course_name']}")


if __name__ == "__main__":
    main()
