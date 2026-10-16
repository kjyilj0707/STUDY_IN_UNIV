"""웹 서버 (로컬 미리보기 · Render 배포 공용). 실행: python -X utf8 -m uvicorn app.server:app --port 8000  (STUDY_IN_UNIV에서)

- 로그인: Supabase Auth (이메일 + 비밀번호). 가입에는 초대 코드(INVITE_CODE, 없으면 ACCESS_CODE)가 필요하다.
  토큰은 httponly 쿠키에 두고, 만료되면 refresh 토큰으로 자동 갱신한다.
- 저장: Supabase (app/store.py). 사용자마다 자기 과목·강의만 보인다. 사용 기록은 events 표에 쌓는다.
- 한도: 한 사람당 하루 노트 생성 DAILY_LIMIT(기본 3)개. ADMIN_EMAILS 에 있는 사람은 제한 없음 + 관리자 화면.
- 생성은 몇 분 걸리므로 스레드로 돌리고, 화면은 /api/lectures/{lid}/progress 를 폴링한다.
"""
import hmac
import os
import tempfile
import threading
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import engine, feedback, store

STATIC = Path(__file__).parent / "static"
TMP = Path(tempfile.gettempdir()) / "study-in-univ"
TMP.mkdir(parents=True, exist_ok=True)
if os.environ.get("DATA_DIR"):
    engine.USAGE_LOG = Path(os.environ["DATA_DIR"]) / "api_usage.jsonl"

INVITE_CODE = engine.env_value("INVITE_CODE") or engine.env_value("ACCESS_CODE")
ADMIN_EMAILS = {e.strip().lower() for e in engine.env_value("ADMIN_EMAILS").split(",") if e.strip()}
DAILY_LIMIT = int(engine.env_value("DAILY_LIMIT") or 3)
ACCESS_COOKIE, REFRESH_COOKIE = "siu_at", "siu_rt"

app = FastAPI(title="STUDY IN UNIV")
JOBS = {}  # lid → {"phase", "chars"}  (진행 상황만. 결과는 DB에)
LOCK = threading.Lock()
_token_cache = {}  # access token → (user, 확인 시각)

try:
    store.fail_interrupted_jobs()
except Exception as e:  # 설정이 없으면 화면에서 안내한다
    print("Supabase 연결 확인 실패:", e)


# ---------- 로그인 처리 ----------

def is_admin(user):
    return user["email"].lower() in ADMIN_EMAILS


def _user_for(token):
    hit = _token_cache.get(token)
    if hit and time.time() - hit[1] < 120:
        return hit[0]
    user = store.user_from_token(token)
    if user:
        _token_cache[token] = (user, time.time())
    return user


def _set_session(res, request, session):
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    opts = {"httponly": True, "samesite": "lax", "secure": secure, "max_age": 60 * 60 * 24 * 30}
    res.set_cookie(ACCESS_COOKIE, session["access_token"], **opts)
    res.set_cookie(REFRESH_COOKIE, session["refresh_token"], **opts)


@app.middleware("http")
async def attach_user(request: Request, call_next):
    request.state.user, refreshed = None, None
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        request.state.user = _user_for(token)
    if not request.state.user and request.cookies.get(REFRESH_COOKIE):
        refreshed = store.refresh(request.cookies[REFRESH_COOKIE])
        if refreshed:
            request.state.user = refreshed["user"]
    response = await call_next(request)
    if refreshed:
        _set_session(response, request, refreshed)
    return response


def require_user(request: Request):
    if not request.state.user:
        raise HTTPException(401, "로그인이 필요해요.")
    return request.state.user


class Credentials(BaseModel):
    email: str
    password: str
    invite_code: str = ""


@app.post("/api/auth/signup")
def signup(body: Credentials, request: Request):
    if not INVITE_CODE or not hmac.compare_digest(body.invite_code.strip(), INVITE_CODE):
        raise HTTPException(400, "초대 코드가 맞지 않아요.")
    try:
        session = store.sign_up(body.email.strip(), body.password)
    except store.StoreError as e:
        raise HTTPException(400, str(e))
    store.log_event(session["user"]["id"], "signup")
    res = JSONResponse({"ok": True})
    _set_session(res, request, session)
    return res


@app.post("/api/auth/login")
def login(body: Credentials, request: Request):
    try:
        session = store.sign_in(body.email.strip(), body.password)
    except store.StoreError as e:
        raise HTTPException(400, str(e))
    store.log_event(session["user"]["id"], "login")
    res = JSONResponse({"ok": True})
    _set_session(res, request, session)
    return res


@app.post("/api/auth/logout")
def logout():
    res = JSONResponse({"ok": True})
    res.delete_cookie(ACCESS_COOKIE)
    res.delete_cookie(REFRESH_COOKIE)
    return res


@app.get("/api/me")
def me(request: Request):
    user = require_user(request)
    admin = is_admin(user)
    return {**user, "is_admin": admin, "daily_limit": None if admin else DAILY_LIMIT,
            "generations_today": store.generations_today(user["id"]), "profile": profile_view(user)}


# ---------- 프로필 ----------

GRADES = {"1", "2", "3", "4", "5", "6", "grad", "etc"}
AVATAR_TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png"}  # 파일 앞부분으로 확인
AVATAR_MAX = 2_000_000


def profile_view(user):
    p = store.get_profile(user["id"])
    view = {k: p.get(k) for k in store.PROFILE_FIELDS}
    # 사진 주소에 바꾼 시각을 붙여 새 사진이 바로 보이게 한다 (브라우저 캐시)
    view["avatar_url"] = f"/api/profile/avatar?v={p['avatar_at']}" if p.get("avatar_at") else None
    return view


class Profile(BaseModel):
    display_name: str = ""
    school: str = ""
    department: str = ""
    grade: str = ""
    age: int | None = None


@app.get("/api/profile")
def get_profile(request: Request):
    return profile_view(require_user(request))


@app.put("/api/profile")
def save_profile(body: Profile, request: Request):
    user = require_user(request)
    fields = {k: (getattr(body, k) or "").strip() or None for k in ("display_name", "school", "department", "grade")}
    if any(v and len(v) > 40 for v in fields.values()):
        raise HTTPException(400, "40자 이내로 적어 주세요.")
    if fields["grade"] and fields["grade"] not in GRADES:
        raise HTTPException(400, "학년을 목록에서 골라 주세요.")
    if body.age is not None and not 10 <= body.age <= 99:
        raise HTTPException(400, "나이는 10~99 사이로 적어 주세요.")
    fields["age"] = body.age
    try:
        store.save_profile(user["id"], user["email"], fields)
    except Exception as e:
        if "column" in str(e).lower():  # 003_profile.sql을 아직 실행하지 않음
            raise HTTPException(503, "프로필 저장 준비가 아직 안 됐어요 (관리자: supabase/003_profile.sql 실행 필요).")
        raise
    store.log_event(user["id"], "profile_update")
    return profile_view(user)


@app.put("/api/profile/avatar")
def save_avatar(request: Request, file: UploadFile = File(...)):
    """프로필 사진. 화면에서 256px JPEG로 줄여서 보낸다. 서버는 크기·형식만 확인한다."""
    user = require_user(request)
    data = file.file.read(AVATAR_MAX + 1)
    if len(data) > AVATAR_MAX:
        raise HTTPException(400, "사진이 너무 커요 (2MB 이하).")
    ctype = next((t for sig, t in AVATAR_TYPES.items() if data.startswith(sig)), None)
    if not ctype:
        raise HTTPException(400, "JPG 또는 PNG 사진만 올릴 수 있어요.")
    try:
        store.save_avatar(user["id"], user["email"], data, ctype)
    except Exception as e:
        if "column" in str(e).lower():
            raise HTTPException(503, "프로필 저장 준비가 아직 안 됐어요 (관리자: supabase/003_profile.sql 실행 필요).")
        raise
    return profile_view(user)


@app.get("/api/profile/avatar")
def get_avatar(request: Request):
    user = require_user(request)
    try:
        data = store.get_avatar(user["id"])
    except Exception:
        raise HTTPException(404, "사진이 없어요.")
    ctype = next((t for sig, t in AVATAR_TYPES.items() if data.startswith(sig)), "application/octet-stream")
    return Response(data, media_type=ctype,
                    headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@app.delete("/api/profile/avatar")
def delete_avatar(request: Request):
    user = require_user(request)
    store.delete_avatar(user["id"])
    return profile_view(user)


# ---------- 화면 ----------

@app.get("/")
def index():
    # 배포할 때마다 화면이 바뀌므로 브라우저가 예전 화면을 저장해 두지 않게 한다 (매번 서버에 확인)
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz():
    """배포 서비스(Render)의 상태 확인용."""
    return {"ok": True}


# ---------- 과목 ----------

def pipeline(course_type):
    return [{"code": code, "name": name, "ready": code in engine.TEMPLATES}
            for code, name in engine.PIPELINES[course_type]]


def decorate(course):
    course["pipeline"] = pipeline(course["primary_type"])
    course["type_name"] = engine.TYPE_NAMES[course["primary_type"]]
    course["guide"] = feedback.TYPE_GUIDE[course["primary_type"]]
    course["secondary_guides"] = {t: feedback.TYPE_GUIDE[t] for t in course.get("secondary_types") or []
                                  if t in feedback.TYPE_GUIDE}
    return course


@app.get("/api/courses")
def list_courses(request: Request):
    user = require_user(request)
    counts = store.count_lectures(user["id"])
    return [decorate({**c, "lecture_count": counts.get(c["id"], 0)}) for c in store.list_courses(user["id"])]


@app.get("/api/courses/{cid}")
def get_course(cid: str, request: Request):
    user = require_user(request)
    course = store.get_course(user["id"], cid)
    if not course:
        raise HTTPException(404, "과목이 없습니다.")
    lectures = store.list_lectures(user["id"], cid, store.LECTURE_LIST_COLUMNS)
    ratings = store.rated_lectures(user["id"], cid)
    for l in lectures:
        l["rating"] = ratings.get(l["id"])
        if l["id"] in JOBS:
            l["progress"] = JOBS[l["id"]]
    return decorate({**course, "lectures": lectures})


@app.post("/api/classify")
def classify(request: Request, file: UploadFile | None = File(None), text: str = Form("")):
    """수업계획서 PDF 또는 붙여넣은 텍스트 → 유형 판정 결과 (아직 과목을 만들지 않음)."""
    user = require_user(request)
    if file is not None and file.filename:
        tmp = TMP / f"syllabus_{user['id']}_{int(time.time())}.pdf"
        tmp.write_bytes(file.file.read())
        try:
            text = engine.syllabus_text_from_pdf(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    if len(text.strip()) < 50:
        raise HTTPException(400, "수업계획서 내용을 읽지 못했습니다. 텍스트를 직접 붙여넣어 주세요.")
    result, record = engine.classify_syllabus(text)
    store.log_event(user["id"], "classify", primary_type=result["primary_type"],
                    course_name=result["course_name"], cost_usd=record["cost_usd"])
    return {"result": decorate(result), "syllabus_text": text, "cost_usd": record["cost_usd"]}


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
def create_course(body: NewCourse, request: Request):
    user = require_user(request)
    if body.primary_type not in engine.PIPELINES:
        raise HTTPException(400, "알 수 없는 유형입니다.")
    course = store.create_course(user["id"], body.model_dump())
    store.log_event(user["id"], "course_create", course_id=course["id"], primary_type=course["primary_type"])
    return decorate({**course, "lectures": []})


@app.delete("/api/courses/{cid}")
def delete_course(cid: str, request: Request):
    user = require_user(request)
    store.delete_course(user["id"], cid)
    return {"ok": True}


# ---------- 강의 ----------

@app.post("/api/courses/{cid}/lectures")
def add_lecture(cid: str, request: Request, file: UploadFile = File(...), title: str = Form(...), week: str = Form("")):
    user = require_user(request)
    course = store.get_course(user["id"], cid)
    if not course:
        raise HTTPException(404, "과목이 없습니다.")
    stage = course["primary_type"] + "1"
    if stage not in engine.TEMPLATES:
        raise HTTPException(400, f"{engine.TYPE_NAMES[course['primary_type']]}은 아직 자료 생성을 지원하지 않습니다 (MVP: A·B).")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 올릴 수 있습니다.")
    data = file.file.read()
    tmp = TMP / f"upload_{user['id']}_{int(time.time())}.pdf"
    tmp.write_bytes(data)
    try:
        est = engine.estimate_cost(stage, tmp)
    except Exception as e:
        raise HTTPException(400, f"PDF를 읽지 못했습니다: {e}")
    finally:
        tmp.unlink(missing_ok=True)
    lecture = store.create_lecture(user["id"], {
        "course_id": cid, "title": title, "week": week, "stage": stage,
        "pages": est["pages"], "status": "ready", "estimate": est,
    }, data)
    store.log_event(user["id"], "lecture_upload", course_id=cid, lecture_id=lecture["id"],
                    pages=est["pages"], size_kb=len(data) // 1024)
    return {k: lecture[k] for k in ("id", "title", "status")}


def owned_lecture(request, lid, columns="*"):
    user = require_user(request)
    lec = store.get_lecture(user["id"], lid, columns)
    if not lec:
        raise HTTPException(404, "강의가 없습니다.")
    return user, lec


@app.delete("/api/lectures/{lid}")
def delete_lecture(lid: str, request: Request):
    user = require_user(request)
    store.delete_lecture(user["id"], lid)
    return {"ok": True}


def run_generation(uid, lec, course):
    lid = lec["id"]
    job = JOBS[lid]
    label = f"{course['course_name']} ({course['professor']} 교수, {course['semester']})"
    pdf = TMP / f"gen_{lid}.pdf"
    started = time.time()

    def on_text(t):
        job["chars"] += len(t)

    try:
        pdf.write_bytes(store.download_pdf(lec["pdf_path"]))
        job["phase"] = "writing"
        note, rec = engine.generate_note(lec["stage"], pdf, label, lec["week"] or "(미상)", on_text=on_text)
        store.update_lecture(lid, {"note": note})
        job["phase"] = "checking"
        omissions, rec2 = engine.check_omissions(lec["stage"], pdf, note)
        note, results = engine.apply_omissions(note, omissions)
        cost = round(rec["cost_usd"] + rec2["cost_usd"], 3)
        store.update_lecture(lid, {"status": "done", "note": note, "omissions": results, "cost_usd": cost,
                                   "truncated": rec["stop_reason"] == "max_tokens", "error": None,
                                   "finished_at": store.now_iso()})
        store.log_event(uid, "generate_done", course_id=course["id"], lecture_id=lid, cost_usd=cost,
                        seconds=round(time.time() - started), pages=lec["pages"], omissions=len(results),
                        input_tokens=rec["input_tokens"] + rec2["input_tokens"],
                        output_tokens=rec["output_tokens"] + rec2["output_tokens"])
    except Exception as e:
        traceback.print_exc()
        store.update_lecture(lid, {"status": "error", "error": str(e)})
        store.log_event(uid, "generate_error", course_id=course["id"], lecture_id=lid, error=str(e)[:500])
    finally:
        pdf.unlink(missing_ok=True)
        JOBS.pop(lid, None)


@app.post("/api/lectures/{lid}/generate")
def generate(lid: str, request: Request):
    user, lec = owned_lecture(request, lid, "id,course_id,stage,week,pages,pdf_path,status")
    with LOCK:
        if lid in JOBS:
            return {"status": "running"}
        if not is_admin(user):
            used = store.generations_today(user["id"])
            if used >= DAILY_LIMIT:
                raise HTTPException(429, f"오늘 만들 수 있는 노트 {DAILY_LIMIT}개를 모두 썼어요. 내일 다시 이용해 주세요.")
        JOBS[lid] = {"phase": "queued", "chars": 0}
    course = store.get_course(user["id"], lec["course_id"])
    store.update_lecture(lid, {"status": "running", "error": None})
    store.log_event(user["id"], "generate_start", course_id=lec["course_id"], lecture_id=lid, pages=lec["pages"])
    threading.Thread(target=run_generation, args=(user["id"], lec, course), daemon=True).start()
    return {"status": "running"}


@app.get("/api/lectures/{lid}/progress")
def progress(lid: str, request: Request):
    _, lec = owned_lecture(request, lid, "id,status,error")
    return {**lec, **JOBS.get(lid, {})}


@app.get("/api/lectures/{lid}/note", response_class=PlainTextResponse)
def get_note(lid: str, request: Request):
    _, lec = owned_lecture(request, lid, "note")
    if not lec["note"]:
        raise HTTPException(404, "아직 노트가 없습니다.")
    return lec["note"]


MEMO_LOCK = threading.Lock()  # 한 강의의 여러 칸을 동시에 저장해도 서로 덮어쓰지 않게


@app.get("/api/lectures/{lid}/memos")
def get_memos(lid: str, request: Request):
    user, _ = owned_lecture(request, lid, "id")
    return store.get_memos(user["id"], lid)


class Memo(BaseModel):
    index: int
    text: str


@app.put("/api/lectures/{lid}/memos")
def save_memo(lid: str, body: Memo, request: Request):
    """필기 칸 하나를 저장한다 (빈 글이면 지움)."""
    user, _ = owned_lecture(request, lid, "id")
    if not 0 <= body.index < 5000 or len(body.text) > 20000:
        raise HTTPException(400, "필기 내용이 너무 길어요.")
    with MEMO_LOCK:
        memos = store.get_memos(user["id"], lid)
        if body.text.strip():
            memos[str(body.index)] = body.text
        else:
            memos.pop(str(body.index), None)
        store.save_memos(user["id"], lid, memos)
    return {"ok": True}


@app.get("/api/lectures/{lid}/edited")
def get_edited(lid: str, request: Request):
    user, _ = owned_lecture(request, lid, "id")
    return {"html": store.get_edited(user["id"], lid)}


class Edited(BaseModel):
    html: str


@app.put("/api/lectures/{lid}/edited")
def save_edited(lid: str, body: Edited, request: Request):
    """굵게·형광펜·글 수정을 넣은 노트 HTML을 저장한다 (화면에서 DOMPurify로 정리해서 보여 줌)."""
    user, lec = owned_lecture(request, lid, "id,status")
    if lec["status"] != "done":
        raise HTTPException(400, "노트가 완성된 뒤에 편집할 수 있어요.")
    if not body.html.strip() or len(body.html) > 3_000_000:
        raise HTTPException(400, "편집한 노트가 비어 있거나 너무 커요.")
    store.save_edited(user["id"], lid, body.html)
    return {"ok": True}


@app.delete("/api/lectures/{lid}/edited")
def revert_edited(lid: str, request: Request):
    """원본으로 되돌리기 (필기는 그대로 둔다)."""
    user, _ = owned_lecture(request, lid, "id")
    store.delete_edited(user["id"], lid)
    return {"ok": True}


@app.get("/api/lectures/{lid}/source")
def get_source(lid: str, request: Request):
    _, lec = owned_lecture(request, lid, "pdf_path,title")
    return Response(store.download_pdf(lec["pdf_path"]), media_type="application/pdf")


class Event(BaseModel):
    type: str
    lecture_id: str | None = None
    course_id: str | None = None


@app.post("/api/events")
def client_event(body: Event, request: Request):
    """화면에서만 알 수 있는 사용 기록 (노트 열람·다운로드·인쇄)."""
    user = require_user(request)
    if body.type not in ("note_view", "note_download", "note_print", "note_edit"):
        raise HTTPException(400, "알 수 없는 기록입니다.")
    store.log_event(user["id"], body.type, course_id=body.course_id, lecture_id=body.lecture_id)
    return {"ok": True}


# ---------- 자료 만족도 평가 ----------

@app.get("/api/lectures/{lid}/feedback")
def get_feedback(lid: str, request: Request):
    user, lec = owned_lecture(request, lid, "id,stage")
    return {"form": feedback.form(lec["stage"]), "feedback": store.get_feedback(user["id"], lid)}


@app.put("/api/lectures/{lid}/feedback")
async def save_feedback(lid: str, request: Request):
    user, lec = owned_lecture(request, lid, "id,stage,status,course_id")
    if lec["status"] != "done":
        raise HTTPException(400, "노트가 완성된 뒤에 평가할 수 있어요.")
    row, missing = feedback.validate(lec["stage"], await request.json())
    if missing:
        raise HTTPException(400, "점수 문항에 모두 답해 주세요.")
    course = store.get_course(user["id"], lec["course_id"])
    saved = store.save_feedback(user["id"], lec["course_id"], lid, lec["stage"], course["primary_type"], row)
    store.log_event(user["id"], "feedback_submit", course_id=lec["course_id"], lecture_id=lid,
                    overall=row["r_overall"], stage=lec["stage"])
    return saved


# ---------- 관리자 ----------

@app.get("/api/admin/overview")
def admin_overview(request: Request):
    user = require_user(request)
    if not is_admin(user):
        raise HTTPException(403, "관리자만 볼 수 있어요.")
    return {**store.admin_overview(), "feedback": store.feedback_overview()}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
