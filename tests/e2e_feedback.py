"""유형 안내 + 자료 평가 점검 (17개)

실행: 시험 서버를 먼저 켠다 (STUDY_IN_UNIV 폴더에서)
  INVITE_CODE=test-invite python -X utf8 -m uvicorn app.server:app --port 8020
그다음: python -X utf8 tests/e2e_feedback.py
API 생성 호출 없음. 시험 계정은 끝나면 삭제된다.
"""
import io
import sys
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pypdf  # noqa: E402
from app import store  # noqa: E402
from e2e_lib import Client, multipart  # noqa: E402

results = []


def check(name, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name)


def blank_pdf():
    w = pypdf.PdfWriter()
    w.add_blank_page(width=720, height=540)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


tag = uuid.uuid4().hex[:6]
emails = [f"siu-test-fa-{tag}@example.com", f"siu-test-fb-{tag}@example.com"]
A, B = Client(), Client()
try:
    for _ in range(20):
        try:
            if A.req("GET", "/healthz")[0] == 200:
                break
        except Exception:
            time.sleep(1)
    for c, e in ((A, emails[0]), (B, emails[1])):
        assert c.req("POST", "/api/auth/signup", {"email": e, "password": "test1234", "invite_code": "test-invite"})[0] == 200

    s, course = A.req("POST", "/api/courses", {"course_name": "점검 과목", "primary_type": "A", "secondary_types": ["E"]})
    cid = course["id"]
    check("과목 응답에 유형 안내 포함 (A 서술·해석형)", course["guide"]["name"] == "서술·해석형" and len(course["guide"]["flow"]) == 4)
    check("보조 유형(E) 안내 포함", "E" in course["secondary_guides"])

    data, ct = multipart({"title": "점검 강의", "week": ""}, {"file": ("t.pdf", blank_pdf())})
    s, lec = A.req("POST", f"/api/courses/{cid}/lectures", data, ct)
    lid = lec["id"]
    good = {"ratings": {"overall": 4, "completeness": 5, "accuracy": 4, "structure": 4, "traceability": 5,
                        "writing_space": 3, "time_saving": 5, "stage_specific": 4},
            "reuse": "yes", "usage": ["review", "exam", "hacker"], "time_saved": "60_120",
            "issues": ["missing"], "issue_pages": "p.6", "best": "출처 표시", "worst": "한자 하나 틀림"}
    check("노트 완성 전 평가 거절", A.req("PUT", f"/api/lectures/{lid}/feedback", good)[0] == 400)

    store.update_lecture(lid, {"status": "done", "note": "# 점검 노트\n\n본문"})
    s, f = A.req("GET", f"/api/lectures/{lid}/feedback")
    keys = [r["key"] for r in f["form"]["ratings"]]
    check(f"A1 평가표: 공통 6개 + 원문 정확도 ({len(keys)}개)", s == 200 and len(keys) == 7 and "stage_specific" in keys and f["feedback"] is None)

    bad = {**good, "ratings": {k: v for k, v in good["ratings"].items() if k != "accuracy"}}
    check("점수 하나 빠지면 거절", A.req("PUT", f"/api/lectures/{lid}/feedback", bad)[0] == 400)
    out = {**good, "ratings": {**good["ratings"], "overall": 9}}
    check("점수 범위(1~5) 밖이면 거절", A.req("PUT", f"/api/lectures/{lid}/feedback", out)[0] == 400)

    s, saved = A.req("PUT", f"/api/lectures/{lid}/feedback", good)
    check("평가 저장", s == 200 and saved["r_overall"] == 4 and saved["stage"] == "A1" and saved["course_type"] == "A")
    check("허용되지 않은 선택지는 걸러짐 (usage 'hacker')", saved["usage"] == ["review", "exam"])

    s, saved2 = A.req("PUT", f"/api/lectures/{lid}/feedback", {**good, "ratings": {**good["ratings"], "overall": 2}, "worst": "수정함"})
    rows = store.service().table("feedback").select("id,r_overall,worst").eq("lecture_id", lid).execute().data
    check("다시 저장하면 수정 (한 강의에 1개)", s == 200 and len(rows) == 1 and rows[0]["r_overall"] == 2 and rows[0]["worst"] == "수정함")

    s, c = A.req("GET", f"/api/courses/{cid}")
    check("과목 화면 강의 목록에 내 평가 점수", c["lectures"][0]["rating"] == 2)

    check("B 는 A 강의 평가 못 봄", B.req("GET", f"/api/lectures/{lid}/feedback")[0] == 404)
    check("B 는 A 강의 평가 못 씀", B.req("PUT", f"/api/lectures/{lid}/feedback", good)[0] == 404)

    ov = store.feedback_overview()
    st = next((x for x in ov["by_stage"] if x["stage"] == "A1"), None)
    check("관리자 요약: A1 단계 평균·문제 유형 집계", st and st["averages"].get("overall") and st["issues"].get("missing"))
    check("관리자 요약: 서술 의견 포함", any(cm["worst"] == "수정함" for cm in ov["comments"]))
    view = store.service().table("feedback_by_stage").select("*").execute().data
    check("Supabase 요약 view(feedback_by_stage) 조회", any(v["stage"] == "A1" for v in view))
    ev = store.service().table("events").select("type").eq("lecture_id", lid).eq("type", "feedback_submit").execute().data
    check("사용 기록에 자료 평가 저장", len(ev) == 2)

    A.req("DELETE", f"/api/courses/{cid}")
    check("과목 삭제 시 평가도 삭제", not store.service().table("feedback").select("id").eq("lecture_id", lid).execute().data)
finally:
    for p in store.service().table("profiles").select("id,email").execute().data:
        if p["email"] in emails:
            for c in store.list_courses(p["id"]):
                store.delete_course(p["id"], c["id"])
            store.service().table("events").delete().eq("user_id", p["id"]).neq("type", "api_call").execute()  # API 비용 기록은 남긴다
            store.service().auth.admin.delete_user(p["id"])
    print("시험 계정 정리 완료")
    print(f"\n결과: {sum(results)}/{len(results)} 통과")
