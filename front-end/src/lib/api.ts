import type { DashboardResponse, Farm, WeatherSnapshot } from "../types";

const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const API_BASE_URL = configuredApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Keep the safe HTTP message when the server does not return JSON.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function fetchFarm(): Promise<Farm> {
  return request<Farm>("/api/v1/farm");
}

export function fetchWeather(): Promise<WeatherSnapshot> {
  return request<WeatherSnapshot>("/api/v1/weather");
}

export function fetchDashboard(analysisRunId: string): Promise<DashboardResponse> {
  return request<DashboardResponse>("/api/v1/dashboard", {
    method: "POST",
    // Let the backend's AGROMIND_BATCH_SIZE setting control how the farm is
    // split into provider requests. This keeps the frontend from accidentally
    // overriding a safer, smaller production batch size.
    body: JSON.stringify({ analysis_run_id: analysisRunId }),
  });
}
