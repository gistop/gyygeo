from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypedDict

try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # pragma: no cover - compatibility with older LangGraph releases
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class ExpertImageSelectionState(TypedDict, total=False):
    task_id: str
    selected_item_id: str


@dataclass(frozen=True)
class ExpertImageSelectionCallbacks:
    search_images: Callable[[str], None]
    continue_with_image: Callable[[str, str], None]


def build_expert_image_selection_graph(callbacks: ExpertImageSelectionCallbacks) -> Any:
    def search_images(state: ExpertImageSelectionState) -> ExpertImageSelectionState:
        callbacks.search_images(state["task_id"])
        return {}

    def wait_for_image_selection(
        state: ExpertImageSelectionState,
    ) -> ExpertImageSelectionState:
        selection = interrupt(
            {
                "pending_action": "select_image",
                "task_id": state["task_id"],
                "message": "Select one candidate image to continue the expert map task.",
            }
        )
        if isinstance(selection, dict):
            selected_item_id = selection.get("item_id")
        else:
            selected_item_id = selection
        if not isinstance(selected_item_id, str) or not selected_item_id.strip():
            raise ValueError("Image selection resume payload must include item_id.")
        return {"selected_item_id": selected_item_id.strip()}

    def continue_with_image(state: ExpertImageSelectionState) -> ExpertImageSelectionState:
        callbacks.continue_with_image(state["task_id"], state["selected_item_id"])
        return {}

    graph = StateGraph(ExpertImageSelectionState)
    graph.add_node("search_images", search_images)
    graph.add_node("wait_for_image_selection", wait_for_image_selection)
    graph.add_node("continue_with_image", continue_with_image)
    graph.add_edge(START, "search_images")
    graph.add_edge("search_images", "wait_for_image_selection")
    graph.add_edge("wait_for_image_selection", "continue_with_image")
    graph.add_edge("continue_with_image", END)
    return graph.compile(checkpointer=InMemorySaver())
