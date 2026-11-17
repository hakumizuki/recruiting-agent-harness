"""判定エージェント。baseline (素の1回呼び) と harness (今夜つくる部分) を並べる。

タスク: 採用担当に届いた学生のLINEメッセージが「要返信」か「返信不要」かを判定する。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from llm import call

LABELS = ["要返信", "返信不要"]

SYSTEM = """あなたは新卒採用担当者のアシスタントです。
学生から届いたLINEメッセージを読み、担当者が返信すべきかを判定してください。

- 要返信: 質問・相談・日程調整・不安の表明・判断を求める内容など、担当者のアクションが必要
- 返信不要: お礼のみ、スタンプ的な相槌、了解の連絡など、会話が完結している

出力は次のJSONのみ:
{"label": "要返信" | "返信不要", "reason": "<1文>"}"""


@dataclass
class Prediction:
    label: str | None
    reason: str = ""
    cost: float = 0.0
    latency: float = 0.0
    calls: int = 0
    trace: list[str] = field(default_factory=list)


def parse(text: str) -> tuple[str | None, str]:
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            label = obj.get("label")
            if label in LABELS:
                return label, obj.get("reason", "")
        except json.JSONDecodeError:
            pass
    for lb in LABELS:  # JSONが壊れていてもラベル文字列があれば拾う
        if lb in text:
            return lb, ""
    return None, ""


def format_input(item: dict) -> str:
    history = "\n".join(f"{t['from']}: {t['text']}" for t in item.get("history", []))
    return f"## これまでのやりとり\n{history or '(なし)'}\n\n## 最新の学生メッセージ\n{item['message']}"


# ---------------------------------------------------------------- baseline
def baseline(model: str, item: dict) -> Prediction:
    r = call(model, SYSTEM, format_input(item))
    label, reason = parse(r.text)
    return Prediction(label, reason, r.cost, r.latency, 1, [r.text])


# ---------------------------------------------------------------- harness
# ここを今夜育てる。まずは「自己検証 → 不一致ならやり直し」の最小形。
CRITIC = """あなたは判定のレビュアーです。以下の判定が正しいか、チェックリストで確認してください。

チェックリスト:
1. 文中に疑問文・依頼・日程の話・不安の表明が1つでもあれば「要返信」
2. 「ありがとうございました」で終わっていても、前半に質問があれば「要返信」
3. 担当者が前の発言で質問していて、学生が答えただけなら、追加の確認が要るか考える

出力は次のJSONのみ:
{"ok": true | false, "label": "要返信" | "返信不要", "reason": "<1文>"}"""


def harness(model: str, item: dict, max_rounds: int = 2) -> Prediction:
    pred = baseline(model, item)
    for _ in range(max_rounds):
        review_input = f"{format_input(item)}\n\n## 判定\n{json.dumps({'label': pred.label, 'reason': pred.reason}, ensure_ascii=False)}"
        r = call(model, CRITIC, review_input)
        pred.cost += r.cost
        pred.latency += r.latency
        pred.calls += 1
        pred.trace.append(r.text)
        m = re.search(r"\{.*\}", r.text, re.S)
        try:
            obj = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            obj = {}
        if obj.get("ok", True):
            break
        if obj.get("label") in LABELS:
            pred.label, pred.reason = obj["label"], obj.get("reason", "")
    if pred.label is None:  # 出力形式が壊れたら1回だけ取り直す
        retry = baseline(model, item)
        retry.cost += pred.cost
        retry.latency += pred.latency
        retry.calls += pred.calls
        return retry
    return pred


AGENTS = {"baseline": baseline, "harness": harness}
