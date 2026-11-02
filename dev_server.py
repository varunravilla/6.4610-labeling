"""Local preview without Supabase: serves docs/ and answers /rest/v1/rpc/<fn> like PostgREST.

    python dev_server.py --db postgresql://postgres@127.0.0.1:5432/postgres --port 8000

The page's config.js is replaced so it talks to this server. Calls run as the anon role,
so the preview has exactly the public site's permissions.
"""
import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


class Handler(SimpleHTTPRequestHandler):
    db_url = ""

    def do_GET(self):
        if self.path.split("?")[0] == "/config.js":  # point the page at this server instead of Supabase
            data = b'window.LABELING_CONFIG = { supabaseUrl: location.origin, supabaseAnonKey: "local" };'
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/rest/v1/rpc/"):
            return self.send_error(404)
        fn = self.path.rsplit("/", 1)[1]
        args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            with psycopg.connect(self.db_url, autocommit=True) as conn:
                conn.execute("set role anon")
                names = ", ".join(f"{k} => %s" for k in args)
                values = [Jsonb(v) if isinstance(v, (dict, list)) else v for v in args.values()]
                result = conn.execute(f"select {psycopg.sql.Identifier(fn).as_string(conn)}({names})", values).fetchone()[0]
            self._json(200, result)
        except psycopg.Error as e:
            self._json(400, {"message": (e.diag.message_primary or str(e))})

    def _json(self, code, body):
        data = json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    Handler.db_url = args.db
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(Path(__file__).parent / "docs")))
    print(f"Preview at http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
