import operator
from typing import Annotated
from typing_extensions import TypedDict


class AgentMessage(TypedDict):
    role: str     # "planner" | "researcher" | "analyst" | "reviewer"
    content: str


class AgentState(TypedDict):
    user_input: str
    messages: Annotated[list[AgentMessage], operator.add]
    plan: str
    research: str
    analysis: str
    final_output: str
    iteration: int
    max_iterations: int
    status: str        # "running" | "completed" | "failed"
    error: str | None
