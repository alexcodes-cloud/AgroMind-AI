import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchDashboard, fetchFarm, fetchWeather } from "./lib/api";
import type { DashboardResponse, DashboardZone, Farm, Priority, WeatherSnapshot } from "./types";

const FALLBACK_ENABLED = import.meta.env.VITE_DEMO_FALLBACK === "true";
const RUN_ID = "live_demo_001";
const CACHE_KEY = `agromind.dashboard.cache.v1.${FALLBACK_ENABLED ? "fallback" : "gemini"}`;
const CACHE_TTL_MS = 5 * 60 * 1000;

type DashboardCache = { savedAt: number; farm: Farm; weather: WeatherSnapshot; dashboard: DashboardResponse };

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
  } catch { return null; }
}

function writeCache(value: Omit<DashboardCache, "savedAt">) {
  try { window.sessionStorage.setItem(CACHE_KEY, JSON.stringify({ ...value, savedAt: Date.now() })); } catch { /* optional optimization */ }
}

function statusLabel(status: DashboardZone["hydration_status"]) {
  if (status === "investigation_needed") return "Needs review";
  if (status === "insufficient_evidence") return "Insufficient data";
  return "Normal";
}

function statusTone(status: DashboardZone["hydration_status"]) {
  if (status === "investigation_needed") return "border-amber-200 bg-amber-50 text-amber-800";
  if (status === "insufficient_evidence") return "border-slate-200 bg-slate-50 text-slate-600";
  return "border-emerald-200 bg-emerald-50 text-emerald-800";
}

function riskTone(risk: DashboardZone["hydration_risk"]) {
  if (risk === "high") return "text-red-700";
  if (risk === "medium") return "text-amber-700";
  if (risk === "unknown") return "text-slate-500";
  return "text-emerald-700";
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-2xl font-bold text-slate-900">{value}</p>{detail && <p className="mt-1 text-sm text-slate-500">{detail}</p>}</div>;
}

function WeatherCard({ weather }: { weather: WeatherSnapshot }) {
  const current = weather.current;
  const values = [["Temperature", current?.temperature_c == null ? "—" : `${current.temperature_c} °C`], ["Humidity", current?.relative_humidity_pct == null ? "—" : `${current.relative_humidity_pct}%`], ["Wind", current?.wind_speed_kmh == null ? "—" : `${current.wind_speed_kmh} km/h`], ["Rain", current?.precipitation_mm == null ? "—" : `${current.precipitation_mm} mm`]];
  return <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Weather snapshot</p><h2 className="mt-1 text-lg font-semibold text-slate-900">Current field conditions</h2></div><span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">{weather.source}</span></div><div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">{values.map(([label, value]) => <div key={label}><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold text-slate-900">{value}</p></div>)}</div></section>;
}

function ZoneTable({ zones }: { zones: DashboardZone[] }) {
  return <section id="zones" className="scroll-mt-6 rounded-xl border border-slate-200 bg-white shadow-sm"><div className="flex flex-col gap-1 border-b border-slate-200 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="font-semibold text-slate-900">Zone monitoring</h2><p className="text-sm text-slate-500">Validated hydration and fertilization signals.</p></div><span className="text-sm text-slate-500">{zones.length} zones in this run</span></div><div className="overflow-x-auto"><table className="min-w-full text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-5 py-3 font-semibold">Zone</th><th className="px-5 py-3 font-semibold">Hydration</th><th className="px-5 py-3 font-semibold">Hydration risk</th><th className="px-5 py-3 font-semibold">Fertilization</th><th className="px-5 py-3 font-semibold">Updated</th></tr></thead><tbody className="divide-y divide-slate-100">{zones.map((zone) => <tr key={zone.zone_id} className="hover:bg-slate-50"><td className="whitespace-nowrap px-5 py-4 font-semibold text-slate-900">{zone.zone_id}</td><td className="px-5 py-4"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(zone.hydration_status)}`}>{statusLabel(zone.hydration_status)}</span></td><td className={`px-5 py-4 font-semibold capitalize ${riskTone(zone.hydration_risk)}`}>{zone.hydration_risk}</td><td className="px-5 py-4"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(zone.fertilization_status)}`}>{statusLabel(zone.fertilization_status)}</span></td><td className="whitespace-nowrap px-5 py-4 text-slate-500">{zone.last_updated_at ? new Date(zone.last_updated_at).toLocaleString() : "Not available"}</td></tr>)}</tbody></table></div></section>;
}

function ActionPlan({ actions }: { actions: Priority[] }) {
  return <section id="action-plan" className="scroll-mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-4"><div><h2 className="font-semibold text-slate-900">Recommended actions</h2><p className="mt-1 text-sm text-slate-500">AI suggestions grounded in the validated zone reports.</p></div><span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-800">Human review required</span></div>{actions.length === 0 ? <p className="mt-5 rounded-lg bg-slate-50 p-4 text-sm text-slate-600">No actions were returned for this analysis run.</p> : <ol className="mt-5 space-y-3">{actions.map((item, index) => <li key={`${item.zone_id}-${item.domain}-${item.priority}`} className="flex gap-3 rounded-lg border border-slate-100 bg-slate-50 p-4"><span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-xs font-bold text-emerald-800">{index + 1}</span><div className="min-w-0"><p className="font-semibold text-slate-900">Zone {item.zone_id} · {item.domain}</p><p className="mt-1 text-sm text-slate-700">{item.action}</p><p className="mt-1 text-xs text-slate-500">{item.reason}</p>{item.evidence_refs.length > 0 && <p className="mt-2 text-xs font-medium text-emerald-700">Evidence: {item.evidence_refs.join(", ")}</p>}</div></li>)}</ol>}</section>;
}

function App() {
  const [farm, setFarm] = useState<Farm | null>(null);
  const [weather, setWeather] = useState<WeatherSnapshot | null>(null);
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [usingCache, setUsingCache] = useState(false);
  const started = useRef(false);

  const load = useCallback(async (force = false) => {
    if (!force) {
      const cached = readCache();
      if (cached) { setFarm(cached.farm); setWeather(cached.weather); setDashboard(cached.dashboard); setUsingCache(true); setLoading(false); return; }
    }
    setError(null); setNotice(null); if (force) setRefreshing(true); else setLoading(true);
    try {
      const [farmResult, weatherResult, dashboardResult] = await Promise.all([fetchFarm(), fetchWeather(), fetchDashboard(RUN_ID)]);
      setFarm(farmResult); setWeather(weatherResult); setDashboard(dashboardResult); setUsingCache(false); writeCache({ farm: farmResult, weather: weatherResult, dashboard: dashboardResult }); if (force) setNotice("Fresh analysis completed.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load the farm dashboard.");
      if (force) setNotice("Fresh analysis failed. The last validated result remains available.");
    } finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { if (!started.current) { started.current = true; void load(); } }, [load]);

  const health = useMemo(() => !dashboard?.summary.zones_total ? 0 : Math.round(((dashboard.summary.zones_total - dashboard.summary.zones_needing_attention) / dashboard.summary.zones_total) * 100), [dashboard]);

  if (loading) return <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6"><div className="text-center"><div className="mx-auto h-9 w-9 animate-spin rounded-full border-4 border-emerald-100 border-t-emerald-700" /><p className="mt-4 font-semibold text-slate-800">Loading your farm dashboard…</p><p className="mt-1 text-sm text-slate-500">A fresh AI run may take a moment.</p></div></div>;
  if (!farm || !weather || !dashboard) return <div className="flex min-h-screen items-center justify-center bg-slate-50 px-6"><div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-7 text-center shadow-sm"><h1 className="text-xl font-bold text-slate-900">Dashboard unavailable</h1><p className="mt-2 text-sm leading-6 text-slate-600">{error ?? "The backend did not return a complete response."}</p><button type="button" onClick={() => void load(true)} className="mt-5 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800">Try again</button></div></div>;

  return <div className="min-h-screen bg-slate-50 text-slate-800"><header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4 lg:px-8"><a href="#top" className="flex items-center gap-3" aria-label="AgroMind dashboard home"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-700 text-xl text-white">✦</span><span><span className="block text-lg font-bold tracking-tight text-slate-900">AgroMind <span className="text-emerald-700">AI</span></span><span className="block text-xs text-slate-500">Farm intelligence demo</span></span></a><div className="flex items-center gap-3"><span className={`hidden rounded-full px-3 py-1.5 text-xs font-semibold sm:inline-flex ${FALLBACK_ENABLED ? "bg-amber-50 text-amber-800" : "bg-emerald-50 text-emerald-800"}`}>{FALLBACK_ENABLED ? "Demo fallback" : "Gemini AI active"}</span><button type="button" disabled={refreshing} onClick={() => void load(true)} className="rounded-lg border border-emerald-700 px-3 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-50 disabled:cursor-wait disabled:opacity-60">{refreshing ? "Analyzing…" : "Refresh analysis"}</button></div></div><nav className="border-t border-slate-100 bg-slate-50" aria-label="Dashboard sections"><div className="mx-auto flex max-w-7xl gap-5 overflow-x-auto px-5 py-2 text-sm text-slate-600 lg:px-8"><a className="whitespace-nowrap hover:text-emerald-700" href="#overview">Overview</a><a className="whitespace-nowrap hover:text-emerald-700" href="#zones">Zones</a><a className="whitespace-nowrap hover:text-emerald-700" href="#action-plan">Action plan</a><a className="whitespace-nowrap hover:text-emerald-700" href="#weather">Weather</a></div></nav></header><main id="top" className="mx-auto max-w-7xl space-y-5 px-5 py-6 lg:px-8"><section id="overview" className="flex flex-col justify-between gap-3 scroll-mt-6 sm:flex-row sm:items-end"><div><p className="text-sm font-semibold text-emerald-700">Farm overview</p><h1 className="mt-1 text-3xl font-bold tracking-tight text-slate-900">{farm.farm_name}</h1><p className="mt-1 text-sm text-slate-500">Run {dashboard.analysis_run_id} · {farm.location.timezone}</p></div><span className="w-fit rounded-full bg-emerald-50 px-3 py-1.5 text-sm font-semibold text-emerald-800">● {dashboard.status}</span></section>{usingCache && <div className="flex flex-col justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900 sm:flex-row sm:items-center"><span>Showing the last validated result. Refreshing the page will not start another AI run.</span><button type="button" onClick={() => void load(true)} className="font-semibold underline">Run fresh analysis</button></div>}{notice && <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">{notice}</div>}{error && <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{error} The previous validated dashboard remains visible.</div>}{FALLBACK_ENABLED && <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"><strong>Demo fallback is active.</strong> These results are not AI-generated.</div>}<section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Metric label="Total area" value={`${dashboard.summary.total_area_ha.toFixed(1)} ha`} detail={`${farm.zones.length} configured zones`} /><Metric label="Zones analyzed" value={`${dashboard.summary.zones_analyzed} / ${dashboard.summary.zones_total}`} detail="Validated zone reports" /><Metric label="Needs attention" value={`${dashboard.summary.zones_needing_attention}`} detail="Hydration or fertilizer signal" /><Metric label="Overall health" value={`${health}%`} detail="Based on this analysis run" /></section><div id="weather" className="scroll-mt-6"><WeatherCard weather={weather} /></div><ZoneTable zones={dashboard.zones} /><ActionPlan actions={dashboard.action_plan} /><footer className="pb-4 text-center text-xs text-slate-500">Evidence IDs are preserved · Recommendations require human approval · Last updated from {dashboard.status} run</footer></main></div>;
}

export default App;
