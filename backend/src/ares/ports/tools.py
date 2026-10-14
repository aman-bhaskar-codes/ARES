from typing import Any, Protocol

from ares.domain.tools import ToolContext, ToolResult, ToolSpec


class Tool(Protocol):
    def get_spec(self) -> ToolSpec:
        ...

    def execute(self, context: ToolContext, inputs: dict[str, Any]) -> ToolResult:
        ...
