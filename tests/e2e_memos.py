"""노트 필기 칸 저장 점검 (10개)

실행: 시험 서버를 먼저 켠다 (STUDY_IN_UNIV 폴더에서)
  INVITE_CODE=test-invite python -X utf8 -m uvicorn app.server:app --port 8020
그다음: python -X utf8 tests/e2e_memos.py
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


def memo_file_exists(uid, lid):
    return any(f["name"] == f"{lid}.memos.json" for f in store.service().storage.from_(store.BUCKET).list(uid))


tag = uuid.uuid4().hex[:6]
emails = [f"siu-test-ma-{tag}@example.com", f"siu-test-mb-{tag}@example.com"]
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
    uid = A.req("GET", "/api/me")[1]["id"]

    s, course = A.req("POST", "/api/courses", {"course_name": "점검 과목", "primary_type": "A"})
    cid = course["id"]
    data, ct = multipart({"title": "점검 강의", "week": ""}, {"file": ("t.pdf", blank_pdf())})
    lid = A.req("POST", f"/api/courses/{cid}/lectures", data, ct)[1]["id"]
    store.update_lecture(lid, {"status": "done", "note": "# 점검\n\n> **필기**\n>\n> &nbsp;\n"})

    s, m = A.req("GET", f"/api/lectures/{lid}/memos")
    check("쓴 적 없으면 빈 필기", s == 200 and m == {})

    check("칸 0 저장", A.req("PUT", f"/api/lectures/{lid}/memos", {"index": 0, "text": "첫 칸\n둘째 줄"})[0] == 200)
    check("칸 3 저장", A.req("PUT", f"/api/lectures/{lid}/memos", {"index": 3, "text": "셋째 칸 √x"})[0] == 200)
    s, m = A.req("GET", f"/api/lectures/{lid}/memos")
    check("두 칸 모두 남음 (서로 덮어쓰지 않음)", m == {"0": "첫 칸\n둘째 줄", "3": "셋째 칸 √x"})

    A.req("PUT", f"/api/lectures/{lid}/memos", {"index": 0, "text": "  "})
    check("빈 글이면 그 칸만 지움", A.req("GET", f"/api/lectures/{lid}/memos")[1] == {"3": "셋째 칸 √x"})

    check("너무 긴 글 거절", A.req("PUT", f"/api/lectures/{lid}/memos", {"index": 1, "text": "가" * 20001})[0] == 400)
    check("음수 칸 번호 거절", A.req("PUT", f"/api/lectures/{lid}/memos", {"index": -1, "text": "x"})[0] == 400)

    check("B 는 A 필기 못 봄", B.req("GET", f"/api/lectures/{lid}/memos")[0] == 404)
    check("B 는 A 필기 못 씀", B.req("PUT", f"/api/lectures/{lid}/memos", {"index": 3, "text": "침입"})[0] == 404)

    A.req("DELETE", f"/api/courses/{cid}")
    check("과목 삭제 시 필기 파일도 삭제", not memo_file_exists(uid, lid))
finally:
    for p in store.service().table("profiles").select("id,email").execute().data:
        if p["email"] in emails:
            for c in store.list_courses(p["id"]):
                store.delete_course(p["id"], c["id"])
            store.service().table("events").delete().eq("user_id", p["id"]).execute()
            store.service().auth.admin.delete_user(p["id"])
    print("시험 계정 정리 완료")
    print(f"\n결과: {sum(results)}/{len(results)} 통과")
