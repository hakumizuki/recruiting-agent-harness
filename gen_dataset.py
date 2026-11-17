"""合成データ生成。実データは使わない（デモで画面に映すため）。

  python gen_dataset.py --model aiand:moonshotai/kimi-k3.1-pro --n 40
  python gen_dataset.py --model anthropic:claude-opus-5-5 --n 40

生成後、data/dataset.jsonl を目で見て、ラベルがおかしいものは手で直すこと。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from llm import call

ROOT = Path(__file__).parent

PROMPT = """新卒採用で、内定者・選考中の学生が採用担当者にLINEで送るメッセージの評価用データを作ってください。

各データは「直前のやりとり(0〜3往復)」と「最新の学生メッセージ」と「正解ラベル」からなります。
- 要返信: 担当者のアクションが必要
- 返信不要: 会話が完結している

**判定が難しいケースを半分以上入れてください。** 例:
- お礼で締めているが、途中にさりげない質問が混じる
- 「大丈夫です！」の裏に不安がにじむ（例: 他社と迷っている匂い）
- 疑問符はないが実質的な依頼（「〜だと助かります」）
- 疑問符があるが独り言・相槌（「そうなんですね？笑」）
- 担当者の質問への回答だけで完結しているもの
- 日程の確定連絡（返信不要）と日程の相談（要返信）

ラベルは {n_reply} 件を要返信、{n_noreply} 件を返信不要にしてください。
学生の口調は実在の大学生らしく、絵文字・くだけた表現も混ぜてください。個人名・社名は架空のものに。

JSON Lines で {n} 行だけ出力してください。各行の形式:
{{"history": [{{"from": "担当者" | "学生", "text": "..."}}], "message": "...", "label": "要返信" | "返信不要", "difficulty": "easy" | "hard", "note": "<なぜそのラベルか1文>"}}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default=str(ROOT / "data" / "dataset.jsonl"))
    args = ap.parse_args()

    n_reply = args.n // 2
    prompt = PROMPT.format(n=args.n, n_reply=n_reply, n_noreply=args.n - n_reply)
    r = call(args.model, "You generate evaluation datasets. Output only JSON Lines.", prompt, max_tokens=16000)

    rows = []
    for line in r.text.splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("label") in ("要返信", "返信不要") and obj.get("message"):
            obj["id"] = f"m{len(rows) + 1:03d}"
            rows.append(obj)

    Path(args.out).write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in rows) + "\n")
    hard = sum(o.get("difficulty") == "hard" for o in rows)
    reply = sum(o["label"] == "要返信" for o in rows)
    print(f"wrote {len(rows)} rows (要返信 {reply}, hard {hard}) -> {args.out}  cost ${r.cost:.4f}")


if __name__ == "__main__":
    main()
