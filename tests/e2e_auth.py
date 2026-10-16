"""로그인·사용자 분리·하루 한도·사용 기록 점검 (28개)

실행: 시험 서버를 먼저 켠다 (STUDY_IN_UNIV 폴더에서)
  INVITE_CODE=test-invite python -X utf8 -m uvicorn app.server:app --port 8020
그다음: python -X utf8 tests/e2e_auth.py
API 생성 호출 없음. 시험 계정은 끝나면 삭제된다.
"""
import http.cookiejar
import io
import json
import sys
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import pypdf  # noqa: E402
from app import store  # noqa: E402

BASE = "http://127.0.0.1:8020"
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def req(self, method, path, data=None, ctype=None):
        headers = {}
        if isinstance(data, (dict, list)):
            data, headers["content-type"] = json.dumps(data).encode(), "application/json"
        elif ctype:
            headers["content-type"] = ctype
        r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            with self.op.open(r, timeout=60) as res:
                body = res.read()
                return res.status, (json.loads(body) if res.headers.get("content-type", "").startswith("application/json") else body)
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, body


def multipart(fields, files):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fn, data) in files.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\nContent-Type: application/pdf\r\n\r\n'.encode())
        out.write(data + b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


def blank_pdf():
    w = pypdf.PdfWriter()
    w.add_blank_page(width=720, height=540)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


tag = uuid.uuid4().hex[:6]
emails = [f"siu-test-a-{tag}@example.com", f"siu-test-b-{tag}@example.com"]
A, B = Client(), Client()
try:
    for _ in range(20):
        try:
            if A.req("GET", "/healthz")[0] == 200:
                break
        except Exception:
            time.sleep(1)

    check("로그인 전 /api/me 는 401", A.req("GET", "/api/me")[0] == 401)
    s, b = A.req("POST", "/api/auth/signup", {"email": emails[0], "password": "test1234", "invite_code": "wrong"})
    check("초대 코드 틀리면 가입 거절", s == 400)
    check("A 가입", A.req("POST", "/api/auth/signup", {"email": emails[0], "password": "test1234", "invite_code": "test-invite"})[0] == 200)
    check("B 가입", B.req("POST", "/api/auth/signup", {"email": emails[1], "password": "test5678", "invite_code": "test-invite"})[0] == 200)
    s, b = A.req("POST", "/api/auth/signup", {"email": emails[0], "password": "test1234", "invite_code": "test-invite"})
    check(f"중복 가입 거절 ({b.get('detail') if isinstance(b, dict) else b})", s == 400)
    s, me = A.req("GET", "/api/me")
    check("A /api/me: 일반 사용자, 한도 3", s == 200 and me["email"] == emails[0] and not me["is_admin"] and me["daily_limit"] == 3)

    s, course = A.req("POST", "/api/courses", {"course_name": "점검 과목", "primary_type": "A"})
    check("A 과목 생성", s == 200)
    cid = course["id"]
    data, ct = multipart({"title": "점검 강의", "week": "1주차"}, {"file": ("t.pdf", blank_pdf())})
    s, lec = A.req("POST", f"/api/courses/{cid}/lectures", data, ct)
    check("A 강의 업로드 + 예상 비용", s == 200)
    lid = lec["id"]
    s, c = A.req("GET", f"/api/courses/{cid}")
    check("A 과목에 강의 1개, 상태 ready, 예상 비용 있음",
          s == 200 and len(c["lectures"]) == 1 and c["lectures"][0]["status"] == "ready" and c["lectures"][0]["estimate"])
    s, pdf = A.req("GET", f"/api/lectures/{lid}/source")
    check("A 원본 PDF 받기", s == 200 and pdf[:4] == b"%PDF")

    s, lst = B.req("GET", "/api/courses")
    check("B 에게 A 과목이 안 보임", s == 200 and lst == [])
    check("B 가 A 과목 열기 → 404", B.req("GET", f"/api/courses/{cid}")[0] == 404)
    check("B 가 A 원본 PDF → 404", B.req("GET", f"/api/lectures/{lid}/source")[0] == 404)
    check("B 가 A 강의 생성 → 404", B.req("POST", f"/api/lectures/{lid}/generate")[0] == 404)
    check("B 가 A 과목 삭제 시도 후에도 A 과목 남음",
          B.req("DELETE", f"/api/courses/{cid}")[0] == 200 and A.req("GET", f"/api/courses/{cid}")[0] == 200)

    for _ in range(3):
        store.log_event(me["id"], "generate_start")
    s, b = A.req("POST", f"/api/lectures/{lid}/generate")
    check(f"하루 한도 초과 시 생성 거절 ({s})", s == 429)
    s, me2 = A.req("GET", "/api/me")
    check("A 오늘 생성 횟수 3", me2["generations_today"] == 3)

    check("일반 사용자는 관리자 화면 403", A.req("GET", "/api/admin/overview")[0] == 403)
    check("화면 기록(note_view) 저장", A.req("POST", "/api/events", {"type": "note_view", "lecture_id": lid, "course_id": cid})[0] == 200)

    check("A 로그아웃", A.req("POST", "/api/auth/logout")[0] == 200)
    check("로그아웃 후 401", A.req("GET", "/api/courses")[0] == 401)
    check("A 다시 로그인", A.req("POST", "/api/auth/login", {"email": emails[0], "password": "test1234"})[0] == 200)
    s, lst = A.req("GET", "/api/courses")
    check("다시 로그인하면 이전 과목이 이어서 보임", s == 200 and len(lst) == 1 and lst[0]["lecture_count"] == 1)
    s, b = A.req("POST", "/api/auth/login", {"email": emails[0], "password": "wrong-pw"})
    check(f"비밀번호 틀림 안내 ({b.get('detail')})", s == 400)

    path = store.get_lecture(me["id"], lid, "pdf_path")["pdf_path"]
    check("A 과목 삭제", A.req("DELETE", f"/api/courses/{cid}")[0] == 200)
    check("과목 삭제 시 강의도 삭제", store.get_lecture(me["id"], lid) is None)
    try:
        store.download_pdf(path)
        gone = False
    except Exception:
        gone = True
    check("과목 삭제 시 저장된 PDF도 삭제", gone)
    types = {e["type"] for e in store.service().table("events").select("type").eq("user_id", me["id"]).execute().data}
    check(f"사용 기록 저장: {sorted(types)}", {"signup", "login", "course_create", "lecture_upload", "note_view"} <= types)
finally:
    profiles = store.service().table("profiles").select("id,email").execute().data
    for p in profiles:
        if p["email"] in emails:
            store.service().table("events").delete().eq("user_id", p["id"]).neq("type", "api_call").execute()  # API 비용 기록은 남긴다
            store.service().auth.admin.delete_user(p["id"])
    left = [p for p in store.service().table("profiles").select("email").execute().data if p["email"] in emails]
    print("시험 계정 정리:", "완료" if not left else f"남음 {left}")
    print(f"\n결과: {sum(ok for _, ok in results)}/{len(results)} 통과")
