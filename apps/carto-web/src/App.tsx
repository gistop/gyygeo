import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import maplibregl, { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import {
  CheckCircle2,
  Crosshair,
  Database,
  Loader2,
  Map,
  Play,
  RefreshCcw,
  Search,
  XCircle,
} from "lucide-react";
import {
  config,
  getCartoHealth,
  getCartoJob,
  getDataHealth,
  getDataJob,
  prepareRaster,
  renderPreview,
  searchItems,
} from "./api";
import type { Bbox, JobRecord, JobStatus, PreparePayload, SearchItem } from "./types";

const initialBbox: Bbox = [116.1, 39.7, 116.7, 40.2];

export function App() {
  const [provider, setProvider] = useState("mpc");
  const [collection, setCollection] = useState("landsat-c2-l2");
  const [datetime, setDatetime] = useState("2025-07-01/2025-07-31");
  const [cloudCover, setCloudCover] = useState("20");
  const [limit, setLimit] = useState("10");
  const [bbox, setBbox] = useState<Bbox>(initialBbox);
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
  const cartoHealth = useQuery({
    queryKey: ["health", "carto"],
    queryFn: getCartoHealth,
  });

  const searchMutation = useMutation({
    mutationFn: () =>
      searchItems({
        provider,
        collection,
        bbox,
        datetime: datetime.trim() || undefined,
        limit: clampInt(limit, 1, 100, 10),
        cloud_cover_lte: optionalNumber(cloudCover),
      }),
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
      const payload: PreparePayload = {
        provider,
        collection,
        item_id: selectedItem.item_id,
        bbox,
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

            <BboxInputs bbox={bbox} onChange={setBbox} />

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
          <MapPanel bbox={bbox} onBboxChange={setBbox} />
          <OutputPanel
            preparedPath={preparedDatasetPath}
            prepareJob={prepareJob.data}
            renderJob={renderJob.data}
          />
        </section>
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

function BboxInputs({ bbox, onChange }: { bbox: Bbox; onChange: (bbox: Bbox) => void }) {
  const labels = ["xmin", "ymin", "xmax", "ymax"];
  return (
    <div className="bbox-grid">
      {bbox.map((value, index) => (
        <label key={labels[index]}>
          {labels[index]}
          <input
            inputMode="decimal"
            value={String(value)}
            onChange={(event) => {
              const next = [...bbox] as Bbox;
              next[index] = Number(event.target.value);
              onChange(normalizeBbox(next));
            }}
          />
        </label>
      ))}
    </div>
  );
}

function MapPanel({
  bbox,
  onBboxChange,
}: {
  bbox: Bbox;
  onBboxChange: (bbox: Bbox) => void;
}) {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const drawStartRef = useRef<[number, number] | null>(null);
  const [drawing, setDrawing] = useState(false);

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
      map.addSource("bbox", {
        type: "geojson",
        data: bboxFeature(bbox),
      });
      map.addLayer({
        id: "bbox-fill",
        type: "fill",
        source: "bbox",
        paint: {
          "fill-color": "#39a0a8",
          "fill-opacity": 0.16,
        },
      });
      map.addLayer({
        id: "bbox-line",
        type: "line",
        source: "bbox",
        paint: {
          "line-color": "#176b6f",
          "line-width": 2,
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
    const source = map.getSource("bbox") as GeoJSONSource | undefined;
    source?.setData(bboxFeature(bbox));
  }, [bbox]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) {
      return;
    }

    map.getCanvas().style.cursor = drawing ? "crosshair" : "";
    if (drawing) {
      map.dragPan.disable();
    } else {
      map.dragPan.enable();
      drawStartRef.current = null;
    }

    const onMouseDown = (event: maplibregl.MapMouseEvent) => {
      if (!drawing) {
        return;
      }
      drawStartRef.current = [event.lngLat.lng, event.lngLat.lat];
    };
    const onMouseMove = (event: maplibregl.MapMouseEvent) => {
      const start = drawStartRef.current;
      if (!drawing || !start) {
        return;
      }
      onBboxChange(normalizeBbox([start[0], start[1], event.lngLat.lng, event.lngLat.lat]));
    };
    const onMouseUp = (event: maplibregl.MapMouseEvent) => {
      const start = drawStartRef.current;
      if (!drawing || !start) {
        return;
      }
      onBboxChange(normalizeBbox([start[0], start[1], event.lngLat.lng, event.lngLat.lat]));
      drawStartRef.current = null;
      setDrawing(false);
    };

    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("mouseup", onMouseUp);
    return () => {
      map.off("mousedown", onMouseDown);
      map.off("mousemove", onMouseMove);
      map.off("mouseup", onMouseUp);
    };
  }, [drawing, onBboxChange]);

  return (
    <div className="map-panel">
      <div ref={mapContainerRef} className="map-container" />
      <div className="map-tools">
        <button
          className={`tool-button ${drawing ? "active" : ""}`}
          type="button"
          onClick={() => setDrawing((value) => !value)}
          title="绘制 bbox"
        >
          <Crosshair size={18} />
          <span>绘制范围</span>
        </button>
        <button
          className="tool-button"
          type="button"
          onClick={() => mapRef.current?.fitBounds(bbox, { padding: 80, duration: 500 })}
          title="定位范围"
        >
          <Play size={17} />
          <span>定位</span>
        </button>
      </div>
    </div>
  );
}

function OutputPanel({
  preparedPath,
  prepareJob,
  renderJob,
}: {
  preparedPath?: string;
  prepareJob?: JobRecord;
  renderJob?: JobRecord;
}) {
  const previewPath = extractPreviewPath(renderJob);
  return (
    <section className="output-panel">
      <div>
        <p className="eyebrow">Pipeline</p>
        <h2>输出</h2>
      </div>
      <dl className="output-list">
        <div>
          <dt>Prepared dataset</dt>
          <dd>{preparedPath || statusText(prepareJob?.status)}</dd>
        </div>
        <div>
          <dt>Preview</dt>
          <dd>{previewPath || statusText(renderJob?.status)}</dd>
        </div>
      </dl>
      {renderJob?.status === "failed" ? <ErrorText error={renderJob.error ?? "Render failed"} /> : null}
      {prepareJob?.status === "failed" ? <ErrorText error={prepareJob.error ?? "Prepare failed"} /> : null}
    </section>
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

function statusText(status?: JobStatus): string {
  if (!status) {
    return "-";
  }
  return status;
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
