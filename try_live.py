"""ボタンを押す代わりに API でイベントを送り、結果を要約表示する。 python try_live.py on en e1 e2 e3"""
import json, sys, time, urllib.request
on, lang, evs = sys.argv[1] == "on", sys.argv[2], sys.argv[3:]
B = "http://127.0.0.1:8765"
post = lambda p: json.load(urllib.request.urlopen(urllib.request.Request(B + p, method="POST")))
sid = post(f"/api/session?harness={int(on)}&lang={lang}")["session"]
r = urllib.request.urlopen(f"{B}/api/stream?session={sid}")
for e in evs: post(f"/api/event?session={sid}&e={e}")
idle = 0
for line in r:
    if not line.startswith(b"data: "): continue
    e = json.loads(line[6:]); t = e["type"]
    if t == "arrive": print(f"\n📩 {e['from']}")
    elif t == "call" and e["tool"] not in ("list_inbox", "get_tomorrow_schedule", "get_candidate", "finish"):
        print(f"  [{e['decision']:6}] {e['label']} {e['candidate']} :: {str(e['detail'])[:70]!r}")
    elif t == "guard": print(f"  GUARD {e['candidate']} risk={e['risk']} ({e['reason']})")
    elif t == "verify": print(f"  VERIFY {e['ok']} {e['text']}")
    elif t == "incident": print(f"  !!! INCIDENT {e['name']} {e['why']}")
    elif t == "error": print("  ERROR", e["text"])
    elif t == "idle":
        idle += 1
        if idle == len(evs): break
