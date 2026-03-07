const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

interface ApiOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

async function request<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {} } = options;

  const token = typeof window !== "undefined" ? localStorage.getItem("pub_token") : null;

  const res = await fetch(`${API_BASE}${endpoint}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed: ${res.status}`);
  }

  return res.json();
}

// Chat
export function sendMessage(conversationId: string | null, message: string) {
  return request<{ content: string; conversation_id: string; message_id: string; model_used: string; tokens_in: number; tokens_out: number; latency_ms: number }>("/api/chat", {
    method: "POST",
    body: { conversation_id: conversationId, message },
  });
}

export function getConversations() {
  return request<{ id: string; title: string; updated_at: string }[]>(
    "/api/chat/conversations"
  );
}

export function getConversation(id: string) {
  return request<{ messages: { role: string; content: string; created_at: string }[] }>(
    `/api/chat/conversations/${id}`
  );
}

export function sendFeedback(messageId: string, rating: 1 | 2) {
  return request("/api/chat/feedback", {
    method: "POST",
    body: { message_id: messageId, rating },
  });
}

// Agents
export function spawnAgent(agentType: string, task: string) {
  return request<{ id: string; status: string }>("/api/agents/spawn", {
    method: "POST",
    body: { agent_type: agentType, task },
  });
}

export function getAgentStatus(id: string) {
  return request<{ id: string; status: string; result?: unknown }>(`/api/agents/${id}`);
}

export function messageAgent(id: string, message: string) {
  return request<{ response: string }>(`/api/agents/${id}/message`, {
    method: "POST",
    body: { message },
  });
}

export function stopAgent(id: string) {
  return request(`/api/agents/${id}`, { method: "DELETE" });
}

// Teams
export function createTeam(name: string, agents: { type: string; role: string }[]) {
  return request<{ id: string }>("/api/teams", {
    method: "POST",
    body: { name, agents },
  });
}

export function getTeamStatus(id: string) {
  return request<{ id: string; agents: unknown[]; status: string }>(`/api/teams/${id}`);
}

// Workflows
export function createWorkflow(name: string, steps: unknown[]) {
  return request<{ id: string }>("/api/workflows", {
    method: "POST",
    body: { name, steps },
  });
}

export function getWorkflows() {
  return request<{ id: string; name: string }[]>("/api/workflows");
}

export function runWorkflow(id: string) {
  return request<{ run_id: string }>(`/api/workflows/${id}/run`, { method: "POST" });
}

export function getWorkflowRun(workflowId: string, runId: string) {
  return request<{ status: string; step_results: unknown[] }>(
    `/api/workflows/${workflowId}/runs/${runId}`
  );
}

// Code Execution
export function executeCode(language: string, code: string) {
  return request<{ output: string; exit_code: number }>("/api/execute", {
    method: "POST",
    body: { language, code },
  });
}

// Knowledge
export function uploadKnowledge(title: string, content: string, sourceType: string) {
  return request<{ id: string }>("/api/knowledge/ingest", {
    method: "POST",
    body: { title, content, source_type: sourceType },
  });
}

export function queryKnowledge(query: string) {
  return request<{ entries: { id: string; content: string; distance: number | null; metadata: Record<string, unknown> }[] }>(
    "/api/knowledge/query",
    { method: "POST", body: { query } }
  );
}

export function getKnowledgeEntries() {
  return request<{ id: string; title: string; source_type: string; created_at: string }[]>(
    "/api/knowledge/entries"
  );
}

// API Keys
export function generateApiKey(name: string, platform: string) {
  return request<{ key: string; id: string }>("/api/auth/api-keys", {
    method: "POST",
    body: { name, platform },
  });
}

export function getApiKeys() {
  return request<
    { id: string; key_prefix: string; name: string; platform: string; is_active: boolean; created_at: string }[]
  >("/api/auth/api-keys");
}

export function revokeApiKey(id: string) {
  return request(`/api/auth/api-keys/${id}`, { method: "DELETE" });
}
