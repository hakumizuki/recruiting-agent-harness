"""100万件のメッセージで、学習の仕組みを比べるシミュレーション（LLM は呼ばない。数秒で終わる）。

  python scale_sim.py            # 100万件
  python scale_sim.py 200000     # 件数を指定

比べるもの:
  naive   : デモと同じ「承認1回でルールを覚え、以後ずっと自動」
  rulebook: learning.py（統計で昇格・降格、直近の窓、抜き取り検査、前提の版）

世界の設定（合成）:
  - 種類ごとに「エージェントの返信を人が承認する確率」が違う
      dress 99% / logistics 98% / docs 75%（自動化してはいけない） / other は常に人
  - 人の押し間違い 1%
  - 60万件目で懇親会の会場が変わる。エージェントは古い情報で答え続けるので logistics の承認率は 20% に落ちる
    （情報の版を更新するのは運用側が気づいた 70万件目。それまでは統計の降格だけが頼り）
"""

from __future__ import annotations

import random
import sys
import time

from learning import AUDIT_RATE, RuleBook

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
MIX = [("dress", 0.30), ("logistics", 0.30), ("docs", 0.15), ("other", 0.25)]
QUALITY = {"dress": 0.99, "logistics": 0.98, "docs": 0.75}
MISCLICK = 0.01
CHANGE_AT, VERSION_BUMP_AT = int(N * 0.6), int(N * 0.7)


def quality(cat: str, t: int) -> float:
    if cat == "logistics" and t >= CHANGE_AT:
        return 0.20
    return QUALITY[cat]


def run(kind: str, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    cats, weights = zip(*MIX)
    book, naive_rules = RuleBook(), set()
    auto = review = wrong_auto = 0
    for t in range(N):
        cat = rnd.choices(cats, weights)[0]
        if cat == "other":
            review += 1
            continue
        good = rnd.random() < quality(cat, t)                          # この返信は本当に正しいか
        judged = good if rnd.random() > MISCLICK else not good          # 人の判断（押し間違いあり）
        version = "v2" if t >= VERSION_BUMP_AT else "v1"
        if kind == "naive":
            if cat in naive_rules:
                auto += 1
                wrong_auto += not good
            else:
                review += 1
                if judged:
                    naive_rules.add(cat)
        else:
            if book.is_auto(cat, version, t):
                auto += 1
                wrong_auto += not good
                if rnd.random() < AUDIT_RATE:                         # 抜き取り検査の結果だけ学習に使う
                    book.record(cat, judged, version, t)
            else:
                review += 1
                book.record(cat, judged, version, t)
    return {"auto": auto, "review": review, "wrong_auto": wrong_auto, "book": book}


def main() -> None:
    t0 = time.time()
    res = {k: run(k) for k in ("naive", "rulebook")}
    print(f"{N:,} messages simulated in {time.time() - t0:.1f}s\n")
    print(f"{'':10} {'auto-sent':>12} {'human review':>13} {'wrong auto-sends':>17} {'wrong rate':>11}")
    for k, r in res.items():
        rate = r["wrong_auto"] / r["auto"] if r["auto"] else 0
        print(f"{k:10} {r['auto']:>12,} {r['review']:>13,} {r['wrong_auto']:>17,} {rate:>10.2%}")
    print("\nrulebook state changes:")
    for cat, rule in res["rulebook"]["book"].rules.items():
        for t, state, why in rule.history:
            print(f"  {cat:10} #{(t or 0):>9,}  → {state:9}  {why}")


if __name__ == "__main__":
    main()
