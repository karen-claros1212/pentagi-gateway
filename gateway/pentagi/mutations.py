"""Controlled PentAGI GraphQL mutation constants.

Policy/approval checks must happen before these are called.
These constants are schema-aligned for PentAGI v2.0.0 and are covered by mocked tests only.
"""

CREATE_FLOW_MUTATION = """
mutation CreateFlow($modelProvider: String!, $input: String!) {
  createFlow(modelProvider: $modelProvider, input: $input) {
    id
    title
    status
    provider {
      name
      type
    }
    createdAt
    updatedAt
  }
}
"""

PUT_USER_INPUT_MUTATION = """
mutation PutUserInput($flowId: ID!, $input: String!, $modelProvider: String) {
  putUserInput(flowId: $flowId, input: $input, modelProvider: $modelProvider)
}
"""

STOP_FLOW_MUTATION = """
mutation StopFlow($flowId: ID!) {
  stopFlow(flowId: $flowId)
}
"""

FINISH_FLOW_MUTATION = """
mutation FinishFlow($flowId: ID!) {
  finishFlow(flowId: $flowId)
}
"""

RENAME_FLOW_MUTATION = """
mutation RenameFlow($flowId: ID!, $title: String!) {
  renameFlow(flowId: $flowId, title: $title)
}
"""

DELETE_FLOW_MUTATION = """
mutation DeleteFlow($flowId: ID!) {
  deleteFlow(flowId: $flowId)
}
"""

CREATE_ASSISTANT_MUTATION = """
mutation CreateAssistant($flowId: ID!, $modelProvider: String!, $input: String!, $useAgents: Boolean!) {
  createAssistant(flowId: $flowId, modelProvider: $modelProvider, input: $input, useAgents: $useAgents) {
    flow {
      id
      title
      status
    }
    assistant {
      id
      title
      status
      provider {
        name
        type
      }
      flowId
      useAgents
      createdAt
    }
  }
}
"""

CALL_ASSISTANT_MUTATION = """
mutation CallAssistant($flowId: ID!, $assistantId: ID!, $input: String!, $useAgents: Boolean!) {
  callAssistant(flowId: $flowId, assistantId: $assistantId, input: $input, useAgents: $useAgents)
}
"""

STOP_ASSISTANT_MUTATION = """
mutation StopAssistant($flowId: ID!, $assistantId: ID!) {
  stopAssistant(flowId: $flowId, assistantId: $assistantId) {
    id
    title
    status
    provider {
      name
      type
    }
    flowId
    useAgents
    createdAt
  }
}
"""

DELETE_ASSISTANT_MUTATION = """
mutation DeleteAssistant($flowId: ID!, $assistantId: ID!) {
  deleteAssistant(flowId: $flowId, assistantId: $assistantId)
}
"""
