export type Bbox = [number, number, number, number];
export type LngLatPair = [number, number];
export type AoiMode = "rectangle" | "polygon";

export interface PolygonGeometry {
  type: "Polygon";
  coordinates: LngLatPair[][];
}

export type JobStatus = "pending" | "running" | "done" | "failed";

export interface HealthResponse {
  status?: string;
  service?: string;
  [key: string]: unknown;
}

export interface AssetSummary {
  key: string;
  title?: string | null;
  media_type?: string | null;
  roles?: string[];
  eo_bands?: string[];
  metadata?: Record<string, unknown>;
}

export interface SearchItem {
  provider: string;
  collection: string;
  item_id: string;
  datetime?: string | null;
  bbox?: number[];
  cloud_cover?: number | null;
  assets?: AssetSummary[];
  metadata?: Record<string, unknown>;
}

export interface SearchResponse {
  items: SearchItem[];
}

export interface JobRecord {
  id: string;
  type: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  requested_by?: string | null;
  output_dir: string;
  config: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  log_path?: string | null;
}

export interface JobCreateResponse {
  job: JobRecord;
}

export interface SearchPayload {
  provider: string;
  collection: string;
  bbox: Bbox;
  geometry?: PolygonGeometry;
  datetime?: string;
  limit: number;
  cloud_cover_lte?: number;
}

export interface PreparePayload {
  provider: string;
  collection: string;
  item_id: string;
  bbox: Bbox;
  geometry?: PolygonGeometry;
  bbox_crs: string;
  bands: string[];
  target_resolution?: number;
  target_crs?: string;
  requested_by?: string;
  output: {
    format: "geotiff";
    purpose: "carto-render";
  };
}

export interface TilejsonPayload {
  provider: string;
  collection: string;
  item_id: string;
  bands: string[];
}

export interface TilejsonResponse {
  provider: string;
  collection: string;
  item_id: string;
  tiles: string[];
  tilejson: Record<string, unknown>;
  bounds?: Bbox | null;
  minzoom?: number | null;
  maxzoom?: number | null;
}

export interface RenderPayload {
  requested_by?: string;
  dry_run: boolean;
  project: {
    project_name: string;
    template_id: string;
    title?: string;
    layers: Array<{
      id: string;
      name: string;
      data_source?: string;
      visible: boolean;
      opacity: number;
    }>;
    fit_to_layers: boolean;
    fit_layer_names: string[];
    fit_padding: number;
    layout_elements?: LayoutElementPosition[];
    export: {
      format: "png" | "jpg" | "pdf";
      dpi: number;
      layout_name?: string;
    };
  };
}

export interface AiChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AiChatPayload {
  messages: AiChatMessage[];
  context?: string;
}

export interface AiChatResponse {
  message: AiChatMessage;
  model: string;
}

export interface LayoutElementPosition {
  element_name: string;
  x: number;
  y: number;
  units: "millimeter" | "centimeter" | "inch";
}

export interface AgentPageContext {
  provider: string;
  collection: string;
  datetime?: string;
  cloud_cover_lte?: number;
  limit: number;
  aoi_mode: AoiMode;
  bbox: Bbox;
  geometry?: PolygonGeometry;
  bands: string[];
  target_resolution?: number;
  target_crs?: string;
  map_title?: string;
  layout_name?: string;
  prepared_dataset_path?: string;
  layout_elements?: LayoutElementPosition[];
}

export type AgentTaskStatus = "queued" | "running" | "waiting_for_user" | "done" | "failed";
export type AgentStepStatus = "pending" | "running" | "done" | "failed";

export interface AgentStep {
  name: string;
  status: AgentStepStatus;
  summary: string;
  started_at?: string | null;
  finished_at?: string | null;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error?: string | null;
}

export interface AgentTask {
  id: string;
  kind: string;
  status: AgentTaskStatus;
  created_at: string;
  updated_at: string;
  message: string;
  map_spec: Record<string, unknown>;
  steps: AgentStep[];
  outputs: Record<string, unknown>;
  error?: string | null;
}

export interface AgentChatPayload {
  messages: AiChatMessage[];
  context?: AgentPageContext;
}

export interface AgentChatResponse {
  message: AiChatMessage;
  model: string;
  task?: AgentTask | null;
  requires_confirmation: boolean;
}

export interface AgentImageSelectionPayload {
  item_id: string;
}
