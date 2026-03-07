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

// Auth
export function register(username: string, password: string, email?: string) {
  return request<{ id: string; username: string }>("/api/auth/register", {
    method: "POST",
    body: { username, password, email },
  });
}

export function login(username: string, password: string) {
  return request<{ access_token: string; token_type: string }>("/api/auth/login", {
    method: "POST",
    body: { username, password },
  });
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

// Training

export function startFinetune(config: {
  base_model: string;
  learning_rate: number;
  epochs: number;
  batch_size: number;
  lora_rank: number;
  dataset_id: string;
}) {
  return request<{ job_id: string }>("/api/training/finetune", {
    method: "POST",
    body: config,
  });
}

export function startMerge(config: {
  models: string[];
  method: string;
  interpolation_factor: number;
}) {
  return request<{ job_id: string }>("/api/training/merge", {
    method: "POST",
    body: config,
  });
}

export function startRLHF() {
  return request<{ job_id: string }>("/api/training/rlhf", { method: "POST" });
}

export async function uploadDataset(file: File, type: string) {
  const token = typeof window !== "undefined" ? localStorage.getItem("pub_token") : null;
  const form = new FormData();
  form.append("file", file);
  form.append("type", type);

  const res = await fetch(`${API_BASE}/api/training/upload-dataset`, {
    method: "POST",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: form,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Upload failed: ${res.status}`);
  }

  return res.json();
}

export function getTrainingJobs() {
  return request<{ id: string; type: string; status: string; progress: number; total_steps: number; current_step: number; loss_history: number[]; started_at: string; config: Record<string, unknown> }[]>(
    "/api/training/jobs"
  );
}

export function getJobStatus(id: string) {
  return request<{ id: string; type: string; status: string; progress: number; total_steps: number; current_step: number; loss_history: number[]; started_at: string }>(
    `/api/training/jobs/${id}`
  );
}

export function cancelJob(id: string) {
  return request(`/api/training/jobs/${id}`, { method: "DELETE" });
}

export function exportModel(modelId: string, format: string) {
  return request<{ status: string }>("/api/training/export", {
    method: "POST",
    body: { model_id: modelId, format },
  });
}

export function listDatasets() {
  return request<{ id: string; name: string; size: number; type: string; created_at: string }[]>(
    "/api/training/datasets"
  );
}

export function deleteDataset(id: string) {
  return request(`/api/training/datasets/${id}`, { method: "DELETE" });
}

export function exportChatDataset() {
  return request<{ id: string }>("/api/training/datasets/export-chat", { method: "POST" });
}

export function listModels() {
  return request<{ id: string; name: string; type: string; size_mb: number; created_at: string; dataset_used?: string; is_active: boolean }[]>(
    "/api/training/models"
  );
}

export function setActiveModel(modelId: string) {
  return request(`/api/training/models/${modelId}/activate`, { method: "POST" });
}

export function getFeedbackStats() {
  return request<{ liked: number; disliked: number; pairs: number }>(
    "/api/training/feedback-stats"
  );
}
