from __future__ import annotations

from flask import Flask, current_app, jsonify, request

from .config import BASE_INSTRUCTIONS, GPT5_CODEX_INSTRUCTIONS
from .http import build_cors_headers
from .routes_openai import openai_bp
from .routes_ollama import ollama_bp
from .runtime import IpRemarkRegistry, is_within_bad_gateway_window, parse_bad_gateway_window


def create_app(
    verbose: bool = False,
    verbose_obfuscation: bool = False,
    reasoning_effort: str = "medium",
    reasoning_summary: str = "auto",
    reasoning_compat: str = "think-tags",
    debug_model: str | None = None,
    expose_reasoning_models: bool = False,
    default_web_search: bool = False,
    ip_remarks_file: str | None = None,
    bad_gateway_window_start: str | None = None,
    bad_gateway_window_end: str | None = None,
) -> Flask:
    app = Flask(__name__)
    outage_start, outage_end = parse_bad_gateway_window(
        bad_gateway_window_start,
        bad_gateway_window_end,
    )

    app.config.update(
        VERBOSE=bool(verbose),
        VERBOSE_OBFUSCATION=bool(verbose_obfuscation),
        REASONING_EFFORT=reasoning_effort,
        REASONING_SUMMARY=reasoning_summary,
        REASONING_COMPAT=reasoning_compat,
        DEBUG_MODEL=debug_model,
        BASE_INSTRUCTIONS=BASE_INSTRUCTIONS,
        GPT5_CODEX_INSTRUCTIONS=GPT5_CODEX_INSTRUCTIONS,
        EXPOSE_REASONING_MODELS=bool(expose_reasoning_models),
        DEFAULT_WEB_SEARCH=bool(default_web_search),
        IP_REMARKS_REGISTRY=IpRemarkRegistry(ip_remarks_file),
        DAILY_BAD_GATEWAY_START=outage_start,
        DAILY_BAD_GATEWAY_END=outage_end,
        DAILY_BAD_GATEWAY_MESSAGE=(
            "Scheduled network outage: service is unavailable between "
            f"{outage_start.strftime('%H:%M')} and {outage_end.strftime('%H:%M')} local time."
        ),
    )

    @app.get("/")
    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.before_request
    def _scheduled_bad_gateway():
        if request.method == "OPTIONS":
            return None
        if not is_within_bad_gateway_window(
            current_app.config["DAILY_BAD_GATEWAY_START"],
            current_app.config["DAILY_BAD_GATEWAY_END"],
        ):
            return None
        return (
            jsonify({"error": {"message": current_app.config["DAILY_BAD_GATEWAY_MESSAGE"]}}),
            502,
        )

    @app.after_request
    def _cors(resp):
        for k, v in build_cors_headers().items():
            resp.headers.setdefault(k, v)
        return resp

    app.register_blueprint(openai_bp)
    app.register_blueprint(ollama_bp)

    return app
