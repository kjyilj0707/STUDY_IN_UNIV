"""강의 PDF → 노트 생성 → 누락 점검·보충 (1단계 엔진 CLI). 엔진 본체는 app/engine.py.

사용:
  python -I -X utf8 scripts/generate_note.py A1 <입력.pdf> <출력.md> --course "고전문학의 이해 (교수A 교수, 2026-2)" --week "7주차 \"...\"" [--dry-run]
  --dry-run   : 생성하지 않고 예상 비용만 출력 (count_tokens, 무료)
  --check-only: 이미 있는 <출력.md>에 누락 점검만 돌려서 보충
  --no-check  : 누락 점검을 건너뜀
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import engine  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template", choices=sorted(engine.TEMPLATES))
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--course", default="")
    ap.add_argument("--week", default="(미상)")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--check-only", action="store_true")
    group.add_argument("--no-check", action="store_true")
    args = ap.parse_args()

    if args.dry_run:
        est = engine.estimate_cost(args.template, args.pdf, args.course, args.week)
        print(f"PDF {est['pages']}장, 입력 {est['input_tokens']:,} 토큰 → 생성+점검 예상 ${est['low_usd']}~{est['high_usd']}")
        return

    if args.check_only:
        note = args.out.read_text(encoding="utf-8")
    else:
        if not args.course:
            sys.exit("--course 가 필요합니다.")
        note, rec = engine.generate_note(args.template, args.pdf, args.course, args.week, args.effort)
        print(f"생성: 입력 {rec['input_tokens']:,} / 출력 {rec['output_tokens']:,} 토큰 / ${rec['cost_usd']} / {rec['seconds']}초")
        if rec["stop_reason"] == "max_tokens":
            print("⚠ max_tokens 도달 — 노트가 중간에 잘렸을 수 있음")

    if not args.no_check:
        omissions, rec = engine.check_omissions(args.template, args.pdf, note, args.effort)
        note, results = engine.apply_omissions(note, omissions)
        print(f"누락 점검: {len(omissions)}건 / 입력 {rec['input_tokens']:,} / 출력 {rec['output_tokens']:,} 토큰 / ${rec['cost_usd']}")
        for r in results:
            print(f"  [p.{r['page']}] {r['description']} → {r['placed']}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(note, encoding="utf-8")
    print(f"저장: {args.out}")


if __name__ == "__main__":
    main()
