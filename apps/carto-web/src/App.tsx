import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import maplibregl, { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import {
  Bot,
  CheckCircle2,
  Crosshair,
  Database,
  Loader2,
  Map,
  Pentagon,
  Play,
  Plus,
  RefreshCcw,
  Search,
  SendHorizontal,
  Sparkles,
  Square,
  Trash2,
  XCircle,
} from "lucide-react";
import {
  config,
  getCartoHealth,
  getCartoWebApiHealth,
  getCartoJob,
  getDataHealth,
  getDataJob,
  prepareRaster,
  renderPreview,
  sendAiChat,
  searchItems,
} from "./api";
import type {
  AiChatMessage,
  AoiMode,
  Bbox,
  JobRecord,
  JobStatus,
  LngLatPair,
  PolygonGeometry,
  PreparePayload,
  SearchItem,
} from "./types";

const initialBbox: Bbox = [116.1, 39.7, 116.7, 40.2];
const initialPolygon: LngLatPair[] = [
  [116.2, 39.78],
  [116.58, 39.82],
  [116.5, 40.1],
  [116.24, 40.06],
];

export function App() {
  const [provider, setProvider] = useState("mpc");
  const [collection, setCollection] = useState("landsat-c2-l2");
  const [datetime, setDatetime] = useState("2025-07-01/2025-07-31");
  const [cloudCover, setCloudCover] = useState("20");
  const [limit, setLimit] = useState("10");
  const [aoiMode, setAoiMode] = useState<AoiMode>("rectangle");
  const [bbox, setBbox] = useState<Bbox>(initialBbox);
  const [polygonCoordinates, setPolygonCoordinates] = useState<LngLatPair[]>(initialPolygon);
  const [bands, setBands] = useState("red,green,blue");
  const [targetResolution, setTargetResolution] = useState("120");
  const [targetCrs, setTargetCrs] = useState("EPSG:3857");
  const [mapTitle, setMapTitle] = useState("Landsat Map");
  const [layoutName, setLayoutName] = useState("Layout");
  const [dryRun, setDryRun] = useState(false);
  const [selectedItem, setSelectedItem] = useState<SearchItem | null>(null);
  const [prepareJobId, setPrepareJobId] = useState<string | null>(null);
  const [renderJobId, setRenderJobId] = useState<string | null>(null);

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
      setSelectedItem(response.items[0] ?? null);
      setPrepareJobId(null);
      setRenderJobId(null);
    },
  });

  const prepareMutation = useMutation({
    mutationFn: () => {
      if (!selectedItem) {
        throw new Error("请先选择一个数据项。");
      }
      if (aoiMode === "polygon" && !activeGeometry) {
        throw new Error("多边形范围至少需要 3 个顶点。");
      }
      const payload: PreparePayload = {
        provider,
        collection,
        item_id: selectedItem.item_id,
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

  const items = searchMutation.data?.items ?? [];
  const canPrepare = Boolean(selectedItem) && !prepareMutation.isPending;
  const canRender =
    dryRun ||
    (prepareJob.data?.status === "done" && Boolean(preparedDatasetPath) && !renderMutation.isPending);
  const aiContext = useMemo(() => {
    return [
      `Provider: ${provider}`,
      `Collection: ${collection}`,
      `Datetime: ${datetime}`,
      `AOI type: ${aoiMode}`,
      `BBOX: ${activeBbox.join(", ")}`,
      `Polygon vertices: ${aoiMode === "polygon" ? polygonCoordinates.length : "-"}`,
      `Bands: ${bands}`,
      `Target CRS: ${targetCrs}`,
      `Selected item: ${selectedItem?.item_id ?? "-"}`,
      `Prepare job: ${prepareJob.data?.status ?? "-"}`,
      `Prepared dataset: ${preparedDatasetPath ?? "-"}`,
      `Render job: ${renderJob.data?.status ?? "-"}`,
      `Preview: ${extractPreviewPath(renderJob.data) ?? "-"}`,
    ].join("\n");
  }, [
    activeBbox,
    aoiMode,
    bands,
    collection,
    datetime,
    polygonCoordinates,
    preparedDatasetPath,
    prepareJob.data,
    provider,
    renderJob.data,
    selectedItem,
    targetCrs,
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
                items.map((item) => (
                  <button
                    key={item.item_id}
                    type="button"
                    className={`item-card ${
                      selectedItem?.item_id === item.item_id ? "selected" : ""
                    }`}
                    onClick={() => setSelectedItem(item)}
                  >
                    <span>{item.item_id}</span>
                    <small>{formatItemMeta(item)}</small>
                  </button>
                ))
              )}
            </div>
            {searchMutation.error ? <ErrorText error={searchMutation.error} /> : null}
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
              onClick={() => prepareMutation.mutate()}
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
              {renderMutation.isPending ? <Loader2 className="spin" size={18} /> : <Map size={18} />}
              生成地图
            </button>
            {renderMutation.error ? <ErrorText error={renderMutation.error} /> : null}
            <JobLine job={renderJob.data} loading={renderJob.isFetching} label="carto job" />
          </div>
        </aside>

        <section className="map-stage">
          <MapPanel
            mode={aoiMode}
            bbox={bbox}
            polygon={polygonCoordinates}
            onModeChange={setAoiMode}
            onBboxChange={setBbox}
            onPolygonChange={setPolygonCoordinates}
          />
        </section>
        <ChatPanel context={aiContext} />
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

function MapPanel({
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
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const drawStartRef = useRef<[number, number] | null>(null);
  const [drawingMode, setDrawingMode] = useState<AoiMode | null>(null);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "OpenStreetMap",
          },
        },
        layers: [
          {
            id: "osm",
            type: "raster",
            source: "osm",
          },
        ],
      },
      center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
      zoom: 8,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      map.addSource("aoi", {
        type: "geojson",
        data: aoiFeatureCollection(mode, bbox, polygon),
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
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) {
      return;
    }
    const source = map.getSource("aoi") as GeoJSONSource | undefined;
    source?.setData(aoiFeatureCollection(mode, bbox, polygon));
  }, [bbox, mode, polygon]);

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
      </div>
    </div>
  );
}

function ChatPanel({ context }: { context: string }) {
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<AiChatMessage[]>([
    {
      role: "assistant",
      content: "你好，我是 gyygeo AI 助手。可以帮你选数据、解释参数、规划制图流程或排查服务状态。",
    },
  ]);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  const chatMutation = useMutation({
    mutationFn: (nextMessages: AiChatMessage[]) =>
      sendAiChat({
        messages: nextMessages,
        context,
      }),
    onSuccess: (response) => {
      setMessages((current) => [...current, response.message]);
    },
  });

  useEffect(() => {
    messageListRef.current?.scrollTo({
      top: messageListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, chatMutation.isPending]);

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
            <p className="eyebrow">DeepSeek</p>
            <h2>AI 对话</h2>
          </div>
        </div>
        <span className="model-pill">
          <Sparkles size={14} />
          deepseek-v4-flash
        </span>
      </header>

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
          placeholder="问问当前地图、数据或制图流程"
          rows={3}
        />
        <button className="send-button" type="submit" disabled={!draft.trim() || chatMutation.isPending}>
          {chatMutation.isPending ? <Loader2 className="spin" size={17} /> : <SendHorizontal size={17} />}
        </button>
      </form>
    </aside>
  );
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
