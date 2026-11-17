"""Neo4j で「埋め込みなしの意味検索」。

ai& には埋め込みAPIがないので、ベクトルの代わりに「概念のグラフ」で意味の近さを測る。
  1. 各メッセージから、LLM（ai&）で概念を 3〜6 個取り出す。英語・小文字・基本形に正規化するので、
     日本語「私服でOK？」と英語「Should I wear a suit?」がどちらも "dress code" に当たる
  2. Neo4j に (:Message)-[:ABOUT]->(:Concept) として入れる
  3. 検索: 問い合わせの概念を同じく取り出し、共有する概念を辿る。概念の重みは IDF（多くのメッセージに
     出てくるありふれた概念ほど軽い）。スコア = 共有概念の IDF の合計 / 問い合わせ側の IDF の合計
学習ルールを「決め打ちの4種類」ではなく「過去に承認された似たメッセージ」に結び付けるための土台。

  docker run -d --name harness-neo4j -p 127.0.0.1:7687:7687 -e NEO4J_AUTH=neo4j/<your-password> neo4j:5
  （.env に NEO4J_PASSWORD=<your-password> を書く）
  python graph_search.py
"""

from __future__ import annotations

import json
import os
import re

from neo4j import GraphDatabase

from harness import GUARD_MODEL, client

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_AUTH = (os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", ""))  # .env に書く

CONCEPT_SYSTEM = """Extract 3 to 6 key concepts from a message a student sent to a recruiter.
Concepts must be short canonical English noun phrases, lowercase, singular, generic
(e.g. "dress code", "what to bring", "meeting time", "meeting place", "social event",
"acceptance deadline", "other company", "parents", "paperwork").
Use the same wording for the same idea, whatever language the message is in.
Output JSON only: {"concepts": ["...", "..."]}"""


def concepts(text: str) -> list[str]:
    r = client.messages.create(model=GUARD_MODEL, max_tokens=1024, system=CONCEPT_SYSTEM,
                               messages=[{"role": "user", "content": text}])
    out = "".join(b.text for b in r.content if b.type == "text")
    m = re.search(r"\{.*\}", out, re.S)
    try:
        cs = json.loads(m.group(0)).get("concepts", []) if m else []
    except json.JSONDecodeError:
        cs = []
    return sorted({c.strip().lower() for c in cs if isinstance(c, str) and c.strip()})


class GraphSearch:
    def __init__(self) -> None:
        self.db = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        with self.db.session() as s:
            s.run("CREATE CONSTRAINT msg_id IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE")
            s.run("CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE")

    def reset(self) -> None:
        with self.db.session() as s:
            s.run("MATCH (n) DETACH DELETE n")

    def add(self, mid: str, text: str, label: str = "", cs: list[str] | None = None) -> list[str]:
        cs = cs if cs is not None else concepts(text)
        with self.db.session() as s:
            s.run("""MERGE (m:Message {id: $id}) SET m.text = $text, m.label = $label
                     WITH m UNWIND $cs AS name
                     MERGE (c:Concept {name: name}) MERGE (m)-[:ABOUT]->(c)""", id=mid, text=text, label=label, cs=cs)
        return cs

    def search(self, text: str, k: int = 3) -> tuple[list[str], list[dict]]:
        qc = concepts(text)
        with self.db.session() as s:
            rows = s.run("""
                MATCH (mm:Message) WITH count(mm) AS N
                UNWIND $qc AS name
                OPTIONAL MATCH (c:Concept {name: name})<-[:ABOUT]-(x:Message)
                WITH N, name, count(x) AS df
                WITH N, name, log(1.0 + toFloat(N) / (1 + df)) AS idf
                WITH N, collect({name: name, idf: idf}) AS q, sum(idf) AS qtotal
                UNWIND q AS qi
                MATCH (c:Concept {name: qi.name})<-[:ABOUT]-(m:Message)
                WITH m, qtotal, sum(qi.idf) AS hit, collect(qi.name) AS shared
                WITH m, shared, hit / qtotal AS score, COUNT { (m)-[:ABOUT]->() } AS dsize
                // 同点なら、余計な話題（問い合わせにない概念）が少ないメッセージを上にする
                RETURN m.id AS id, m.text AS text, m.label AS label, shared, score, dsize
                ORDER BY score DESC, dsize ASC LIMIT $k""", qc=qc, k=k).data()
        return qc, rows


def main() -> None:
    from world import SCENE_EVENTS
    g = GraphSearch()
    g.reset()
    # 「承認済みの返信」として初日のメッセージ（日本語）と、いくつかの別の話題を入れる
    seed = [(e["id"], e["items"][0][1], e["btn"]) for e in SCENE_EVENTS["ja"]["d1"]]
    seed += [("x-docs", "入社手続きの書類って、いつまでに何を出せばいいですか？", "書類の質問"),
             ("x-salary", "初任給の支給日はいつですか？", "給与の質問")]
    print("== index (Japanese, approved replies)")
    for mid, text, label in seed:
        print(f"  {mid:8} {g.add(mid, text, label)}  ← {text[:30]}")
    # 1週間後のメッセージ（英語）で検索。言語が違っても概念で当たるか
    print("\n== search (English, one week later)")
    for e in SCENE_EVENTS["en"]["d7"]:
        q = e["items"][0][1]
        qc, rows = g.search(q)
        print(f"\n  Q: {q[:70]}\n     concepts: {qc}")
        for r in rows:
            print(f"     {r['score']:.2f}  {r['id']:8} shared={r['shared']}  {r['text'][:28]}")


if __name__ == "__main__":
    main()
