"""실제 노트 생성 1회(5강 3장) + 로그인 자동 연장 점검

실행: 시험 서버를 먼저 켠다 (STUDY_IN_UNIV 폴더에서)
  INVITE_CODE=test-invite python -X utf8 -m uvicorn app.server:app --port 8020
그다음: python -X utf8 tests/e2e_generate.py
실제 생성 약 $0.2 (data/courses 의 5강 PDF 필요). 시험 계정은 끝나면 삭제된다.
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

SRC = ROOT / "data" / "courses" / "A_고전문학의이해" / "2_강의자료" / "5강 사물에 빗댄 중세 지성의 사유, 가전.pdf"
r = pypdf.PdfReader(SRC)
w = pypdf.PdfWriter()
for i in (3, 4, 5):  # 4~6쪽 (본문 슬라이드)
    w.add_page(r.pages[i])
buf = io.BytesIO()
w.write(buf)

email = f"siu-test-gen-{uuid.uuid4().hex[:6]}@example.com"
A = Client()
try:
    assert A.req("POST", "/api/auth/signup", {"email": email, "password": "test1234", "invite_code": "test-invite"})[0] == 200
    _, course = A.req("POST", "/api/courses", {"course_name": "생성 점검", "professor": "교수A", "semester": "2026-2", "primary_type": "A"})
    data, ct = multipart({"title": "5강 일부", "week": "7주차"}, {"file": ("p.pdf", buf.getvalue())})
    s, lec = A.req("POST", f"/api/courses/{course['id']}/lectures", data, ct)
    lid = lec["id"]
    s, b = A.req("POST", f"/api/lectures/{lid}/generate")
    print("generate:", s, b)
    t0, last = time.time(), None
    while time.time() - t0 < 600:
        s, p = A.req("GET", f"/api/lectures/{lid}/progress")
        state = (p.get("status"), p.get("phase"), p.get("chars"))
        if state != last:
            print(f"  {int(time.time() - t0)}s", state)
            last = state
        if p.get("status") != "running":
            break
        time.sleep(3)
    s, c = A.req("GET", f"/api/courses/{course['id']}")
    l = c["lectures"][0]
    print("final:", l["status"], "cost", l["cost_usd"], "omissions", l["omissions"], "error", l["error"])
    s, note = A.req("GET", f"/api/lectures/{lid}/note")
    text = note.decode("utf-8") if isinstance(note, bytes) else str(note)
    print("note:", s, len(text), "chars;", text[:300].replace("\n", " | "))

    # 토큰 자동 갱신: access 토큰을 망가뜨리고 refresh 토큰만으로 요청
    for ck in A.jar:
        if ck.name == "siu_at":
            ck.value = "broken-token"
    s, me = A.req("GET", "/api/me")
    new_at = next(ck.value for ck in A.jar if ck.name == "siu_at")
    print("refresh:", s, me.get("email") == email if isinstance(me, dict) else me, "| new access cookie set:", new_at != "broken-token")
    s, ev = 0, store.service().table("events").select("type,data").eq("user_id", me["id"]).eq("type", "generate_done").execute().data
    print("generate_done event:", ev)
finally:
    for p in store.service().table("profiles").select("id,email").execute().data:
        if p["email"] == email:
            for c in store.list_courses(p["id"]):
                store.delete_course(p["id"], c["id"])
            store.service().table("events").delete().eq("user_id", p["id"]).execute()
            store.service().auth.admin.delete_user(p["id"])
            print("시험 계정 정리 완료")
