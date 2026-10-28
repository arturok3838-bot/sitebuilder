"""Защита сайта от спама и перегрузки (DoS/DDoS) без внешних сервисов.

- RateLimiter — скользящее окно на один IP: слишком частые запросы получают 429.
- заголовки безопасности (CSP, запрет вставки в чужой фрейм и т. п.).
- ограничение размера запроса, чтобы огромным телом не забивали память.

Это первый рубеж. Реальную защиту от крупных DDoS даёт слой перед сайтом
(Cloudflare, обратный прокси) — см. README.
"""
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse, Response

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",                      # нельзя встроить сайт в чужой iframe
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    # Разрешаем только свои ресурсы; микрофон — для голосового ввода.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "Permissions-Policy": "microphone=(self), camera=(), geolocation=()",
}


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.enabled = True
        self.hits: dict[str, list[float]] = {}
        self.lock = threading.Lock()
        self._last_sweep = 0.0

    def allow(self, key: str) -> bool:
        if not self.enabled:
            return True
        now = time.time()
        with self.lock:
            window = [t for t in self.hits.get(key, []) if now - t < 60]
            if len(window) >= self.per_minute:
                self.hits[key] = window
                return False
            window.append(now)
            self.hits[key] = window
            if now - self._last_sweep > 300:  # изредка чистим память от старых IP
                self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < 120}
                self._last_sweep = now
            return True


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def install(app, cfg: dict):
    sec = cfg["security"]
    limiter = RateLimiter(int(sec["requests_per_minute"]))
    max_body = int(sec["max_body_mb"]) * 1024 * 1024
    trust = bool(sec.get("trust_proxy_header"))
    app.state.rate_limiter = limiter

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > max_body:
            return JSONResponse({"detail": "Запрос слишком большой"}, status_code=413)
        if not limiter.allow(client_ip(request, trust)):
            return JSONResponse({"detail": "Слишком много запросов. Подождите немного."},
                                status_code=429, headers={"Retry-After": "30"})
        response: Response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    return limiter
