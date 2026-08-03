import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import Ruler from "@scena/react-ruler";
import maplibregl, { GeoJSONSource, Map as MapLibreMap, type StyleSpecification } from "maplibre-gl";
import {
  Bot,
  Check,
  CheckCircle2,
  Compass,
  Crosshair,
  Database,
  Eye,
  FileImage,
  Hand,
  Layers,
  Layers3,
  Loader2,
  Map as MapIcon,
  MousePointer2,
  Pentagon,
  Play,
  Plus,
  RefreshCcw,
  RotateCcw,
  Ruler as RulerIcon,
  Search,
  SendHorizontal,
  Scissors,
  Sparkles,
  Square,
  Trash2,
  ZoomIn,
  ZoomOut,
  XCircle,
} from "lucide-react";
import {
  config,
  getAgentTask,
  getCartoHealth,
  getCartoWebApiHealth,
  getCartoJob,
  getDataHealth,
  getDataJob,
  getPreviewTilejson,
  prepareRaster,
  renderPreview,
  sendAgentChat,
  sendExpertAgentChat,
  selectAgentTaskImage,
  searchItems,
} from "./api";
import type {
  AgentPageContext,
  AgentTask,
  AiChatMessage,
  AoiMode,
  Bbox,
  JobRecord,
  JobStatus,
  LngLatPair,
  PolygonGeometry,
  PreparePayload,
  SearchItem,
  TilejsonResponse,
} from "./types";

interface PreviewRasterLayer {
  itemId: string;
  label: string;
  tilejson: TilejsonResponse;
  bounds?: Bbox;
}

type WorkflowTabId = "data" | "processing" | "cartography";
type BaseLayer = "streets" | "esri-world-imagery";
type LayoutTool = "select" | "pan";
type LayoutPaperId = "a4-landscape" | "a4-portrait" | "custom-145x100";
type LayoutAdornmentId = "north-arrow" | "scale-bar";
type LayoutElementId = "map-frame" | LayoutAdornmentId;
type ResizeHandle = "n" | "e" | "s" | "w" | "ne" | "nw" | "se" | "sw";
type LayoutElementRect = {
  height: number;
  width: number;
  x: number;
  y: number;
};

const previewSourcePrefix = "landsat-preview-source";
const previewLayerPrefix = "landsat-preview-layer";
const tileSize = 256;
const tileOffsetMin = -8;
const tileOffsetMax = 2;
const minMapFrameSizeMm = 24;
const rulerGutterMm = 30;
const offsetTileProtocol = "gyygeo-offset-tile";
const offsetTileImageCache = new Map<string, Promise<ImageBitmap | null>>();
const offsetTileDataCache = new Map<string, Promise<ArrayBuffer>>();
let isOffsetTileProtocolRegistered = false;

const workflowTabs: Array<{
  id: WorkflowTabId;
  label: string;
  icon: typeof Layers3;
}> = [
  { id: "data", label: "数据", icon: Layers3 },
  { id: "processing", label: "处理", icon: Scissors },
  { id: "cartography", label: "制图", icon: FileImage },
];

const layoutPaperPresets: Array<{
  id: LayoutPaperId;
  label: string;
  shortLabel: string;
  widthMm: number;
  heightMm: number;
}> = [
  { id: "custom-145x100", label: "专题横版", shortLabel: "145 x 100", widthMm: 145, heightMm: 100 },
  { id: "a4-landscape", label: "A4 横版", shortLabel: "A4 横", widthMm: 297, heightMm: 210 },
  { id: "a4-portrait", label: "A4 竖版", shortLabel: "A4 竖", widthMm: 210, heightMm: 297 },
];

const cssPixelPerMm = 4.8;
const mapResizeHandles: ResizeHandle[] = ["n", "e", "s", "w", "ne", "nw", "se", "sw"];

const initialBbox: Bbox = [111.60403861995178, 26.215688129123563, 111.61948814387728, 26.226467899170814];
const initialPolygon: LngLatPair[] = [
  [111.60403861995178, 26.215688129123563],
  [111.61948814387728, 26.215688129123563],
  [111.61948814387728, 26.226467899170814],
  [111.60403861995178, 26.226467899170814],
];

export function App() {
  const [provider, setProvider] = useState("mpc");
  const [collection, setCollection] = useState("landsat-c2-l2");
  const [datetime, setDatetime] = useState("2025-03-01/2025-05-31");
  const [cloudCover, setCloudCover] = useState("20");
  const [limit, setLimit] = useState("10");
  const [aoiMode, setAoiMode] = useState<AoiMode>("rectangle");
  const [bbox, setBbox] = useState<Bbox>(initialBbox);
  const [polygonCoordinates, setPolygonCoordinates] = useState<LngLatPair[]>(initialPolygon);
  const [bands, setBands] = useState("red,green,blue");
  const [targetResolution, setTargetResolution] = useState("30");
  const [targetCrs, setTargetCrs] = useState("EPSG:3857");
  const [mapTitle, setMapTitle] = useState("Landsat Map");
  const [layoutName, setLayoutName] = useState("Layout");
  const [dryRun, setDryRun] = useState(false);
  const [searchResults, setSearchResults] = useState<SearchItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<SearchItem | null>(null);
  const [previewLayers, setPreviewLayers] = useState<PreviewRasterLayer[]>([]);
  const [prepareJobId, setPrepareJobId] = useState<string | null>(null);
  const [renderJobId, setRenderJobId] = useState<string | null>(null);
  const [agentImageSelectionTaskId, setAgentImageSelectionTaskId] = useState<string | null>(null);
  const [activeWorkflowTab, setActiveWorkflowTab] = useState<WorkflowTabId>("data");
  const [baseLayer, setBaseLayer] = useState<BaseLayer>("streets");
  const [layoutTool, setLayoutTool] = useState<LayoutTool>("select");
  const [layoutZoom, setLayoutZoom] = useState(100);
  const [layoutMapZoom, setLayoutMapZoom] = useState(14);
  const [layoutTileZoom, setLayoutTileZoom] = useState(0);
  const [paperSize, setPaperSize] = useState<LayoutPaperId>("custom-145x100");
  const [layoutAdornmentIds, setLayoutAdornmentIds] = useState<LayoutAdornmentId[]>([]);

  const dataHealth = useQuery({
    queryKey: ["health", "data"],
    queryFn: getDataHealth,
  });
  const webApiHealth = useQuery({
    queryKey: ["health", "carto-web-api"],
    queryFn: getCartoWebApiHealth,
  });
  const cartoHealth = useQuery({
    queryKey: ["health", "carto"],
    queryFn: getCartoHealth,
  });

  const activeGeometry = useMemo(() => {
    return aoiMode === "polygon" ? polygonGeometry(polygonCoordinates) : undefined;
  }, [aoiMode, polygonCoordinates]);
  const activeBbox = useMemo(() => {
    return activeGeometry ? bboxFromCoordinates(polygonCoordinates) : bbox;
  }, [activeGeometry, bbox, polygonCoordinates]);

  useEffect(() => {
    setPreviewLayers([]);
  }, [bands, collection, provider]);

  const searchMutation = useMutation({
    mutationFn: () =>
      {
        if (aoiMode === "polygon" && !activeGeometry) {
          throw new Error("多边形范围至少需要 3 个顶点。");
        }
        return searchItems({
        provider,
        collection,
        bbox: activeBbox,
        geometry: activeGeometry,
        datetime: datetime.trim() || undefined,
        limit: clampInt(limit, 1, 100, 10),
        cloud_cover_lte: optionalNumber(cloudCover),
        });
    },
    onSuccess: (response) => {
      setSearchResults(response.items);
      setSelectedItem(response.items[0] ?? null);
      setPreviewLayers([]);
      setPrepareJobId(null);
      setRenderJobId(null);
    },
  });

  const previewMutation = useMutation({
    mutationFn: (item: SearchItem) =>
      getPreviewTilejson({
        provider: item.provider || provider,
        collection: item.collection || collection,
        item_id: item.item_id,
        bands: previewBands(splitCsv(bands), item),
      }),
    onSuccess: (response, item) => {
      setSelectedItem(item);
      setPreviewLayers((current) => [
        ...current.filter((layer) => layer.itemId !== item.item_id),
        {
          itemId: item.item_id,
          label: item.item_id,
          tilejson: response,
          bounds: validBbox(response.bounds) ?? validBbox(item.bbox),
        },
      ]);
    },
  });

  const prepareMutation = useMutation({
    mutationFn: (item?: SearchItem) => {
      const itemToPrepare = item ?? selectedItem;
      if (!itemToPrepare) {
        throw new Error("请先选择一个数据项。");
      }
      if (aoiMode === "polygon" && !activeGeometry) {
        throw new Error("多边形范围至少需要 3 个顶点。");
      }
      const payload: PreparePayload = {
        provider,
        collection,
        item_id: itemToPrepare.item_id,
        bbox: activeBbox,
        geometry: activeGeometry,
        bbox_crs: "EPSG:4326",
        bands: splitCsv(bands),
        target_resolution: optionalNumber(targetResolution),
        target_crs: targetCrs.trim() || undefined,
        requested_by: "carto-web",
        output: {
          format: "geotiff",
          purpose: "carto-render",
        },
      };
      return prepareRaster(payload);
    },
    onSuccess: (response) => {
      setPrepareJobId(response.job.id);
      setRenderJobId(null);
    },
  });

  const prepareJob = useQuery({
    queryKey: ["data-job", prepareJobId],
    queryFn: () => getDataJob(prepareJobId!),
    enabled: Boolean(prepareJobId),
    refetchInterval: (query) =>
      isTerminal(query.state.data?.status) ? false : 2000,
  });

  const preparedDatasetPath = useMemo(() => {
    return extractPreparedPath(prepareJob.data);
  }, [prepareJob.data]);

  const renderMutation = useMutation({
    mutationFn: () => {
      const layerPath = dryRun ? undefined : preparedDatasetPath;
      if (!dryRun && !layerPath) {
        throw new Error("准备数据完成后才能真实渲染。");
      }
      return renderPreview({
        requested_by: "carto-web",
        dry_run: dryRun,
        project: {
          project_name: slugName(mapTitle) || "carto-web-map",
          template_id: "default",
          title: mapTitle.trim() || undefined,
          layers: layerPath
            ? [
                {
                  id: "prepared-raster",
                  name: "Prepared Raster",
                  data_source: layerPath,
                  visible: true,
                  opacity: 1,
                },
              ]
            : [],
          fit_to_layers: Boolean(layerPath),
          fit_layer_names: layerPath ? ["Prepared Raster"] : [],
          fit_padding: 0.08,
          export: {
            format: "png",
            dpi: 150,
            layout_name: layoutName.trim() || undefined,
          },
        },
      });
    },
    onSuccess: (response) => {
      setRenderJobId(response.job.id);
    },
  });

  const renderJob = useQuery({
    queryKey: ["carto-job", renderJobId],
    queryFn: () => getCartoJob(renderJobId!),
    enabled: Boolean(renderJobId),
    refetchInterval: (query) =>
      isTerminal(query.state.data?.status) ? false : 2000,
  });

  const agentImageSelectionMutation = useMutation({
    mutationFn: ({ taskId, itemId }: { taskId: string; itemId: string }) =>
      selectAgentTaskImage(taskId, { item_id: itemId }),
    onSuccess: () => {
      setAgentImageSelectionTaskId(null);
    },
  });

  const items = searchResults;
  const canPrepare = Boolean(selectedItem) && !prepareMutation.isPending;
  const canRender =
    dryRun ||
    (prepareJob.data?.status === "done" && Boolean(preparedDatasetPath) && !renderMutation.isPending);
  const handleSearchItemSelect = useCallback(
    (item: SearchItem) => {
      setSelectedItem(item);
      if (!agentImageSelectionTaskId || agentImageSelectionMutation.isPending) {
        return;
      }
      agentImageSelectionMutation.mutate({
        taskId: agentImageSelectionTaskId,
        itemId: item.item_id,
      });
    },
    [agentImageSelectionMutation, agentImageSelectionTaskId],
  );
  const handleAgentTaskUpdate = useCallback((task: AgentTask) => {
    if (isAgentWaitingForImageSelection(task)) {
      setAgentImageSelectionTaskId(task.id);
      return;
    }
    setAgentImageSelectionTaskId((current) => (current === task.id ? null : current));
  }, []);
  const toggleLayoutAdornment = useCallback((adornmentId: LayoutAdornmentId) => {
    setLayoutAdornmentIds((current) =>
      current.includes(adornmentId) ? current.filter((id) => id !== adornmentId) : [...current, adornmentId],
    );
  }, []);
  const agentContext = useMemo<AgentPageContext>(() => {
    return {
      provider,
      collection,
      datetime: datetime.trim() || undefined,
      cloud_cover_lte: optionalNumber(cloudCover),
      limit: clampInt(limit, 1, 100, 10),
      aoi_mode: aoiMode,
      bbox: activeBbox,
      geometry: activeGeometry,
      bands: splitCsv(bands),
      target_resolution: optionalNumber(targetResolution),
      target_crs: targetCrs.trim() || undefined,
      map_title: mapTitle.trim() || undefined,
      layout_name: layoutName.trim() || undefined,
      prepared_dataset_path: preparedDatasetPath,
    };
  }, [
    activeBbox,
    activeGeometry,
    aoiMode,
    bands,
    cloudCover,
    collection,
    datetime,
    layoutName,
    limit,
    mapTitle,
    preparedDatasetPath,
    provider,
    targetCrs,
    targetResolution,
  ]);
  return (
    <main className="shell">
      <section className="workspace">
        <aside className="side-panel">
          <header className="brand-bar">
            <div>
              <p className="eyebrow">GYYGEO</p>
              <h1>AI 制图工作台</h1>
            </div>
            <button
              className="icon-button"
              onClick={() => {
                void dataHealth.refetch();
                void webApiHealth.refetch();
                void cartoHealth.refetch();
              }}
              title="刷新服务状态"
              type="button"
            >
              <RefreshCcw size={18} />
            </button>
          </header>

          <div className="service-grid">
            <ServicePill label="data-service" query={dataHealth} url={config.dataServiceUrl} />
            <ServicePill label="carto-web-api" query={webApiHealth} url={config.cartoWebApiUrl} />
            <ServicePill label="carto-engine" query={cartoHealth} url={config.cartoEngineUrl} />
          </div>

          <div className="workflow-tabs" role="tablist" aria-label="生产流程">
            {workflowTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = tab.id === activeWorkflowTab;

              return (
                <button
                  aria-selected={isActive}
                  className={isActive ? "workflow-tab active" : "workflow-tab"}
                  key={tab.id}
                  onClick={() => setActiveWorkflowTab(tab.id)}
                  role="tab"
                  type="button"
                >
                  <Icon size={16} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {activeWorkflowTab === "data" ? (
            <>
              <form
                className="control-stack"
                onSubmit={(event) => {
                  event.preventDefault();
                  searchMutation.mutate();
                }}
              >
                <div className="field-row">
                  <label>
                    Provider
                    <input value={provider} onChange={(event) => setProvider(event.target.value)} />
                  </label>
                  <label>
                    Collection
                    <input value={collection} onChange={(event) => setCollection(event.target.value)} />
                  </label>
                </div>

                <label>
                  Datetime
                  <input value={datetime} onChange={(event) => setDatetime(event.target.value)} />
                </label>

                <div className="field-row">
                  <label>
                    Cloud {"<="}
                    <input
                      inputMode="decimal"
                      value={cloudCover}
                      onChange={(event) => setCloudCover(event.target.value)}
                    />
                  </label>
                  <label>
                    Limit
                    <input
                      inputMode="numeric"
                      value={limit}
                      onChange={(event) => setLimit(event.target.value)}
                    />
                  </label>
                </div>

                <AoiInputs
                  mode={aoiMode}
                  bbox={bbox}
                  polygon={polygonCoordinates}
                  onModeChange={setAoiMode}
                  onBboxChange={setBbox}
                  onPolygonChange={setPolygonCoordinates}
                />

                <button className="primary-button" type="submit" disabled={searchMutation.isPending}>
                  {searchMutation.isPending ? <Loader2 className="spin" size={18} /> : <Search size={18} />}
                  搜索数据
                </button>
              </form>

              <div className="section-block">
                <div className="section-title">
                  <Database size={17} />
                  <span>检索结果</span>
                </div>
                <div className="item-list">
                  {items.length === 0 ? (
                    <div className="empty-state">暂无数据项</div>
                  ) : (
                    items.map((item) => {
                      const isSelected = selectedItem?.item_id === item.item_id;
                      const isPreviewed = previewLayers.some((layer) => layer.itemId === item.item_id);
                      const isPreviewLoading =
                        previewMutation.isPending && previewMutation.variables?.item_id === item.item_id;
                      return (
                        <div key={item.item_id} className={`item-card ${isSelected ? "selected" : ""}`}>
                          <button className="item-card-main" type="button" onClick={() => handleSearchItemSelect(item)}>
                            <span>{item.item_id}</span>
                            <small>{formatItemMeta(item)}</small>
                          </button>
                          <button
                            className={`item-preview-button ${isPreviewed ? "active" : ""}`}
                            type="button"
                            disabled={previewMutation.isPending}
                            onClick={() => {
                              setSelectedItem(item);
                              if (isPreviewed) {
                                setPreviewLayers((current) =>
                                  current.filter((layer) => layer.itemId !== item.item_id),
                                );
                              } else {
                                previewMutation.mutate(item);
                              }
                            }}
                            aria-label={isPreviewed ? "移除影像预览" : "预览影像"}
                            title={isPreviewed ? "移除影像预览" : "预览影像"}
                          >
                            {isPreviewLoading ? (
                              <Loader2 className="spin" size={15} />
                            ) : (
                              <Eye className={isPreviewed ? "filled-eye" : ""} size={16} />
                            )}
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
                {agentImageSelectionTaskId ? (
                  <div className="empty-state">请选择一景影像继续专家制图任务。</div>
                ) : null}
                {searchMutation.error ? <ErrorText error={searchMutation.error} /> : null}
                {agentImageSelectionMutation.error ? <ErrorText error={agentImageSelectionMutation.error} /> : null}
                {previewMutation.error ? <ErrorText error={previewMutation.error} /> : null}
              </div>

              <div className="control-stack">
                <div className="field-row">
                  <label>
                    Bands
                    <input value={bands} onChange={(event) => setBands(event.target.value)} />
                  </label>
                  <label>
                    Resolution
                    <input
                      inputMode="decimal"
                      value={targetResolution}
                      onChange={(event) => setTargetResolution(event.target.value)}
                    />
                  </label>
                </div>
                <label>
                  Target CRS
                  <input value={targetCrs} onChange={(event) => setTargetCrs(event.target.value)} />
                </label>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={!canPrepare}
                  onClick={() => prepareMutation.mutate(undefined)}
                >
                  {prepareMutation.isPending ? <Loader2 className="spin" size={18} /> : <Database size={18} />}
                  准备数据
                </button>
                {prepareMutation.error ? <ErrorText error={prepareMutation.error} /> : null}
                <JobLine job={prepareJob.data} loading={prepareJob.isFetching} label="data job" />
              </div>

              <div className="control-stack">
                <label>
                  Map Title
                  <input value={mapTitle} onChange={(event) => setMapTitle(event.target.value)} />
                </label>
                <div className="field-row">
                  <label>
                    Layout
                    <input value={layoutName} onChange={(event) => setLayoutName(event.target.value)} />
                  </label>
                  <label className="toggle-field">
                    <input
                      type="checkbox"
                      checked={dryRun}
                      onChange={(event) => setDryRun(event.target.checked)}
                    />
                    Dry run
                  </label>
                </div>
                <button
                  className="primary-button"
                  type="button"
                  disabled={!canRender || renderMutation.isPending}
                  onClick={() => renderMutation.mutate()}
                >
                  {renderMutation.isPending ? <Loader2 className="spin" size={18} /> : <MapIcon size={18} />}
                  生成地图
                </button>
                {renderMutation.error ? <ErrorText error={renderMutation.error} /> : null}
                <JobLine job={renderJob.data} loading={renderJob.isFetching} label="carto job" />
              </div>
            </>
          ) : null}

          {activeWorkflowTab === "processing" ? (
            <div className="empty-state processing-empty">处理工具待接入</div>
          ) : null}

          {activeWorkflowTab === "cartography" ? (
            <CartographyWorkspace
              activeLayoutAdornmentIds={layoutAdornmentIds}
              baseLayer={baseLayer}
              layoutMapZoom={layoutMapZoom}
              layoutTileZoom={layoutTileZoom}
              layoutTool={layoutTool}
              layoutZoom={layoutZoom}
              onBaseLayerChange={setBaseLayer}
              onLayoutMapZoomChange={setLayoutMapZoom}
              onLayoutTileZoomChange={setLayoutTileZoom}
              onLayoutToolChange={setLayoutTool}
              onLayoutZoomChange={setLayoutZoom}
              onPaperSizeChange={setPaperSize}
              onToggleLayoutAdornment={toggleLayoutAdornment}
              paperSize={paperSize}
            />
          ) : null}
        </aside>

        <section className="map-stage">
          {activeWorkflowTab === "cartography" ? (
            <LayoutMapPanel
              baseLayer={baseLayer}
              layoutAdornmentIds={layoutAdornmentIds}
              layoutMapZoom={layoutMapZoom}
              layoutTileZoom={layoutTileZoom}
              layoutTool={layoutTool}
              layoutZoom={layoutZoom}
              paperSize={paperSize}
              previewLayers={previewLayers}
              onLayoutMapZoomChange={setLayoutMapZoom}
            />
          ) : (
            <MapPanel
              baseLayer={baseLayer}
              mode={aoiMode}
              bbox={bbox}
              polygon={polygonCoordinates}
              previewLayers={previewLayers}
              onBaseLayerChange={setBaseLayer}
              onModeChange={setAoiMode}
              onBboxChange={setBbox}
              onPolygonChange={setPolygonCoordinates}
            />
          )}
        </section>
      <ChatPanel
        context={agentContext}
        onSearchResults={(nextItems) => {
          setSearchResults(nextItems);
          setSelectedItem(nextItems[0] ?? null);
          setPreviewLayers([]);
          setPrepareJobId(null);
          setRenderJobId(null);
        }}
        onTaskUpdate={handleAgentTaskUpdate}
      />
      </section>
    </main>
  );
}

function ServicePill({
  label,
  query,
  url,
}: {
  label: string;
  query: ReturnType<typeof useQuery<unknown, Error>>;
  url: string;
}) {
  const ok = query.isSuccess;
  return (
    <div className={`service-pill ${ok ? "ok" : query.isError ? "bad" : ""}`}>
      {ok ? <CheckCircle2 size={16} /> : query.isError ? <XCircle size={16} /> : <Loader2 className="spin" size={16} />}
      <div>
        <strong>{label}</strong>
        <span>{url}</span>
      </div>
    </div>
  );
}

function AoiInputs({
  mode,
  bbox,
  polygon,
  onModeChange,
  onBboxChange,
  onPolygonChange,
}: {
  mode: AoiMode;
  bbox: Bbox;
  polygon: LngLatPair[];
  onModeChange: (mode: AoiMode) => void;
  onBboxChange: (bbox: Bbox) => void;
  onPolygonChange: (polygon: LngLatPair[]) => void;
}) {
  const rectangleLabels = ["西界 xmin", "南界 ymin", "东界 xmax", "北界 ymax"];
  return (
    <div className="aoi-control">
      <div className="segmented-control" aria-label="范围类型">
        <button
          className={mode === "rectangle" ? "active" : ""}
          type="button"
          onClick={() => onModeChange("rectangle")}
        >
          <Square size={15} />
          矩形
        </button>
        <button
          className={mode === "polygon" ? "active" : ""}
          type="button"
          onClick={() => onModeChange("polygon")}
        >
          <Pentagon size={15} />
          多边形
        </button>
      </div>

      {mode === "rectangle" ? (
        <div className="bbox-grid">
          {bbox.map((value, index) => (
            <label key={rectangleLabels[index]}>
              {rectangleLabels[index]}
              <input
                inputMode="decimal"
                value={String(value)}
                onChange={(event) => {
                  const next = [...bbox] as Bbox;
                  next[index] = Number(event.target.value);
                  onBboxChange(normalizeBbox(next));
                }}
              />
            </label>
          ))}
        </div>
      ) : (
        <div className="polygon-editor">
          <div className="polygon-summary">
            <span>{polygon.length} 个顶点</span>
            <span>外包矩形 {bboxFromCoordinates(polygon).map(formatCoord).join(", ")}</span>
          </div>
          <div className="vertex-list">
            {polygon.map((coordinate, index) => (
              <div className="vertex-row" key={index}>
                <span className="vertex-index">{index + 1}</span>
                <label>
                  经度
                  <input
                    inputMode="decimal"
                    value={String(coordinate[0])}
                    onChange={(event) => {
                      const next = polygon.map((point) => [...point] as LngLatPair);
                      next[index][0] = Number(event.target.value);
                      onPolygonChange(next);
                    }}
                  />
                </label>
                <label>
                  纬度
                  <input
                    inputMode="decimal"
                    value={String(coordinate[1])}
                    onChange={(event) => {
                      const next = polygon.map((point) => [...point] as LngLatPair);
                      next[index][1] = Number(event.target.value);
                      onPolygonChange(next);
                    }}
                  />
                </label>
                <button
                  className="mini-icon-button"
                  type="button"
                  onClick={() => onPolygonChange(polygon.filter((_, pointIndex) => pointIndex !== index))}
                  title="删除顶点"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
          <button
            className="secondary-button"
            type="button"
            onClick={() => onPolygonChange([...polygon, polygon[polygon.length - 1] ?? bboxCenter(bbox)])}
          >
            <Plus size={16} />
            添加顶点
          </button>
        </div>
      )}
    </div>
  );
}

function CartographyWorkspace({
  activeLayoutAdornmentIds,
  baseLayer,
  layoutMapZoom,
  layoutTileZoom,
  layoutTool,
  layoutZoom,
  onBaseLayerChange,
  onLayoutMapZoomChange,
  onLayoutTileZoomChange,
  onLayoutToolChange,
  onLayoutZoomChange,
  onPaperSizeChange,
  onToggleLayoutAdornment,
  paperSize,
}: {
  activeLayoutAdornmentIds: LayoutAdornmentId[];
  baseLayer: BaseLayer;
  layoutMapZoom: number;
  layoutTileZoom: number;
  layoutTool: LayoutTool;
  layoutZoom: number;
  onBaseLayerChange: (baseLayer: BaseLayer) => void;
  onLayoutMapZoomChange: (zoom: number) => void;
  onLayoutTileZoomChange: (zoom: number) => void;
  onLayoutToolChange: (tool: LayoutTool) => void;
  onLayoutZoomChange: (zoom: number) => void;
  onPaperSizeChange: (paperId: LayoutPaperId) => void;
  onToggleLayoutAdornment: (adornmentId: LayoutAdornmentId) => void;
  paperSize: LayoutPaperId;
}) {
  const setLayoutZoom = (zoom: number) => onLayoutZoomChange(clampNumber(zoom, 50, 180));
  const setMapZoom = (zoom: number) => onLayoutMapZoomChange(Math.round(clampNumber(zoom, 2, 19)));
  const minTileOffset = Math.max(tileOffsetMin, -layoutMapZoom);
  const setTileZoom = (zoom: number) => onLayoutTileZoomChange(Math.round(clampNumber(zoom, minTileOffset, tileOffsetMax)));
  const tileOffsetLabel = `Z${layoutTileZoom > 0 ? `+${layoutTileZoom}` : layoutTileZoom}`;
  const adornments: Array<{ id: LayoutAdornmentId; label: string; meta: string; icon: typeof Compass }> = [
    { id: "north-arrow", label: "指北针", meta: "插入地图", icon: Compass },
    { id: "scale-bar", label: "比例尺", meta: "插入地图", icon: RulerIcon },
  ];

  return (
    <div className="cartography-workspace">
      <section className="cartography-panel">
        <div className="section-title">
          <FileImage size={17} />
          <span>版面导航</span>
        </div>

        <div className="layout-tool-grid">
          <button
            className={layoutTool === "select" ? "layout-tool-button active" : "layout-tool-button"}
            onClick={() => onLayoutToolChange("select")}
            type="button"
          >
            <MousePointer2 size={16} />
            <span>选择</span>
          </button>
          <button
            className={layoutTool === "pan" ? "layout-tool-button active" : "layout-tool-button"}
            onClick={() => onLayoutToolChange("pan")}
            type="button"
          >
            <Hand size={16} />
            <span>平移纸张</span>
          </button>
        </div>

        <div className="layout-zoom-row">
          <button aria-label="缩小纸张" onClick={() => setLayoutZoom(layoutZoom - 10)} type="button">
            <ZoomOut size={16} />
          </button>
          <input
            aria-label="纸张缩放"
            max="180"
            min="50"
            onChange={(event) => setLayoutZoom(Number(event.currentTarget.value))}
            type="range"
            value={layoutZoom}
          />
          <button aria-label="放大纸张" onClick={() => setLayoutZoom(layoutZoom + 10)} type="button">
            <ZoomIn size={16} />
          </button>
          <strong>{layoutZoom}%</strong>
        </div>

        <button className="layout-reset-view" onClick={() => setLayoutZoom(100)} type="button">
          <RotateCcw size={16} />
          <span>缩放到 100%</span>
        </button>

        <div className="layout-tile-zoom-row">
          <span>地图缩放</span>
          <button aria-label="缩小图框内地图" onClick={() => setMapZoom(layoutMapZoom - 1)} type="button">
            <ZoomOut size={16} />
          </button>
          <input
            aria-label="图框内地图缩放"
            max="19"
            min="2"
            onChange={(event) => setMapZoom(Number(event.currentTarget.value))}
            step="1"
            type="number"
            value={layoutMapZoom}
          />
          <button aria-label="放大图框内地图" onClick={() => setMapZoom(layoutMapZoom + 1)} type="button">
            <ZoomIn size={16} />
          </button>
        </div>

        <div className="layout-tile-zoom-row">
          <span>瓦片级数</span>
          <button
            aria-label="降低瓦片级数"
            onClick={() => setTileZoom(layoutTileZoom - 1)}
            title="降低取样级数，地理范围不变"
            type="button"
          >
            <ZoomOut size={16} />
          </button>
          <input aria-label="瓦片级数" readOnly title={tileOffsetLabel} type="text" value={tileOffsetLabel} />
          <button
            aria-label="提高瓦片级数"
            onClick={() => setTileZoom(layoutTileZoom + 1)}
            title="提高取样级数，地理范围不变"
            type="button"
          >
            <ZoomIn size={16} />
          </button>
        </div>
      </section>

      <section className="cartography-panel">
        <div className="section-title">
          <Layers size={17} />
          <span>底图</span>
        </div>
        <div className="base-layer-grid">
          <button
            className={baseLayer === "streets" ? "base-layer-button active" : "base-layer-button"}
            onClick={() => onBaseLayerChange("streets")}
            type="button"
          >
            <span>街道底图</span>
            {baseLayer === "streets" ? <Check size={15} /> : null}
          </button>
          <button
            className={baseLayer === "esri-world-imagery" ? "base-layer-button active" : "base-layer-button"}
            onClick={() => onBaseLayerChange("esri-world-imagery")}
            type="button"
          >
            <span>Esri World Imagery</span>
            {baseLayer === "esri-world-imagery" ? <Check size={15} /> : null}
          </button>
        </div>
      </section>

      <section className="cartography-panel">
        <div className="section-title">
          <FileImage size={17} />
          <span>纸张尺寸</span>
        </div>
        <div className="paper-size-grid">
          {layoutPaperPresets.map((paper) => (
            <button
              className={paperSize === paper.id ? "paper-size-button active" : "paper-size-button"}
              key={paper.id}
              onClick={() => onPaperSizeChange(paper.id)}
              type="button"
            >
              <span>{paper.shortLabel}</span>
              <strong>
                {paper.widthMm} x {paper.heightMm} mm
              </strong>
            </button>
          ))}
        </div>
      </section>

      <section className="cartography-panel">
        <div className="section-title">
          <Compass size={17} />
          <span>地图整饰</span>
        </div>
        <div className="layout-insert-tools">
          {adornments.map((adornment) => {
            const Icon = adornment.icon;
            const isActive = activeLayoutAdornmentIds.includes(adornment.id);
            return (
              <button
                aria-pressed={isActive}
                className={isActive ? "layout-insert-item active" : "layout-insert-item"}
                key={adornment.id}
                onClick={() => onToggleLayoutAdornment(adornment.id)}
                type="button"
              >
                <Icon size={18} />
                <span>{adornment.meta}</span>
                <strong>{adornment.label}</strong>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function MapPanel({
  baseLayer,
  mode,
  bbox,
  polygon,
  previewLayers,
  onBaseLayerChange,
  onModeChange,
  onBboxChange,
  onPolygonChange,
}: {
  baseLayer: BaseLayer;
  mode: AoiMode;
  bbox: Bbox;
  polygon: LngLatPair[];
  previewLayers: PreviewRasterLayer[];
  onBaseLayerChange: (baseLayer: BaseLayer) => void;
  onModeChange: (mode: AoiMode) => void;
  onBboxChange: (bbox: Bbox) => void;
  onPolygonChange: (polygon: LngLatPair[]) => void;
}) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const drawStartRef = useRef<[number, number] | null>(null);
  const [drawingMode, setDrawingMode] = useState<AoiMode | null>(null);
  const [isLayerMenuOpen, setIsLayerMenuOpen] = useState(false);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: createMapStyle(baseLayer),
      center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
      zoom: 14,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      syncAoiLayer(map, mode, bbox, polygon);
      syncPreviewRasterLayers(map, previewLayers, false);
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    map.setStyle(createMapStyle(baseLayer));
    const syncLayers = () => {
      syncPreviewRasterLayers(map, previewLayers, false);
      syncAoiLayer(map, mode, bbox, polygon);
    };
    map.once("styledata", syncLayers);
    return () => {
      map.off("styledata", syncLayers);
    };
  }, [baseLayer]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) {
      return;
    }
    syncAoiLayer(map, mode, bbox, polygon);
  }, [bbox, mode, polygon]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    const syncPreviewLayers = () => syncPreviewRasterLayers(map, previewLayers, true);

    if (map.isStyleLoaded()) {
      syncPreviewLayers();
      return;
    }

    map.once("load", syncPreviewLayers);
    return () => {
      map.off("load", syncPreviewLayers);
    };
  }, [previewLayers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    map.getCanvas().style.cursor = drawingMode ? "crosshair" : "";
    if (drawingMode) {
      map.dragPan.disable();
    } else {
      map.dragPan.enable();
      drawStartRef.current = null;
    }

    const onMouseDown = (event: maplibregl.MapMouseEvent) => {
      if (drawingMode !== "rectangle") {
        return;
      }
      drawStartRef.current = [event.lngLat.lng, event.lngLat.lat];
    };
    const onMouseMove = (event: maplibregl.MapMouseEvent) => {
      const start = drawStartRef.current;
      if (drawingMode !== "rectangle" || !start) {
        return;
      }
      onBboxChange(normalizeBbox([start[0], start[1], event.lngLat.lng, event.lngLat.lat]));
    };
    const onMouseUp = (event: maplibregl.MapMouseEvent) => {
      const start = drawStartRef.current;
      if (drawingMode !== "rectangle" || !start) {
        return;
      }
      onBboxChange(normalizeBbox([start[0], start[1], event.lngLat.lng, event.lngLat.lat]));
      drawStartRef.current = null;
      setDrawingMode(null);
    };
    const onClick = (event: maplibregl.MapMouseEvent) => {
      if (drawingMode !== "polygon") {
        return;
      }
      onPolygonChange([...polygon, [event.lngLat.lng, event.lngLat.lat]]);
    };

    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("mouseup", onMouseUp);
    map.on("click", onClick);
    return () => {
      map.off("mousedown", onMouseDown);
      map.off("mousemove", onMouseMove);
      map.off("mouseup", onMouseUp);
      map.off("click", onClick);
    };
  }, [drawingMode, onBboxChange, onPolygonChange, polygon]);

  const currentBounds = mode === "polygon" && polygon.length >= 3 ? bboxFromCoordinates(polygon) : bbox;

  return (
    <div className="map-panel">
      <div ref={mapContainerRef} className="map-container" />
      <div className="map-tools">
        <button
          className={`tool-button ${mode === "rectangle" ? "active" : ""}`}
          type="button"
          onClick={() => {
            onModeChange("rectangle");
            setDrawingMode((value) => (value === "rectangle" ? null : "rectangle"));
          }}
          title="绘制矩形范围"
        >
          <Square size={17} />
          <span>矩形</span>
        </button>
        <button
          className={`tool-button ${mode === "polygon" ? "active" : ""}`}
          type="button"
          onClick={() => {
            onModeChange("polygon");
            onPolygonChange([]);
            setDrawingMode("polygon");
          }}
          title="绘制多边形范围"
        >
          <Pentagon size={17} />
          <span>多边形</span>
        </button>
        {drawingMode === "polygon" ? (
          <button
            className="tool-button"
            type="button"
            disabled={polygon.length < 3}
            onClick={() => setDrawingMode(null)}
            title="完成多边形"
          >
            <CheckCircle2 size={17} />
            <span>完成</span>
          </button>
        ) : null}
        {mode === "polygon" && polygon.length ? (
          <button
            className="tool-button"
            type="button"
            onClick={() => onPolygonChange([])}
            title="清除多边形"
          >
            <Trash2 size={17} />
            <span>清除</span>
          </button>
        ) : null}
        <button
          className="tool-button"
          type="button"
          onClick={() => setDrawingMode(null)}
          title="停止绘制"
        >
          <Crosshair size={17} />
          <span>停止</span>
        </button>
        <button
          className="tool-button"
          type="button"
          onClick={() => mapRef.current?.fitBounds(currentBounds, { padding: 80, duration: 500 })}
          title="定位范围"
        >
          <Play size={17} />
          <span>定位</span>
        </button>
        <div className="map-layer-menu-shell">
          <button
            aria-expanded={isLayerMenuOpen}
            className="tool-button icon-only"
            onClick={() => setIsLayerMenuOpen((open) => !open)}
            title="切换底图"
            type="button"
          >
            <Layers size={17} />
          </button>
          {isLayerMenuOpen ? (
            <div className="map-layer-menu" role="menu">
              <button
                onClick={() => {
                  onBaseLayerChange("streets");
                  setIsLayerMenuOpen(false);
                }}
                role="menuitem"
                type="button"
              >
                <span>街道底图</span>
                {baseLayer === "streets" ? <Check size={15} /> : null}
              </button>
              <button
                onClick={() => {
                  onBaseLayerChange("esri-world-imagery");
                  setIsLayerMenuOpen(false);
                }}
                role="menuitem"
                type="button"
              >
                <span>Esri World Imagery</span>
                {baseLayer === "esri-world-imagery" ? <Check size={15} /> : null}
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function LayoutMapPanel({
  baseLayer,
  layoutAdornmentIds,
  layoutMapZoom,
  layoutTileZoom,
  layoutTool,
  layoutZoom,
  paperSize,
  previewLayers,
  onLayoutMapZoomChange,
}: {
  baseLayer: BaseLayer;
  layoutAdornmentIds: LayoutAdornmentId[];
  layoutMapZoom: number;
  layoutTileZoom: number;
  layoutTool: LayoutTool;
  layoutZoom: number;
  paperSize: LayoutPaperId;
  previewLayers: PreviewRasterLayer[];
  onLayoutMapZoomChange: (zoom: number) => void;
}) {
  const boardRef = useRef<HTMLDivElement | null>(null);
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const panStartRef = useRef<{
    clientX: number;
    clientY: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const paper = getLayoutPaperPreset(paperSize);
  const [elementRects, setElementRects] = useState(() => createInitialElementRects(paper));
  const [paperOffset, setPaperOffset] = useState({ x: 0, y: 0 });
  const [boardScroll, setBoardScroll] = useState({ left: 0, top: 0 });
  const [selectedElementId, setSelectedElementId] = useState<LayoutElementId | null>(null);
  const zoomScale = layoutZoom / 100;
  const pageWidthPx = mmToCssPx(paper.widthMm, zoomScale);
  const pageHeightPx = mmToCssPx(paper.heightMm, zoomScale);
  const rulerGutterPx = mmToCssPx(rulerGutterMm, zoomScale);
  const rulerZoom = cssPixelPerMm * zoomScale;
  const rulerScrollLeftMm = (boardScroll.left - paperOffset.x) / rulerZoom - rulerGutterMm;
  const rulerScrollTopMm = (boardScroll.top - paperOffset.y) / rulerZoom - rulerGutterMm;
  const center = bboxCenter(initialBbox);

  useEffect(() => {
    setPaperOffset({ x: 0, y: 0 });
    setSelectedElementId(null);
    setElementRects(createInitialElementRects(paper));
  }, [paperSize]);

  useEffect(() => {
    if (layoutTool !== "select") {
      setSelectedElementId(null);
    }
  }, [layoutTool]);

  useEffect(() => {
    if (selectedElementId && selectedElementId !== "map-frame" && !layoutAdornmentIds.includes(selectedElementId)) {
      setSelectedElementId(null);
    }
  }, [layoutAdornmentIds, selectedElementId]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      attributionControl: false,
      container: mapContainerRef.current,
      center,
      maxZoom: 19,
      minZoom: 2,
      pitch: 0,
      style: createMapStyle(baseLayer, layoutTileZoom),
      zoom: layoutMapZoom,
    });

    mapRef.current = map;
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.on("load", () => syncPreviewRasterLayers(map, previewLayers, false));
    map.on("moveend", () => {
      const nextZoom = Math.round(map.getZoom());
      onLayoutMapZoomChange(nextZoom);
    });

    const resizeObserver = new ResizeObserver(() => map.resize());
    resizeObserver.observe(mapContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    map.setStyle(createMapStyle(baseLayer, layoutTileZoom));
    const syncLayers = () => syncPreviewRasterLayers(map, previewLayers, false);
    map.once("styledata", syncLayers);
    return () => {
      map.off("styledata", syncLayers);
    };
  }, [baseLayer, layoutTileZoom]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    if (Math.abs(map.getZoom() - layoutMapZoom) > 0.05) {
      map.zoomTo(layoutMapZoom, { duration: 200 });
    }
  }, [layoutMapZoom]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }
    const syncPreviewLayers = () => syncPreviewRasterLayers(map, previewLayers, false);
    if (map.isStyleLoaded()) {
      syncPreviewLayers();
      return;
    }
    map.once("load", syncPreviewLayers);
    return () => {
      map.off("load", syncPreviewLayers);
    };
  }, [previewLayers]);

  useEffect(() => {
    mapRef.current?.resize();
  }, [elementRects, layoutZoom, paperSize]);

  const handleBoardScroll = () => {
    const board = boardRef.current;
    if (!board) {
      return;
    }
    setBoardScroll({ left: board.scrollLeft, top: board.scrollTop });
  };

  const beginBoardPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (layoutTool !== "pan") {
      return;
    }
    panStartRef.current = {
      clientX: event.clientX,
      clientY: event.clientY,
      offsetX: paperOffset.x,
      offsetY: paperOffset.y,
    };
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const moveBoardPan = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = panStartRef.current;
    if (!start || layoutTool !== "pan") {
      return;
    }
    setPaperOffset({
      x: start.offsetX + event.clientX - start.clientX,
      y: start.offsetY + event.clientY - start.clientY,
    });
  };

  const stopBoardPan = () => {
    panStartRef.current = null;
  };

  const beginPageSelection = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (layoutTool !== "select" || event.target !== event.currentTarget) {
      return;
    }
    setSelectedElementId(null);
  };

  const beginElementDrag = (elementId: LayoutElementId, event: ReactPointerEvent<HTMLDivElement>) => {
    if (layoutTool !== "select") {
      return;
    }
    const startRect = elementRects[elementId];
    const startClientX = event.clientX;
    const startClientY = event.clientY;

    setSelectedElementId(elementId);
    event.preventDefault();
    event.stopPropagation();

    const handleMove = (moveEvent: PointerEvent) => {
      const deltaX = (moveEvent.clientX - startClientX) / (cssPixelPerMm * zoomScale);
      const deltaY = (moveEvent.clientY - startClientY) / (cssPixelPerMm * zoomScale);

      setElementRects((current) => ({
        ...current,
        [elementId]: {
          ...current[elementId],
          x: clampNumber(startRect.x + deltaX, 0, paper.widthMm - startRect.width),
          y: clampNumber(startRect.y + deltaY, 0, paper.heightMm - startRect.height),
        },
      }));
    };

    const stopMove = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", stopMove);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", stopMove);
  };

  const beginMapResize = (handle: ResizeHandle, event: ReactPointerEvent<HTMLSpanElement>) => {
    if (layoutTool !== "select") {
      return;
    }

    const startRect = elementRects["map-frame"];
    const startClientX = event.clientX;
    const startClientY = event.clientY;

    setSelectedElementId("map-frame");
    event.preventDefault();
    event.stopPropagation();

    const handleMove = (moveEvent: PointerEvent) => {
      const deltaX = (moveEvent.clientX - startClientX) / (cssPixelPerMm * zoomScale);
      const deltaY = (moveEvent.clientY - startClientY) / (cssPixelPerMm * zoomScale);
      let nextX = startRect.x;
      let nextY = startRect.y;
      let nextWidth = startRect.width;
      let nextHeight = startRect.height;

      if (handle.includes("w")) {
        const right = startRect.x + startRect.width;
        nextX = clampNumber(startRect.x + deltaX, 0, right - minMapFrameSizeMm);
        nextWidth = right - nextX;
      }

      if (handle.includes("e")) {
        nextWidth = clampNumber(startRect.width + deltaX, minMapFrameSizeMm, paper.widthMm - startRect.x);
      }

      if (handle.includes("n")) {
        const bottom = startRect.y + startRect.height;
        nextY = clampNumber(startRect.y + deltaY, 0, bottom - minMapFrameSizeMm);
        nextHeight = bottom - nextY;
      }

      if (handle.includes("s")) {
        nextHeight = clampNumber(startRect.height + deltaY, minMapFrameSizeMm, paper.heightMm - startRect.y);
      }

      setElementRects((current) => ({
        ...current,
        "map-frame": {
          height: nextHeight,
          width: nextWidth,
          x: nextX,
          y: nextY,
        },
      }));
    };

    const stopResize = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", stopResize);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", stopResize);
  };

  return (
    <div className={`layout-workspace ${layoutTool}-mode`}>
      <div className="layout-ruler-corner" aria-hidden="true" />
      <div className="layout-ruler layout-ruler-top" aria-hidden="true">
        <Ruler
          backgroundColor="#f6f8f9"
          direction="end"
          font="12px sans-serif"
          lineColor="#667a84"
          negativeRuler={false}
          range={[0, paper.widthMm]}
          scrollPos={rulerScrollLeftMm}
          segment={10}
          textColor="#54646d"
          textFormat={(scale) => `${scale}`}
          textOffset={[2, 2]}
          type="horizontal"
          unit={10}
          zoom={rulerZoom}
        />
      </div>
      <div className="layout-ruler layout-ruler-left" aria-hidden="true">
        <Ruler
          backgroundColor="#f6f8f9"
          direction="end"
          font="12px sans-serif"
          lineColor="#667a84"
          negativeRuler={false}
          range={[0, paper.heightMm]}
          scrollPos={rulerScrollTopMm}
          segment={10}
          textColor="#54646d"
          textFormat={(scale) => `${scale}`}
          textOffset={[2, 1]}
          type="vertical"
          unit={10}
          zoom={rulerZoom}
        />
      </div>
      <div
        className="layout-board"
        onPointerCancel={stopBoardPan}
        onPointerDown={beginBoardPan}
        onPointerMove={moveBoardPan}
        onPointerUp={stopBoardPan}
        onScroll={handleBoardScroll}
        ref={boardRef}
      >
        <div
          className="layout-canvas"
          style={{
            padding: rulerGutterPx,
            transform: `translate(${paperOffset.x}px, ${paperOffset.y}px)`,
          }}
        >
          <div className="layout-page" onPointerDown={beginPageSelection} style={{ height: pageHeightPx, width: pageWidthPx }}>
            <div className="layout-page-label">
              <span>{paper.label}</span>
              <strong>
                {layoutZoom}% / {paper.widthMm} x {paper.heightMm} mm
              </strong>
            </div>
            <div
              className={selectedElementId === "map-frame" ? "layout-map-frame selected" : "layout-map-frame"}
              onPointerDown={(event) => beginElementDrag("map-frame", event)}
              style={rectToLayoutStyle(elementRects["map-frame"], zoomScale)}
            >
              <div className="layout-maplibre" ref={mapContainerRef} />
              {selectedElementId === "map-frame"
                ? mapResizeHandles.map((handle) => (
                    <span
                      aria-hidden="true"
                      className={`layout-resize-handle ${handle}`}
                      key={handle}
                      onPointerDown={(event) => beginMapResize(handle, event)}
                    />
                  ))
                : null}
            </div>
            {layoutAdornmentIds.includes("north-arrow") ? (
              <div
                aria-label="North arrow"
                className={selectedElementId === "north-arrow" ? "layout-north-arrow selected" : "layout-north-arrow"}
                onPointerDown={(event) => beginElementDrag("north-arrow", event)}
                role="button"
                style={rectToLayoutStyle(elementRects["north-arrow"], zoomScale)}
                tabIndex={0}
              >
                <span>N</span>
              </div>
            ) : null}
            {layoutAdornmentIds.includes("scale-bar") ? (
              <div
                aria-label="Scale bar"
                className={selectedElementId === "scale-bar" ? "layout-scale-bar selected" : "layout-scale-bar"}
                onPointerDown={(event) => beginElementDrag("scale-bar", event)}
                role="button"
                style={rectToLayoutStyle(elementRects["scale-bar"], zoomScale)}
                tabIndex={0}
              >
                <div className="layout-scale-track">
                  <span />
                  <span />
                </div>
                <strong>0</strong>
                <strong>5 km</strong>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function ChatPanel({
  context,
  onSearchResults,
  onTaskUpdate,
}: {
  context: AgentPageContext;
  onSearchResults: (items: SearchItem[]) => void;
  onTaskUpdate: (task: AgentTask) => void;
}) {
  const [agentMode, setAgentMode] = useState<"workflow" | "expert">("workflow");
  const [draft, setDraft] = useState("");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [reportedTaskId, setReportedTaskId] = useState<string | null>(null);
  const reportedSearchResultsRef = useRef<string | null>(null);
  const [messages, setMessages] = useState<AiChatMessage[]>([
    {
      role: "assistant",
      content: "你好，我是 gyygeo AI 助手。可以帮你选数据、解释参数、规划制图流程或排查服务状态。",
    },
  ]);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  const chatMutation = useMutation({
    mutationFn: (nextMessages: AiChatMessage[]) => {
      const payload = {
        messages: nextMessages,
        context,
      };
      return agentMode === "expert" ? sendExpertAgentChat(payload) : sendAgentChat(payload);
    },
    onSuccess: (response) => {
      setMessages((current) => [...current, response.message]);
      if (response.task?.id) {
        setActiveTaskId(response.task.id);
        setReportedTaskId(null);
      }
    },
  });

  const activeTask = useQuery({
    queryKey: ["agent-task", activeTaskId],
    queryFn: () => getAgentTask(activeTaskId!),
    enabled: Boolean(activeTaskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" ? false : 2000;
    },
  });

  useEffect(() => {
    messageListRef.current?.scrollTo({
      top: messageListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, chatMutation.isPending, activeTask.data]);

  useEffect(() => {
    const task = activeTask.data;
    if (!task || reportedTaskId === task.id || (task.status !== "done" && task.status !== "failed")) {
      return;
    }
    setReportedTaskId(task.id);
    setMessages((current) => [
      ...current,
      {
        role: "assistant",
        content: formatAgentTaskResult(task),
      },
    ]);
  }, [activeTask.data, reportedTaskId]);

  useEffect(() => {
    const task = activeTask.data;
    const searchItems = extractAgentSearchItems(task);
    if (!task || searchItems.length === 0) {
      return;
    }
    const signature = `${task.id}:${searchItems.map((item) => item.item_id).join(",")}`;
    if (reportedSearchResultsRef.current === signature) {
      return;
    }
    reportedSearchResultsRef.current = signature;
    onSearchResults(searchItems);
  }, [activeTask.data, onSearchResults]);

  useEffect(() => {
    const task = activeTask.data;
    if (!task) {
      return;
    }
    onTaskUpdate(task);
  }, [activeTask.data, onTaskUpdate]);

  const submitMessage = () => {
    const content = draft.trim();
    if (!content || chatMutation.isPending) {
      return;
    }
    const nextMessages: AiChatMessage[] = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setDraft("");
    chatMutation.mutate(nextMessages);
  };

  return (
    <aside className="ai-panel">
      <header className="ai-header">
        <div className="ai-title">
          <Bot size={18} />
          <div>
            <p className="eyebrow">Map Agent</p>
            <h2>AI 对话</h2>
          </div>
        </div>
        <span className="model-pill">
          <Sparkles size={14} />
          {agentMode === "expert" ? "expert-arcpy" : "gyygeo-agent"}
        </span>
      </header>

      <div className="agent-mode-toggle segmented-control" aria-label="Agent mode">
        <button
          className={agentMode === "workflow" ? "active" : ""}
          type="button"
          onClick={() => setAgentMode("workflow")}
        >
          <Play size={15} />
          工作流
        </button>
        <button
          className={agentMode === "expert" ? "active" : ""}
          type="button"
          onClick={() => setAgentMode("expert")}
        >
          <Sparkles size={15} />
          专家
        </button>
      </div>

      <div className="chat-list" ref={messageListRef}>
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className={`chat-message ${message.role}`}>
            <div className="chat-bubble">{message.content}</div>
          </div>
        ))}
        {chatMutation.isPending ? (
          <div className="chat-message assistant">
            <div className="chat-bubble pending">
              <Loader2 className="spin" size={15} />
              正在生成回复
            </div>
          </div>
        ) : null}
        {activeTask.data && activeTask.data.status !== "done" && activeTask.data.status !== "failed" ? (
          <div className="chat-message assistant">
            <div className="chat-bubble pending">
              <Loader2 className="spin" size={15} />
              {formatAgentTaskProgress(activeTask.data)}
            </div>
          </div>
        ) : null}
      </div>

      {chatMutation.error ? <ErrorText error={chatMutation.error} /> : null}

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault();
          submitMessage();
        }}
      >
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submitMessage();
            }
          }}
          placeholder={
            agentMode === "expert"
              ? "描述制图需求，或直接粘贴完整 ArcPy Python"
              : "问问当前地图、数据或制图流程"
          }
          rows={3}
        />
        <button className="send-button" type="submit" disabled={!draft.trim() || chatMutation.isPending}>
          {chatMutation.isPending ? <Loader2 className="spin" size={17} /> : <SendHorizontal size={17} />}
        </button>
      </form>
    </aside>
  );
}

function formatAgentTaskProgress(task: AgentTask): string {
  const runningStep = task.steps.find((step) => step.status === "running");
  const doneCount = task.steps.filter((step) => step.status === "done").length;
  const total = task.steps.length;
  return `Agent task ${task.id}: ${task.status}. ${doneCount}/${total} steps done${
    runningStep ? `, running ${runningStep.name}` : ""
  }.`;
}

function formatAgentTaskResult(task: AgentTask): string {
  if (task.status === "failed") {
    return `Agent task ${task.id} failed: ${task.error ?? task.message}`;
  }
  const render = task.outputs?.render as { files?: { preview?: unknown } } | undefined;
  const run = task.outputs?.run as
    | { files?: { preview?: unknown; script?: unknown; stderr?: unknown } }
    | undefined;
  const preview =
    typeof render?.files?.preview === "string"
      ? render.files.preview
      : typeof run?.files?.preview === "string"
        ? run.files.preview
        : "-";
  const qa = task.outputs?.qa as { summary?: unknown } | undefined;
  const qaSummary = typeof qa?.summary === "string" ? qa.summary : "QA finished.";
  const script = typeof run?.files?.script === "string" ? `\nScript: ${run.files.script}` : "";
  return `Agent task ${task.id} completed.\nOutput: ${preview}${script}\n${qaSummary}`;
}

function JobLine({
  job,
  loading,
  label,
}: {
  job?: JobRecord;
  loading: boolean;
  label: string;
}) {
  if (!job) {
    return <div className="job-line muted">{label}: -</div>;
  }
  return (
    <div className={`job-line ${job.status}`}>
      {loading && !isTerminal(job.status) ? <Loader2 className="spin" size={15} /> : statusIcon(job.status)}
      <span>{label}: {job.status}</span>
      <small>{job.id}</small>
    </div>
  );
}

function ErrorText({ error }: { error: unknown }) {
  return <div className="error-text">{error instanceof Error ? error.message : String(error)}</div>;
}

function normalizeBbox(values: Bbox): Bbox {
  const [a, b, c, d] = values.map((value) => (Number.isFinite(value) ? value : 0));
  return [Math.min(a, c), Math.min(b, d), Math.max(a, c), Math.max(b, d)];
}

function bboxFromCoordinates(coordinates: LngLatPair[]): Bbox {
  const finite = coordinates.filter(
    ([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat),
  );
  if (!finite.length) {
    return [0, 0, 0, 0];
  }
  const lngs = finite.map(([lng]) => lng);
  const lats = finite.map(([, lat]) => lat);
  return [
    Math.min(...lngs),
    Math.min(...lats),
    Math.max(...lngs),
    Math.max(...lats),
  ];
}

function bboxCenter(bbox: Bbox): LngLatPair {
  return [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2];
}

function polygonGeometry(coordinates: LngLatPair[]): PolygonGeometry | undefined {
  const finite = coordinates.filter(
    ([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat),
  );
  if (finite.length < 3) {
    return undefined;
  }
  const ring = finite.map(([lng, lat]) => [lng, lat] as LngLatPair);
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) {
    ring.push([first[0], first[1]]);
  }
  return {
    type: "Polygon",
    coordinates: [ring],
  };
}

function aoiFeatureCollection(
  mode: AoiMode,
  bbox: Bbox,
  polygon: LngLatPair[],
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  if (mode === "rectangle") {
    features.push(bboxFeature(bbox));
  } else {
    const geometry = polygonGeometry(polygon);
    if (geometry) {
      features.push({
        type: "Feature",
        properties: {},
        geometry,
      });
    } else if (polygon.length >= 2) {
      features.push({
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: polygon,
        },
      });
    }
    if (polygon.length) {
      features.push({
        type: "Feature",
        properties: {},
        geometry: {
          type: "MultiPoint",
          coordinates: polygon,
        },
      });
    }
  }

  return {
    type: "FeatureCollection",
    features,
  };
}

function bboxFeature(bbox: Bbox): GeoJSON.Feature<GeoJSON.Polygon> {
  const [xmin, ymin, xmax, ymax] = bbox;
  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [xmin, ymin],
          [xmax, ymin],
          [xmax, ymax],
          [xmin, ymax],
          [xmin, ymin],
        ],
      ],
    },
  };
}

function syncAoiLayer(map: MapLibreMap, mode: AoiMode, bbox: Bbox, polygon: LngLatPair[]) {
  const data = aoiFeatureCollection(mode, bbox, polygon);
  const source = map.getSource("aoi") as GeoJSONSource | undefined;
  if (source) {
    source.setData(data);
    return;
  }

  map.addSource("aoi", {
    type: "geojson",
    data,
  });
  map.addLayer({
    id: "aoi-fill",
    type: "fill",
    source: "aoi",
    paint: {
      "fill-color": "#39a0a8",
      "fill-opacity": 0.16,
    },
  });
  map.addLayer({
    id: "aoi-line",
    type: "line",
    source: "aoi",
    paint: {
      "line-color": "#176b6f",
      "line-width": 2,
    },
  });
  map.addLayer({
    id: "aoi-vertices",
    type: "circle",
    source: "aoi",
    paint: {
      "circle-color": "#176b6f",
      "circle-radius": 4,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 1.5,
    },
  });
}

function syncPreviewRasterLayers(map: MapLibreMap, previewLayers: PreviewRasterLayer[], fitLatest: boolean) {
  const activeLayerIds = new Set(previewLayers.map((layer) => previewLayerIdFor(layer.itemId)));
  const activeSourceIds = new Set(previewLayers.map((layer) => previewSourceIdFor(layer.itemId)));
  for (const layerId of previewLayerIds(map)) {
    if (!activeLayerIds.has(layerId) && map.getLayer(layerId)) {
      map.removeLayer(layerId);
    }
  }
  for (const sourceId of previewSourceIds(map)) {
    if (!activeSourceIds.has(sourceId) && map.getSource(sourceId)) {
      map.removeSource(sourceId);
    }
  }

  for (const layer of previewLayers) {
    if (!layer.tilejson.tiles.length) {
      continue;
    }
    const sourceId = previewSourceIdFor(layer.itemId);
    const layerId = previewLayerIdFor(layer.itemId);
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, {
        type: "raster",
        tiles: layer.tilejson.tiles,
        tileSize,
        bounds: layer.bounds,
        minzoom: layer.tilejson.minzoom ?? undefined,
        maxzoom: layer.tilejson.maxzoom ?? undefined,
        attribution: "Microsoft Planetary Computer",
      });
    }
    if (!map.getLayer(layerId)) {
      map.addLayer(
        {
          id: layerId,
          type: "raster",
          source: sourceId,
          paint: {
            "raster-opacity": 0.74,
          },
        },
        map.getLayer("aoi-fill") ? "aoi-fill" : undefined,
      );
    }
  }

  const latestBounds = previewLayers[previewLayers.length - 1]?.bounds;
  if (fitLatest && latestBounds) {
    map.fitBounds(latestBounds, { padding: 70, duration: 500, maxZoom: 13 });
  }
}

function wrapTileX(x: number, z: number) {
  const max = 2 ** z;
  return ((x % max) + max) % max;
}

function isValidTileY(y: number, z: number) {
  return y >= 0 && y < 2 ** z;
}

function formatTileUrl(tileTemplate: string, z: number, x: number, y: number) {
  return tileTemplate.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
}

function rememberCacheValue<TKey, TValue>(cache: Map<TKey, TValue>, key: TKey, value: TValue, maxEntries: number) {
  if (cache.has(key)) {
    cache.delete(key);
  }
  cache.set(key, value);
  while (cache.size > maxEntries) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) {
      break;
    }
    cache.delete(oldestKey);
  }
  return value;
}

async function fetchTileBitmap(tileTemplate: string, z: number, x: number, y: number, signal?: AbortSignal) {
  if (z < 0 || z > 19 || !isValidTileY(y, z)) {
    return null;
  }
  const wrappedX = wrapTileX(x, z);
  const key = `${tileTemplate}|${z}/${wrappedX}/${y}`;
  if (offsetTileImageCache.has(key)) {
    return offsetTileImageCache.get(key);
  }
  const promise = fetch(formatTileUrl(tileTemplate, z, wrappedX, y), { signal })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Tile request failed: ${response.status}`);
      }
      return response.blob();
    })
    .then((blob) => createImageBitmap(blob));
  promise.catch(() => offsetTileImageCache.delete(key));
  return rememberCacheValue(offsetTileImageCache, key, promise, 420);
}

function createOffsetTileCanvas() {
  if (typeof OffscreenCanvas !== "undefined") {
    return new OffscreenCanvas(tileSize, tileSize);
  }
  const canvas = document.createElement("canvas");
  canvas.width = tileSize;
  canvas.height = tileSize;
  return canvas;
}

function offsetCanvasToBlob(canvas: OffscreenCanvas | HTMLCanvasElement) {
  if ("convertToBlob" in canvas) {
    return canvas.convertToBlob({ quality: 0.92, type: "image/jpeg" });
  }
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) {
          resolve(blob);
          return;
        }
        reject(new Error("Failed to render offset tile"));
      },
      "image/jpeg",
      0.92,
    );
  });
}

async function renderOffsetTile(
  tileTemplate: string,
  z: number,
  x: number,
  y: number,
  requestedOffset: number,
  signal?: AbortSignal,
) {
  const effectiveOffset = Math.round(clampNumber(requestedOffset, -z, 19 - z));
  const key = `${tileTemplate}|${z}/${x}/${y}/${effectiveOffset}`;
  if (offsetTileDataCache.has(key)) {
    return offsetTileDataCache.get(key);
  }
  const promise = (async () => {
    const canvas = createOffsetTileCanvas();
    const ctx = canvas.getContext("2d") as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null;
    if (!ctx) {
      throw new Error("Failed to create offset tile canvas context");
    }
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";

    if (effectiveOffset >= 0) {
      const factor = 2 ** effectiveOffset;
      const sourceZ = z + effectiveOffset;
      const drawSize = tileSize / factor;
      for (let tileY = 0; tileY < factor; tileY += 1) {
        for (let tileX = 0; tileX < factor; tileX += 1) {
          const bitmap = await fetchTileBitmap(tileTemplate, sourceZ, x * factor + tileX, y * factor + tileY, signal);
          if (bitmap) {
            ctx.drawImage(bitmap, tileX * drawSize, tileY * drawSize, drawSize, drawSize);
          }
        }
      }
    } else {
      const factor = 2 ** Math.abs(effectiveOffset);
      const sourceZ = z + effectiveOffset;
      const parentX = Math.floor(x / factor);
      const parentY = Math.floor(y / factor);
      const bitmap = await fetchTileBitmap(tileTemplate, sourceZ, parentX, parentY, signal);
      if (bitmap) {
        const sourceSize = tileSize / factor;
        const sourceX = (((x % factor) + factor) % factor) * sourceSize;
        const sourceY = (((y % factor) + factor) % factor) * sourceSize;
        ctx.drawImage(bitmap, sourceX, sourceY, sourceSize, sourceSize, 0, 0, tileSize, tileSize);
      }
    }

    const blob = await offsetCanvasToBlob(canvas);
    return blob.arrayBuffer();
  })();
  promise.catch(() => offsetTileDataCache.delete(key));
  return rememberCacheValue(offsetTileDataCache, key, promise, 260);
}

function ensureOffsetTileProtocol() {
  if (isOffsetTileProtocolRegistered || typeof maplibregl.addProtocol !== "function") {
    return;
  }

  maplibregl.addProtocol(offsetTileProtocol, async (params, abortController) => {
    const url = new URL(params.url);
    const [zText, xText, yText] = url.pathname.split("/").filter(Boolean);
    const z = Number(zText);
    const x = Number(xText);
    const y = Number(yText);
    const offset = Number(url.searchParams.get("offset") || 0);
    const tileTemplate = url.searchParams.get("template");
    if (!tileTemplate) {
      throw new Error("Offset tile template is missing");
    }
    const data = await renderOffsetTile(tileTemplate, z, x, y, offset, abortController.signal);
    return { data };
  });

  isOffsetTileProtocolRegistered = true;
}

function createOffsetTileUrl(tileTemplate: string, tileOffset: number) {
  const offset = Math.round(tileOffset);
  if (offset === 0 || typeof maplibregl.addProtocol !== "function") {
    return tileTemplate;
  }
  ensureOffsetTileProtocol();
  return `${offsetTileProtocol}://tile/{z}/{x}/{y}?offset=${offset}&template=${encodeURIComponent(tileTemplate)}`;
}

function createMapStyle(baseLayer: BaseLayer, tileOffset = 0): StyleSpecification {
  const isImagery = baseLayer === "esri-world-imagery";
  const tileTemplate = isImagery
    ? "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    : "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

  return {
    version: 8,
    sources: {
      base: {
        type: "raster",
        tiles: [createOffsetTileUrl(tileTemplate, tileOffset)],
        tileSize,
        maxzoom: 19,
        attribution: isImagery ? "Tiles © Esri" : "© OpenStreetMap contributors",
      },
    },
    layers: [
      {
        id: isImagery ? "esri-world-imagery" : "osm-standard",
        type: "raster",
        source: "base",
      },
    ],
  };
}

function createInitialElementRects(paper: { heightMm: number; widthMm: number }): Record<LayoutElementId, LayoutElementRect> {
  const mapX = 11;
  const mapY = 18;
  const mapWidth = Math.max(minMapFrameSizeMm, paper.widthMm - mapX * 2);
  const mapHeight = Math.max(minMapFrameSizeMm, paper.heightMm - mapY - 11);

  return {
    "map-frame": {
      height: mapHeight,
      width: mapWidth,
      x: mapX,
      y: mapY,
    },
    "north-arrow": {
      height: 15,
      width: 12,
      x: Math.max(4, mapX + mapWidth - 16),
      y: mapY + 5,
    },
    "scale-bar": {
      height: 10,
      width: 36,
      x: mapX + 5,
      y: Math.max(4, mapY + mapHeight - 15),
    },
  };
}

function getLayoutPaperPreset(paperSize: LayoutPaperId) {
  return layoutPaperPresets.find((paper) => paper.id === paperSize) ?? layoutPaperPresets[0];
}

function mmToCssPx(valueMm: number, zoomScale: number) {
  return Math.round(valueMm * cssPixelPerMm * zoomScale);
}

function rectToLayoutStyle(
  rect: { x: number; y: number; width: number; height: number },
  zoomScale: number,
): CSSProperties {
  return {
    height: mmToCssPx(rect.height, zoomScale),
    left: mmToCssPx(rect.x, zoomScale),
    top: mmToCssPx(rect.y, zoomScale),
    width: mmToCssPx(rect.width, zoomScale),
  };
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function formatCoord(value: number): string {
  return Number.isFinite(value) ? value.toFixed(5) : "-";
}

function optionalNumber(value: string): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function clampInt(value: string, min: number, max: number, fallback: number): number {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function previewBands(requestedBands: string[], item: SearchItem): string[] {
  const assetKeys = new Set((item.assets ?? []).map((asset) => asset.key));
  const requested = requestedBands.slice(0, 3).filter((band) => assetKeys.has(band));
  if (requested.length >= 3) {
    return requested;
  }
  if (assetKeys.has("visual")) {
    return ["visual"];
  }
  return requestedBands.slice(0, 3);
}

function validBbox(value?: number[] | null): Bbox | undefined {
  if (!Array.isArray(value) || value.length !== 4) {
    return undefined;
  }
  const bbox = value.map(Number);
  if (!bbox.every(Number.isFinite) || bbox[0] >= bbox[2] || bbox[1] >= bbox[3]) {
    return undefined;
  }
  return [bbox[0], bbox[1], bbox[2], bbox[3]];
}

function previewSourceIdFor(itemId: string): string {
  return `${previewSourcePrefix}-${safeMapId(itemId)}`;
}

function previewLayerIdFor(itemId: string): string {
  return `${previewLayerPrefix}-${safeMapId(itemId)}`;
}

function previewLayerIds(map: MapLibreMap): string[] {
  return map
    .getStyle()
    .layers.filter((layer) => layer.id.startsWith(`${previewLayerPrefix}-`))
    .map((layer) => layer.id);
}

function previewSourceIds(map: MapLibreMap): string[] {
  const sources = map.getStyle().sources ?? {};
  return Object.keys(sources).filter((sourceId) => sourceId.startsWith(`${previewSourcePrefix}-`));
}

function safeMapId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, "-");
}

function isTerminal(status?: JobStatus): boolean {
  return status === "done" || status === "failed";
}

function extractPreparedPath(job?: JobRecord): string | undefined {
  const dataset = job?.result?.dataset as { path?: unknown } | undefined;
  return typeof dataset?.path === "string" ? dataset.path : undefined;
}

function extractPreviewPath(job?: JobRecord): string | undefined {
  const files = job?.result?.files as { preview?: unknown } | undefined;
  return typeof files?.preview === "string" ? files.preview : undefined;
}

function extractAgentSearchItems(task?: AgentTask): SearchItem[] {
  const search = isRecord(task?.outputs.search) ? task.outputs.search : undefined;
  const rawItems = Array.isArray(search?.items) ? search.items : [];
  return rawItems.flatMap((item) => {
    if (!isRecord(item) || typeof item.item_id !== "string") {
      return [];
    }
    return [item as unknown as SearchItem];
  });
}

function isAgentWaitingForImageSelection(task: AgentTask): boolean {
  const pendingAction = isRecord(task.outputs.pending_action) ? task.outputs.pending_action : undefined;
  return task.status === "waiting_for_user" && pendingAction?.type === "select_image";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function formatItemMeta(item: SearchItem): string {
  const pieces = [
    item.datetime ? new Date(item.datetime).toISOString().slice(0, 10) : "",
    typeof item.cloud_cover === "number" ? `cloud ${item.cloud_cover.toFixed(1)}` : "",
    item.assets?.length ? `${item.assets.length} assets` : "",
  ].filter(Boolean);
  return pieces.join(" | ") || item.collection;
}

function statusIcon(status: JobStatus) {
  if (status === "done") {
    return <CheckCircle2 size={15} />;
  }
  if (status === "failed") {
    return <XCircle size={15} />;
  }
  return <Loader2 className="spin" size={15} />;
}

function slugName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-")
    .replace(/^-+|-+$/g, "");
}
