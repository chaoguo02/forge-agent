import { apiGet } from "./client";

export interface ModelCatalogItem {
  key: string;
  family: string;
  note: string;
}

export function getModelCatalog(signal?: AbortSignal): Promise<ModelCatalogItem[]> {
  return apiGet("/api/config/models", signal);
}
