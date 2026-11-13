"""Production entry. Render sets PORT."""

import os

from waitress import serve

from app import app

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    print(f"Serving on http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=4)
