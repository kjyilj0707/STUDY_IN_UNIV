"""관리자 사용자 상세 · 사용량·요금 점검 (15개).

실행: 시험 서버를 관리자 시험 계정과 함께 켠다 (STUDY_IN_UNIV 폴더에서)
  INVITE_CODE=test-invite ADMIN_EMAILS=siu-test-admin@example.com python -X utf8 -m uvicorn app.server:app --port 8020
그다음: python -X utf8 tests/e2e_admin.py
Claude 생성 호출 없음 (강의 업로드의 토큰 세기만, 무료). AI 호출 기록은 가짜로 넣고 끝나면 지운다.
"""
import io
import sys
from pathlib import Path
import time
import uuid

import pypdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from app import store  # noqa: E402
from e2e_lib import Client, multipart  # noqa: E402

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra else ""))


def blank_pdf():
    w = pypdf.PdfWriter()
    w.add_blank_page(width=720, height=540)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


admin_email = "siu-test-admin@example.com"
user_email = f"siu-test-ad-{uuid.uuid4().hex[:6]}@example.com"
ADM, U = Client(), Client()
uids = []
try:
    for _ in range(20):
        try:
            if ADM.req("GET", "/healthz")[0] == 200:
                break
        except Exception:
            time.sleep(1)
    for c, e in ((ADM, admin_email), (U, user_email)):
        s, r = c.req("POST", "/api/auth/signup", {"email": e, "password": "test1234", "invite_code": "test-invite"})
        assert s == 200, r
        uids.append(c.req("GET", "/api/me")[1]["id"])
    aid, uid = uids
    check("관리자 시험 계정이 관리자로 인식", ADM.req("GET", "/api/me")[1]["is_admin"] is True)

    # 일반 사용자: 막힘
    check("일반 사용자는 사용량 페이지 403", U.req("GET", "/api/admin/usage")[0] == 403)
    check("일반 사용자는 사용자 상세 403", U.req("GET", f"/api/admin/users/{aid}")[0] == 403)

    # 일반 사용자 활동 만들기: 과목 + 강의 업로드 + 열람 기록 + 가짜 AI 호출 2개
    s, course = U.req("POST", "/api/courses", {"course_name": "관리자 점검 과목", "primary_type": "A"})
    data, ct = multipart({"title": "점검 강의", "week": "1주차"}, {"file": ("t.pdf", blank_pdf())})
    s, lec = U.req("POST", f"/api/courses/{course['id']}/lectures", data, ct)
    U.req("POST", "/api/events", {"type": "note_view", "lecture_id": lec["id"], "course_id": course["id"]})
    store.log_event(uid, "api_call", course_id=course["id"], lecture_id=lec["id"], kind="generate",
                    input_tokens=50000, output_tokens=30000, cost_usd=0.8, seconds=120, model="claude-opus-5-5")
    store.log_event(uid, "api_call", course_id=course["id"], lecture_id=lec["id"], kind="check",
                    input_tokens=60000, output_tokens=2000, cost_usd=0.28, seconds=40, model="claude-opus-5-5")

    # 개요
    s, ov = ADM.req("GET", "/api/admin/overview")
    ec = ov.get("event_counts", {}).get(uid, {})
    check("개요: 사용자별 기록 개수", s == 200 and ec.get("lecture_upload") == 1 and ec.get("note_view") == 1, str(ec))

    # 사용자 상세
    s, d = ADM.req("GET", f"/api/admin/users/{uid}")
    check("상세: 프로필·과목·강의", s == 200 and d["profile"]["email"] == user_email and len(d["courses"]) == 1 and len(d["lectures"]) == 1)
    act = d["lectures"][0]["activity"] if s == 200 else {}
    check("상세: 강의별 열람·AI 비용", act.get("note_view") == 1 and abs(act.get("api_cost", 0) - 1.08) < 1e-6, str(act))
    check("상세: 기능별 횟수", d["counts"].get("course_create") == 1 and d["counts"].get("api_call") == 2, str(d["counts"]))
    check("상세: 기록에 과목·강의 이름", any(e["lecture"] == "점검 강의" and e["course"] == "관리자 점검 과목" for e in d["events"]))
    check("상세: 없는 사용자는 404", ADM.req("GET", f"/api/admin/users/{uuid.uuid4()}")[0] == 404)

    # 사용량·요금
    s, u = ADM.req("GET", "/api/admin/usage?days=7")
    check("사용량: 7일 · 날짜 7칸", s == 200 and u["days"] == 7 and len(u["daily"]) == 7)
    mine = next((x for x in u.get("by_user", []) if x["user_id"] == uid), None)
    check("사용량: 사용자별 합계", mine and abs(mine["cost_usd"] - 1.08) < 1e-6 and mine["calls"] == 2
          and mine["input_tokens"] == 110000 and mine["output_tokens"] == 32000, str(mine))
    today = u["daily"][-1] if s == 200 else {}
    check("사용량: 오늘 칸에 기능별 비용", today.get("cost", {}).get("generate", 0) >= 0.8 and today.get("cost", {}).get("check", 0) >= 0.28, str(today))
    check("사용량: 오늘·이번 달 합계가 기간 합계 안에서 맞음",
          u["totals"]["today_usd"] >= 1.08 and u["totals"]["month_usd"] >= u["totals"]["today_usd"] - 1e-9)
    check("사용량: 최근 호출 목록에 이메일", any(c.get("email") == user_email and c["kind"] == "generate" for c in u["recent"]))
    check("사용량: 예산·가격 정보", u["budget_usd"] > 0 and u["prices"]["output"] > u["prices"]["input"])
finally:
    for uid_ in uids:
        for c in store.list_courses(uid_):
            store.delete_course(uid_, c["id"])
        store.service().table("events").delete().eq("user_id", uid_).execute()  # 가짜 AI 호출 기록도 지운다
        store.service().auth.admin.delete_user(uid_)
    print("시험 계정 정리 완료")
    print(f"\n결과: {sum(results)}/{len(results)} 통과")
