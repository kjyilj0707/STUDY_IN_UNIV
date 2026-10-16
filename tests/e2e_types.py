"""테스트 단계 유형 정책 점검: C·D·E로 판정돼도 A·B 중 가까운 유형으로 서비스 (5개, --live 면 +3개)

실행: 시험 서버를 먼저 켠다 (STUDY_IN_UNIV 폴더에서)
  INVITE_CODE=test-invite python -X utf8 -m uvicorn app.server:app --port 8020
그다음: python -X utf8 tests/e2e_types.py [--live <수업계획서 텍스트 파일>] [--live-pdf <글자가 도형인 수업계획서 PDF>]
--live: 실제 유형 판정 1회 (Claude API 약 $0.1). 시험 계정은 끝나면 삭제된다.
--live-pdf: 텍스트 레이어가 없는 PDF(한컴 PDF 등)를 올려 페이지 이미지 판정 1회 (약 $0.1~0.2)
"""
import sys
from pathlib import Path
import time
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from app import engine, store  # noqa: E402
from e2e_lib import Client, multipart  # noqa: E402

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f" — {extra}" if extra else ""))


check("기본 대응표: C→A, D→B, E→A, A·B는 그대로",
      [engine.served_type(t) for t in "ABCDE"] == ["A", "B", "A", "B", "A"])
check("모델이 고른 가까운 유형을 우선 (C→B)", engine.served_type("C", "B") == "B" and engine.served_type("A", "B") == "A")

email = f"siu-test-ty-{uuid.uuid4().hex[:6]}@example.com"
A = Client()
try:
    for _ in range(20):
        try:
            if A.req("GET", "/healthz")[0] == 200:
                break
        except Exception:
            time.sleep(1)
    assert A.req("POST", "/api/auth/signup", {"email": email, "password": "test1234", "invite_code": "test-invite"})[0] == 200
    uid = A.req("GET", "/api/me")[1]["id"]

    s, c = A.req("POST", "/api/courses", {"course_name": "유형 점검 1", "primary_type": "C"})
    check("C로 만들려 해도 A로 저장, 단계 1 생성 가능", s == 200 and c["primary_type"] == "A" and c["pipeline"][0]["ready"])
    s, c2 = A.req("POST", "/api/courses", {"course_name": "유형 점검 2", "primary_type": "B", "judged_type": "D",
                                          "service_reason": "계산 문제 위주"})
    check("D로 판정 → B로 선택하면 B", s == 200 and c2["primary_type"] == "B")
    ev = store.service().table("events").select("data").eq("course_id", c2["id"]).eq("type", "course_create").execute().data
    check("사용 기록에 원래 판정(D)과 근거 남음", ev and ev[0]["data"]["judged_type"] == "D" and ev[0]["data"]["service_reason"] == "계산 문제 위주")

    if "--live" in sys.argv:
        text = Path(sys.argv[sys.argv.index("--live") + 1]).read_text(encoding="utf-8")
        body = urllib.parse.urlencode({"text": text}).encode()
        s, r = A.req("POST", "/api/classify", body, "application/x-www-form-urlencoded")
        res = r["result"] if s == 200 else {}
        print(f"  판정 {res.get('judged_type')} → 서비스 {res.get('primary_type')} · 근거: {res.get('service_reason')} · ${r.get('cost_usd') if s == 200 else '-'}")
        check("실제 판정: 서비스 유형은 A·B", s == 200 and res["primary_type"] in ("A", "B"), str(r)[:200] if s != 200 else "")
        check("실제 판정: 원래 판정 유형 함께 옴", res.get("judged_type") in engine.PIPELINES)
        check("실제 판정: 단계 1 생성 가능", res.get("pipeline", [{}])[0].get("ready") is True)

    if "--live-pdf" in sys.argv:
        pdf = Path(sys.argv[sys.argv.index("--live-pdf") + 1])
        data, ct = multipart({"text": ""}, {"file": ("syllabus.pdf", pdf.read_bytes())})
        s, r = A.req("POST", "/api/classify", data, ct)
        res = r["result"] if s == 200 else {}
        print(f"  [PDF] {res.get('course_name')} · 판정 {res.get('judged_type')} → 서비스 {res.get('primary_type')} · "
              f"평가 {res.get('evaluation')} · 주차 {len(res.get('weeks', []))}개 · 전문 {len(r.get('syllabus_text', '')) if s == 200 else 0}자 · "
              f"${r.get('cost_usd') if s == 200 else '-'}")
        check("글자 없는 PDF: 판정 성공", s == 200 and res["primary_type"] in ("A", "B"), str(r)[:200] if s != 200 else "")
        check("글자 없는 PDF: 수업계획서 전문을 글자로 받아 옴", s == 200 and len(r["syllabus_text"]) >= 200)
        check("글자 없는 PDF: 결과에 전문 칸이 섞이지 않음", "syllabus_text" not in res)
finally:
    for c in store.list_courses(uid) if "uid" in dir() else []:
        store.delete_course(uid, c["id"])
    for p in store.service().table("profiles").select("id,email").execute().data:
        if p["email"] == email:
            store.service().table("events").delete().eq("user_id", p["id"]).neq("type", "api_call").execute()  # API 비용 기록은 남긴다
            store.service().auth.admin.delete_user(p["id"])
    print("시험 계정 정리 완료")
    print(f"\n결과: {sum(results)}/{len(results)} 통과")
