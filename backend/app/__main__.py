"""Cloud Run entry point: python -m app."""
import os

import uvicorn


def main():
    raw_port = os.environ.get("PORT") or "8080"
    try:
        port = int(raw_port)
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise SystemExit("PORT must be an integer between 1 and 65535")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        limit_concurrency=12,
        timeout_keep_alive=5,
        access_log=True,
    )


if __name__ == "__main__":
    main()
