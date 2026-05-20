"""Read-only PentAGI GraphQL query constants — v2.0.0 schema compatible."""

PROVIDERS_QUERY = """
query Providers {
  providers {
    name
    type
  }
}
"""

SETTINGS_PROVIDERS_QUERY = """
query SettingsProviders {
  settingsProviders {
    enabled {
      openai
      anthropic
      gemini
      bedrock
      ollama
      custom
      deepseek
      glm
      kimi
      qwen
    }
    userDefined {
      id
      name
      type
      createdAt
      updatedAt
    }
  }
}
"""

FLOWS_QUERY = """
query Flows {
  flows {
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

FLOW_QUERY = """
query Flow($flowId: ID!) {
  flow(flowId: $flowId) {
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

ASSISTANTS_QUERY = """
query Assistants($flowId: ID!) {
  assistants(flowId: $flowId) {
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
    updatedAt
  }
}
"""

TASKS_QUERY = """
query Tasks($flowId: ID!) {
  tasks(flowId: $flowId) {
    id
    title
    status
    input
    result
    flowId
    createdAt
    updatedAt
  }
}
"""

MESSAGE_LOGS_QUERY = """
query MessageLogs($flowId: ID!) {
  messageLogs(flowId: $flowId) {
    id
    type
    message
    thinking
    result
    resultFormat
    flowId
    taskId
    subtaskId
    createdAt
  }
}
"""

TERMINAL_LOGS_QUERY = """
query TerminalLogs($flowId: ID!) {
  terminalLogs(flowId: $flowId) {
    id
    type
    text
    terminal
    flowId
    taskId
    subtaskId
    createdAt
  }
}
"""

AGENT_LOGS_QUERY = """
query AgentLogs($flowId: ID!) {
  agentLogs(flowId: $flowId) {
    id
    initiator
    executor
    task
    result
    flowId
    taskId
    subtaskId
    createdAt
  }
}
"""
