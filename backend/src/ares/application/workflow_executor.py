import logging
from uuid import UUID
from ares.domain.workflows import WorkflowPlan, WorkflowNodeState
from ares.application.tool_executor import ToolExecutor
from ares.domain.tools import ToolContext
from ares.application.repository import Repository
import hashlib

logger = logging.getLogger(__name__)

class WorkflowExecutor:
    def __init__(self, tool_executor: ToolExecutor, repository: Repository):
        self.tool_executor = tool_executor
        self.repository = repository

    def execute_plan(self, plan: WorkflowPlan, context: ToolContext) -> bool:
        if not plan.validate_dag():
            logger.error("Workflow DAG validation failed")
            return False

        # Find executable nodes (dependencies met)
        executable_nodes = []
        for node in plan.nodes.values():
            if node.state == "pending":
                can_run = True
                for dep_id in node.dependencies:
                    if plan.nodes[dep_id].state != "completed":
                        can_run = False
                        break
                if can_run:
                    executable_nodes.append(node)

        # Enforce concurrency limit (<= 2)
        concurrent = 0
        for node in plan.nodes.values():
            if node.state == "running":
                concurrent += 1

        for node in executable_nodes:
            if concurrent >= 2:
                break
                
            node.state = "running"
            concurrent += 1
            
            # Identity Hash (simplified)
            h = hashlib.sha256()
            h.update(str(node.node_id).encode())
            h.update(node.tool_name.encode())
            h.update(str(node.inputs).encode())
            node.identity_hash = h.hexdigest()
            
            # Update context for the node
            node_context = ToolContext(
                workspace_id=context.workspace_id,
                run_id=context.run_id,
                node_id=node.node_id,
                lease_token=context.lease_token,
                deadline=context.deadline,
                policy_version=context.policy_version,
                remaining_budgets=context.remaining_budgets,
                permitted_asset_ids=context.permitted_asset_ids,
                permitted_source_ids=context.permitted_source_ids
            )
            
            # Execute tool
            try:
                result = self.tool_executor.execute_tool(node.tool_name, node_context, node.inputs)
                
                if result.error_category:
                    if node.retries_remaining > 0 and result.error_category not in ["not_authorized", "invalid_input"]:
                        node.retries_remaining -= 1
                        node.state = "pending"  # Will retry next tick
                    else:
                        node.state = "failed"
                else:
                    node.state = "completed"
                    node.output_references = result.payload
            except Exception as e:
                logger.exception(f"Unhandled error in node execution {node.node_id}")
                if node.retries_remaining > 0:
                    node.retries_remaining -= 1
                    node.state = "pending"
                else:
                    node.state = "failed"

        # Check if plan is completely done
        all_done = True
        for node in plan.nodes.values():
            if node.state not in ["completed", "failed", "cancelled"]:
                all_done = False
                break
                
        return all_done
