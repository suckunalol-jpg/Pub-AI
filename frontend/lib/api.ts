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
  return request<{ access_token: string; token_type: string; role: string }>("/api/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

// Chat — SSE streaming types and function

export type StreamPhase =
  | "thinking" | "analyzing" | "planning" | "writing"
  | "coding" | "debugging" | "executing"
  | "reading_file" | "writing_file"
  | "searching_web" | "searching_knowledge"
  | "spawning_agent" | "calling_tool"
  | "reviewing" | "summarizing" | "formatting";

export interface StreamEvent {
  type: "status" | "token" | "code" | "done" | "error";
  data: Record<string, unknown>;
}

export interface StreamCallbacks {
  onStatus?: (phase: StreamPhase, conversationId?: string) => void;
  onToken?: (content: string) => void;
  onCode?: (language: string, content: string) => void;
  onDone?: (messageId: string, model: string, conversationId: string, latencyMs: number) => void;
  onError?: (detail: string) => void;
}

/**
 * Stream a chat message via SSE. Returns an AbortController to cancel the stream.
 */
export function streamMessage(
  conversationId: string | null,
  message: string,
  callbacks: StreamCallbacks
): AbortController {
  const controller = new AbortController();
  const token = typeof window !== "undefined" ? localStorage.getItem("pub_token") : null;

  // Fire-and-forget async — caller controls lifecycle via AbortController
  (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ conversation_id: conversationId, message }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        callbacks.onError?.(err.detail || `Stream failed: ${res.status}`);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        callbacks.onError?.("ReadableStream not supported");
        return;
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Parse complete SSE events from the buffer
        const lines = buffer.split("\n");
        buffer = "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const rawData = line.slice(6);
            try {
              const data = JSON.parse(rawData);
              switch (currentEvent) {
                case "status":
                  callbacks.onStatus?.(
                    data.phase as StreamPhase,
                    data.conversation_id as string | undefined
                  );
                  break;
                case "token":
                  callbacks.onToken?.(data.content as string);
                  break;
                case "code":
                  callbacks.onCode?.(
                    data.language as string,
                    data.content as string
                  );
                  break;
                case "done":
                  callbacks.onDone?.(
                    data.message_id as string,
                    data.model as string,
                    data.conversation_id as string,
                    data.latency_ms as number
                  );
                  break;
                case "error":
                  callbacks.onError?.(data.detail as string);
                  break;
              }
            } catch {
              // Incomplete JSON — put back into buffer
              buffer = line + "\n";
            }
            currentEvent = "";
          } else if (line === "") {
            // Empty line = event boundary, reset
            currentEvent = "";
          } else {
            // Incomplete line — put back into buffer
            buffer += line + "\n";
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // User cancelled — not an error
        return;
      }
      callbacks.onError?.(err instanceof Error ? err.message : "Stream connection failed");
    }
  })();

  return controller;
}

// Chat — non-streaming (legacy)
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

// Agents — see bottom of file for agent API functions

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

// User Management
export function getMe() {
  return request<{ id: string; username: string; email: string | null; role: string }>(
    "/api/auth/me"
  );
}

export function getUsers() {
  return request<{ id: string; username: string; role: string; created_at: string }[]>(
    "/api/auth/users"
  );
}

export function setUserRole(userId: string, role: string) {
  return request<{ detail: string; user_id: string; role: string }>(
    `/api/auth/users/${userId}/role`,
    { method: "PUT", body: { role } }
  );
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

export async function listDatasets() {
  const res = await request<{ datasets: { id: string; name: string; size: number; type: string; created_at: string }[] }>(
    "/api/training/datasets"
  );
  return res.datasets || [];
}

export function deleteDataset(id: string) {
  return request(`/api/training/datasets/${id}`, { method: "DELETE" });
}

export function exportChatDataset() {
  return request<{ id: string }>("/api/training/datasets/export-chat", { method: "POST" });
}

export async function listModels() {
  const res = await request<{ models: { id: string; name: string; type: string; size_mb: number; created_at: string; dataset_used?: string; is_active: boolean }[] }>(
    "/api/training/models"
  );
  return res.models || [];
}

export function setActiveModel(modelId: string) {
  return request(`/api/training/models/${modelId}/activate`, { method: "POST" });
}

export function getFeedbackStats() {
  return request<{ liked: number; disliked: number; pairs: number }>(
    "/api/training/feedback-stats"
  );
}

// Preferences
export function getPreferences() {
  return request<{ theme: string; custom_instructions: string }>(
    "/api/preferences"
  );
}

export function savePreferences(prefs: { theme?: string; custom_instructions?: string }) {
  return request<{ detail: string; theme: string; custom_instructions: string }>(
    "/api/preferences",
    { method: "PUT", body: prefs }
  );
}

// Slash Commands
export interface SlashCommand {
  name: string;
  description: string;
  usage: string;
  type: "local" | "server";
}

export function getSlashCommands() {
  return request<SlashCommand[]>("/api/chat/commands");
}

// File Uploads
export interface UploadResult {
  id: string;
  filename: string;
  url: string;
  content_type: string;
  size: number;
}

export async function uploadFile(file: File): Promise<UploadResult> {
  const token = localStorage.getItem("token");
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/chat/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Upload failed");
  }

  return res.json();
}

// ---------- Agent API ----------

export interface AgentStatus {
  id: string;
  agent_type: string;
  agent_name: string;
  status: string;
  result: Record<string, unknown> | null;
}

export function getAgentStatus(agentId: string) {
  return request<AgentStatus>(`/api/agents/${agentId}`);
}

export function getAgentState(agentId: string) {
  return request<Record<string, unknown>>(`/api/agents/${agentId}/state`);
}

export function listAgents() {
  return request<AgentStatus[]>("/api/agents/list");
}

export function messageAgent(agentId: string, message: string) {
  return request<{ response: string }>(`/api/agents/${agentId}/message`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function spawnAgent(agentType: string, task: string, conversationId?: string) {
  return request<AgentStatus>("/api/agents/spawn", {
    method: "POST",
    body: JSON.stringify({
      agent_type: agentType,
      task,
      conversation_id: conversationId,
    }),
  });
}

export function stopAgent(agentId: string) {
  return request(`/api/agents/${agentId}`, { method: "DELETE" });
}
