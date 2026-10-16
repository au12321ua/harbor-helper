import { api, type Docker } from "@/api";
import { useState } from "react";
export function useDockerDiagnostics() {
  const [docker, setDocker] = useState<Docker>();
  const [dockerBusy, setDockerBusy] = useState(false);
  const [dockerError, setDockerError] = useState<unknown>();
  async function discoverDocker() {
    setDockerBusy(true);
    setDockerError(undefined);
    try {
      setDocker(await api("/admin/docker"));
    } catch (e) {
      setDockerError(e);
    } finally {
      setDockerBusy(false);
    }
  }
  return { docker, dockerBusy, dockerError, discoverDocker };
}
