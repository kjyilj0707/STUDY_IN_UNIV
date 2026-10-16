"""프로필 점검 (12개). 먼저 supabase/003_profile.sql 을 실행해 둔다.

실행: 시험 서버를 먼저 켠다 (STUDY_IN_UNIV 폴더에서)
  INVITE_CODE=test-invite python -X utf8 -m uvicorn app.server:app --port 8020
그다음: python -X utf8 tests/e2e_profile.py
API 생성 호출 없음. 시험 계정은 끝나면 삭제된다.
"""
import base64
import sys
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from app import store  # noqa: E402
from e2e_lib import Client, multipart  # noqa: E402

results = []


def check(name, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name)


# 1×1 PNG
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

tag = uuid.uuid4().hex[:6]
emails = [f"siu-test-pa-{tag}@example.com", f"siu-test-pb-{tag}@example.com"]
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

    s, me = A.req("GET", "/api/me")
    check("처음엔 빈 프로필", s == 200 and me["profile"]["display_name"] is None and me["profile"]["avatar_url"] is None)

    good = {"display_name": " 민수 ", "school": "한국대학교", "department": "국어국문학과", "grade": "2", "age": 21}
    s, p = A.req("PUT", "/api/profile", good)
    check("프로필 저장 (앞뒤 공백 정리)", s == 200 and p["display_name"] == "민수" and p["grade"] == "2" and p["age"] == 21)
    check("/api/me 에 프로필 포함", A.req("GET", "/api/me")[1]["profile"]["school"] == "한국대학교")

    check("학년 목록 밖이면 거절", A.req("PUT", "/api/profile", {**good, "grade": "9"})[0] == 400)
    check("나이 범위 밖이면 거절", A.req("PUT", "/api/profile", {**good, "age": 150})[0] == 400)
    check("40자 넘으면 거절", A.req("PUT", "/api/profile", {**good, "school": "가" * 41})[0] == 400)
    s, p = A.req("PUT", "/api/profile", {**good, "age": None, "grade": ""})
    check("나이·학년 비우기", s == 200 and p["age"] is None and p["grade"] is None)

    data, ct = multipart({}, {"file": ("x.txt", b"<script>alert(1)</script>")})
    check("사진이 아닌 파일 거절", A.req("PUT", "/api/profile/avatar", data, ct)[0] == 400)
    data, ct = multipart({}, {"file": ("a.png", PNG)})
    s, p = A.req("PUT", "/api/profile/avatar", data, ct)
    check("사진 올리기 → 주소 생김", s == 200 and p["avatar_url"] and p["avatar_url"].startswith("/api/profile/avatar?v="))
    s, img = A.req("GET", "/api/profile/avatar")
    check("내 사진 받기", s == 200 and img == PNG)
    check("B 는 자기 사진이 없음 (A 사진 안 보임)", B.req("GET", "/api/profile/avatar")[0] == 404)

    s, p = A.req("DELETE", "/api/profile/avatar")
    check("사진 지우기", s == 200 and p["avatar_url"] is None and A.req("GET", "/api/profile/avatar")[0] == 404)
finally:
    for p in store.service().table("profiles").select("id,email").execute().data:
        if p["email"] in emails:
            store.service().storage.from_(store.BUCKET).remove([store.avatar_path(p["id"])])
            store.service().table("events").delete().eq("user_id", p["id"]).execute()
            store.service().auth.admin.delete_user(p["id"])
    print("시험 계정 정리 완료")
    print(f"\n결과: {sum(results)}/{len(results)} 통과")
