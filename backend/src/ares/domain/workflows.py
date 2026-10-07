from typing import Any, Literal
from pydantic import BaseModel, Field
from uuid import UUID

WorkflowNodeState = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "waiting_for_user"
]

class WorkflowNode(BaseModel):
    node_id: UUID
    tool_name: str
    dependencies: list[UUID] = Field(default_factory=list)
    state: WorkflowNodeState = "pending"
    inputs: dict[str, Any] = Field(default_factory=dict)
    output_references: dict[str, Any] = Field(default_factory=dict)
    retries_remaining: int = 2
    identity_hash: str | None = None

class WorkflowPlan(BaseModel):
    plan_id: UUID
    template_version: str
    goal: str
    facets: list[str] = Field(default_factory=list)
    nodes: dict[UUID, WorkflowNode] = Field(default_factory=dict)
    allowed_tool_names: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    
    def validate_dag(self) -> bool:
        if len(self.nodes) > 12:
            return False
            
        # Check depth <= 4 and basic DAG properties
        visited = set()
        temp_mark = set()
        
        def visit(node_id: UUID, depth: int) -> bool:
            if depth > 4:
                return False
            if node_id in temp_mark: # cycle
                return False
            if node_id in visited:
                return True
                
            temp_mark.add(node_id)
            node = self.nodes[node_id]
            for dep in node.dependencies:
                if dep not in self.nodes:
                    return False
                if not visit(dep, depth + 1):
                    return False
            
            temp_mark.remove(node_id)
            visited.add(node_id)
            return True
            
        for node_id in self.nodes:
            if node_id not in visited:
                if not visit(node_id, 1):
                    return False
                    
        return True
