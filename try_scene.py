"""学習シーンを API で通す。 python try_scene.py en on"""
import json, sys, urllib.request
lang, on = sys.argv[1], sys.argv[2] == "on"
B = "http://127.0.0.1:8765"
post = lambda p: json.load(urllib.request.urlopen(urllib.request.Request(B + p, method="POST")))
post(f"/api/memory-reset?lang={lang}")

def day(d, evs, approve=False):
    sid = post(f"/api/session?harness={int(on)}&lang={lang}&scene={d}")["session"]
    r = urllib.request.urlopen(f"{B}/api/stream?session={sid}")
    for e in evs: post(f"/api/event?session={sid}&e={e}")
    idle, pend = 0, []
    print(f"===== {d}")
    for line in r:
        if not line.startswith(b"data: "): continue
        e = json.loads(line[6:]); t = e["type"]
        if t == "arrive": print(f"📩 {e['from']}: {e['items'][0]['text'][:50]}")
        elif t == "call" and e["tool"] in ("send_line", "escalate"):
            print(f"  [{e['decision']:6}] {e['label']} :: {str(e['detail'])[:60]!r}\n           why: {e['reason']}")
        elif t == "guard": print(f"  GUARD risk={e['risk']} ({e['reason']})")
        elif t == "classify": print(f"  TYPE {e['category']}")
        elif t == "learned": print(f"  LEARNED {e['text']}")
        elif t == "incident": print(f"  !!! INCIDENT {e['name']}")
        elif t == "bucket" and e["bucket"] == "pending": pend.append(e["item"]["id"])
        elif t == "error": print("  ERROR", e["text"])
        elif t == "idle":
            idle += 1
            if idle == len(evs): break
    if approve:
        for p in pend: post(f"/api/approve?session={sid}&p={p}")
        # learned イベントを読む
        for line in r:
            if line.startswith(b"data: "):
                e = json.loads(line[6:])
                if e["type"] == "learned": print(f"  LEARNED {e['text']}")
                if e["type"] == "approved" and e["id"] == pend[-1]: break

day("d1", ["a1", "a2", "a3", "a4"], approve=on)
day("d7", ["b1", "b2", "b3"])
