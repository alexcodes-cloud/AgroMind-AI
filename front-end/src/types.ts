export type HealthStatus = "normal" | "investigation_needed" | "insufficient_evidence";
export type Risk = "low" | "medium" | "high" | "unknown";

export interface WeatherSnapshot {
  source: string;
  current: {
    temperature_c: number | null;
    relative_humidity_pct: number | null;
    wind_speed_kmh: number | null;
    precipitation_mm: number | null;
    et0_mm: number | null;
  } | null;
}

export interface Farm {
  farm_id: string;
  farm_name: string;
  location: { latitude: number; longitude: number; timezone: string };
  zones: Array<{ zone_id: string; area_ha: number }>;
}

export interface DashboardZone {
  zone_id: string;
  hydration_status: HealthStatus;
  hydration_risk: Risk;
  fertilization_status: HealthStatus;
  fertilization_risk: Risk;
  last_updated_at: string | null;
}

export interface Priority {
  priority: number;
  zone_id: string;
  domain: "hydration" | "fertilization";
  action: string;
  reason: string;
  evidence_refs: string[];
  uncertainty: string;
  requires_human_approval: boolean;
}

export interface DashboardResponse {
  schema_version: "1.0";
  farm_id: string;
  analysis_run_id: string;
  status: "completed" | "processing" | "partial" | "failed";
  summary: {
    total_area_ha: number;
    zones_total: number;
    zones_analyzed: number;
    zones_needing_attention: number;
  };
  zones: DashboardZone[];
  action_plan: Priority[];
  error?: string | null;
}
