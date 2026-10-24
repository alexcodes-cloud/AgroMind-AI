import type { DashboardResponse, Farm, WeatherSnapshot } from "../types";

const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const API_BASE_URL = configuredApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
const MAX_REQUEST_ATTEMPTS = 3;
const RETRYABLE_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504]);

function waitForRetry(attempt: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, 700 * 2 ** attempt));
}

async function request<T>(path: string, init?: RequestInit, attempt = 0): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (error) {
    if (attempt < MAX_REQUEST_ATTEMPTS - 1) {
      await waitForRetry(attempt);
      return request<T>(path, init, attempt + 1);
    }
    throw error;
  }
  if (!response.ok) {
    let detail = `Request failed with HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Keep the safe HTTP message when the server does not return JSON.
    }
    if (RETRYABLE_STATUS_CODES.has(response.status) && attempt < MAX_REQUEST_ATTEMPTS - 1) {
      await waitForRetry(attempt);
      return request<T>(path, init, attempt + 1);
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
    body: JSON.stringify({ analysis_run_id: analysisRunId, batch_size: 4 }),
  });
}
