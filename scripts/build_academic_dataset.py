"""claude.ai 내보내기(conversations.json) + 라벨(labels/claude_conversations.csv)
→ 학업 관련 대화만 과목별로 정제해서 data/processed/ 에 저장한다.

사용: python scripts/build_academic_dataset.py
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data/raw/claude_export/conversations/conversations.json"
LABELS = ROOT / "data/labels/claude_conversations.csv"
OUT = ROOT / "data/processed"


def message_text(m):
    parts = [b.get("text", "") for b in m.get("content", []) if b.get("type") == "text"]
    return "\n".join(p for p in parts if p).strip() or (m.get("text") or "").strip()


def file_names(m):
    names = [a.get("file_name") for a in m.get("attachments", [])]
    names += [f.get("file_name") for f in m.get("files", [])]
    return [n for n in names if n]


def main():
    convs = json.loads(RAW.read_text(encoding="utf-8"))
    labels = {r["id"]: r for r in csv.DictReader(LABELS.open(encoding="utf-8"))}

    by_id = {c["uuid"][:8]: c for c in convs}
    missing = set(by_id) - set(labels)
    unknown = set(labels) - set(by_id)
    assert not missing, f"라벨 없는 대화: {sorted(missing)}"
    assert not unknown, f"대화 없는 라벨: {sorted(unknown)}"

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "academic").mkdir(exist_ok=True)

    # 1) 전체 인덱스
    with (OUT / "conversation_index.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "date", "title", "messages", "group", "course", "semester", "activities", "note"])
        for c in sorted(convs, key=lambda c: c["created_at"]):
            lb = labels[c["uuid"][:8]]
            w.writerow([lb["id"], c["created_at"][:10], c.get("name") or "", len(c.get("chat_messages", [])),
                        lb["group"], lb["course"], lb["semester"], lb["activities"], lb["note"]])

    # 2) 과목별 정제 데이터 (제외 그룹은 저장하지 않음)
    grouped = defaultdict(list)
    for c in convs:
        lb = labels[c["uuid"][:8]]
        if lb["group"] == "제외":
            continue
        msgs = []
        for m in c.get("chat_messages", []):
            text = message_text(m)
            files = file_names(m)
            if text or files:
                msgs.append({"sender": m.get("sender"), "created_at": m.get("created_at"),
                             "text": text, "files": files})
        grouped[(lb["group"], lb["course"])].append({
            "id": lb["id"], "uuid": c["uuid"], "date": c["created_at"][:10], "title": c.get("name") or "",
            "semester": lb["semester"], "activities": [a for a in lb["activities"].split(";") if a],
            "note": lb["note"], "summary": c.get("summary") or "", "messages": msgs,
        })

    for (group, course), items in grouped.items():
        d = OUT / "academic" / group
        d.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in course)
        with (d / f"{safe}.jsonl").open("w", encoding="utf-8") as f:
            for it in sorted(items, key=lambda x: x["date"]):
                f.write(json.dumps(it, ensure_ascii=False) + "\n")

    # 3) 요약 리포트
    rows = sorted(grouped.items(), key=lambda kv: (kv[0][0], -len(kv[1])))
    acts_all = Counter(a for items in grouped.values() for it in items for a in it["activities"])
    act_cols = [a for a, _ in acts_all.most_common()]
    excl = Counter(lb["note"] for lb in labels.values() if lb["group"] == "제외")

    lines = ["# Claude 대화 기록 — 학업 관련 정제 결과", "",
             f"- 전체 대화: {len(convs)}개 / 포함: {sum(len(v) for v in grouped.values())}개 / "
             f"제외: {sum(excl.values())}개", "",
             "## 그룹·과목별 대화 수와 활동 유형", "",
             "| 그룹 | 과목 | 대화 | 메시지 | " + " | ".join(act_cols) + " |",
             "|---|---|---|---|" + "---|" * len(act_cols)]
    for (group, course), items in rows:
        cnt = Counter(a for it in items for a in it["activities"])
        n_msg = sum(len(it["messages"]) for it in items)
        lines.append(f"| {group} | {course} | {len(items)} | {n_msg} | "
                     + " | ".join(str(cnt.get(a, "")) for a in act_cols) + " |")
    lines += ["", "## 활동 유형 전체 합계", ""]
    lines += [f"- {a}: {n}" for a, n in acts_all.most_common()]
    lines += ["", "## 제외 사유", ""]
    lines += [f"- {k or '(사유 없음)'}: {n}" for k, n in excl.most_common()]
    (OUT / "academic_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"included={sum(len(v) for v in grouped.values())} excluded={sum(excl.values())} courses={len(grouped)}")


if __name__ == "__main__":
    main()
