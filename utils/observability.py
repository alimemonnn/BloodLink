"""Structured logs, request ids and optional Sentry error tracking.

* LOG_FORMAT=json prints one JSON object per line (easy to search on Render, Datadog, Loki ...).
* Every request gets an id (also returned in the X-Request-ID header) that appears on its log lines,
  so one user report can be traced through the logs.
* Logs never contain query strings, form bodies, messages, locations or contact details.
* SENTRY_DSN switches on error reporting with personal data switched off.
"""
import json
import logging
import time
import uuid

from flask import g, has_request_context, request


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                "logger": record.name, "message": record.getMessage(), "request_id": getattr(record, "request_id", "-")}
        for extra in ("method", "path", "status", "ms"):
            if hasattr(record, extra):
                data[extra] = getattr(record, extra)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def init_logging(app, production):
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if app.config["LOG_FORMAT"] == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s]: %(message)s"))
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO if production else logging.DEBUG)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)       # we log requests ourselves, without query strings
    access = logging.getLogger("bloodlink.access")

    @app.before_request
    def _start():
        g.request_id = (request.headers.get("X-Request-ID", "")[:40] or uuid.uuid4().hex[:12])
        g._started = time.perf_counter()

    @app.after_request
    def _finish(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        if not request.path.startswith("/static") and request.path != "/healthz":
            ms = round((time.perf_counter() - getattr(g, "_started", time.perf_counter())) * 1000)
            access.info("%s %s %s %sms", request.method, request.path, response.status_code, ms,
                        extra={"method": request.method, "path": request.path, "status": response.status_code, "ms": ms})
        return response


def init_sentry(app):
    dsn = app.config.get("SENTRY_DSN")
    if not dsn:
        return False
    import sentry_sdk

    def scrub(event, hint):
        req = event.get("request", {})
        for part in ("data", "cookies", "query_string", "headers"):
            req.pop(part, None)
        return event

    sentry_sdk.init(dsn=dsn, send_default_pii=False, traces_sample_rate=0.0, before_send=scrub,
                    environment="production" if app.config.get("IS_PRODUCTION") else "development")
    return True
