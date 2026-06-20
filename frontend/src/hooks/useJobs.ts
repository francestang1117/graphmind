import axios from "axios";
import { useCallback, useEffect, useMemo, useState } from "react";
import { cancelJob, listJobs, type JobHistoryItem } from "../services/api";

const activeStates = new Set(["PENDING", "STARTED", "PROGRESS"]);

export function isActiveJob(job: JobHistoryItem) {
  return activeStates.has(job.status.toUpperCase());
}

export function useJobs(refreshKey = "") {
  const [jobs, setJobs] = useState<JobHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const hasActiveJob = useMemo(() => jobs.some(isActiveJob), [jobs]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setJobs(await listJobs(8));
    } catch (err) {
      if (axios.isAxiosError(err)) {
        if (err.response?.status === 404) {
          setError("Job history endpoint is not available. Restart the backend with the latest code.");
          return;
        }
        if (!err.response) {
          setError("Job history is waiting for the backend. Start the API server and refresh.");
          return;
        }
      }
      setError("Job history is unavailable right now. Uploads still work.");
    } finally {
      setLoading(false);
    }
  }, []);

  const cancel = useCallback(
    async (jobId: string) => {
      await cancelJob(jobId);
      await refresh();
    },
    [refresh],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh, refreshKey]);

  useEffect(() => {
    if (!hasActiveJob) return;

    // Keep the history panel current even if the upload row has disappeared.
    const timer = window.setInterval(refresh, 3500);
    return () => window.clearInterval(timer);
  }, [hasActiveJob, refresh]);

  return { jobs, loading, error, hasActiveJob, refresh, cancel };
}
