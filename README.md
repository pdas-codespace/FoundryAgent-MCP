# FoundryAgent-MCP

## Overview

FoundryAgent-MCP is a Python sample that demonstrates how to drive an Azure AI Foundry agent that can call:

1. Model Context Protocol (MCP) tools (e.g. a Weather MCP server exposing `get_alerts`, `get_forecast`).
2. The Foundry "Files" (Vector Store) search tool for retrieval-augmented responses, when you provide existing vector store IDs.

It also streams operational telemetry into Azure Monitor / Application Insights. The project provisions an AI Project client, creates an agent tied to your model deployment, binds both MCP and (optionally) File Search capabilities, and orchestrates a full run including tool call approvals and step-level tracing.

## Key features

- **Azure AI Foundry agent orchestration** powered by `azure-ai-projects` and `azure-ai-agents`.
- **MCP tool integration** for weather data lookups (`get_alerts`, `get_forecast`).
- **Foundry File Search (Vector Store) integration** by supplying existing vector store IDs via `FILES_VECTOR_STORE_IDS` (no recreation of stores required).
- **Connected agent orchestration**: The agent can select among MCP tools and File Search in a single run (with tool approval gating) enabling multi-tool reasoning.
- **Step-level tracing & reasoning capture** when `ENABLE_STEP_TRACE=true` (shows incremental run steps and proposed tool calls).
- **Application Insights monitoring** via the Azure Monitor OpenTelemetry exporter with structured logging and spans.
- **Environment-driven configuration** using a `.env` file and `python-dotenv`.

## Prerequisites

- Python 3.10 or newer (tested with 3.12).
- An Azure subscription with access to an Azure AI project and model deployment.
- An Application Insights (Azure Monitor) resource if you want telemetry.
- Access to an MCP-compatible weather service (the sample expects a server URL and label).

## Project structure

```text
WeatherAgent.py     # Main entry point that sets up and runs the agent
requirements.txt    # Python dependencies
.env                # Environment variable template (do not commit real secrets)
```text

## Configuration

1. Copy `.env` and fill in the required values:
   - `PROJECT_ENDPOINT`: Azure AI project endpoint URL.
   - `MODEL_DEPLOYMENT_NAME`: Name of your model deployment (e.g. `gpt-4o`).
   - `MCP_SERVER_URL`: Base URL of the Weather MCP server.
   - `MCP_SERVER_LABEL`: Friendly label for the MCP server (used in the tool definition).
   - `APPLICATIONINSIGHTS_CONNECTION_STRING`: *(optional)* Connection string for your Application Insights instance.
   - `FILES_VECTOR_STORE_IDS`: *(optional)* Comma-separated list of existing vector store IDs to enable the File Search tool (e.g. `vs_weather_docs,vs_adventure_gear`). If omitted, File Search is not attached.
   - `AGENT_INSTRUCTIONS`: *(optional)* Override system instructions for the agent (multi-line supported). If not set, defaults provided in code.
   - `USER_ADVENTURE_PROMPT` / `USER_WEATHER_PROMPT`: *(optional)* Override initial user message.
   - `ENABLE_STEP_TRACE`: *(optional, default `true`)* Emit live run step tracing (reasoning + pending tool calls) to console + telemetry.
   - `AGENT_ID`: *(optional)* If set, reuses an existing agent instead of creating a new one. Clear/unset this if you add new tools (e.g. File Search) and need them attached during agent creation.
   - `CONNECTED_AGENT_ID`: *(optional)* If set, uses an existing agent to create a connected workflow

2. Ensure you are authenticated for Azure (e.g. `az login`, managed identity, or service principal creds).

## Install dependencies

```powershell
python -m pip install -r requirements.txt
```text

> If you are using a virtual environment, activate it first (e.g. `.\.venv\Scripts\Activate.ps1`).

## Run the agent

```powershell
python WeatherAgent.py
```

If you add `FILES_VECTOR_STORE_IDS` later and previously pinned an `AGENT_ID`, clear `AGENT_ID` so the agent is recreated with the File Search tool bound:

```powershell
Remove-Item Env:AGENT_ID -ErrorAction SilentlyContinue
$env:FILES_VECTOR_STORE_IDS = "vs_weather_docs,vs_adventure_gear"
python WeatherAgent.py
```

The script will:

1. Initialize telemetry (if the Application Insights connection string is provided).
2. Create an agent bound to the specified model deployment.
3. Attach MCP tool definitions and optionally File Search tool definitions (if `FILES_VECTOR_STORE_IDS` present) and create the agent.
4. Post the configured user message and create a run.
5. Poll run status; when the model proposes tool calls the run enters `requires_action` and the script auto-approves eligible MCP / File Search calls.
6. Stream run status, live step traces (if enabled), tool approvals, and conversation data to the console (and to Application Insights when enabled).

### Agent Orchestration Flow

```
User Prompt -> Agent (system instructions) -> Model reasoning -> (Propose tool calls?) -> requires_action
      -> Tool approvals (script) -> submit approvals -> model executes tools (MCP / File Search)
      -> Additional reasoning -> final answer -> run completion
```

Step tracing prints lines like:

```
[STEP TRACE] id=step_abc status=in_progress type=message_creation
   tool_calls (1 pending):
      - id=call_xyz type=file_search
```

These are also emitted as OpenTelemetry span events for deep diagnostics.

## Monitoring with Application Insights

- Logs are emitted with structured properties (`weather_agent` logger).
- A span named `weather_agent.run` captures the overall execution; inspect it in Application Insights > Transactions.
- Each SDK call is wrapped in a child span (e.g. `runs.create`, `run_steps.list`).
- Live run steps (when enabled) appear as span events named `run_step` with attributes: `step.id`, `step.status`, `tool.call.count`, and any heuristic `step.reasoning` text captured.
- Tool selection decisions are recorded via events `tool_selection` and `tool_selection_error`.
- Add custom metrics or traces by extending the helper `log_info` function or using the `tracer` instance.

### Common Telemetry Attributes

| Attribute | Meaning |
|-----------|---------|
| weather.agent_id | The created/reused agent ID |
| weather.run.status | Final run status |
| weather.user_prompt | Truncated initial user prompt (first 500 chars) |
| step.reasoning | Captured reasoning snippet (heuristic) |
| tool.call.count | Number of tool calls proposed in that step |

## Troubleshooting

- **Missing imports**: run `python -m pip install -r requirements.txt` to pull in all dependencies.
- **Authentication errors**: confirm `az login` or service principal environment variables are set.
- **Telemetry not appearing**: double-check the Application Insights connection string and verify outbound network access.
- **File Search tool not used**: Ensure `FILES_VECTOR_STORE_IDS` is set before agent creation and `AGENT_ID` is unset so a fresh agent is created. Confirm the vector store IDs are valid.
- **No tool calls proposed**: The model may think it can answer directly—reinforce instructions to "Use File Search before answering product or catalog questions." Adjust `AGENT_INSTRUCTIONS` accordingly.
- **Existing agent missing new tools**: Remove `AGENT_ID` or delete the agent so it is recreated with updated tool definitions.

## Next steps

- Replace the sample MCP URL with your own tool server.
- Parameterize the user prompt to take dynamic inputs.
- Package the agent as an Azure Function, container app, or web job for automation.
- Extend monitoring with custom metrics or dashboards.
- Add retry/backoff or exponential polling strategy for long runs.
- Integrate a CLI flag to switch between Adventure and Weather instruction profiles.
- Cache run steps or responses to disk for offline analysis.
