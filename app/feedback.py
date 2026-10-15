"""과목 유형 안내 문구 + 자료 만족도 평가표 정의.

평가표는 화면(문항 표시)과 서버(값 검사)와 DB(칸 이름)가 같은 정의를 쓴다.
점수 문항은 모두 1~5점 (1 전혀 아니다 · 3 보통 · 5 매우 그렇다). DB 칸 이름 = "r_" + key.
"""

# ---------- 과목 유형 안내 (docs/course_types_v0.md 1·2절을 사용자용 말로) ----------

TYPE_GUIDE = {
    "A": {
        "name": "서술·해석형",
        "about": "작품·원문·사상을 읽고 해석하는 과목이에요. 강의에서 다룬 내용을 빠짐없이 정리하고, "
                 "원문과 해석을 연결해 서술형 답안으로 풀어내는 힘이 중요해요.",
        "exam": "서술형·논술형 시험 (예: \"~에 대해 설명하라\")",
        "flow": ["강의 내용을 빠짐없이 정리", "작품·원문 확인", "개념끼리 연결", "서술형 답안 준비"],
    },
    "B": {
        "name": "수리·계산형",
        "about": "정의·공식과 계산 절차를 익혀 문제를 푸는 과목이에요. 공식을 정확히 정리하고, "
                 "예제와 유사문제를 반복해서 푸는 것이 중요해요.",
        "exam": "계산·풀이 문제, 객관식(선지 판단)",
        "flow": ["장별로 정의·공식 정리", "계산 원리·유도 이해", "예제·유사문제 반복", "실전 문제와 오답 분석"],
    },
    "C": {
        "name": "개념·사례 이해형",
        "about": "개념과 용어, 사례를 이해하는 과목이에요. 헷갈리는 개념끼리 구분하고, "
                 "사례를 강의의 틀에 맞춰 정리하는 것이 중요해요.",
        "exam": "객관식·단답형 위주",
        "flow": ["장별 정리", "개념 사이 관계 정리", "사례 쉽게 정리", "시험 대비"],
    },
    "D": {
        "name": "코딩·실습형",
        "about": "코드를 읽고 직접 작성하는 과목이에요. 코드가 어떻게 동작하는지 이해하고, "
                 "기출 형식에 맞춘 문제를 풀어 보는 것이 중요해요.",
        "exam": "코드 작성·빈칸 채우기·결과값 쓰기",
        "flow": ["주차별 코드 노트", "헷갈리는 문법 정리", "예상문제 풀기", "오답 노트"],
    },
    "E": {
        "name": "과제·프로젝트형",
        "about": "보고서·발표·과제가 평가의 중심인 과목이에요. 과제 조건과 채점 기준을 먼저 파악하고, "
                 "자료를 엮어 구조를 세우는 것이 중요해요.",
        "exam": "보고서·발표 (채점 기준표로 평가)",
        "flow": ["과제 조건·채점 기준 정리", "자료 정리", "구조(개요) 세우기", "근거·형식 맞추기"],
    },
}

# ---------- 자료 만족도 평가표 ----------

COMMON_RATINGS = [
    ("completeness", "완전성", "슬라이드 내용이 빠짐없이 들어 있었다"),
    ("accuracy", "정확성", "원본과 다르게 옮겨진 곳(글자·숫자·용어)이 없었다"),
    ("structure", "구성", "목차와 제목 구성이 따라가기 쉬웠다"),
    ("traceability", "출처 대조", "[p.N] 표시로 원본 슬라이드를 찾기 쉬웠다"),
    ("writing_space", "필기 공간", "필기 여백이 실제로 쓸모 있었다"),
    ("time_saving", "시간 절약", "직접 정리하는 것보다 시간이 줄었다"),
]

STAGE_RATING = {  # 단계별로 하나씩 더 묻는 문항 (DB 칸은 r_stage_specific 하나)
    "A1": ("stage_specific", "원문 정확도", "원문·인용(작품 원문, 한자, 출전)이 정확하게 옮겨졌다"),
    "B1": ("stage_specific", "수식·예제", "수식과 예제(문제·풀이)가 정확하고 보기 좋았다"),
}

OVERALL = ("overall", "전체 유용성", "전체적으로 이 자료는 공부에 유용했다")

REUSE = [("yes", "예"), ("maybe", "아마도"), ("no", "아니오")]
USAGE = [("preview", "수업 전 예습"), ("in_class", "수업 중 필기"), ("review", "복습"),
         ("exam", "시험 공부"), ("not_yet", "아직 안 씀")]
TIME_SAVED = [("none", "거의 없음"), ("lt30", "30분 미만"), ("30_60", "30분~1시간"),
              ("60_120", "1~2시간"), ("gt120", "2시간 이상")]
ISSUES = [("missing", "빠진 내용이 있다"), ("wrong", "잘못 옮겨진 내용이 있다"), ("added", "원본에 없는 내용이 있다"),
          ("order", "순서·구성이 이상하다"), ("math", "수식·표가 깨졌다"), ("too_long", "너무 길다"),
          ("hard_to_read", "읽기 어렵다"), ("none", "문제 없음")]

SCALE = {1: "전혀 아니다", 2: "아니다", 3: "보통", 4: "그렇다", 5: "매우 그렇다"}


def form(stage):
    ratings = list(COMMON_RATINGS)
    if stage in STAGE_RATING:
        ratings.append(STAGE_RATING[stage])
    return {
        "scale": SCALE,
        "overall": dict(zip(("key", "label", "question"), OVERALL)),
        "ratings": [dict(zip(("key", "label", "question"), r)) for r in ratings],
        "reuse": REUSE, "usage": USAGE, "time_saved": TIME_SAVED, "issues": ISSUES,
    }


def rating_keys(stage):
    keys = [OVERALL[0]] + [r[0] for r in COMMON_RATINGS]
    if stage in STAGE_RATING:
        keys.append(STAGE_RATING[stage][0])
    return keys


def validate(stage, data):
    """화면에서 온 평가를 DB 행 형태로 바꾼다. 점수는 모두 필수, 나머지는 선택."""
    row, errors = {}, []
    for key in rating_keys(stage):
        v = data.get("ratings", {}).get(key)
        if not isinstance(v, int) or not 1 <= v <= 5:
            errors.append(key)
        row[f"r_{key}"] = v
    allowed = {k for k, _ in REUSE}
    row["reuse"] = data.get("reuse") if data.get("reuse") in allowed else None
    row["usage"] = [u for u in data.get("usage", []) if u in {k for k, _ in USAGE}]
    row["time_saved"] = data.get("time_saved") if data.get("time_saved") in {k for k, _ in TIME_SAVED} else None
    row["issues"] = [i for i in data.get("issues", []) if i in {k for k, _ in ISSUES}]
    for key in ("best", "worst", "issue_pages"):
        row[key] = (data.get(key) or "").strip()[:2000]
    return row, errors
