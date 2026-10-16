"""생성 엔진: 수업계획서 → 과목 유형 판정 / 강의 PDF → 단계별 노트 생성 → 누락 점검·보충.

CLI(scripts/generate_note.py)와 웹 서버(app/server.py)가 같이 쓴다.
PDF는 document 블록으로 그대로 보낸다. API가 페이지마다 텍스트 레이어와 페이지 이미지를 함께 읽으므로
"텍스트 추출 → 부족하면 이미지" 판별은 모델에 맡기고, 여기서는 판별 결과를 프롬프트 힌트로만 준다.
"""
import base64
import difflib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
import pypdf

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-5-5"
PRICE_PER_MTOK = {"input": 4.0, "output": 20.0}  # USD, claude-opus-5-5
LOW_TEXT_CHARS = 100  # A1 규칙 1절: 페이지 텍스트가 이 값 미만이면 이미지 글자로 본다
USAGE_LOG = ROOT / "logs" / "api_usage.jsonl"

# 규칙 파일. B1은 "A1을 기본으로 하고 아래만 다르다"이므로 A1을 함께 넣는다.
TEMPLATES = {
    "A1": ["A1_강의노트.md"],
    "B1": ["A1_강의노트.md", "B1_장별노트.md"],
}

# course_types_v0.md 2절. 생성 규칙이 있는 단계만 ready.
PIPELINES = {
    "A": [("A1", "주차별 강의 노트"), ("A2", "작품·원문 가이드"), ("A3", "개념 연결 노트"), ("A4", "서술형 대비 자료")],
    "B": [("B1", "장별 노트"), ("B2", "계산 원리·유도 노트"), ("B3", "예제·유사문제집"), ("B4", "실전 세트 + 오답·선지 분석")],
    "C": [("C1", "장별 노트"), ("C2", "개념 관계 노트"), ("C3", "사례 쉬운 정리"), ("C4", "시험 대비")],
    "D": [("D1", "주차 코드 노트"), ("D2", "헷갈리는 문법 Q&A"), ("D3", "예상문제 세트"), ("D4", "오답 노트")],
    "E": [("E1", "과제 조건·루브릭 정리"), ("E2", "자료 프레임 노트"), ("E3", "구조(개요)"), ("E4", "근거·출처 모음"), ("E5", "형식 맞추기")],
}
TYPE_NAMES = {"A": "서술·해석형", "B": "수리·계산형", "C": "개념·사례 이해형", "D": "코딩·실습형", "E": "과제·프로젝트형"}

# 테스트 단계(2026-10-16 결정): 자료를 만들 수 있는 유형은 A·B뿐 → C·D·E로 판정되면 A·B 중 가까운 쪽으로 서비스한다.
# 판정 때 모델이 과목마다 service_type을 고르고, 그 값이 없을 때만 아래 기본값을 쓴다.
SERVED_TYPES = ("A", "B")
NEAREST_SERVED = {"C": "A", "D": "B", "E": "A"}


def served_type(judged, suggested=None):
    if judged in SERVED_TYPES:
        return judged
    return suggested if suggested in SERVED_TYPES else NEAREST_SERVED.get(judged, "A")

COMMON_RULES = """# 모든 문서 공통 규칙 (사용자 대화 기록에서 반복 확인)
- 정리 = 구조화. 요약·축약·누락 금지. 슬라이드의 모든 문장을 빠짐없이 옮긴다.
- 필기 여백 확보 (`> **필기**` + `&nbsp;` 3줄)
- 입력 우선순위: 강의 스크립트·필기 > PPT > 외부 자료(쓰지 않음)
- 원본에 없는 내용 넣지 않기 (배경지식·해설·외부 자료 금지), 출처 슬라이드 `[p.N]` 표시
- 원본 오타는 고치지 않고 `⚠ 원본 표기` 메모
- 색·이모지 없이 검정 기준 (색 강조 → **굵게**)
- 문제는 문제 / 풀이(답안) / 풀이 공간 분리"""

# T4에서 4강 p.6의 한자 원문 단락이 통째로 빠졌다 → 빠지기 쉬운 요소를 이름으로 짚는다.
COMPLETENESS_RULES = """# 빠뜨리기 쉬운 요소 (반드시 옮긴다)
- 번역문과 한자 원문이 함께 있으면 **둘 다** 옮긴다. 한자 원문 단락·괄호 속 원문·출전(『책』「편」)을 생략하지 않는다.
- 슬라이드 구석의 짧은 문장, 화살표로 이어진 문장, 표 아래 주석, 그림 캡션, 말풍선 속 문장도 옮긴다.
- 같은 제목이 이어지는 슬라이드를 묶더라도 각 슬라이드의 내용은 하나도 빼지 않는다."""

OUTPUT_RULES = """# 출력 형식
- 완성된 마크다운 노트 본문만 출력한다. 앞뒤 설명, 인사, 코드블록(```)으로 감싸기 금지.
- 규칙 문서의 "기준 결과물" 경로는 참고용 이름일 뿐이며, 그 파일은 제공되지 않는다."""

OMISSION_SCHEMA = {
    "type": "object",
    "properties": {
        "omissions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer"},
                    "description": {"type": "string"},
                    "anchor": {"type": "string"},
                    "insert": {"type": "string"},
                },
                "required": ["page", "description", "anchor", "insert"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["omissions"],
    "additionalProperties": False,
}

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "course_name": {"type": "string"},
        "professor": {"type": "string"},
        "semester": {"type": "string"},
        "primary_type": {"type": "string", "enum": ["A", "B", "C", "D", "E"]},
        "secondary_types": {"type": "array", "items": {"type": "string", "enum": ["A", "B", "C", "D", "E"]}},
        "service_type": {"type": "string", "enum": ["A", "B"]},
        "service_reason": {"type": "string"},
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"signal": {"type": "string"}, "evidence": {"type": "string"}},
                "required": ["signal", "evidence"],
                "additionalProperties": False,
            },
        },
        "evaluation": {"type": "string"},
        "weeks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"week": {"type": "string"}, "topic": {"type": "string"}},
                "required": ["week", "topic"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["course_name", "professor", "semester", "primary_type", "secondary_types", "service_type", "service_reason",
                 "reasons", "evaluation", "weeks"],
    "additionalProperties": False,
}


# ---------- 공통 ----------

def env_value(name):
    """환경변수 → 없으면 STUDY_IN_UNIV/.env 에서 읽는다."""
    if os.environ.get(name):
        return os.environ[name].strip()
    env = ROOT / ".env"
    if not env.exists():
        return ""
    m = re.search(rf"^{name}=(.*)$", env.read_text(encoding="utf-8-sig"), re.M)
    return m.group(1).strip() if m else ""


def load_api_key():
    key = env_value("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 가 없습니다 (.env 또는 환경변수).")
    return key


def client():
    return anthropic.Anthropic(api_key=load_api_key())


def cost_usd(usage):
    return (usage.input_tokens * PRICE_PER_MTOK["input"] + usage.output_tokens * PRICE_PER_MTOK["output"]) / 1e6


def log_usage(kind, name, msg, seconds, **extra):
    record = {
        "time": datetime.now().isoformat(timespec="seconds"), "kind": kind, "name": name, "model": msg.model,
        "input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens,
        "cost_usd": round(cost_usd(msg.usage), 4), "seconds": round(seconds), "stop_reason": msg.stop_reason,
        "message_id": msg.id, **extra,
    }
    USAGE_LOG.parent.mkdir(exist_ok=True)
    with USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def stream_message(on_text=None, **params):
    """긴 출력용 스트리밍 호출. 안전 분류기가 거절하면 서버가 다른 모델로 이어서 처리하도록 fallbacks를 켠다."""
    with client().beta.messages.stream(
        model=MODEL,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        **params,
    ) as stream:
        if on_text:
            for text in stream.text_stream:
                on_text(text)
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"요청이 거절되었습니다: {msg.stop_details}")
    return msg


def message_text(msg):
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def pdf_block(pdf_path):
    return {"type": "document", "source": {
        "type": "base64", "media_type": "application/pdf",
        "data": base64.standard_b64encode(Path(pdf_path).read_bytes()).decode("ascii"),
    }}


# ---------- 강의 노트 생성 ----------

def pdf_profile(path):
    """페이지별 텍스트 길이로 '글자가 이미지인 PDF'인지 판별한다 (프롬프트 힌트·로그용)."""
    reader = pypdf.PdfReader(path)
    chars = [len((p.extract_text() or "").strip()) for p in reader.pages]
    low = sum(c < LOW_TEXT_CHARS for c in chars)
    return {"pages": len(chars), "low_text_pages": low, "image_text": low > len(chars) / 2}


def build_system(template):
    parts = [(ROOT / "docs" / "templates" / name).read_text(encoding="utf-8") for name in TEMPLATES[template]]
    parts += [COMMON_RULES, COMPLETENESS_RULES, OUTPUT_RULES]
    return "\n\n---\n\n".join(parts)


def build_user_text(template, profile, course, week):
    lines = [
        f"첨부한 강의 PDF로 {template} 생성 규칙에 따라 노트를 작성하라.",
        "",
        f"- 과목: {course}",
        f"- 수업계획서 주차: {week}",
        f"- 입력 자료: 강의 PPT {profile['pages']}장 (스크립트·필기 없음 → PPT만으로 작성, 필기 여백 크게)",
    ]
    if profile["image_text"]:
        lines.append(
            f"- PDF 상태: {profile['pages']}장 중 {profile['low_text_pages']}장의 텍스트 레이어가 {LOW_TEXT_CHARS}자 미만이다. "
            "글자가 이미지로 저장된 PDF이므로 페이지 이미지를 기준으로 읽고, 텍스트 레이어(주로 한자)는 대조용으로만 써라."
        )
    if template == "B1":
        lines.append("- 수식은 텍스트 레이어가 깨져 있으므로 항상 페이지 이미지를 기준으로 LaTeX로 옮겨라.")
    return "\n".join(lines)


def note_request(template, pdf_path, course, week):
    profile = pdf_profile(pdf_path)
    system = build_system(template)
    messages = [{"role": "user", "content": [
        pdf_block(pdf_path),
        {"type": "text", "text": build_user_text(template, profile, course, week)},
    ]}]
    return profile, system, messages


def estimate_cost(template, pdf_path, course="", week=""):
    """생성 + 누락 점검 예상 비용. 입력은 count_tokens(무료)로 재고, 출력은 T4 실측(장당 약 450~600 토큰)으로 어림한다."""
    profile, system, messages = note_request(template, pdf_path, course, week)
    n_in = client().messages.count_tokens(model=MODEL, system=system, messages=messages).input_tokens
    per_page = 600 if template.startswith("B") else 450
    note_out = profile["pages"] * per_page
    low = ((n_in * 2 + note_out) * PRICE_PER_MTOK["input"] + note_out * 1.2 * PRICE_PER_MTOK["output"]) / 1e6
    high = ((n_in * 2 + note_out) * PRICE_PER_MTOK["input"] + note_out * 2.0 * PRICE_PER_MTOK["output"]) / 1e6
    return {"pages": profile["pages"], "input_tokens": n_in, "low_usd": round(low, 2), "high_usd": round(high, 2)}


def generate_note(template, pdf_path, course, week, effort="high", on_text=None):
    profile, system, messages = note_request(template, pdf_path, course, week)
    start = time.time()
    msg = stream_message(on_text=on_text, max_tokens=64000, output_config={"effort": effort},
                         system=system, messages=messages)
    record = log_usage("generate", Path(pdf_path).name, msg, time.time() - start,
                       template=template, pages=profile["pages"], effort=effort)
    return message_text(msg), record


# ---------- 누락 점검 ----------

CHECK_PROMPT = """첨부한 강의 PDF와 아래 노트를 슬라이드 한 장씩 대조하라.
슬라이드에 있는데 노트에 **빠진 내용**만 찾는다: 문장, 글머리표 항목, 한자 원문·병기 단락, 출전, 인용, 표의 행·셀, 그림 캡션, [이미지] 설명.

찾지 않는 것: 표현·띄어쓰기·문장부호 차이, 노트가 묶거나 순서를 바꾼 것, 요약표, 필기 여백, 메타 표, ⚠ 메모.
노트에 이미 있는 내용을 다시 넣지 않는다. 확실한 누락만 보고한다.

각 누락마다:
- page: 슬라이드 번호
- description: 무엇이 빠졌는지 한 줄
- anchor: 이 내용이 들어갈 자리 **바로 앞**에 있는, 노트에 실제로 있는 한 줄을 글자 그대로 복사 (앞뒤 공백 제외)
- insert: 노트에 끼워 넣을 마크다운. 생성 규칙(원문 그대로, 인용은 `>` 블록, 출전 표기, 색 강조는 굵게)을 따르고 줄 끝에 `[p.N]`을 붙인다

빠진 것이 없으면 omissions를 빈 배열로 둔다.

<note>
{note}
</note>"""


HANJA = re.compile(r"[㐀-䶿一-鿿豈-﫿]")


def text_layer_gaps(pdf_path, note, min_chars=8):
    """기계 대조: 쪽마다 텍스트 레이어의 한자 덩어리가 노트에 있는지 본다.
    T4에서 모델 점검만으로는 한자 원문 단락 누락(4강 p.6)을 못 잡았다. 한자는 이미지 글자 PDF에서도 텍스트로 남는다."""
    note_hanja = "".join(HANJA.findall(note))
    gaps = []
    for no, page in enumerate(pypdf.PdfReader(pdf_path).pages, 1):
        text = page.extract_text() or ""
        # 문장부호·공백으로 이어진 한자 덩어리 (한글이 끼면 끊는다)
        for run in re.findall(r"[㐀-䶿一-鿿豈-﫿][㐀-䶿一-鿿豈-﫿\s,.·…:;!?、。，]*", text):
            chars = "".join(HANJA.findall(run))
            if len(chars) < min_chars:
                continue
            # 8자씩 잘라서 절반 넘게 노트에 없으면 누락 의심
            pieces = [chars[i:i + 8] for i in range(0, len(chars) - 7, 8)] or [chars]
            missing = sum(p not in note_hanja for p in pieces)
            if missing / len(pieces) > 0.5:
                gaps.append({"page": no, "text": re.sub(r"\s+", " ", run).strip()})
    return gaps


def check_omissions(template, pdf_path, note, effort="high"):
    gaps = text_layer_gaps(pdf_path, note)
    prompt = CHECK_PROMPT.format(note=note)
    if gaps:
        hints = "\n".join(f"- p.{g['page']}: {g['text'][:300]}" for g in gaps)
        prompt += ("\n\n<machine_check>\nPDF 텍스트 레이어와 노트를 기계로 대조한 결과, 아래 한자 원문이 노트에서 발견되지 않았다. "
                   "해당 쪽 이미지에서 확인하고, 실제로 빠졌으면 omissions에 반드시 포함하라 (원문은 페이지 이미지 기준, "
                   f"텍스트 레이어는 대조용).\n{hints}\n</machine_check>")
    start = time.time()
    msg = stream_message(
        max_tokens=32000,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": OMISSION_SCHEMA}},
        system=build_system(template),
        messages=[{"role": "user", "content": [pdf_block(pdf_path), {"type": "text", "text": prompt}]}],
    )
    data = json.loads(message_text(msg))
    record = log_usage("check", Path(pdf_path).name, msg, time.time() - start,
                       template=template, omissions=len(data["omissions"]), machine_gaps=len(gaps))
    return data["omissions"], record


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def apply_omissions(note, omissions):
    """anchor 줄 뒤에 insert를 끼워 넣는다. 표·인용 블록 한가운데면 블록이 끝난 뒤에 넣는다.
    anchor를 못 찾으면 맨 끝 '누락 점검으로 보충한 내용' 절에 모은다. 반환: (새 노트, 적용 결과 목록)."""
    lines = note.split("\n")
    norm_lines = [_norm(l) for l in lines]
    inserts = {}  # 줄 번호 → 끼워 넣을 블록들
    leftover, results = [], []
    for om in omissions:
        anchor = _norm(om["anchor"])
        idx = next((i for i, l in enumerate(norm_lines) if l == anchor), None)
        if idx is None and anchor:
            scored = [(difflib.SequenceMatcher(None, anchor, l).ratio(), i) for i, l in enumerate(norm_lines) if l]
            best = max(scored, default=(0, None))
            idx = best[1] if best[0] >= 0.9 else None
        if idx is None:
            leftover.append(om)
            results.append({**om, "placed": "appendix"})
            continue
        lead = lines[idx].lstrip()[:1]
        if lead in ("|", ">"):
            while idx + 1 < len(lines) and lines[idx + 1].lstrip()[:1] == lead:
                idx += 1
        inserts.setdefault(idx, []).append(om["insert"].strip())
        results.append({**om, "placed": "inline"})

    list_item = re.compile(r"^\s*([-*+]|\d+\.)\s")
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        for block in inserts.get(i, []):
            # 목록 항목 사이에 목록 항목을 넣을 때는 빈 줄 없이 붙여야 목록이 끊기지 않는다
            out += [block] if list_item.match(line) and list_item.match(block) else ["", block, ""]
    if leftover:
        out += ["", "---", "", "## 누락 점검으로 보충한 내용", "",
                "> 자동 점검에서 찾았지만 들어갈 자리를 정하지 못한 내용 (원본 쪽 표시 참고)", ""]
        for om in leftover:
            out += [f"### {om['description']} `[p.{om['page']}]`", "", om["insert"].strip(), ""]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n", results


# ---------- 과목 유형 판정 ----------

CLASSIFY_PROMPT = """아래 수업계획서로 과목 유형을 판정하라. 유형 정의와 판정 기준은 system의 문서(과목 유형 정의 v0) 1·3절을 따른다.

- primary_type: 주 유형 하나. secondary_types: 함께 붙는 유형 (예: 보고서·발표·과제 비중이 50% 이상이면 E). 없으면 빈 배열
- service_type: 지금 서비스는 A·B 파이프라인만 자료를 만든다. primary_type이 A나 B면 그대로 적는다.
  C·D·E면 이 과목의 실제 공부 흐름이 어느 쪽에 더 가까운지로 고른다 — 강의 내용을 읽고 정리·해석·서술·암기하는 쪽이면 A,
  계산·공식·풀이 과정을 익히고 문제를 푸는 쪽이면 B. 시험 형식(서술형·논술 / 계산·객관식 문제)과 수업 자료 성격을 근거로.
- service_reason: service_type을 고른 근거 한 줄 (primary_type이 A·B면 빈 문자열)
- reasons: 판정 근거. signal = 판정 기준 중 무엇인지 (학문 분야 / 수업 자료 성격 / 시험 형식 / 평가 비중), evidence = 수업계획서의 원문 문장을 그대로
- evaluation: 평가 항목과 비율을 한 줄로 (예: "기말 40 / 중간 대체과제 15 / 조별발표 20")
- weeks: 주차별 강의 주제. 수업계획서에 있는 그대로 (week 예: "7주차")
- 수업계획서에 없는 정보는 빈 문자열

<syllabus>
{text}
</syllabus>"""


def syllabus_text_from_pdf(pdf_path):
    """학교 포털 수업계획서 PDF(한글 폰트 미내장)는 전용 추출기, 실패하면 일반 텍스트 추출."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from extract_syllabus_pdf import extract
        text = extract(str(pdf_path))
    except Exception:
        text = ""
    if len(text.strip()) < 200:
        text = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(pdf_path).pages)
    return text.strip()


# 글자가 도형(선)으로 그려진 PDF(예: 한컴 PDF로 저장한 전북대 포털 강의계획서)는 텍스트 레이어가 0자다.
# 이때는 PDF를 그대로 보내 페이지 이미지로 판정하고, 수업계획서 전문도 같은 호출에서 글자로 옮겨 받는다.
CLASSIFY_PDF_SCHEMA = {
    **CLASSIFY_SCHEMA,
    "properties": {**CLASSIFY_SCHEMA["properties"], "syllabus_text": {"type": "string"}},
    "required": CLASSIFY_SCHEMA["required"] + ["syllabus_text"],
}
CLASSIFY_PDF_NOTE = """- syllabus_text: 첨부 PDF의 수업계획서 내용을 빠짐없이 글자 그대로 옮긴 전문 (표는 "항목: 값" 줄로, 체크 표시는 ☑/☐로)
- 첨부 PDF는 글자가 도형으로 그려져 텍스트 레이어가 없다. 페이지 이미지를 기준으로 읽어라."""


def classify_syllabus(text="", pdf_path=None):
    """text로 판정한다. text 없이 pdf_path만 주면 PDF를 페이지 이미지로 읽어 판정하고 result["syllabus_text"]에 전문을 담는다."""
    if pdf_path:
        prompt = CLASSIFY_PROMPT.format(text="(첨부한 PDF)") + "\n\n" + CLASSIFY_PDF_NOTE
        content = [pdf_block(pdf_path), {"type": "text", "text": prompt}]
        schema = CLASSIFY_PDF_SCHEMA
    else:
        content, schema = CLASSIFY_PROMPT.format(text=text[:60000]), CLASSIFY_SCHEMA
    start = time.time()
    msg = stream_message(
        max_tokens=16000,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        system=(ROOT / "docs" / "course_types_v0.md").read_text(encoding="utf-8"),
        messages=[{"role": "user", "content": content}],
    )
    record = log_usage("classify", "syllabus", msg, time.time() - start, source="pdf_image" if pdf_path else "text")
    return json.loads(message_text(msg)), record
