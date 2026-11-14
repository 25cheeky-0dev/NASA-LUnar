"""Fail the image build if its actual server cannot serve health and the UI."""
import json
import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def main():
    # A nondefault port verifies that the entry point honors Cloud Run's PORT.
    port = "18080"
    env = dict(os.environ, PORT=port)
    opener = build_opener(ProxyHandler({}))
    process = subprocess.Popen([sys.executable, "-m", "app"], env=env)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Server exited during startup: {process.returncode}")
            try:
                with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    body = json.load(response)
                    if response.status != 200 or body.get("status") not in ("OK", "DEGRADED"):
                        raise RuntimeError(f"Unexpected health response: {body}")
                break
            except (URLError, TimeoutError):
                time.sleep(0.25)
        else:
            raise RuntimeError("Server did not become healthy within 60 seconds")
        if env.get("WISPR_STATIC_DIR"):
            with opener.open(f"http://127.0.0.1:{port}/", timeout=5) as response:
                if response.status != 200 or "text/html" not in response.headers.get("Content-Type", ""):
                    raise RuntimeError("Bundled frontend did not serve HTML")
        print("Container startup check passed", flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
