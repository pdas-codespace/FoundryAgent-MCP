# FoundryAgent-MCP

## Overview

FoundryAgent-MCP is a Python sample that demonstrates how to drive an Azure AI Foundry agent that can call Model Context Protocol (MCP) tools while streaming operational telemetry into Azure Monitor / Application Insights. The project provisions an AI Project client, creates an agent tied to your model deployment, and orchestrates a full run that calls a weather-focused MCP server.

## Key features

- **Azure AI Foundry agent orchestration** powered by `azure-ai-projects` and `azure-ai-agents`.
- **MCP tool integration** for weather data lookups (`get_alerts`, `get_forecast`).
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
```

## Configuration

1. Copy `.env` and fill in the required values:
   - `PROJECT_ENDPOINT`: Azure AI project endpoint URL.
   - `MODEL_DEPLOYMENT_NAME`: Name of your model deployment (e.g. `gpt-4o`).
   - `MCP_SERVER_URL`: Base URL of the weather MCP server.
   - `MCP_SERVER_LABEL`: Friendly label for the MCP server.
   - `APPLICATIONINSIGHTS_CONNECTION_STRING`: *(optional)* Connection string for your Application Insights instance.

2. Ensure you are authenticated for Azure (e.g. `az login`, managed identity, or service principal creds).

## Install dependencies

```powershell
python -m pip install -r requirements.txt
```

> If you are using a virtual environment, activate it first (e.g. `.\.venv\Scripts\Activate.ps1`).

## Run the agent

```powershell
python WeatherAgent.py
```

The script will:

1. Initialize telemetry (if the Application Insights connection string is provided).
2. Create an agent bound to the specified model deployment.
3. Post a weather-related message and run the agent.
4. Stream run status, tool approvals, and conversation data to the console (and to Application Insights when enabled).

## Monitoring with Application Insights

- Logs are emitted with structured properties (`weather_agent` logger).
- A span named `weather_agent.run` captures the overall execution; inspect it in Application Insights > Transactions.
- Add custom metrics or traces by extending the helper `log_info` function or using the `tracer` instance.

## Troubleshooting

- **Missing imports**: run `python -m pip install -r requirements.txt` to pull in all dependencies.
- **Authentication errors**: confirm `az login` or service principal environment variables are set.
- **Telemetry not appearing**: double-check the Application Insights connection string and verify outbound network access.

## Next steps

- Replace the sample MCP URL with your own tool server.
- Parameterize the user prompt to take dynamic inputs.
- Package the agent as an Azure Function, container app, or web job for automation.
- Extend monitoring with custom metrics or dashboards.
