import type {
  AgentChatPayload,
  AgentChatResponse,
  AgentImageSelectionPayload,
  AgentTask,
  AiChatPayload,
  AiChatResponse,
  CogResolutionPayload,
  CogResolutionResponse,
  HealthResponse,
  JobCreateResponse,
  JobRecord,
  PreparePayload,
  RenderPayload,
  SearchPayload,
  SearchResponse,
  TilejsonPayload,
  TilejsonResponse,
} from "./types";

export const config = {
  dataServiceUrl: trimSlash(
    import.meta.env.VITE_DATA_SERVICE_URL ?? "http://127.0.0.1:8010",
  ),
  cartoWebApiUrl: trimSlash(
    import.meta.env.VITE_CARTO_WEB_API_URL ?? "http://127.0.0.1:8020",
  ),
  cartoEngineUrl: trimSlash(
    import.meta.env.VITE_CARTO_ENGINE_URL ?? "http://127.0.0.1:8000",
  ),
};

function trimSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, {
    headers,
    ...init,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown; error?: unknown };
      detail = String(payload.detail ?? payload.error ?? detail);
    } catch {
      detail = await response.text();
    }
    throw new Error(`${response.status} ${detail}`);
  }

  return (await response.json()) as T;
}

export function getDataHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${config.dataServiceUrl}/health`);
}

export function getCartoWebApiHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${config.cartoWebApiUrl}/health`);
}

export function getCartoHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${config.cartoEngineUrl}/health`);
}

export function searchItems(payload: SearchPayload): Promise<SearchResponse> {
  return requestJson<SearchResponse>(`${config.dataServiceUrl}/api/v1/searches`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function prepareRaster(payload: PreparePayload): Promise<JobCreateResponse> {
  return requestJson<JobCreateResponse>(`${config.dataServiceUrl}/api/v1/prepare-jobs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCogResolutions(payload: CogResolutionPayload): Promise<CogResolutionResponse> {
  return requestJson<CogResolutionResponse>(`${config.dataServiceUrl}/api/v1/cog-resolutions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getPreviewTilejson(payload: TilejsonPayload): Promise<TilejsonResponse> {
  return requestJson<TilejsonResponse>(`${config.dataServiceUrl}/api/v1/tilejson`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDataJob(jobId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`${config.dataServiceUrl}/api/v1/jobs/${jobId}`);
}

export function renderPreview(payload: RenderPayload): Promise<JobCreateResponse> {
  return requestJson<JobCreateResponse>(`${config.cartoEngineUrl}/api/v1/render/preview`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCartoJob(jobId: string): Promise<JobRecord> {
  return requestJson<JobRecord>(`${config.cartoEngineUrl}/api/v1/jobs/${jobId}`);
}

export function sendAiChat(payload: AiChatPayload): Promise<AiChatResponse> {
  return requestJson<AiChatResponse>(`${config.cartoWebApiUrl}/api/v1/ai/chat`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendAgentChat(payload: AgentChatPayload): Promise<AgentChatResponse> {
  return requestJson<AgentChatResponse>(`${config.cartoWebApiUrl}/api/v1/agent/chat`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendExpertAgentChat(payload: AgentChatPayload): Promise<AgentChatResponse> {
  return requestJson<AgentChatResponse>(`${config.cartoWebApiUrl}/api/v1/agent/expert/chat`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAgentTask(taskId: string): Promise<AgentTask> {
  return requestJson<AgentTask>(`${config.cartoWebApiUrl}/api/v1/agent/tasks/${taskId}`);
}

export function selectAgentTaskImage(
  taskId: string,
  payload: AgentImageSelectionPayload,
): Promise<AgentTask> {
  return requestJson<AgentTask>(`${config.cartoWebApiUrl}/api/v1/agent/tasks/${taskId}/select-image`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
