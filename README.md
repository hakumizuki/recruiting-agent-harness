# Recruiting Agent Harness

An agent harness for a new-graduate recruiter's assistant, built at an "Agent Harness Build Night" hackathon.

**The model stays the same cheap open model the whole time. Only the harness changes.**

- Harness OFF: the agent replies to a hesitating student with a cheerful template → incident
- Harness ON: every tool call goes through a permission layer, a guard, and verification
- Learning: when the recruiter approves a reply, the harness learns a rule for that kind of message, so one week later the same kind of question is handled automatically — while risky messages are still stopped

All data is synthetic. No real people or companies.

## What the harness does

| Part | What it does | Where |
|---|---|---|
| Agent loop | Tool-use loop over the Anthropic Messages API format | `harness.py: Session.process` |
| Permission layer | Every tool call is `allow` / `auto` / `queue` (human review) / `block` / `reject` | `harness.py: Session.policy` |
| Guard | Before sending a LINE message, a second model checks the student's last message for signs of withdrawal | `harness.py: guard_check` |
| Verification | Handover notes to executives must mention the key concern; on `finish`, every final interview must have a handover | `harness.py: Session.policy`, `Session.process` |
| Learning | An approved reply becomes a rule for its message type; the guard always wins over learned rules | `harness.py: LearnSession` |
| Visualization | Every step is emitted as an event and streamed to the UI (SSE); step-by-step mode pauses before each model call and each tool execution | `server.py`, `ui.html`, `scene.html` |

See `harness-overview.html` for diagrams.

## Learning at scale (1M+ messages)

The demo learns a rule from a single approval. At scale that breaks: one mis-click or one outdated fact spreads to thousands of messages. `learning.py` keeps learning correct with:

1. **Promote by statistics** — a rule turns automatic only when the Wilson lower bound of its recent approval rate is ≥ 0.95 (n ≥ 30)
2. **Demote by statistics** — automatic replies are spot-checked (2%); if the Wilson upper bound drops below 0.90, the rule is suspended
3. **Sliding window** — only the last 400 decisions count, so rules follow changes
4. **Knowledge versions** — a rule depends on the version of the info it uses (e.g. event venue); a new version sends it back to learning

The guard (withdrawal signs) always runs before any learned rule.

```bash
.venv/bin/python scale_sim.py   # 1,000,000 synthetic messages, no LLM calls, a few seconds
```

Synthetic world: different approval rates per message type, 1% mis-clicks, and the event venue changes at message 600k (the agent keeps answering with the old info).

### Semantic search on Neo4j without embeddings

ai& has no embeddings endpoint, so `graph_search.py` measures meaning with a **concept graph** instead of vectors:

1. A cheap LLM extracts 3–6 canonical English concepts from each message (`"dress code"`, `"meeting place"`, …), whatever language it is in
2. Messages and concepts go into Neo4j as `(:Message)-[:ABOUT]->(:Concept)`
3. A query's concepts are matched by graph traversal, weighted by IDF (common concepts count less)

Japanese messages indexed, English questions one week later: *"Should I wear a suit to the social?"* → top hit *「懇親会って私服で大丈夫ですか？」* (score 1.00); *"what time and where…?"* → *「何時にどこに集合…？」* (1.00). This lets a learned rule attach to "similar approved messages" instead of a fixed list of categories.

```bash
docker run -d --name harness-neo4j -p 127.0.0.1:7687:7687 -e NEO4J_AUTH=neo4j/<password> neo4j:5
# put NEO4J_PASSWORD=<password> in .env
.venv/bin/python graph_search.py
```

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # put your ai& API key in AIAND_API_KEY
.venv/bin/python server.py
```

- http://localhost:8765/demo#en — guided demo (press Space to advance)
- http://localhost:8765/scene#en — learning scene (Day 1 → one week later)
- http://localhost:8765/#en — day simulator (LINE / email / Teams messages arrive on button press)

Models are served by [ai&](https://aiand.com) through its Anthropic-compatible API (`zai-org/glm-5.3-flash` by default). Japanese UI: drop `#en`.

## Files

| File | Role |
|---|---|
| `harness.py` | Agent loop, permission layer, guard, verification, learning |
| `world.py` | Synthetic world: candidates, incoming messages, tool side effects |
| `server.py` | HTTP + SSE server, sessions, step-by-step gate |
| `ui.html` / `scene.html` / `demo.html` | Day simulator / learning scene / guided demo |
| `learning.py` / `scale_sim.py` | Rule book for learning at scale / 1M-message simulation |
| `graph_search.py` | Semantic search on Neo4j with an LLM-extracted concept graph (no embeddings) |
| `try_*.py` | Run scenarios from the command line |
| `eval.py`, `agents.py`, `gen_dataset.py`, `llm.py` | Early classification eval (reply needed / not needed) |
