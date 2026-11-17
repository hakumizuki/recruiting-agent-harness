"""デモ用サーバー。 python server.py → http://localhost:8765

画面のボタンを押すと連絡（LINE・メール・Teams）が1件届き、エージェントがその場で対応する。
GET  /                              画面
GET  /api/events-catalog?lang=ja    ボタンの一覧
POST /api/session?harness=1&lang=ja&step=0&skip_reads=1   新しい1日を始める → {"session": id}
GET  /api/stream?session=id         イベントを SSE で流す
POST /api/event?session=id&e=e1     連絡を1件届ける（処理は順番に）
POST /api/step?session=id[&all=1]   ステップ実行で次の一歩へ（all=1 で自動に戻す）
POST /api/mode?session=id&step=1    ステップ実行の切り替え
POST /api/approve?session=id&p=p1   確認待ちを承認して実行
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import harness
from world import EVENTS, SCENE_DATE, SCENE_EVENTS, TODAY

ROOT = Path(__file__).parent
SESSIONS: dict[str, dict] = {}
MEMORY: dict[str, dict] = {}  # 学習シーンの「覚えたルール」。言語ごとに1つ、日をまたいで残る


def new_session(harness_on: bool, lang: str, step_mode: bool, skip_reads: bool, scene_day: str = "") -> str:
    sid = uuid.uuid4().hex[:8]
    st = {"events": [], "step": step_mode, "skip_reads": skip_reads, "go": threading.Event(), "n": 0,
          "q": queue.Queue(), "busy": False}

    def emit(ev: dict) -> None:
        ev["t"] = time.time()
        st["events"].append(ev)

    def gate(label: str, info: dict) -> None:
        if not st["step"] or (st["skip_reads"] and info.get("read")):
            return
        st["n"] += 1
        emit({"type": "pause", "n": st["n"], "next": label})
        st["go"].wait()
        st["go"].clear()
        emit({"type": "resume"})

    if scene_day:
        mem = MEMORY.setdefault(lang, {"rules": {}})
        st["session"] = harness.LearnSession(harness_on, emit, harness.DEFAULT_MODEL, gate, lang, memory=mem, day=scene_day)
        st["events_src"] = SCENE_EVENTS[lang][scene_day]
    else:
        st["session"] = harness.Session(harness_on, emit, harness.DEFAULT_MODEL, gate, lang, preload=False)
        st["events_src"] = EVENTS[lang]

    def worker() -> None:  # 届いた連絡を1件ずつ順番に処理
        while True:
            ev = st["q"].get()
            st["busy"] = True
            try:
                st["session"].handle_event(ev)
            except Exception as e:
                emit({"type": "error", "text": repr(e)[:300]})
            st["busy"] = False

    threading.Thread(target=worker, daemon=True).start()
    emit({"type": "start", "harness": harness_on, "lang": lang, "model": harness.DEFAULT_MODEL})
    SESSIONS[sid] = st
    return sid


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        lang = "en" if q.get("lang", ["ja"])[0] == "en" else "ja"
        if u.path in ("/", "/scene", "/demo"):
            body = (ROOT / {"/": "ui.html", "/scene": "scene.html", "/demo": "demo.html"}[u.path]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/events-catalog":
            self._json({"today": TODAY[lang], "model": harness.DEFAULT_MODEL,
                        "events": [{k: e[k] for k in ("id", "channel", "btn", "from") if k in e} | {"bonus": e.get("bonus", False)}
                                   for e in EVENTS[lang]]})
        elif u.path == "/api/scene-catalog":
            day = "d7" if q.get("day", ["d1"])[0] == "d7" else "d1"
            self._json({"today": SCENE_DATE[lang][day], "model": harness.DEFAULT_MODEL,
                        "events": [{k: e[k] for k in ("id", "channel", "btn", "from")} for e in SCENE_EVENTS[lang][day]],
                        "rules": [{**r, "label": harness.CATEGORIES[r["category"]][lang]}
                                  for r in MEMORY.get(lang, {"rules": {}})["rules"].values()]})
        elif u.path == "/api/stream":
            st = SESSIONS.get(q.get("session", [""])[0])
            if not st:
                return self._json({"error": "no session"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            i = 0
            try:
                while True:
                    evs = st["events"]
                    while i < len(evs):
                        self.wfile.write(f"data: {json.dumps(evs[i], ensure_ascii=False)}\n\n".encode())
                        i += 1
                    self.wfile.flush()
                    time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        g = lambda k, d="": q.get(k, [d])[0]
        if u.path == "/api/session":
            day = g("scene")
            sid = new_session(g("harness", "1") == "1", "en" if g("lang") == "en" else "ja",
                              g("step", "0") == "1", g("skip_reads", "1") == "1", day if day in ("d1", "d7") else "")
            return self._json({"session": sid})
        if u.path == "/api/memory-reset":
            MEMORY.pop("en" if g("lang") == "en" else "ja", None)
            return self._json({"ok": True})
        st = SESSIONS.get(g("session"))
        if not st:
            return self._json({"error": "no session"}, 404)
        if u.path == "/api/event":
            ev = next((e for e in st["events_src"] if e["id"] == g("e")), None)
            if not ev:
                return self._json({"error": "unknown event"}, 400)
            st["q"].put(ev)
            self._json({"ok": True})
        elif u.path == "/api/step":
            if g("all") == "1":
                st["step"] = False
            st["go"].set()
            self._json({"ok": True})
        elif u.path == "/api/mode":
            st["step"] = g("step") == "1"
            if not st["step"]:
                st["go"].set()
            self._json({"ok": True})
        elif u.path == "/api/approve":
            st["session"].approve(g("p"))
            self._json({"ok": True})
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    print("http://localhost:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
