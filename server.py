"""Universal AI Router: a remote MCP server for Claude custom connectors.

Provider credentials are read only from server environment variables. Never pass
API keys in tool arguments or commit them to source control.
"""
from __future__ import annotations

import asyncio
import os
import secrets
from typing import Any

import httpx
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from mcp.server.fastmcp import FastMCP

APP_NAME = "Universal AI Router"

# OpenAI-compatible APIs. Model IDs are provider-specific and can change;
# use ai_list_models to query the provider's current catalogue.
PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY"},
    "mistral": {"base_url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY"},
    "together": {"base_url": "https://api.together.xyz/v1", "key_env": "TOGETHER_API_KEY"},
    "xai": {"base_url": "https://api.x.ai/v1", "key_env": "XAI_API_KEY"},
    "cerebras": {"base_url": "https://api.cerebras.ai/v1", "key_env": "CEREBRAS_API_KEY"},
    "fireworks": {"base_url": "https://api.fireworks.ai/inference/v1", "key_env": "FIREWORKS_API_KEY"},
}

mcp = FastMCP(APP_NAME)


def _configured(provider: str) -> tuple[str, str]:
    name = provider.lower().strip()
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'. Available: {', '.join(PROVIDERS)}")
    cfg = PROVIDERS[name]
    key = os.getenv(cfg["key_env"], "").strip()
    if not key:
        raise ValueError(f"{name} is not configured. Set {cfg['key_env']} in your hosting environment.")
    return cfg["base_url"], key


def _default_provider() -> str:
    requested = os.getenv("DEFAULT_PROVIDER", "openrouter").lower().strip()
    if requested in PROVIDERS and os.getenv(PROVIDERS[requested]["key_env"]):
        return requested
    for name, cfg in PROVIDERS.items():
        if os.getenv(cfg["key_env"]):
            return name
    raise ValueError("No AI provider is configured yet. Add at least one provider API key to the server environment.")


async def _request(provider: str, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url, key = _configured(provider)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = os.getenv("APP_URL", "https://github.com/")
        headers["X-Title"] = APP_NAME
    timeout = httpx.Timeout(float(os.getenv("PROVIDER_TIMEOUT_SECONDS", "90")))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, f"{base_url}{path}", headers=headers, json=body)
    if response.is_error:
        # Avoid echoing credentials or full request headers in tool errors.
        detail = response.text[:1200]
        raise RuntimeError(f"{provider} API returned HTTP {response.status_code}: {detail}")
    return response.json()


@mcp.tool()
async def ai_list_providers() -> dict[str, Any]:
    """List supported providers and indicate which API keys are configured."""
    return {
        "providers": [
            {"name": name, "configured": bool(os.getenv(cfg["key_env"])), "key_environment_variable": cfg["key_env"]}
            for name, cfg in PROVIDERS.items()
        ],
        "default_provider": os.getenv("DEFAULT_PROVIDER", "openrouter"),
        "note": "Only providers with configured API keys can be used. API usage is billed by each provider, not by Claude.",
    }


@mcp.tool()
async def ai_list_models(provider: str) -> dict[str, Any]:
    """Fetch the current model catalogue from a configured provider. Supply e.g. openai, gemini, deepseek, openrouter, groq, mistral, together, xai, cerebras, or fireworks."""
    data = await _request(provider.lower().strip(), "/models")
    models = []
    for item in data.get("data", []):
        if isinstance(item, dict) and item.get("id"):
            models.append({"id": item["id"], "name": item.get("name", item["id"])})
    return {"provider": provider, "models": models, "count": len(models)}


@mcp.tool()
async def ai_chat(
    prompt: str,
    provider: str = "auto",
    model: str = "",
    system: str = "You are a helpful, accurate assistant.",
    max_tokens: int = 2048,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Ask an external AI model. Set provider to auto or a configured provider; provide a provider-specific model ID. Use ai_list_models to discover IDs."""
    if not prompt.strip():
        raise ValueError("prompt cannot be empty")
    if not 1 <= max_tokens <= 32000:
        raise ValueError("max_tokens must be between 1 and 32000")
    if not 0 <= temperature <= 2:
        raise ValueError("temperature must be between 0 and 2")
    selected = _default_provider() if provider.lower().strip() == "auto" else provider.lower().strip()
    if not model:
        model = os.getenv(f"{selected.upper()}_MODEL", "")
    if not model:
        raise ValueError(f"No model specified. Call ai_list_models('{selected}') and pass a model ID, or set {selected.upper()}_MODEL.")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    data = await _request(selected, "/chat/completions", method="POST", body=payload)
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"{selected} returned no choices: {str(data)[:1000]}")
    message = choices[0].get("message", {})
    return {
        "provider": selected,
        "model": data.get("model", model),
        "content": message.get("content", ""),
        "finish_reason": choices[0].get("finish_reason"),
        "usage": data.get("usage", {}),
    }


@mcp.tool()
async def ai_compare(
    prompt: str,
    targets: list[str],
    system: str = "You are a helpful, accurate assistant.",
    max_tokens: int = 1500,
) -> dict[str, Any]:
    """Send the same prompt to several providers in parallel. Each target must be 'provider:model-id'. Example: ['openai:gpt-model', 'deepseek:deepseek-chat']."""
    if not targets:
        raise ValueError("Provide at least one target in provider:model format")
    if len(targets) > 5:
        raise ValueError("Compare up to five targets at a time")

    async def one(target: str) -> dict[str, Any]:
        if ":" not in target:
            return {"target": target, "error": "Target must be provider:model-id"}
        provider, model = target.split(":", 1)
        try:
            result = await ai_chat(prompt, provider, model, system, max_tokens, 0.2)
            return {"target": target, **result}
        except Exception as exc:
            return {"target": target, "error": str(exc)}

    return {"results": await asyncio.gather(*(one(target) for target in targets))}


class SharedSecretMiddleware(BaseHTTPMiddleware):
    """Protect the public MCP endpoint with a bearer token."""
    async def dispatch(self, request, call_next):
        if request.url.path in ("/", "/health"):
            return await call_next(request)
        expected = os.getenv("MCP_AUTH_TOKEN", "").strip()
        if not expected:
            return JSONResponse({"error": "Server is not configured: MCP_AUTH_TOKEN is missing."}, status_code=503)
        supplied = request.headers.get("authorization", "")
        if not supplied.startswith("Bearer ") or not secrets.compare_digest(supplied[7:], expected):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


async def health(_request):
    return PlainTextResponse("Universal AI Router is running", status_code=200)


def main() -> None:
    app = mcp.streamable_http_app()
    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    app.routes.insert(0, Route("/", health, methods=["GET"]))
    app.add_middleware(SharedSecretMiddleware)
    port = int(os.getenv("PORT", os.getenv("MCP_PORT", "8000")))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
