"""Controlled PentAGI GraphQL mutation constants.

Policy/approval checks must happen before these are called.
These constants are schema-aligned for PentAGI v2.0.0 and are covered by mocked tests only.
"""

RESULT_FIELDS = """
    ok
    message
    error
"""

CREATE_FLOW_MUTATION = f"""
mutation CreateFlow($modelProvider: String!, $input: String!) {{
  createFlow(modelProvider: $modelProvider, input: $input) {{
{RESULT_FIELDS}
  }}
}}
"""
PUT_USER_INPUT_MUTATION = f"""
mutation PutUserInput($flowId: ID!, $input: String!) {{
  putUserInput(flowId: $flowId, input: $input) {{
{RESULT_FIELDS}
  }}
}}
"""
STOP_FLOW_MUTATION = f"""
mutation StopFlow($flowId: ID!) {{
  stopFlow(flowId: $flowId) {{
{RESULT_FIELDS}
  }}
}}
"""
FINISH_FLOW_MUTATION = f"""
mutation FinishFlow($flowId: ID!) {{
  finishFlow(flowId: $flowId) {{
{RESULT_FIELDS}
  }}
}}
"""
RENAME_FLOW_MUTATION = f"""
mutation RenameFlow($flowId: ID!, $title: String!) {{
  renameFlow(flowId: $flowId, title: $title) {{
{RESULT_FIELDS}
  }}
}}
"""
DELETE_FLOW_MUTATION = f"""
mutation DeleteFlow($flowId: ID!) {{
  deleteFlow(flowId: $flowId) {{
{RESULT_FIELDS}
  }}
}}
"""
