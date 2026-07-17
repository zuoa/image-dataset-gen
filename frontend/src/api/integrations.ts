import { apiRequest } from "./client";
import type { ExternalConnection } from "../lib/types";

export function listRoboflowConnections(token: string) {
  return apiRequest<{ connections: ExternalConnection[] }>(
    "/integrations/roboflow/connections",
    { token },
  );
}

export function createRoboflowConnection(token: string, name: string, apiKey: string) {
  return apiRequest<{ connection: ExternalConnection }>(
    "/integrations/roboflow/connections",
    {
      method: "POST",
      token,
      body: JSON.stringify({ name, apiKey }),
    },
  );
}

export function validateRoboflowConnection(token: string, connectionId: string) {
  return apiRequest<{ connection: ExternalConnection }>(
    `/integrations/roboflow/connections/${connectionId}/validate`,
    { method: "POST", token, body: JSON.stringify({}) },
  );
}

export function deleteRoboflowConnection(token: string, connectionId: string) {
  return apiRequest<{ deleted: boolean; id: string }>(
    `/integrations/roboflow/connections/${connectionId}`,
    { method: "DELETE", token },
  );
}
