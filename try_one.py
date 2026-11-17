"""1件だけ流す。 python try_one.py en off d1 a4  /  python try_one.py en on d7 b3 (先にルールを入れる場合は learn 引数)"""
import json, sys, urllib.request
lang, on, d, ev = sys.argv[1], sys.argv[2] == "on", sys.argv[3], sys.argv[4]
B = "http://127.0.0.1:8765"
post = lambda p: json.load(urllib.request.urlopen(urllib.request.Request(B + p, method="POST")))
sid = post(f"/api/session?harness={int(on)}&lang={lang}&scene={d}")["session"]
r = urllib.request.urlopen(f"{B}/api/stream?session={sid}")
post(f"/api/event?session={sid}&e={ev}")
for line in r:
    if not line.startswith(b"data: "): continue
    e = json.loads(line[6:]); t = e["type"]
    if t == "call" and e["tool"] in ("send_line", "escalate"): print(f"  [{e['decision']:6}] {e['label']} :: {str(e['detail'])[:50]!r} | {e['reason']}")
    elif t == "guard": print(f"  GUARD risk={e['risk']} ({e['reason']})")
    elif t == "classify": print(f"  TYPE {e['category']}")
    elif t == "incident": print(f"  !!! INCIDENT {e['name']}")
    elif t == "idle": break
