"""大量のメッセージでも「正しく」学習するためのルール帳。

デモ（scene.html）は承認1回でルールを覚えるが、100万件規模ではそれだと
押し間違い1回や、前提の変化（懇親会の情報が変わった等）で間違ったルールが広がる。
ここでは次の4つでそれを防ぐ。

1. 昇格は統計で決める      : 直近の判断で、承認率の Wilson 下限が PROMOTE 以上になったら自動化
2. 降格も統計で決める      : 自動化後も、抜き取り検査の結果で Wilson 上限が DEMOTE を下回ったら停止
3. 直近の判断だけを見る    : 古い判断は窓（WINDOW 件）から押し出されるので、状況の変化に追従する
4. 前提が変わったら学び直し : ルールは依存する情報の版を持ち、版が変わったら学習中に戻す

自動化したルールは人の目を通らなくなるので、AUDIT_RATE の割合で抜き取り検査し、その結果だけを学習に使う。
ガード（辞退の兆候）は常にこのルール帳より優先する（harness.py 側で先に判定する）。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

PROMOTE = 0.95     # 自動化に必要な承認率の下限（Wilson 下限）
DEMOTE = 0.90      # これを下回る疑いがあれば停止（Wilson 上限）
MIN_N = 30         # 昇格に必要な最低件数
WINDOW = 400       # 直近何件の判断を見るか
AUDIT_RATE = 0.02  # 自動送信のうち人が事後に確認する割合


def wilson(ok: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """承認率の 95% 信頼区間 (下限, 上限)"""
    if n == 0:
        return 0.0, 1.0
    p = ok / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d, (c + r) / d


@dataclass
class Rule:
    category: str
    knowledge_version: str = ""
    state: str = "learning"  # learning（人が確認）→ auto（自動）→ suspended（停止して学び直し）
    recent: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    history: list = field(default_factory=list)  # (何件目, 新しい状態, 理由)

    def bounds(self) -> tuple[float, float]:
        return wilson(sum(self.recent), len(self.recent))


class RuleBook:
    def __init__(self) -> None:
        self.rules: dict[str, Rule] = {}

    def rule(self, category: str) -> Rule:
        return self.rules.setdefault(category, Rule(category))

    def is_auto(self, category: str, knowledge_version: str = "", t: int | None = None) -> bool:
        if category == "other":
            return False
        r = self.rule(category)
        if r.state == "auto" and knowledge_version and r.knowledge_version != knowledge_version:
            self._move(r, "learning", "依存する情報の版が変わった", t)
            r.recent.clear()
        return r.state == "auto"

    def record(self, category: str, approved: bool, knowledge_version: str = "", t: int | None = None) -> None:
        """人の判断（確認待ちの承認/却下、または自動送信の抜き取り検査の結果）を1件記録する"""
        if category == "other":
            return
        r = self.rule(category)
        if knowledge_version and r.knowledge_version != knowledge_version:
            r.knowledge_version = knowledge_version
            if r.state != "learning":
                self._move(r, "learning", "依存する情報の版が変わった", t)
            r.recent.clear()
        r.recent.append(1 if approved else 0)
        lo, hi = r.bounds()
        if r.state in ("learning", "suspended") and len(r.recent) >= MIN_N and lo >= PROMOTE:
            self._move(r, "auto", f"承認率の下限 {lo:.3f} ≥ {PROMOTE}（n={len(r.recent)}）", t)
        elif r.state == "auto" and hi < DEMOTE:
            self._move(r, "suspended", f"承認率の上限 {hi:.3f} < {DEMOTE}（n={len(r.recent)}）", t)
            r.recent.clear()

    @staticmethod
    def _move(r: Rule, state: str, why: str, t: int | None) -> None:
        r.state = state
        r.history.append((t, state, why))
