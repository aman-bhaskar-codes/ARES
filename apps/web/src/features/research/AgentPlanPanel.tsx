import React from 'react';
import type { WorkflowPlan, WorkflowNode } from '@/lib/api/types';

interface AgentPlanPanelProps {
  plan: WorkflowPlan;
  budget: { token_limit: number; tokens_used: number; wall_clock_limit_seconds: number; };
  onCancel: () => void;
  onResume: (nodeId: string, clarification: string) => void;
}

export function AgentPlanPanel({ plan, budget, onCancel, onResume }: AgentPlanPanelProps) {
  const allNodes = Object.values(plan.nodes);
  const completedNodes = allNodes.filter(n => n.state === 'completed').length;
  const totalNodes = allNodes.length;
  
  return (
    <div className="bg-white rounded-lg shadow p-4 border border-gray-200">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold text-gray-900">Research Plan</h2>
        <span className="text-sm text-gray-500">
          {completedNodes} / {totalNodes} Steps Completed
        </span>
      </div>
      
      <div className="mb-4 text-sm text-gray-700">
        <strong>Goal:</strong> {plan.goal}
      </div>

      <div className="mb-4 p-3 bg-gray-50 rounded-md text-sm text-gray-600">
        <div className="font-medium text-gray-800 mb-1">Resource Budget</div>
        <div className="flex justify-between">
          <span>Tokens: {budget.tokens_used} / {budget.token_limit}</span>
          <span>Time Limit: {budget.wall_clock_limit_seconds}s</span>
        </div>
      </div>

      <div className="space-y-3">
        {allNodes.map((node: WorkflowNode) => (
          <div 
            key={node.node_id} 
            className={`p-3 rounded border ${
              node.state === 'completed' ? 'bg-green-50 border-green-200' :
              node.state === 'running' ? 'bg-blue-50 border-blue-200 shadow-inner' :
              node.state === 'failed' ? 'bg-red-50 border-red-200' :
              node.state === 'waiting_for_user' ? 'bg-yellow-50 border-yellow-200' :
              'bg-gray-50 border-gray-100 text-gray-500'
            }`}
          >
            <div className="flex justify-between items-start">
              <div>
                <div className="font-medium text-gray-900 capitalize">
                  {node.tool_name.replace(/_/g, ' ')}
                </div>
                <div className="text-xs mt-1 uppercase font-semibold opacity-70">
                  {node.state}
                </div>
              </div>
              {node.state === 'waiting_for_user' && (
                <button
                  onClick={() => onResume(node.node_id, 'Proceed')}
                  className="px-3 py-1 bg-yellow-600 text-white rounded text-sm hover:bg-yellow-700"
                >
                  Clarify & Resume
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {completedNodes < totalNodes && (
        <div className="mt-6 flex justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 border border-red-300 text-red-600 rounded-md hover:bg-red-50 transition-colors"
          >
            Cancel Execution
          </button>
        </div>
      )}
    </div>
  );
}
