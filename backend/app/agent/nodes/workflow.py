from langgraph.graph import END, START, StateGraph

from app.agent.nodes.steps import (
    analyze_results,
    classify_request,
    execute_query_node,
    generate_query,
    retrieve_schema,
    respond,
    validate_query,
)
from app.agent.state import AssistantState


def _after_classification(state: AssistantState) -> str:
    if state.get("workflow_status") == "failed":
        return "respond"
    if state["intent"] in {"database_query", "schema_question"}:
        return "retrieve_schema"
    return "respond"


def _after_schema(state: AssistantState) -> str:
    if state.get("workflow_status") == "failed":
        return "respond"
    if state["intent"] == "database_query":
        return "generate_query"
    return "respond"


def _after_generation(state: AssistantState) -> str:
    generation = state.get("generation")
    if generation is not None and generation.status == "success":
        return "validate_query"
    return "respond"


def _after_validation(state: AssistantState) -> str:
    return "execute_query" if not state.get("validation_errors") else "respond"


def _after_execution(state: AssistantState) -> str:
    execution = state.get("execution")
    return "analyze_results" if execution is not None and execution.status == "success" else "respond"


def build_assistant_graph():
    graph = StateGraph(AssistantState)
    graph.add_node("classify_request", classify_request)
    graph.add_node("retrieve_schema", retrieve_schema)
    graph.add_node("generate_query", generate_query)
    graph.add_node("validate_query", validate_query)
    graph.add_node("execute_query", execute_query_node)
    graph.add_node("analyze_results", analyze_results)
    graph.add_node("respond", respond)

    graph.add_edge(START, "classify_request")
    graph.add_conditional_edges(
        "classify_request",
        _after_classification,
        {"retrieve_schema": "retrieve_schema", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "retrieve_schema",
        _after_schema,
        {"generate_query": "generate_query", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "generate_query",
        _after_generation,
        {"validate_query": "validate_query", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "validate_query",
        _after_validation,
        {"execute_query": "execute_query", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "execute_query",
        _after_execution,
        {"analyze_results": "analyze_results", "respond": "respond"},
    )
    graph.add_edge("analyze_results", "respond")
    graph.add_edge("respond", END)
    return graph.compile()


assistant_graph = build_assistant_graph()
