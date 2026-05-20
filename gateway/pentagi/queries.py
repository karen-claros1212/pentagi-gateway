"""Read-only PentAGI GraphQL query constants."""

PROVIDERS_QUERY = """
query Providers { providers { id name provider model baseUrl status } }
"""
SETTINGS_PROVIDERS_QUERY = """
query SettingsProviders { settingsProviders { id name provider model baseUrl status } }
"""
FLOWS_QUERY = """
query Flows { flows { id name title description status provider createdAt updatedAt } }
"""
FLOW_QUERY = """
query Flow($flowId: ID!) { flow(flowId: $flowId) { id name title description status provider createdAt updatedAt } }
"""
TASKS_QUERY = """
query Tasks($flowId: ID!) { tasks(flowId: $flowId) { id name title status result createdAt updatedAt } }
"""
MESSAGE_LOGS_QUERY = """
query MessageLogs($flowId: ID!, $limit: Int) { messageLogs(flowId: $flowId, limit: $limit) { id role content createdAt updatedAt } }
"""
TERMINAL_LOGS_QUERY = """
query TerminalLogs($flowId: ID!, $limit: Int) { terminalLogs(flowId: $flowId, limit: $limit) { id content createdAt } }
"""
AGENT_LOGS_QUERY = """
query AgentLogs($flowId: ID!, $limit: Int) { agentLogs(flowId: $flowId, limit: $limit) { id agent content createdAt } }
"""
