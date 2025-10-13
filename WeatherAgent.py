# Import necessary libraries

import os, time
import logging
from dotenv import load_dotenv
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

# Load environment variables from .env file if present
load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger("weather_agent")

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
    ToolApproval
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

# Create agent with MCP tool and process agent run
with project_client:
    agents_client = project_client.agents

    

    
    with tracer.start_as_current_span("weather_agent.run") as run_span:
        # get agent by ID and if it doesn't exist create a new one
        agent_id = os.environ.get("AGENT_ID")
        agent = agents_client.get_agent(agent_id) if agent_id else None

        # Create a new agent if no existing agent found with AGENT_ID.       
        if not agent:
            agent = agents_client.create_agent(
                model=os.environ["MODEL_DEPLOYMENT_NAME"],
                name="Weather-agent",
                instructions="You are a weather assistant that helps users find weather updates and warnings for a given US state and City",
                tools=mcp_tool.definitions
            )
            print(f"Created agent, ID: {agent.id}")
        else:
            print(f"Using existing agent, ID: {agent.id}")

        run_span.set_attribute("weather.agent_id", agent.id)
        run_span.set_attribute("weather.model_deployment", os.environ["MODEL_DEPLOYMENT_NAME"])

        
        print("No custom tools registered in this simplified run.")
        log_info("Agent created", agent_id=agent.id, model=os.environ["MODEL_DEPLOYMENT_NAME"])

        # Create thread for communication
        thread = agents_client.threads.create()
        print(f"Created thread, ID: {thread.id}")
        log_info("Thread created", thread_id=thread.id)

        # Create message to thread
        message = agents_client.messages.create(
            thread_id=thread.id,
            role="user",
            content="I live in Lafayette Hill, Pennsylvania and wondering what kind of clothing and accessory I should weather today when I go out?",
        )
        print(f"Created message, ID: {message.id}")
        log_info("Message created", message_id=message.id, thread_id=thread.id)
        # Create and process agent run in thread
        run = agents_client.runs.create(thread_id=thread.id, agent_id=agent.id)
        print(f"Created run, ID: {run.id}")
        log_info("Run created", run_id=run.id, thread_id=thread.id)

        while run.status in ["queued", "in_progress", "requires_action"]:
            time.sleep(1)
            run = agents_client.runs.get(thread_id=thread.id, run_id=run.id)

            if run.status == "requires_action" and isinstance(run.required_action, SubmitToolApprovalAction):
                tool_calls = run.required_action.submit_tool_approval.tool_calls
                if not tool_calls:
                    print("No tool calls provided - cancelling run")
                    log_info("Run cancelled due to missing tool calls", run_id=run.id)
                    agents_client.runs.cancel(thread_id=thread.id, run_id=run.id)
                    break

                tool_approvals = []
                for tool_call in tool_calls:
                    if isinstance(tool_call, RequiredMcpToolCall):
                        try:
                            print(f"Approving tool call: {tool_call}")
                            log_info("Tool call approval", run_id=run.id, tool_call_id=tool_call.id)
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

                print(f"tool_approvals: {tool_approvals}")
                if tool_approvals:
                    agents_client.runs.submit_tool_outputs(
                        thread_id=thread.id, run_id=run.id, tool_approvals=tool_approvals
                    )
                    log_info("Submitted tool approvals", run_id=run.id, approvals=str(len(tool_approvals)))

            
            print(f"Current run status: {run.status}")
            log_info("Run status", run_id=run.id, status=run.status)

        print(f"Run completed with status: {run.status}")
        log_info("Run completed", run_id=run.id, status=run.status)
        if run.status == "failed":
            print(f"Run failed: {run.last_error}")
            log_info("Run failed", run_id=run.id, error=str(run.last_error))

    # Display run steps and tool calls
    run_steps = agents_client.run_steps.list(thread_id=thread.id, run_id=run.id)

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
    messages = agents_client.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
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