"""Supabase 저장 계층: 로그인(Auth), 사용자별 과목·강의(Postgres), 강의 PDF(Storage), 사용 기록(events).

서버만 secret key로 접근한다. 표에는 RLS가 켜져 있고 정책이 없어서 브라우저에서는 직접 못 읽는다.
그래서 여기의 모든 조회는 user_id로 직접 거른다 (빠뜨리면 다른 사용자 자료가 보인다).
"""
import re
from datetime import datetime, timedelta, timezone

from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

from app import engine

BUCKET = "lectures"
KST = timezone(timedelta(hours=9))


class StoreError(Exception):
    pass


def _options():
    # 서버에서는 세션을 저장하거나 자동 갱신하지 않는다 (사용자 토큰은 쿠키로 따로 관리)
    return SyncClientOptions(auto_refresh_token=False, persist_session=False)


def _config():
    url, key = engine.env_value("SUPABASE_URL"), engine.env_value("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise StoreError("SUPABASE_URL / SUPABASE_SECRET_KEY 가 없습니다 (.env 또는 환경변수).")
    # 대시보드 '데이터 API' 화면은 https://xxx.supabase.co/rest/v1/ 형태로 보여 준다 → 프로젝트 주소만 남긴다
    url = re.sub(r"/(rest|auth|storage)/v1/?$", "", url.strip()).rstrip("/")
    return url, key


_service = None


def service():
    """데이터 접근용 클라이언트. 이 클라이언트로는 절대 로그인하지 않는다 (로그인하면 권한이 사용자 것으로 바뀐다)."""
    global _service
    if _service is None:
        _service = create_client(*_config(), options=_options())
    return _service


def _auth_client():
    """로그인·토큰 갱신용 일회용 클라이언트."""
    return create_client(*_config(), options=_options()).auth


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------- 로그인 ----------

AUTH_MESSAGES = {
    "Invalid login credentials": "이메일 또는 비밀번호가 맞지 않아요.",
    "already been registered": "이미 가입된 이메일이에요. 로그인해 주세요.",
    "already registered": "이미 가입된 이메일이에요. 로그인해 주세요.",
    "Password should be at least": "비밀번호는 6자 이상이어야 해요.",
    "Unable to validate email address": "이메일 형식이 올바르지 않아요.",
}


def auth_message(e):
    text = str(e)
    return next((v for k, v in AUTH_MESSAGES.items() if k in text), f"로그인 처리 중 오류: {text}")


def _session_dict(res):
    s = res.session
    return {"access_token": s.access_token, "refresh_token": s.refresh_token,
            "user": {"id": res.user.id, "email": res.user.email}}


def sign_up(email, password):
    """이메일 인증 없이 바로 쓸 수 있는 계정을 만들고 로그인한다."""
    try:
        res = service().auth.admin.create_user({"email": email, "password": password, "email_confirm": True})
    except Exception as e:
        raise StoreError(auth_message(e))
    service().table("profiles").upsert({"id": res.user.id, "email": email}).execute()
    return sign_in(email, password)


def sign_in(email, password):
    try:
        return _session_dict(_auth_client().sign_in_with_password({"email": email, "password": password}))
    except Exception as e:
        raise StoreError(auth_message(e))


def refresh(refresh_token):
    try:
        res = _auth_client().refresh_session(refresh_token)
    except Exception:
        return None
    return _session_dict(res) if res and res.session else None


def user_from_token(access_token):
    try:
        res = service().auth.get_user(access_token)
    except Exception:
        return None
    return {"id": res.user.id, "email": res.user.email} if res and res.user else None


# ---------- 과목 ----------

def list_courses(uid):
    return service().table("courses").select("*").eq("user_id", uid).order("created_at").execute().data


def get_course(uid, cid):
    rows = service().table("courses").select("*").eq("user_id", uid).eq("id", cid).execute().data
    return rows[0] if rows else None


def create_course(uid, data):
    return service().table("courses").insert({**data, "user_id": uid}).execute().data[0]


def delete_course(uid, cid):
    paths = [l["pdf_path"] for l in list_lectures(uid, cid) if l.get("pdf_path")]
    if paths:
        service().storage.from_(BUCKET).remove(paths)
    service().table("courses").delete().eq("user_id", uid).eq("id", cid).execute()


# ---------- 강의 ----------

LECTURE_LIST_COLUMNS = "id,course_id,title,week,stage,pages,status,estimate,omissions,cost_usd,truncated,error,created_at,finished_at"


def list_lectures(uid, cid, columns=LECTURE_LIST_COLUMNS + ",pdf_path"):
    return (service().table("lectures").select(columns).eq("user_id", uid).eq("course_id", cid)
            .order("created_at").execute().data)


def count_lectures(uid):
    rows = service().table("lectures").select("course_id").eq("user_id", uid).execute().data
    counts = {}
    for r in rows:
        counts[r["course_id"]] = counts.get(r["course_id"], 0) + 1
    return counts


def get_lecture(uid, lid, columns="*"):
    rows = service().table("lectures").select(columns).eq("user_id", uid).eq("id", lid).execute().data
    return rows[0] if rows else None


def create_lecture(uid, data, pdf_bytes):
    row = service().table("lectures").insert({**data, "user_id": uid}).execute().data[0]
    path = f"{uid}/{row['id']}.pdf"
    service().storage.from_(BUCKET).upload(path, pdf_bytes, {"content-type": "application/pdf"})
    return update_lecture(row["id"], {"pdf_path": path})


def update_lecture(lid, fields):
    """작업 스레드에서도 부르므로 user_id 조건 없이 id로만 갱신한다 (lid는 서버가 만든 값만 들어온다)."""
    return service().table("lectures").update(fields).eq("id", lid).execute().data[0]


def delete_lecture(uid, lid):
    lec = get_lecture(uid, lid, "id,pdf_path")
    if not lec:
        return
    if lec.get("pdf_path"):
        service().storage.from_(BUCKET).remove([lec["pdf_path"]])
    service().table("lectures").delete().eq("user_id", uid).eq("id", lid).execute()


def download_pdf(path):
    return service().storage.from_(BUCKET).download(path)


def fail_interrupted_jobs():
    """서버가 재시작되면 돌던 생성 작업은 사라진다 → 'running'으로 남은 강의를 오류로 바꾼다."""
    service().table("lectures").update({
        "status": "error", "error": "서버가 다시 시작되어 생성이 중단됐어요. 다시 만들기를 눌러 주세요.",
    }).eq("status", "running").execute()


# ---------- 사용 기록 ----------

def log_event(uid, type_, course_id=None, lecture_id=None, **data):
    try:
        service().table("events").insert({"user_id": uid, "type": type_, "course_id": course_id,
                                          "lecture_id": lecture_id, "data": data}).execute()
    except Exception:
        pass  # 기록 실패가 서비스 사용을 막으면 안 된다


def generations_today(uid):
    start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    res = (service().table("events").select("id", count="exact").eq("user_id", uid)
           .eq("type", "generate_start").gte("created_at", start.isoformat()).execute())
    return res.count or 0


# ---------- 관리자 ----------

def admin_overview():
    profiles = service().table("profiles").select("*").order("created_at").execute().data
    lectures = service().table("lectures").select("user_id,status,cost_usd").execute().data
    courses = service().table("courses").select("user_id").execute().data
    events = (service().table("events").select("user_id,type,data,created_at,course_id,lecture_id")
              .order("created_at", desc=True).limit(100).execute().data)
    users = {p["id"]: {**p, "courses": 0, "lectures": 0, "notes": 0, "cost_usd": 0.0, "last_seen": None}
             for p in profiles}
    for c in courses:
        if c["user_id"] in users:
            users[c["user_id"]]["courses"] += 1
    for l in lectures:
        u = users.get(l["user_id"])
        if u:
            u["lectures"] += 1
            u["notes"] += l["status"] == "done"
            u["cost_usd"] += float(l["cost_usd"] or 0)
    for e in reversed(events):
        if e["user_id"] in users:
            users[e["user_id"]]["last_seen"] = e["created_at"]
    emails = {p["id"]: p["email"] for p in profiles}
    for e in events:
        e["email"] = emails.get(e["user_id"], "(탈퇴·알 수 없음)")
    total = round(sum(u["cost_usd"] for u in users.values()), 2)
    return {"users": list(users.values()), "events": events, "total_cost_usd": total}
