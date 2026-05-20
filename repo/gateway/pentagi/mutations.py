"""Controlled PentAGI GraphQL mutation constants.

Policy/approval checks must happen before these are called.
"""

CREATE_FLOW_MUTATION = """
mutation CreateFlow($input: CreateFlowInput!) { createFlow(input: $input) { id name status createdAt } }
"""
PUT_USER_INPUT_MUTATION = """
mutation PutUserInput($flowId: ID!, $input: String!) { putUserInput(flowId: $flowId, input: $input) { id status updatedAt } }
"""
STOP_FLOW_MUTATION = """
mutation StopFlow($flowId: ID!) { stopFlow(flowId: $flowId) { id status updatedAt } }
"""
FINISH_FLOW_MUTATION = """
mutation FinishFlow($flowId: ID!) { finishFlow(flowId: $flowId) { id status updatedAt } }
"""
RENAME_FLOW_MUTATION = """
mutation RenameFlow($flowId: ID!, $name: String!) { renameFlow(flowId: $flowId, name: $name) { id name updatedAt } }
"""
DELETE_FLOW_MUTATION = """
mutation DeleteFlow($flowId: ID!) { deleteFlow(flowId: $flowId) }
"""
