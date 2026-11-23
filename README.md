# Universal AI Router for Claude

A small **remote MCP server** that lets Claude Chat call AI models from providers that expose an OpenAI-compatible API. It is designed for Claude's **Custom Connector (remote MCP)** feature.

> Important: this does not replace Claude's built-in model or bypass Claude plan limits. It adds tools Claude can call to ask other providers. Each provider requires its own API account/key and bills usage separately.

## Supported providers

OpenAI, Google Gemini, DeepSeek, OpenRouter, Groq, Mistral, Together AI, xAI, Cerebras, and Fireworks. The provider catalogue is easy to extend in `server.py`.

The server exposes these MCP tools:

- `ai_list_providers` — show configured providers.
- `ai_list_models` — fetch the current model list from one provider.
- `ai_chat` — ask one selected provider/model, or `auto` to use the configured default.
- `ai_compare` — ask up to five provider/model combinations in parallel.

## Easiest deployment: GitHub + Render

1. Create a new **private** GitHub repository (recommended because the repository itself should not contain secrets).
2. Upload the contents of this folder to the repository root. Do not upload `.env` files or API keys.
3. In Render, choose **New → Blueprint**, connect your GitHub repository, and deploy. Render reads `render.yaml` and builds the Docker image.
4. In the Render service's **Environment** settings, add at least one provider API key, for example `OPENROUTER_API_KEY` or `OPENAI_API_KEY`. Add more keys to enable more providers.
5. Keep the generated `MCP_AUTH_TOKEN` secret. Copy its value from Render's Environment page. Do not paste it into GitHub or a public chat.
6. After deployment, copy the public service URL. Your MCP endpoint is that URL plus `/mcp`, for example `https://YOUR-SERVICE.onrender.com/mcp`.

Render may require a paid instance for a continuously available service. On a free or sleeping host, the first request can be delayed while it wakes.

## Connect it to Claude Chat

1. Open Claude → **Customize → Connectors**.
2. Choose **Add custom connector** (or **Add → Custom → Web**, depending on the interface).
3. Name it `Universal AI Router`.
4. Enter the public MCP endpoint ending in `/mcp`.
5. In authentication / request headers, configure:
   - Header name: `Authorization`
   - Header value: `Bearer YOUR_MCP_AUTH_TOKEN`
6. Save and connect the connector. Enable it for the conversation from the `+` menu → Connectors if needed.

Claude's UI changes over time. If the connector setup offers a different authentication flow, use a fixed request header for the bearer token; this server currently uses bearer-token authentication, not OAuth.

## First use in Claude

Ask Claude to call `ai_list_providers`. Then call `ai_list_models` with a configured provider, for example `openrouter` or `gemini`.

Then ask it to use `ai_chat` with:

- `provider`: `openai`, `gemini`, `deepseek`, `openrouter`, etc.
- `model`: exact ID returned by `ai_list_models`.
- `prompt`: your task.

For comparison, call `ai_compare` with targets like `provider:model-id` (up to five at once).

## Local run (optional)

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, fill in `MCP_AUTH_TOKEN` and provider keys, then set the variables in your terminal or use a dotenv runner. Start with:

```bash
python server.py
```

The local MCP endpoint is `http://127.0.0.1:8000/mcp`. Claude Chat's remote connector cannot reach localhost; use a public HTTPS deployment for Claude Chat.

## Security

- Never commit `.env`, provider API keys, or `MCP_AUTH_TOKEN`.
- Use a private repository if you prefer; the deployed server does not need a public source repository.
- Keep the MCP bearer token private and rotate it if exposed.
- Only enable providers you trust. Provider prompts and outputs are sent to the selected provider under its terms.
- This starter server does not store prompts or API keys in a database. Hosting providers may still retain operational logs.
- Restrict access to your Render account and use provider spending limits where available.

## Notes and limitations

- The providers listed here use OpenAI-compatible chat-completions endpoints. Availability and model IDs depend on your account, region, provider API and current catalogue.
- `ai_list_models` queries the provider's `/models` endpoint. Some providers may return incomplete lists or require a specific model ID from their dashboard.
- `auto` selects `DEFAULT_PROVIDER` if configured, otherwise the first provider with a key. It does not intelligently infer the best model and does not automatically retry across providers. Use `ai_compare` to compare; automatic failover can be added in a later version.
- This is a remote MCP connector project, not a Claude plugin ZIP containing a local MCP server. Claude's local plugin MCP servers run in Cowork and Claude Code; Claude Chat uses remote custom connectors.

## License

MIT. See `LICENSE`.
