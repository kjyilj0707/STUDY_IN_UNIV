"""수동(승인) 노트 vs 자동 생성 노트 비교 — 구조 지표 + 누락 의심 문장.

사용: python -I -X utf8 scripts/compare_notes.py <기준.md> <자동.md>
"""
import difflib
import re
import sys
from pathlib import Path

PAGE = re.compile(r"\[p\.(\d+)(?:~(\d+))?\]")


def pages_cited(text):
    pages = set()
    for a, b in PAGE.findall(text):
        pages.update(range(int(a), int(b or a) + 1))
    return pages


def body_lines(text):
    """비교용 본문 줄: 필기 여백·구분선·빈 줄 제외, 마크다운 기호·쪽 표시 제거."""
    out = []
    for line in text.splitlines():
        s = PAGE.sub("", line)
        s = re.sub(r"[`*>#|\-]", " ", s).replace("&nbsp;", " ")
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) >= 8 and s != "필기":
            out.append(s)
    return out


def stats(text):
    return {
        "줄 수": len(text.splitlines()),
        "## 단원": len(re.findall(r"^## ", text, re.M)),
        "### 묶음": len(re.findall(r"^### ", text, re.M)),
        "필기 여백": text.count("> **필기**"),
        "풀이 공간": text.count("> **풀이 공간**"),
        "⚠ 메모": text.count("⚠"),
        "굵게": len(re.findall(r"\*\*[^*]+\*\*", text)),
        "인용쪽 수": len(pages_cited(text)),
    }


def main():
    ref, auto = (Path(p).read_text(encoding="utf-8") for p in sys.argv[1:3])
    s_ref, s_auto = stats(ref), stats(auto)
    print(f"{'지표':<10}{'기준':>8}{'자동':>8}")
    for k in s_ref:
        print(f"{k:<10}{s_ref[k]:>8}{s_auto[k]:>8}")

    missing_pages = sorted(pages_cited(ref) - pages_cited(auto))
    print(f"\n자동 노트에 [p.N] 표시가 없는 쪽: {missing_pages or '없음'}")

    auto_lines = body_lines(auto)
    auto_joined = " ".join(auto_lines)
    missing = []
    for line in body_lines(ref):
        if line in auto_joined:
            continue
        best = max((difflib.SequenceMatcher(None, line, a).ratio() for a in auto_lines), default=0)
        if best < 0.8:
            missing.append((best, line))
    total = len(body_lines(ref))
    print(f"기준 본문 {total}줄 중 자동 노트에서 비슷한 줄(유사도 0.8 이상)을 못 찾은 줄: {len(missing)}줄 "
          f"({len(missing) / max(total, 1):.0%})")
    for best, line in missing[:40]:
        print(f"  [{best:.2f}] {line[:110]}")
    whole = difflib.SequenceMatcher(None, " ".join(body_lines(ref)), auto_joined, autojunk=False).ratio()
    print(f"\n전체 본문 유사도: {whole:.2f}")


if __name__ == "__main__":
    main()
