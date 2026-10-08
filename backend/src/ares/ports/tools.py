from typing import Protocol, Any
from ares.domain.tools import ToolSpec, ToolContext, ToolResult

class Tool(Protocol):
    def get_spec(self) -> ToolSpec:
        ...

    def execute(self, context: ToolContext, inputs: dict[str, Any]) -> ToolResult:
        ...
