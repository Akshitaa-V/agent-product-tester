"""Run the app locally: python -m app [--bug NAME ...] then open http://127.0.0.1:8000"""
import argparse

import uvicorn

from .main import KNOWN_BUGS, create_app

p = argparse.ArgumentParser(prog="app")
p.add_argument("--db", default="app.db")
p.add_argument("--port", type=int, default=8000)
p.add_argument("--bug", action="append", default=[], choices=sorted(KNOWN_BUGS))
a = p.parse_args()
uvicorn.run(create_app(a.db, set(a.bug)), host="127.0.0.1", port=a.port)
