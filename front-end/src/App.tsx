import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchDashboard, fetchFarm, fetchWeather } from "./lib/api";
import type {
  DashboardResponse,
  DashboardZone,
  Farm,
  Priority,
  WeatherSnapshot,
} from "./types";

const FALLBACK_ENABLED = import.meta.env.VITE_DEMO_FALLBACK === "true";
const RUN_ID = "live_demo_001";
const CACHE_KEY = `agromind.dashboard.cache.v1.${FALLBACK_ENABLED ? "fallback" : "gemini"}`;
const CACHE_TTL_MS = 5 * 60 * 1000;

type DashboardCache = {
  savedAt: number;
  farm: Farm;
  weather: WeatherSnapshot;
  dashboard: DashboardResponse;
};

function readCache(): DashboardCache | null {
  try {
    const raw = window.sessionStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw) as DashboardCache;
    if (!cached.savedAt || Date.now() - cached.savedAt > CACHE_TTL_MS) {
      window.sessionStorage.removeItem(CACHE_KEY);
      return null;
    }
    return cached.farm && cached.weather && cached.dashboard ? cached : null;
  } catch {
    return null;
  }
}

function writeCache(value: Omit<DashboardCache, "savedAt">) {
  try {
    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ ...value, savedAt: Date.now() }),
    );
  } catch {
    /* optional optimization */
  }
}

function statusLabel(status: DashboardZone["hydration_status"]) {
  if (status === "investigation_needed") return "Needs review";
  if (status === "insufficient_evidence") return "Insufficient data";
  return "Normal";
}

function statusTone(status: DashboardZone["hydration_status"]) {
  if (status === "investigation_needed")
    return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "insufficient_evidence")
    return "border-slate-200 bg-slate-50 text-slate-600";
  return "border-emerald-200 bg-emerald-50 text-emerald-800";
}

function riskTone(risk: DashboardZone["hydration_risk"]) {
  if (risk === "high") return "text-red-700";
  if (risk === "medium") return "text-amber-700";
  if (risk === "unknown") return "text-slate-500";
  return "text-emerald-700";
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>
      {detail && <p className="mt-1 text-sm text-slate-500">{detail}</p>}
    </div>
  );
}

function WeatherCard({ weather }: { weather: WeatherSnapshot }) {
  const current = weather.current;
  const values = [
    [
      "Temperature",
      current?.temperature_c == null ? "—" : `${current.temperature_c} °C`,
    ],
    [
      "Humidity",
      current?.relative_humidity_pct == null
        ? "—"
        : `${current.relative_humidity_pct}%`,
    ],
    [
      "Wind",
      current?.wind_speed_kmh == null ? "—" : `${current.wind_speed_kmh} km/h`,
    ],
    [
      "Rain",
      current?.precipitation_mm == null
        ? "—"
        : `${current.precipitation_mm} mm`,
    ],
  ];
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Weather snapshot
          </p>
          <h2 className="mt-1 text-lg font-semibold text-slate-900">
            Current field conditions
          </h2>
        </div>
        <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">
          {weather.source}
        </span>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {values.map(([label, value]) => (
          <div key={label}>
            <p className="text-xs text-slate-500">{label}</p>
            <p className="mt-1 font-semibold text-slate-900">{value}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ZoneTable({ zones }: { zones: DashboardZone[] }) {
  return (
    <section
      id="zones"
      className="scroll-mt-6 rounded-xl border border-slate-200 bg-white shadow-sm"
    >
      <div className="flex flex-col gap-1 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-semibold text-slate-900">Zone monitoring</h2>
          <p className="text-sm text-slate-500">
            Validated hydration and fertilization signals.
          </p>
        </div>
        <span className="text-sm text-slate-500">
          {zones.length} zones in this run
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-5 py-3 font-semibold">Zone</th>
              <th className="px-5 py-3 font-semibold">Hydration</th>
              <th className="px-5 py-3 font-semibold">Hydration risk</th>
              <th className="px-5 py-3 font-semibold">Fertilization</th>
              <th className="px-5 py-3 font-semibold">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {zones.map((zone) => (
              <tr key={zone.zone_id} className="hover:bg-slate-50">
                <td className="whitespace-nowrap px-5 py-4 font-semibold text-slate-900">
                  {zone.zone_id}
                </td>
                <td className="px-5 py-4">
                  <span
                    className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(zone.hydration_status)}`}
                  >
                    {statusLabel(zone.hydration_status)}
                  </span>
                </td>
                <td
                  className={`px-5 py-4 font-semibold capitalize ${riskTone(zone.hydration_risk)}`}
                >
                  {zone.hydration_risk}
                </td>
                <td className="px-5 py-4">
                  <span
                    className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(zone.fertilization_status)}`}
                  >
                    {statusLabel(zone.fertilization_status)}
                  </span>
                </td>
                <td className="whitespace-nowrap px-5 py-4 text-slate-500">
                  {zone.last_updated_at
                    ? new Date(zone.last_updated_at).toLocaleString()
                    : "Not available"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ActionPlan({ actions }: { actions: Priority[] }) {
  return (
    <section
      id="action-plan"
      className="scroll-mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold text-slate-900">Recommended actions</h2>
          <p className="mt-1 text-sm text-slate-500">
            AI suggestions grounded in the validated zone reports.
          </p>
        </div>
        <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-800">
          Human review required
        </span>
      </div>
      {actions.length === 0 ? (
        <p className="mt-5 rounded-lg bg-slate-50 p-4 text-sm text-slate-600">
          No actions were returned for this analysis run.
        </p>
      ) : (
        <ol className="mt-5 space-y-3">
          {actions.map((item, index) => (
            <li
              key={`${item.zone_id}-${item.domain}-${item.priority}`}
              className="flex gap-3 rounded-lg border border-slate-100 bg-slate-50 p-4"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-xs font-bold text-emerald-800">
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className="font-semibold text-slate-900">
                  Zone {item.zone_id} · {item.domain}
                </p>
                <p className="mt-1 text-sm text-slate-700">{item.action}</p>
                <p className="mt-1 text-xs text-slate-500">{item.reason}</p>
                {item.evidence_refs.length > 0 && (
                  <p className="mt-2 text-xs font-medium text-emerald-700">
                    Evidence: {item.evidence_refs.join(", ")}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function FarmMap({
  zones,
  actions,
}: {
  zones: DashboardZone[];
  actions: Priority[];
}) {
  type MapSeverity = "critical" | "high" | "medium" | "unknown" | "low";

  const getZoneSeverity = (zoneId: string): MapSeverity => {
    const zone = zones.find((item) => item.zone_id === zoneId);
    if (!zone) return "unknown";

    const zoneActions = actions.filter((item) => item.zone_id === zoneId);
    const hasEvidenceGap =
      zone.hydration_status === "insufficient_evidence" ||
      zone.fertilization_status === "insufficient_evidence" ||
      zone.hydration_risk === "unknown" ||
      zone.fertilization_risk === "unknown";

    // A documented urgent action takes precedence over the risk colors.
    const priorityValues = zoneActions.map((item) => {
      const raw = String(item.priority ?? "").toLowerCase();
      if (raw.includes("critical")) return 4;
      if (raw.includes("high")) return 3;
      if (raw.includes("medium")) return 2;
      if (raw.includes("low")) return 1;
      const numeric = Number(raw);
      // In the API contract, smaller numeric values mean higher priority.
      return Number.isFinite(numeric) && numeric > 0 ? Math.max(1, 5 - numeric) : 0;
    });
    const actionSeverity = Math.max(0, ...priorityValues);
    if (actionSeverity >= 4) return "critical";
    if (actionSeverity === 3) return "high";
    if (actionSeverity === 2) return "medium";

    const risks = [zone.hydration_risk, zone.fertilization_risk];
    if (risks.includes("high")) return "high";
    if (risks.includes("medium")) return "medium";
    if (hasEvidenceGap) return "unknown";
    return "low";
  };

  const severityStyles: Record<MapSeverity, { fill: string; stroke: string; label: string }> = {
    critical: { fill: "rgba(153, 27, 27, 0.52)", stroke: "#991b1b", label: "Urgent priority" },
    high: { fill: "rgba(239, 68, 68, 0.40)", stroke: "#dc2626", label: "High risk" },
    medium: { fill: "rgba(245, 158, 11, 0.38)", stroke: "#d97706", label: "Medium risk" },
    unknown: { fill: "rgba(100, 116, 139, 0.38)", stroke: "#64748b", label: "Insufficient evidence" },
    low: { fill: "rgba(16, 185, 129, 0.27)", stroke: "#059669", label: "Low risk / normal" },
  };

  // Approximate field-parcel boundaries traced against the supplied 790 × 513 image.
  // These are visual demo polygons, not surveyed/GIS boundaries.
  const parcels: Array<{ id: string; points: string; label: [number, number] }> = [
    { id: "Z-1", points: "0,0 171,0 184,40 198,100 220,164 246,204 211,211 192,197 174,185 151,185 130,194 103,201 58,204 24,204 0,201", label: [94, 150] },
    { id: "Z-2", points: "171,0 250,0 310,0 389,0 426,119 389,130 350,151 310,211 248,212 246,204 220,164 198,100 184,40", label: [300, 75] },
    { id: "Z-3", points: "389,0 518,0 676,0 648,204 595,237 510,205 470,168 426,119", label: [553, 94] },
    { id: "Z-4", points: "0,201 24,204 58,204 103,201 130,194 151,185 174,185 201,205 190,250 179,278 162,344 0,344", label: [83, 278] },
    { id: "Z-5", points: "201,205 211,211 248,212 310,211 350,151 389,130 426,160 470,168 510,205 476,270 434,319 400,359 367,345 338,345 309,350 272,349 255,382 242,382 220,365 190,350 162,344 179,278 190,250", label: [355, 270] },
    { id: "Z-6", points: "426,160 470,168 510,205 595,237 570,360 548,446 500,451 448,445 417,431 404,410 412,386 400,359 434,319 476,270", label: [500, 300] },
    { id: "Z-7", points: "595,237 648,204 666,207 690,216 728,241 790,276 790,380 790,469 708,486 600,462 552,446 570,360", label: [686, 350] },
    { id: "Z-8", points: "0,364 112,369 112,500 0,500", label: [53, 435] },
    { id: "Z-9", points: "112,369 156,376 190,375 192,500 112,500", label: [151, 435] },
    { id: "Z-10", points: "190,375 220,365 242,382 255,382 272,349 309,350 338,345 367,345 400,359 412,386 404,410 417,431 448,445 448,500 192,500", label: [320, 456] },
    { id: "Z-11", points: "448,445 500,451 552,446 575,453 562,500 448,500", label: [510, 478] },
    { id: "Z-12", points: "575,453 600,462 708,486 790,469 790,513 562,513 562,500", label: [680, 493] },
  ];

  return (
    <section className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 px-5 py-4">
        <h2 className="font-semibold text-slate-900">Satellite Zone Map</h2>
        <p className="text-sm text-slate-500">
          12-zone overlay colored from hydration risk, fertilization risk, evidence quality, and action priority
        </p>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-slate-600">
          {(["critical", "high", "medium", "unknown", "low"] as MapSeverity[]).map((severity) => (
            <span key={severity} className="inline-flex items-center gap-1.5">
              <span className="h-3 w-3 rounded-sm border" style={{ backgroundColor: severityStyles[severity].fill, borderColor: severityStyles[severity].stroke }} />
              {severityStyles[severity].label}
            </span>
          ))}
        </div>
      </div>

      <div className="relative w-full bg-slate-100">
        <img
          src="https://s3-eu-west-1.amazonaws.com/ifj/WEBFILES/000/378/780/1041580-378780.jpg"
          alt="Farm satellite view"
          className="block h-auto w-full"
        />
        <svg
          viewBox="0 0 790 513"
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
          aria-label="Twelve farm zones colored by operational priority and crop risks"
        >
          {parcels.map((parcel) => {
            const severity = getZoneSeverity(parcel.id);
            const style = severityStyles[severity];
            const zone = zones.find((item) => item.zone_id === parcel.id);
            const title = zone
              ? `${parcel.id}: ${style.label}; hydration ${zone.hydration_risk}; fertilization ${zone.fertilization_risk}`
              : `${parcel.id}: no current zone data`;
            return (
              <g key={parcel.id}>
                <title>{title}</title>
                <polygon
                  points={parcel.points}
                  fill={style.fill}
                  stroke={style.stroke}
                  strokeWidth="1.5"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                  className="cursor-pointer transition-[fill,opacity] duration-300 hover:opacity-80"
                />
                <text
                  x={parcel.label[0]}
                  y={parcel.label[1]}
                  fill="white"
                  fontSize="13"
                  fontWeight="700"
                  textAnchor="middle"
                  paintOrder="stroke"
                  stroke="rgba(15, 23, 42, 0.9)"
                  strokeWidth="3"
                  strokeLinejoin="round"
                  className="pointer-events-none select-none"
                >
                  {parcel.id}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}

function LoadingScreen({ darkMode, completedSteps }: { darkMode: boolean; completedSteps: string[] }) {
  const steps = [
    { id: "farm", title: "Loading farm profile", detail: "Preparing field boundaries and zone configuration", icon: "⌖" },
    { id: "weather", title: "Collecting weather data", detail: "Checking current conditions for the farm", icon: "☼" },
    { id: "analysis", title: "Analyzing zone signals", detail: "Validating hydration and fertilization reports", icon: "✳" },
  ];
  const completed = steps.filter((step) => completedSteps.includes(step.id)).length;
  const progress = Math.min(96, 8 + Math.round((completed / steps.length) * 84));

  return (
    <div className={`${darkMode ? "dark" : ""} ag-loading min-h-screen overflow-hidden bg-slate-50 text-slate-800`}>
      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl items-center px-5 py-12 lg:px-8">
        <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
          <div className="ag-glow ag-glow-one" />
          <div className="ag-glow ag-glow-two" />
          <div className="ag-grid-pattern" />
        </div>

        <div className="relative grid w-full items-center gap-12 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="mx-auto w-full max-w-xl lg:mx-0">
            <div className="mb-8 inline-flex items-center gap-3 rounded-full border border-emerald-200 bg-white/80 px-4 py-2 shadow-sm backdrop-blur dark:border-emerald-900 dark:bg-slate-900/80">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-700 text-xl text-white">✦</span>
              <span>
                <span className="block text-sm font-bold tracking-tight text-slate-900 dark:text-white">AgroMind <span className="text-emerald-600">AI</span></span>
                <span className="block text-[11px] uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">Farm intelligence</span>
              </span>
            </div>

            <p className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.22em] text-emerald-700 dark:text-emerald-400">
              <span className="ag-live-dot" /> Preparing your workspace
            </p>
            <h1 className="max-w-lg text-4xl font-bold leading-tight tracking-tight text-slate-950 dark:text-white sm:text-5xl">
              Turning field data into <span className="text-emerald-600 dark:text-emerald-400">clear decisions.</span>
            </h1>
            <p className="mt-5 max-w-lg text-base leading-7 text-slate-600 dark:text-slate-300">
              We’re bringing together farm configuration, local weather, and zone reports to prepare your monitoring dashboard.
            </p>

            <div className="mt-9 rounded-2xl border border-slate-200 bg-white/90 p-5 shadow-xl shadow-slate-200/40 backdrop-blur dark:border-slate-700 dark:bg-slate-900/90 dark:shadow-black/20 sm:p-6">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-slate-900 dark:text-white">Setup progress</p>
                  <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{completed} of {steps.length} data sources ready</p>
                </div>
                <span className="text-2xl font-bold tabular-nums text-emerald-700 dark:text-emerald-400">{progress}%</span>
              </div>
              <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="progressbar" aria-label="Dashboard loading progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
                <div className="ag-progress-fill h-full rounded-full bg-gradient-to-r from-emerald-600 via-lime-500 to-emerald-400 transition-all duration-700" style={{ width: `${progress}%` }} />
              </div>
              <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">Currently: <span className="font-semibold text-slate-700 dark:text-slate-200">{completed === steps.length ? "Finalizing dashboard" : "Waiting for data sources"}</span></p>

              <div className="mt-6 space-y-3">
                {steps.map((step, index) => {
                  const done = completedSteps.includes(step.id);
                  const active = !done;
                  return (
                    <div key={step.id} className={`flex items-center gap-3 rounded-xl border p-3 transition-colors ${done ? "border-emerald-100 bg-emerald-50/80 dark:border-emerald-900/70 dark:bg-emerald-950/30" : active ? "border-emerald-200 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/20" : "border-slate-100 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-800/40"}`}>
                      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-lg ${done ? "bg-emerald-600 text-white" : active ? "bg-white text-emerald-700 shadow-sm dark:bg-slate-800 dark:text-emerald-300" : "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500"}`}>
                        {done ? "✓" : active ? <span className="ag-step-pulse">{step.icon}</span> : step.icon}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={`block text-sm font-semibold ${done ? "text-emerald-900 dark:text-emerald-300" : "text-slate-800 dark:text-slate-100"}`}>{step.title}</span>
                        <span className="mt-0.5 block text-xs leading-5 text-slate-500 dark:text-slate-400">{step.detail}</span>
                      </span>
                      <span className={`shrink-0 text-[10px] font-bold uppercase tracking-wider ${done ? "text-emerald-700 dark:text-emerald-400" : active ? "text-emerald-700 dark:text-emerald-400" : "text-slate-400"}`}>{done ? "Ready" : "Working"}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <p className="mt-5 text-xs text-slate-500 dark:text-slate-400">This may take a little longer when a fresh AI analysis is required.</p>
          </div>

          <div className="relative mx-auto hidden w-full max-w-md lg:block" aria-hidden="true">
            <div className="ag-orbit-scene">
              <div className="ag-orbit ag-orbit-outer" />
              <div className="ag-orbit ag-orbit-inner" />
              <div className="ag-earth">
                <div className="ag-field-lines" />
                <div className="ag-field-glow" />
                <span className="ag-sprout">✦</span>
              </div>
              <span className="ag-float-chip ag-chip-one">⌁ <span>Soil signals</span></span>
              <span className="ag-float-chip ag-chip-two">☼ <span>Weather</span></span>
              <span className="ag-float-chip ag-chip-three">✳ <span>Zone analysis</span></span>
              <span className="ag-orbit-node ag-node-one" />
              <span className="ag-orbit-node ag-node-two" />
            </div>
            <p className="mt-2 text-center text-sm text-slate-500 dark:text-slate-400">One farm. Twelve zones. Smarter decisions.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function App() {
  const [darkMode, setDarkMode] = useState(() => {
    try {
      return window.localStorage.getItem("agromind.theme") === "dark";
    } catch {
      return false;
    }
  });
  const [farm, setFarm] = useState<Farm | null>(null);
  const [weather, setWeather] = useState<WeatherSnapshot | null>(null);
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [completedSteps, setCompletedSteps] = useState<string[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [usingCache, setUsingCache] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    try {
      window.localStorage.setItem("agromind.theme", darkMode ? "dark" : "light");
    } catch {
      // Theme persistence is optional.
    }
  }, [darkMode]);

  const load = useCallback(async (force = false) => {
    if (!force) {
      const cached = readCache();
      if (cached) {
        setFarm(cached.farm);
        setWeather(cached.weather);
        setDashboard(cached.dashboard);
        setUsingCache(true);
        setLoading(false);
        return;
      }
    }
    setError(null);
    setNotice(null);
    setCompletedSteps([]);
    if (force) setRefreshing(true);
    else setLoading(true);
    try {
      const farmPromise = fetchFarm().then((result) => {
        setCompletedSteps((current) => current.includes("farm") ? current : [...current, "farm"]);
        return result;
      });
      const weatherPromise = fetchWeather().then((result) => {
        setCompletedSteps((current) => current.includes("weather") ? current : [...current, "weather"]);
        return result;
      });
      const dashboardPromise = fetchDashboard(RUN_ID).then((result) => {
        setCompletedSteps((current) => current.includes("analysis") ? current : [...current, "analysis"]);
        return result;
      });
      const [farmResult, weatherResult, dashboardResult] = await Promise.all([
        farmPromise,
        weatherPromise,
        dashboardPromise,
      ]);
      setFarm(farmResult);
      setWeather(weatherResult);
      setDashboard(dashboardResult);
      setUsingCache(false);
      writeCache({
        farm: farmResult,
        weather: weatherResult,
        dashboard: dashboardResult,
      });
      if (force) setNotice("Fresh analysis completed.");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not load the farm dashboard.",
      );
      if (force)
        setNotice(
          "Fresh analysis failed. The last validated result remains available.",
        );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!started.current) {
      started.current = true;
      void load();
    }
  }, [load]);

  const health = useMemo(
    () =>
      !dashboard?.summary.zones_total
        ? 0
        : Math.round(
            ((dashboard.summary.zones_total -
              dashboard.summary.zones_needing_attention) /
              dashboard.summary.zones_total) *
              100,
          ),
    [dashboard],
  );

  if (loading) return <LoadingScreen darkMode={darkMode} completedSteps={completedSteps} />;
  if (!farm || !weather || !dashboard)
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
        <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-7 text-center shadow-sm">
          <h1 className="text-xl font-bold text-slate-900">
            Dashboard unavailable
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            {error ?? "The backend did not return a complete response."}
          </p>
          <button
            type="button"
            onClick={() => void load(true)}
            className="mt-5 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800"
          >
            Try again
          </button>
        </div>
      </div>
    );

  return (
    <div className={`${darkMode ? "dark" : ""} min-h-screen bg-slate-50 text-slate-800 transition-colors duration-200`}>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 lg:px-8">
          <a
            href="#top"
            className="flex items-center gap-3"
            aria-label="AgroMind dashboard home"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-700 text-xl text-white">
              ✦
            </span>
            <span>
              <span className="block text-lg font-bold tracking-tight text-slate-900">
                AgroMind <span className="text-emerald-700">AI</span>
              </span>
              <span className="block text-xs text-slate-500">
                Farm intelligence demo
              </span>
            </span>
          </a>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setDarkMode((current) => !current)}
              aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
              aria-pressed={darkMode}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700"
            >
              <span aria-hidden="true">{darkMode ? "☀️" : "🌙"}</span>
              <span className="hidden sm:inline">{darkMode ? "Light mode" : "Dark mode"}</span>
            </button>
            <span
              className={`hidden rounded-full px-3 py-1.5 text-xs font-semibold sm:inline-flex ${FALLBACK_ENABLED ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-800"}`}
            >
              {FALLBACK_ENABLED ? "Demo fallback" : "Gemini AI active"}
            </span>
            <button
              type="button"
              disabled={refreshing}
              onClick={() => void load(true)}
              className="rounded-lg border border-emerald-700 px-3 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-50 disabled:cursor-wait disabled:opacity-60"
            >
              {refreshing ? "Analyzing…" : "Refresh analysis"}
            </button>
          </div>
        </div>
        <nav
          className="border-t border-slate-100 bg-slate-50"
          aria-label="Dashboard sections"
        >
          <div className="mx-auto flex max-w-7xl gap-5 overflow-x-auto px-5 py-2 text-sm text-slate-600 lg:px-8">
            <a
              className="whitespace-nowrap hover:text-emerald-700"
              href="#overview"
            >
              Overview
            </a>
            <a
              className="whitespace-nowrap hover:text-emerald-700"
              href="#zones"
            >
              Zones
            </a>
            <a
              className="whitespace-nowrap hover:text-emerald-700"
              href="#action-plan"
            >
              Action plan
            </a>
            <a
              className="whitespace-nowrap hover:text-emerald-700"
              href="#weather"
            >
              Weather
            </a>
          </div>
        </nav>
      </header>
      <main id="top" className="mx-auto max-w-7xl space-y-5 px-5 py-6 lg:px-8">
        <section
          id="overview"
          className="flex flex-col justify-between gap-3 scroll-mt-6 sm:flex-row sm:items-end"
        >
          <div>
            <p className="text-sm font-semibold text-emerald-700">
              Farm overview
            </p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight text-slate-900">
              {farm.farm_name}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              Run {dashboard.analysis_run_id} · {farm.location.timezone}
            </p>
          </div>
          <span className="w-fit rounded-full bg-emerald-50 px-3 py-1.5 text-sm font-semibold text-emerald-800">
            ● {dashboard.status}
          </span>
        </section>
        <FarmMap zones={dashboard.zones} actions={dashboard.action_plan} />
        {usingCache && (
          <div className="flex flex-col justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900 sm:flex-row sm:items-center">
            <span>
              Showing the last validated result. Refreshing the page will not
              start another AI run.
            </span>
            <button
              type="button"
              onClick={() => void load(true)}
              className="font-semibold underline"
            >
              Run fresh analysis
            </button>
          </div>
        )}
        {notice && (
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
            {notice}
          </div>
        )}
        {error && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {error} The previous validated dashboard remains visible.
          </div>
        )}
        {FALLBACK_ENABLED && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <strong>Demo fallback is active.</strong> These results are not
            AI-generated.
          </div>
        )}
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            label="Total area"
            value={`${dashboard.summary.total_area_ha.toFixed(1)} ha`}
            detail={`${farm.zones.length} configured zones`}
          />
          <Metric
            label="Zones analyzed"
            value={`${dashboard.summary.zones_analyzed} / ${dashboard.summary.zones_total}`}
            detail="Validated zone reports"
          />
          <Metric
            label="Needs attention"
            value={`${dashboard.summary.zones_needing_attention}`}
            detail="Hydration or fertilizer signal"
          />
          <Metric
            label="Overall health"
            value={`${health}%`}
            detail="Based on this analysis run"
          />
        </section>
        <div id="weather" className="scroll-mt-6">
          <WeatherCard weather={weather} />
        </div>
        <ZoneTable zones={dashboard.zones} />
        <ActionPlan actions={dashboard.action_plan} />
        <footer className="pb-4 text-center text-xs text-slate-500">
          Evidence IDs are preserved · Recommendations require human approval ·
          Last updated from {dashboard.status} run
        </footer>
      </main>
    </div>
  );
}

export default App;
