"""評価ランナー。

例:
  python eval.py --config baseline@anthropic:claude-opus-5-5 \
                 --config baseline@aiand:zai-org/glm-5.3-flash \
                 --config harness@aiand:zai-org/glm-5.3-flash
  python eval.py --config baseline@mock:x --limit 5   # キーなしで動作確認
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents import AGENTS

ROOT = Path(__file__).parent


def run_config(spec: str, data: list[dict], workers: int) -> dict:
    agent_name, model = spec.split("@", 1)
    agent = AGENTS[agent_name]

    def one(item: dict) -> dict:
        try:
            p = agent(model, item)
            return {"id": item["id"], "gold": item["label"], "pred": p.label, "reason": p.reason,
                    "cost": p.cost, "latency": p.latency, "calls": p.calls, "trace": p.trace}
        except Exception as e:  # 1件の失敗で全体を止めない
            return {"id": item["id"], "gold": item["label"], "pred": None, "error": repr(e),
                    "cost": 0.0, "latency": 0.0, "calls": 0, "trace": []}

    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(one, data))

    n = len(rows)
    correct = sum(r["pred"] == r["gold"] for r in rows)
    # 見逃し(要返信なのに返信不要と判定)は採用の現場で一番痛いので別に数える
    miss = sum(r["gold"] == "要返信" and r["pred"] != "要返信" for r in rows)
    summary = {
        "config": spec,
        "n": n,
        "accuracy": correct / n if n else 0,
        "miss_要返信": miss,
        "invalid": sum(r["pred"] is None for r in rows),
        "cost_usd": sum(r["cost"] for r in rows),
        "avg_latency_s": sum(r["latency"] for r in rows) / n if n else 0,
        "avg_calls": sum(r["calls"] for r in rows) / n if n else 0,
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", action="append", required=True, help="agent@provider:model")
    ap.add_argument("--data", default=str(ROOT / "data" / "dataset.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    data = [json.loads(l) for l in Path(args.data).read_text().splitlines() if l.strip()]
    if args.limit:
        data = data[: args.limit]

    results = [run_config(c, data, args.workers) for c in args.config]

    out = ROOT / "results" / f"run_{time.strftime('%H%M%S')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    (ROOT / "results" / "latest.json").write_text(out.read_text())

    print(f"\n{'config':<55} {'acc':>6} {'miss':>5} {'inv':>4} {'cost$':>8} {'lat_s':>6} {'calls':>5}")
    for r in results:
        s = r["summary"]
        print(f"{s['config']:<55} {s['accuracy']:>6.1%} {s['miss_要返信']:>5} {s['invalid']:>4} "
              f"{s['cost_usd']:>8.4f} {s['avg_latency_s']:>6.2f} {s['avg_calls']:>5.1f}")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
