"""로컬 미리보기 웹 서버 (배포 전). 실행: python -I -X utf8 -m uvicorn app.server:app --port 8000  (STUDY_IN_UNIV에서)

저장 위치: data/web/ (개인 자료라 git 제외). 과목 = data/web/courses/{cid}/course.json,
강의 = .../lectures/{lid}/ (source.pdf, note.md, meta.json).
생성은 몇 분 걸리므로 스레드로 돌리고 화면은 /api/jobs/{jid}를 폴링한다.
"""
import hmac
import json
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import engine

ROOT = engine.ROOT
WEB = ROOT / "data" / "web"
COURSES = WEB / "courses"
UPLOADS = WEB / "uploads"
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="STUDY_IN_UNIV 로컬 미리보기")
JOBS = {}
LOCK = threading.Lock()

# 링크로 공유할 때 아무나 크레딧을 쓰지 못하게 하는 접속 코드 (.env 의 ACCESS_CODE). 비어 있으면 검사하지 않는다.
ACCESS_CODE = engine.env_value("ACCESS_CODE")
COOKIE = "siu_access"
LOGIN_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>STUDY IN UNIV</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f6f3;color:#1c1c1a;
font-family:Pretendard,-apple-system,"Malgun Gothic",sans-serif}form{background:#fff;border:1px solid #e2e1dc;
border-radius:12px;padding:28px;width:min(340px,calc(100vw - 32px));display:grid;gap:12px}
h1{font-size:20px;margin:0}p{margin:0;color:#6b6b66;font-size:14px}input{font:inherit;padding:9px 11px;
border:1px solid #e2e1dc;border-radius:8px}button{font:inherit;padding:9px;border:0;border-radius:8px;
background:#2f5d50;color:#fff;cursor:pointer}.err{color:#a33a2c}</style></head><body>
<form method="post" action="/login"><h1>STUDY IN UNIV</h1><p>미리보기 접속 코드를 입력하세요.</p>{error}
<input name="code" type="password" autofocus placeholder="접속 코드"><button>들어가기</button></form></body></html>"""


@app.middleware("http")
async def require_access_code(request: Request, call_next):
    if not ACCESS_CODE or request.url.path == "/login":
        return await call_next(request)
    if hmac.compare_digest(request.cookies.get(COOKIE, ""), ACCESS_CODE):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "접속 코드가 필요합니다. 페이지를 새로고침하세요."}, status_code=401)
    return HTMLResponse(LOGIN_HTML.replace("{error}", ""))


@app.post("/login")
def login(code: str = Form("")):
    if not ACCESS_CODE or not hmac.compare_digest(code.strip(), ACCESS_CODE):
        return HTMLResponse(LOGIN_HTML.replace("{error}", '<p class="err">코드가 맞지 않아요.</p>'), status_code=401)
    res = RedirectResponse("/", status_code=303)
    res.set_cookie(COOKIE, ACCESS_CODE, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax")
    return res


def now():
    return datetime.now().isoformat(timespec="seconds")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def course_dir(cid):
    d = COURSES / cid
    if not (d / "course.json").exists():
        raise HTTPException(404, "과목이 없습니다.")
    return d


def lecture_dir(cid, lid):
    d = course_dir(cid) / "lectures" / lid
    if not (d / "meta.json").exists():
        raise HTTPException(404, "강의가 없습니다.")
    return d


def pipeline(course_type):
    return [{"code": code, "name": name, "ready": code in engine.TEMPLATES}
            for code, name in engine.PIPELINES[course_type]]


def course_summary(d):
    c = read_json(d / "course.json")
    lectures = []
    for ld in sorted((d / "lectures").glob("*/meta.json")):
        lectures.append(read_json(ld))
    lectures.sort(key=lambda m: m.get("created", ""))
    c["lectures"] = lectures
    c["pipeline"] = pipeline(c["primary_type"])
    c["type_name"] = engine.TYPE_NAMES[c["primary_type"]]
    return c


# ---------- 샘플 (처음 실행 시 지금까지 만든 노트를 불러온다) ----------

SAMPLES = [
    {
        "dir": "A_고전문학의이해", "course_name": "고전문학의 이해", "professor": "교수A", "semester": "2026-2",
        "primary_type": "A", "secondary_types": ["E"],
        "evaluation": "기말 40 / 중간 대체과제 15 / 조별발표 20 / 개별보고서 15",
        "reasons": [{"signal": "학문 분야", "evidence": "고전문학 작품(향가·가전 등)의 원문과 해석 중심 강의"},
                    {"signal": "평가 비중", "evidence": "중간 대체과제·조별발표·개별보고서 합계 50% → E 함께 붙음"}],
        "lectures": [
            ("4강 신라인의 낭만과 비애, 향가의 세계", '5~6주차 "신라인의 낭만과 비애, 향가의 세계"',
             "2_강의자료/4강 신라인의 낭만과 비애, 향가의 세계 (5).pdf", "6_생성결과/auto/A1_4강_강의노트_auto.md"),
            ("5강 사물에 빗댄 중세 지성의 사유, 가전", '7주차 "사물에 빗댄 중세 지성의 사유, 가전"',
             "2_강의자료/5강 사물에 빗댄 중세 지성의 사유, 가전.pdf", "6_생성결과/auto/A1_5강_강의노트_auto.md"),
        ],
    },
    {
        "dir": "B_통계와사회", "course_name": "통계와사회", "professor": "교수E", "semester": "2026-2",
        "primary_type": "B", "secondary_types": [],
        "evaluation": "중간 35 / 기말 45 / 연습문제 과제 10",
        "reasons": [{"signal": "학문 분야", "evidence": "확률변수·확률분포 등 통계 이론과 계산"},
                    {"signal": "시험 형식", "evidence": "연습문제 과제(풀이) + 중간·기말 시험"}],
        "lectures": [
            ("4장 확률변수와 확률분포", '5주차 "확률변수와 확률분포1", 6주차 "확률변수와 확률분포2"',
             "2_강의자료/통계사회_제4장 (3).pdf", "6_생성결과/auto/B1_4장_장별노트_auto.md"),
        ],
    },
]


def seed_samples():
    if COURSES.exists() and any(COURSES.iterdir()):
        return
    for s in SAMPLES:
        src = ROOT / "data" / "courses" / s["dir"]
        cid = uuid.uuid4().hex[:8]
        cd = COURSES / cid
        course = {k: s[k] for k in ("course_name", "professor", "semester", "primary_type",
                                     "secondary_types", "evaluation", "reasons")}
        syllabus = src / "1_수업계획서" / "수업계획서.txt"
        course.update(id=cid, weeks=[], sample=True, created=now())
        write_json(cd / "course.json", course)
        if syllabus.exists():
            shutil.copy(syllabus, cd / "syllabus.txt")
        for title, week, pdf, note in s["lectures"]:
            if not (src / pdf).exists() or not (src / note).exists():
                continue
            lid = uuid.uuid4().hex[:8]
            ld = cd / "lectures" / lid
            ld.mkdir(parents=True)
            shutil.copy(src / pdf, ld / "source.pdf")
            shutil.copy(src / note, ld / "note.md")
            write_json(ld / "meta.json", {
                "id": lid, "title": title, "week": week, "stage": s["primary_type"] + "1",
                "pages": engine.pdf_profile(ld / "source.pdf")["pages"], "status": "done",
                "created": now(), "sample": True, "omissions": None, "cost_usd": None,
            })


seed_samples()


# ---------- API ----------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/courses")
def list_courses():
    if not COURSES.exists():
        return []
    items = [course_summary(d) for d in COURSES.iterdir() if (d / "course.json").exists()]
    return sorted(items, key=lambda c: c["created"])


@app.get("/api/courses/{cid}")
def get_course(cid: str):
    return course_summary(course_dir(cid))


@app.post("/api/classify")
def classify(file: UploadFile | None = File(None), text: str = Form("")):
    """수업계획서 PDF 또는 붙여넣은 텍스트 → 유형 판정 결과 (아직 과목을 만들지 않음)."""
    if file is not None and file.filename:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        tmp = UPLOADS / f"syllabus_{uuid.uuid4().hex[:8]}.pdf"
        tmp.write_bytes(file.file.read())
        text = engine.syllabus_text_from_pdf(tmp)
    if len(text.strip()) < 50:
        raise HTTPException(400, "수업계획서 내용을 읽지 못했습니다. 텍스트를 직접 붙여넣어 주세요.")
    result, record = engine.classify_syllabus(text)
    result["pipeline"] = pipeline(result["primary_type"])
    result["type_name"] = engine.TYPE_NAMES[result["primary_type"]]
    return {"result": result, "syllabus_text": text, "cost_usd": record["cost_usd"]}


class NewCourse(BaseModel):
    course_name: str
    professor: str = ""
    semester: str = ""
    primary_type: str
    secondary_types: list[str] = []
    evaluation: str = ""
    reasons: list[dict] = []
    weeks: list[dict] = []
    syllabus_text: str = ""


@app.post("/api/courses")
def create_course(body: NewCourse):
    if body.primary_type not in engine.PIPELINES:
        raise HTTPException(400, "알 수 없는 유형입니다.")
    cid = uuid.uuid4().hex[:8]
    cd = COURSES / cid
    data = body.model_dump(exclude={"syllabus_text"})
    data.update(id=cid, sample=False, created=now())
    write_json(cd / "course.json", data)
    (cd / "syllabus.txt").write_text(body.syllabus_text, encoding="utf-8")
    return course_summary(cd)


@app.delete("/api/courses/{cid}")
def delete_course(cid: str):
    shutil.rmtree(course_dir(cid))
    return {"ok": True}


@app.post("/api/courses/{cid}/lectures")
def add_lecture(cid: str, file: UploadFile = File(...), title: str = Form(...), week: str = Form("")):
    cd = course_dir(cid)
    course = read_json(cd / "course.json")
    stage = course["primary_type"] + "1"
    if stage not in engine.TEMPLATES:
        raise HTTPException(400, f"{engine.TYPE_NAMES[course['primary_type']]}은 아직 자료 생성을 지원하지 않습니다 (MVP: A·B).")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 올릴 수 있습니다.")
    lid = uuid.uuid4().hex[:8]
    ld = cd / "lectures" / lid
    ld.mkdir(parents=True)
    (ld / "source.pdf").write_bytes(file.file.read())
    try:
        est = engine.estimate_cost(stage, ld / "source.pdf")
    except Exception as e:
        shutil.rmtree(ld)
        raise HTTPException(400, f"PDF를 읽지 못했습니다: {e}")
    meta = {"id": lid, "title": title, "week": week, "stage": stage, "pages": est["pages"],
            "status": "ready", "created": now(), "sample": False, "estimate": est,
            "omissions": None, "cost_usd": None}
    write_json(ld / "meta.json", meta)
    return meta


@app.delete("/api/courses/{cid}/lectures/{lid}")
def delete_lecture(cid: str, lid: str):
    shutil.rmtree(lecture_dir(cid, lid))
    return {"ok": True}


def run_generation(jid, cid, lid):
    cd, ld = COURSES / cid, COURSES / cid / "lectures" / lid
    course, meta = read_json(cd / "course.json"), read_json(ld / "meta.json")
    job = JOBS[jid]
    label = f"{course['course_name']} ({course['professor']} 교수, {course['semester']})"

    def on_text(t):
        job["chars"] += len(t)

    try:
        job["phase"] = "writing"
        note, rec = engine.generate_note(meta["stage"], ld / "source.pdf", label, meta["week"] or "(미상)", on_text=on_text)
        (ld / "note.md").write_text(note + "\n", encoding="utf-8")
        cost = rec["cost_usd"]
        job["phase"] = "checking"
        omissions, rec2 = engine.check_omissions(meta["stage"], ld / "source.pdf", note)
        note, results = engine.apply_omissions(note, omissions)
        (ld / "note.md").write_text(note, encoding="utf-8")
        cost += rec2["cost_usd"]
        meta.update(status="done", omissions=results, cost_usd=round(cost, 3),
                    truncated=rec["stop_reason"] == "max_tokens", finished=now())
        job.update(phase="done", cost_usd=meta["cost_usd"])
    except Exception as e:
        traceback.print_exc()
        meta.update(status="error", error=str(e))
        job.update(phase="error", error=str(e))
    write_json(ld / "meta.json", meta)


@app.post("/api/courses/{cid}/lectures/{lid}/generate")
def generate(cid: str, lid: str):
    ld = lecture_dir(cid, lid)
    meta = read_json(ld / "meta.json")
    with LOCK:
        running = next((j for j in JOBS.values() if j["lid"] == lid and j["phase"] in ("writing", "checking")), None)
        if running:
            return running
        jid = uuid.uuid4().hex[:8]
        JOBS[jid] = {"id": jid, "cid": cid, "lid": lid, "phase": "queued", "chars": 0, "started": now()}
    meta["status"] = "running"
    meta["job"] = jid
    write_json(ld / "meta.json", meta)
    threading.Thread(target=run_generation, args=(jid, cid, lid), daemon=True).start()
    return JOBS[jid]


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "작업이 없습니다 (서버를 다시 켰다면 강의를 다시 생성하세요).")
    return JOBS[jid]


@app.get("/api/courses/{cid}/lectures/{lid}/note", response_class=PlainTextResponse)
def get_note(cid: str, lid: str):
    note = lecture_dir(cid, lid) / "note.md"
    if not note.exists():
        raise HTTPException(404, "아직 노트가 없습니다.")
    return note.read_text(encoding="utf-8")


@app.get("/api/courses/{cid}/lectures/{lid}/source")
def get_source(cid: str, lid: str):
    return FileResponse(lecture_dir(cid, lid) / "source.pdf", media_type="application/pdf")


@app.get("/api/usage")
def usage():
    if not engine.USAGE_LOG.exists():
        return {"total_usd": 0, "count": 0}
    rows = [json.loads(l) for l in engine.USAGE_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {"total_usd": round(sum(r.get("cost_usd", 0) for r in rows), 2), "count": len(rows)}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
