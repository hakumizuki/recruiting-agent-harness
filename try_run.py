import sys, json, harness
on = sys.argv[1] == "on"; lang = sys.argv[2] if len(sys.argv) > 2 else "ja"
def emit(e):
    t = e["type"]
    if t == "call": print(f"  [{e['decision']:5}] {e['label']} {e['candidate']} :: {str(e['detail'])[:60]} ({e['reason']})")
    elif t == "guard": print(f"  GUARD {e['candidate']} risk={e['risk']} {e['reason']}")
    elif t == "verify": print("  VERIFY", e["ok"], e.get("uc"), e["text"])
    elif t in ("end","error"): print(t, json.dumps({k:v for k,v in e.items() if k!='type'}, ensure_ascii=False)[:500])
harness.run(on, emit, lang=lang)
