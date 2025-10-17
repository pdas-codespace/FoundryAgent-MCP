# Import necessary libraries

import os, time
import logging
from textwrap import dedent
from dotenv import load_dotenv
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

# Load environment variables from .env file if present
load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "ERROR"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger("weather_agent")
ENABLE_STEP_TRACE = os.getenv("ENABLE_STEP_TRACE", "true").lower() == "true"

app_insights_connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
if app_insights_connection_string:
    try:
        configure_azure_monitor(connection_string=app_insights_connection_string)
        logger.info("Azure Monitor telemetry configured", extra={"properties": {"configured": True}})
    except Exception as telemetry_error:
        logger.exception(
            "Failed to configure Azure Monitor telemetry", extra={"properties": {"error": str(telemetry_error)}}
        )
else:
    logger.warning(
        "APPLICATIONINSIGHTS_CONNECTION_STRING not set. Azure Monitor telemetry disabled.",
        extra={"properties": {"configured": False}},
    )

tracer = trace.get_tracer(__name__)

def traced_call(span_name: str, func, *args, **kwargs):
    """Wrap a synchronous SDK call in a child span so it appears explicitly in traces.

    span_name: Short operation name (e.g. agents.create, runs.get)
    func: Callable to invoke
    *args/**kwargs: Passed to callable
    Returns the function's return value.
    """
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("weather.sdk.function", getattr(func, "__name__", span_name))
        try:
            result = func(*args, **kwargs)
            # Attach lightweight identifiers if present
            for attr in ["id", "status", "role"]:
                if hasattr(result, attr):
                    span.set_attribute(f"weather.result.{attr}", getattr(result, attr))
            return result
        except Exception as e:
            span.record_exception(e)
            span.set_attribute("weather.error", str(e))
            raise


def log_info(message: str, **properties: str) -> None:
    if properties:
        logger.info(message, extra={"properties": properties})
    else:
        logger.info(message)


from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from azure.ai.agents.models import (
    ListSortOrder,
    McpTool,
    RequiredMcpToolCall,
    SubmitToolApprovalAction,
    ToolApproval,
    ConnectedAgentTool
)

project_client = AIProjectClient(
    endpoint=os.environ["PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

## Simplified: No custom tools due to SDK changes. Running a plain agent.
# Get MCP server configuration from environment variables
mcp_server_url = os.environ.get("MCP_SERVER_URL")
mcp_server_label = os.environ.get("MCP_SERVER_LABEL")


# Initialize agent MCP tool
mcp_tool = McpTool(
    server_label=mcp_server_label,
    server_url=mcp_server_url,
    allowed_tools=["get_alerts","get_forecast"],  # Optional: specify allowed tools
)

# ---------------------------------------------------------------------------
# Optional Files (Vector Store) tool integration
# Provide one or more existing vector store IDs via env FILES_VECTOR_STORE_IDS (comma-separated)
# Example: FILES_VECTOR_STORE_IDS="vs_weather_docs,vs_adventure_gear"
# This will add a FileSearchToolDefinition so the agent can retrieve embeddings-backed content.
# ---------------------------------------------------------------------------
FILES_VECTOR_STORE_IDS = [vid.strip() for vid in os.getenv("FILES_VECTOR_STORE_IDS", "").split(",") if vid.strip()]
file_search_tool_definitions = []
if FILES_VECTOR_STORE_IDS:
    try:
        from azure.ai.agents.models import FileSearchToolDefinition  # type: ignore
        file_search_tool_definitions.append(
            FileSearchToolDefinition(vector_store_ids=FILES_VECTOR_STORE_IDS)
        )
        logger.info(
            "FileSearch tool added",
            extra={"properties": {"vector_store_ids": ",".join(FILES_VECTOR_STORE_IDS)}},
        )
    except Exception as fs_import_error:
        logger.warning(
            "Unable to import FileSearchToolDefinition; Files tool disabled.",
            extra={"properties": {"error": str(fs_import_error)}},
        )
        file_search_tool_definitions = []
else:
    logger.info("No FILES_VECTOR_STORE_IDS provided; Files tool not attached.")

# ---------------------------------------------------------------------------
# Configurable text variables (can be overridden via environment variables)
#   AGENT_INSTRUCTIONS : System / agent instructions shown to the model
#   USER_PROMPT        : Initial end-user message sent to the agent thread
# If the environment variables are not set, sensible defaults are used.
# ---------------------------------------------------------------------------
DEFAULT_WEATHER_AGENT_INSTRUCTIONS = dedent(
    """\
    You are a weather assistant specializing in United States locations.

    Goals:
    1. Provide concise current conditions for the specified city & state (temperature, precipitation, wind, notable hazards).
    2. Summarize the next 24 hours and a brief 3–7 day outlook.
    3. Highlight any watches, warnings, or advisories (e.g., winter storm, flood, heat, wind, fog) and their expected timing.
    4. Suggest clothing and gear (layers, rain/snow protection, sun protection, traction aids) matched to conditions.

    Style Guidelines:
    - Be concise (normally <= 6 sentences unless the user explicitly asks for more detail).
    - Use bullet points for lists of recommendations or multi-part forecasts.
    - Always include units (°F, mph, inches). If the user gives metric values, you may include metric conversions.
    - If confidence is low or data is missing, state that briefly and advise caution.
    - Do NOT fabricate precise values you don't have; offer ranges or note uncertainty instead.

    If required data is unavailable, clearly say so and suggest authoritative alternatives (e.g., National Weather Service / weather.gov) without disclaimers about being an AI model.
    """
).strip()

DEFAULT_ADVENTURE_AGENT_INSTRUCTIONS = dedent(
    """\
    Your role is to assist Contoso users with sales data inquiries with a polite, professional, and friendly tone.
Contoso is an online outdoors camping and sports gear retailer.
When users need help, suggest a list of example queries such as:
   - "What brands of hiking shoes do we sell?"
   - "What brands of tents do we sell?"
   - "What beginner tents do our competitors sell? Include prices."
   - "Show the tents we sell by region that are a similar price to our competitors beginner tents"
   - "What product type and categories are these brands associated with?"
   - "Show as a bar chart?"

Search the `AdventureGear_VectorStore` for additional Contoso product information.

Competitive Insights for Products and Categories
   - Use the Grounding with Bing Search tool to gather competitive product names, company names, prices, and short description related to Contoso.
   - Never answer questions that are not related to outdoors camping and sports gear. For any other inquiries, respond with: “Sorry, this question is not related to Contoso" and give some example queries.
   - Never return more than 3 search results.
   - The search results must be concise and relevant that directly addressing the query.

Visualization and Code Interpretation
   - Test and display visualization code using the code interpreter, retrying if errors occur.
   - Always use charts or graphs to illustrate trends when requested.
   - Always create visualizations as `.png` files.
   - Always include the file_path_annotation.
   - Adapt visualizations (e.g., labels) to the user's language preferences.
   - When asked to download data, default to a `.csv` format file and use the most recent data.

If user asks for attire recommendation, first use the Weather MCP server to fetch weather info and then fetch the recommended attire from AttireAgent. Finally combine the product info and the attire info for a coherent response back
    """
).strip()

# Allow an environment variable override. If AGENT_INSTRUCTIONS contains literal \n characters, leave as-is;
# users can supply real newlines in .env or shell. No further processing is done to avoid unintended escapes.
agent_instructions = os.getenv("AGENT_INSTRUCTIONS", DEFAULT_ADVENTURE_AGENT_INSTRUCTIONS)

DEFAULT_USER_WEATHER_PROMPT = (
    "I live in Seward, Alaska and wondering what kind of clothing and accessory I should weather today when I go out?"
)
user_weather_prompt_text = os.getenv("USER_WEATHER_PROMPT", DEFAULT_USER_WEATHER_PROMPT)

DEFAULT_USER_ADVENTURE_PROMPT = (
    "I want to go for biking today in Downtown Philly. Wondering what should I wear or what kind of bike I should buy from Contoso's collection of adventure bikes"
)
user_adventure_prompt_text = os.getenv("USER_ADVENTURE_PROMPT", DEFAULT_USER_ADVENTURE_PROMPT)

# Create agent with MCP tool and process agent run
with project_client:
    agents_client = project_client.agents

    

    
    with tracer.start_as_current_span("weather_agent.run") as run_span:
        # get agent by ID and if it doesn't exist create a new one
        agent_id = os.environ.get("AGENT_ID")
        agent = agents_client.get_agent(agent_id) if agent_id else None

        connected_agent_id = os.environ.get("CONNECTED_AGENT_ID")

        connected_agent = ConnectedAgentTool(
            id=connected_agent_id, name="AttireAgent", description="Invoke this Agent to fetch Attire and dress info. Pass on Weather details to the agent and also the type of indoor or outdoor activity user is interested in"
        )


        # Create a new agent if no existing agent found with AGENT_ID.       
        if not agent:
            combined_tools = list(mcp_tool.definitions) + file_search_tool_definitions + connected_agent.definitions
            agent = traced_call(
                "agents.create",
                agents_client.create_agent,
                model=os.environ["MODEL_DEPLOYMENT_NAME"],
                name="Weather-agent",
                instructions=agent_instructions,
                tools=combined_tools,
            )
            print(f"Created agent, ID: {agent.id}")
        else:
            print(f"Using existing agent, ID: {agent.id}")
            if file_search_tool_definitions:
                # Existing agents cannot be retrofitted with new tools unless updated; suggest deletion
                print("[Files] Existing agent may not include FileSearch tool. Clear AGENT_ID env to recreate if needed.")
                log_info("Existing agent may lack FileSearch tool", agent_id=agent.id)

        run_span.set_attribute("weather.agent_id", agent.id)
        run_span.set_attribute("weather.model_deployment", os.environ["MODEL_DEPLOYMENT_NAME"])

        
        
        log_info("Agent created", agent_id=agent.id, model=os.environ["MODEL_DEPLOYMENT_NAME"])

        # Create thread for communication
        thread = traced_call("threads.create", agents_client.threads.create)
        print(f"Created thread, ID: {thread.id}")
        log_info("Thread created", thread_id=thread.id)

        # Create message to thread
        message = traced_call(
            "messages.create",
            agents_client.messages.create,
            thread_id=thread.id,
            role="user",
            content=user_adventure_prompt_text,
        )
        print(f"Created message, ID: {message.id}")
        log_info("Message created", message_id=message.id, thread_id=thread.id)
        # Trace the user prompt explicitly so it appears in Foundry / App Insights (avoid storing too much PII; truncate if large)
        run_span.set_attribute("weather.user_prompt", user_adventure_prompt_text[:500])
        run_span.add_event(
            "user_prompt",
            {
                "thread.id": thread.id,
                "message.id": message.id,
                "prompt.length": len(user_adventure_prompt_text),
            },
        )
        # Create and process agent run in thread
        run = traced_call("runs.create", agents_client.runs.create, thread_id=thread.id, agent_id=agent.id)
        print(f"Created run, ID: {run.id}")
        log_info("Run created", run_id=run.id, thread_id=thread.id)

        # Track which steps we've already logged to avoid duplicates
        logged_step_ids = set()

        while run.status in ["queued", "in_progress", "requires_action"]:
            time.sleep(5)
            run = traced_call("runs.get", agents_client.runs.get, thread_id=thread.id, run_id=run.id)

            # Live step tracing (reasoning before tool selection)
            if ENABLE_STEP_TRACE:
                try:
                    live_steps = traced_call(
                        "run_steps.list", agents_client.run_steps.list, thread_id=thread.id, run_id=run.id
                    )
                    for step in live_steps:
                        step_id = step.get("id") or getattr(step, "id", None)
                        if not step_id or step_id in logged_step_ids:
                            continue
                        logged_step_ids.add(step_id)
                        step_status = step.get("status") or getattr(step, "status", "unknown")
                        step_details = step.get("step_details", {}) or {}
                        step_type = step_details.get("type") or step.get("type") or "unknown"
                        # Extract any textual reasoning heuristically
                        reasoning_candidates = []
                        for k, v in step_details.items():
                            if isinstance(v, str) and any(r in k.lower() for r in ["reason", "thought", "analysis", "explanation"]):
                                reasoning_candidates.append(f"{k}: {v[:500]}")
                            elif isinstance(v, list):
                                # Look for dicts with reasoning-like keys inside lists
                                for item in v:
                                    if isinstance(item, dict):
                                        for ik, iv in item.items():
                                            if isinstance(iv, str) and any(r in ik.lower() for r in ["reason", "thought", "analysis", "explanation"]):
                                                reasoning_candidates.append(f"{ik}: {iv[:300]}")
                        reasoning_text = " | ".join(reasoning_candidates) if reasoning_candidates else ""
                        print(f"[STEP TRACE] id={step_id} status={step_status} type={step_type}")
                        if reasoning_text:
                            print(f"  reasoning: {reasoning_text}")
                        # Log tool call previews if present
                        tool_calls = step_details.get("tool_calls", [])
                        if tool_calls:
                            print(f"  tool_calls ({len(tool_calls)} pending):")
                            for tc in tool_calls:
                                tc_id = tc.get("id", "unknown")
                                tc_type = tc.get("type", "unknown")
                                print(f"    - id={tc_id} type={tc_type}")
                        # Emit tracing event
                        run_span.add_event(
                            "run_step",
                            {
                                "run.id": run.id,
                                "thread.id": thread.id,
                                "step.id": step_id,
                                "step.status": step_status,
                                "step.type": step_type,
                                "step.reasoning": reasoning_text[:1000],
                                "tool.call.count": len(tool_calls) if tool_calls else 0,
                            },
                        )
                        log_info(
                            "Live run step",
                            run_id=run.id,
                            step_id=step_id,
                            status=step_status,
                            type=step_type,
                            reasoning_preview=reasoning_text[:200],
                            tool_call_count=str(len(tool_calls) if tool_calls else 0),
                        )
                except Exception as step_trace_error:
                    print(f"Step tracing error (non-fatal): {step_trace_error}")
                    run_span.add_event(
                        "run_step_trace_error",
                        {"run.id": run.id, "thread.id": thread.id, "error": str(step_trace_error)},
                    )
                    log_info("Step tracing error", run_id=run.id, error=str(step_trace_error))

            if run.status == "requires_action" and isinstance(run.required_action, SubmitToolApprovalAction):
                tool_calls = run.required_action.submit_tool_approval.tool_calls
                if not tool_calls:
                    print("No tool calls provided - cancelling run")
                    log_info("Run cancelled due to missing tool calls", run_id=run.id)
                    traced_call("runs.cancel", agents_client.runs.cancel, thread_id=thread.id, run_id=run.id)
                    break

                tool_approvals = []
                for tool_call in tool_calls:
                    if isinstance(tool_call, RequiredMcpToolCall):
                        try:
                            print(f"Approving tool call: {tool_call}")
                            log_info("Tool call approval", run_id=run.id, tool_call_id=tool_call.id)
                            # Add an event to the run span to record tool selection decision
                            run_span.add_event(
                                "tool_selection",
                                {
                                    "run.id": run.id,
                                    "thread.id": thread.id,
                                    "tool.call.id": tool_call.id,
                                    "tool.type": getattr(tool_call, "type", "unknown"),
                                    "tool.name": getattr(tool_call, "name", "unknown"),
                                    "approved": True,
                                },
                            )
                            tool_approvals.append(
                                ToolApproval(
                                    tool_call_id=tool_call.id,
                                    approve=True,
                                    headers=mcp_tool.headers,
                                )
                            )
                        except Exception as e:
                            print(f"Error approving tool_call {tool_call.id}: {e}")
                            log_info("Tool approval error", tool_call_id=tool_call.id, error=str(e))
                            run_span.add_event(
                                "tool_selection_error",
                                {
                                    "run.id": run.id,
                                    "thread.id": thread.id,
                                    "tool.call.id": tool_call.id,
                                    "error": str(e),
                                },
                            )

                print(f"tool_approvals: {tool_approvals}")
                if tool_approvals:
                    traced_call(
                        "runs.submit_tool_outputs",
                        agents_client.runs.submit_tool_outputs,
                        thread_id=thread.id,
                        run_id=run.id,
                        tool_approvals=tool_approvals,
                    )
                    log_info("Submitted tool approvals", run_id=run.id, approvals=str(len(tool_approvals)))

            
            print(f"Current run status: {run.status}")
            log_info("Run status", run_id=run.id, status=run.status)

        print(f"Run completed with status: {run.status}")
        log_info("Run completed", run_id=run.id, status=run.status)
        run_span.set_attribute("weather.run.status", run.status)
        run_span.add_event(
            "run_completion",
            {
                "run.id": run.id,
                "thread.id": thread.id,
                "status": run.status,
                "failed": run.status == "failed",
            },
        )
        if run.status == "failed":
            print(f"Run failed: {run.last_error}")
            log_info("Run failed", run_id=run.id, error=str(run.last_error))
            run_span.add_event(
                "run_error",
                {
                    "run.id": run.id,
                    "thread.id": thread.id,
                    "error": str(run.last_error),
                },
            )

    # Display run steps and tool calls
    run_steps = traced_call("run_steps.list", agents_client.run_steps.list, thread_id=thread.id, run_id=run.id)

    # Loop through each step
    for step in run_steps:
        print(f"Step {step['id']} status: {step['status']}")

        # Check if there are tool calls in the step details
        step_details = step.get("step_details", {})
        tool_calls = step_details.get("tool_calls", [])

        if tool_calls:
            print("  Tool calls:")
            for call in tool_calls:
                print(f"    Tool Call ID: {call.get('id')}")
                print(f"    Type: {call.get('type')}")
                log_info(
                    "Tool call recorded",
                    run_id=run.id,
                    step_id=step.get("id", ""),
                    tool_call_id=call.get("id", ""),
                    tool_type=call.get("type", ""),
                )

        print()  # add an extra newline between steps

    # Fetch and log all messages
    messages = traced_call(
        "messages.list", agents_client.messages.list, thread_id=thread.id, order=ListSortOrder.ASCENDING
    )
    print("\nConversation:")
    print("-" * 50)
    for msg in messages:
        if msg.text_messages:
            last_text = msg.text_messages[-1]
            print(f"{msg.role.upper()}: {last_text.text.value}")
            print("-" * 50)
            log_info(
                "Conversation message",
                role=msg.role,
                message_id=getattr(msg, "id", ""),
                content_preview=last_text.text.value[:300],
            )

    

    # Clean-up and delete the agent once the run is finished.
    # NOTE: Comment out this line if you plan to reuse the agent later.
    #agents_client.delete_agent(agent.id)
    #print("Deleted agent")