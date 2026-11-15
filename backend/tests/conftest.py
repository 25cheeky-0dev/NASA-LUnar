"""Isolate per-process HTTP rate counters between independent test cases.

The production limiter remains enabled, including within each test.
"""
import pytest
from app.main import app
from app.security import ResourceLimits

@pytest.fixture(autouse=True)
def isolated_http_rate_budget():
    layer = app.middleware_stack
    while layer is not None:
        if isinstance(layer, ResourceLimits):
            with layer.lock:
                layer.clients.clear()
        layer = getattr(layer, 'app', None)
