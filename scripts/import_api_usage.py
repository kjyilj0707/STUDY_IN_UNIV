"""이 컴퓨터의 Claude 사용 기록(logs/api_usage.jsonl)을 Supabase 사용 기록(api_call)으로 옮긴다.

사이트(Render)에서 한 호출은 서버가 바로 api_call로 남기지만, scripts/generate_note.py 같은 CLI 호출은
이 파일에만 남는다. 관리자 "사용량·요금" 페이지에 모두 보이게 하려고 옮긴다.
이미 옮겼거나 서버가 기록한 호출(같은 message_id)은 건너뛴다. 사용자 칸은 비워 두고 source에 "local"을 붙인다.

실행 (STUDY_IN_UNIV 폴더에서): python -X utf8 scripts/import_api_usage.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import store  # noqa: E402

KEEP = ("kind", "model", "input_tokens", "output_tokens", "cost_usd", "seconds", "stop_reason", "template", "pages",
        "message_id")


def main():
    log = ROOT / "logs" / "api_usage.jsonl"
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    done = {e["data"].get("message_id") for e in
            store._paged(lambda: store.service().table("events").select("data").eq("type", "api_call"))}
    new = []
    for r in rows:
        if not r.get("message_id") or r["message_id"] in done:
            continue
        # 기록 시각은 이 컴퓨터 시간(한국)이다 → UTC로
        at = datetime.fromisoformat(r["time"]).replace(tzinfo=store.KST).astimezone(timezone.utc).isoformat()
        new.append({"user_id": None, "type": "api_call", "created_at": at,
                    "data": {**{k: r[k] for k in KEEP if k in r}, "source": f"local · {r.get('name', '')}", "imported": True}})
    for i in range(0, len(new), 500):
        store.service().table("events").insert(new[i:i + 500]).execute()
    print(f"기록 {len(rows)}개 중 새로 옮김 {len(new)}개 (비용 ${sum(n['data']['cost_usd'] for n in new):.2f})")


if __name__ == "__main__":
    main()
