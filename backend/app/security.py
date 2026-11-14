"""Bounded public computation; deployments additionally require Cloud Run IAM."""
import os
import time
import threading
from collections import OrderedDict, deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class ResourceLimits(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.clients = OrderedDict()
        self.lock = threading.Lock()

    async def dispatch(self, request, call_next):
        if request.url.path.startswith('/api/') and request.method == 'POST':
            try:
                if int(request.headers.get('content-length', '0')) > 65536:
                    return JSONResponse({'detail': 'Request exceeds 64 KiB budget'}, status_code=413)
            except ValueError:
                return JSONResponse({'detail': 'Invalid request length'}, status_code=400)
            # Do not trust user-supplied forwarded identity. Cloud Run IAM is the
            # access boundary; this is only a local/per-instance resource budget.
            key = request.client.host if request.client else 'unknown'
            now = time.monotonic()
            with self.lock:
                queue = self.clients.setdefault(key, deque())
                self.clients.move_to_end(key)
                while queue and queue[0] < now-60:
                    queue.popleft()
                limit = 6 if request.url.path.endswith('/interpret') else 20
                if len(queue) >= limit:
                    return JSONResponse({'detail': 'Request budget reached; retry later'}, status_code=429, headers={'Retry-After':'60'})
                queue.append(now)
                while len(self.clients)>2048:
                    self.clients.popitem(last=False)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if request.url.path.startswith('/assets/'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        elif request.url.path == '/':
            response.headers['Cache-Control'] = 'no-cache'
        return response
