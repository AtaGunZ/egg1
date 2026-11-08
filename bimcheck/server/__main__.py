"""``python -m bimcheck.server [--host 127.0.0.1] [--port 8765] [--data DIR]``"""
import argparse
import os


def main() -> None:
    ap = argparse.ArgumentParser(prog="bimcheck.server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", help="data directory (default ./data)")
    a = ap.parse_args()
    if a.data:
        os.environ["BIMCHECK_DATA"] = a.data
    import uvicorn
    uvicorn.run("bimcheck.server.app:app", host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
