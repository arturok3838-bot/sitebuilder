from fastapi.testclient import TestClient

from arturokai import server
from arturokai.security import RateLimiter


def test_rate_limiter_window():
    rl = RateLimiter(per_minute=3)
    assert [rl.allow("ip1") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("ip2") is True          # другой IP не задет
    rl.enabled = False
    assert rl.allow("ip1") is True          # выключенный лимитер пропускает всё


def test_security_headers_present():
    c = TestClient(server.app)
    h = c.get("/").headers
    assert h["x-frame-options"] == "DENY"
    assert "default-src 'self'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"


def test_rate_limit_returns_429():
    server.rate_limiter.enabled = True
    server.rate_limiter.per_minute = 5
    server.rate_limiter.hits.clear()
    c = TestClient(server.app)
    codes = [c.get("/api/plans").status_code for _ in range(7)]
    assert 429 in codes
    server.rate_limiter.enabled = False
    server.rate_limiter.per_minute = 240
