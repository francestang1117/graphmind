import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { isActiveJob, useJobs } from "../../hooks/useJobs";
import type { JobHistoryItem } from "../../services/api";
import { formatDate } from "../../utils/fileMeta";

interface Props {
  refreshKey?: string;
}

function jobTone(job: JobHistoryItem) {
  const status = job.status.toUpperCase();
  if (["SUCCESS", "DONE"].includes(status)) return "done";
  if (["FAILURE", "ERROR", "REVOKED"].includes(status)) return "error";
  return "processing";
}

function jobLabel(job: JobHistoryItem) {
  const status = job.status.toUpperCase();
  if (status === "SUCCESS") return "Done";
  if (status === "REVOKED") return "Cancelled";
  if (["FAILURE", "ERROR"].includes(status)) return "Failed";
  if (status === "PENDING") return "Queued";
  return "Running";
}

function jobIcon(job: JobHistoryItem) {
  const tone = jobTone(job);
  if (tone === "done") return <CheckCircle2 size={13} />;
  if (tone === "error") return <AlertCircle size={13} />;
  return <Loader2 className="spin" size={13} />;
}

export default function JobHistory({ refreshKey = "" }: Props) {
  const { jobs, loading, error, hasActiveJob, refresh, cancel } = useJobs(refreshKey);

  return (
    <section className="job-history" aria-label="Recent processing jobs">
      <div className="job-history-header">
        <div>
          <span className="section-heading">Recent jobs</span>
          <p>
            {hasActiveJob
              ? "Worker activity is live."
              : "Latest background processing runs."}
          </p>
        </div>
        <button type="button" onClick={refresh} aria-label="Refresh recent jobs">
          {loading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}
        </button>
      </div>

      {error && <div className="job-history-error">{error}</div>}

      {!error && jobs.length === 0 && (
        <div className="job-history-empty">
          <Clock3 size={15} />
          <span>No worker jobs yet.</span>
          <small>Celery uploads and retries will show up here.</small>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="job-history-list">
          {jobs.map((job) => {
            const tone = jobTone(job);
            const progress = Math.max(0, Math.min(100, job.progress ?? 0));
            const updatedAt = job.updated_at || job.finished_at || job.created_at || "";

            return (
              <article className="job-row" key={job.job_id}>
                <div className={`job-icon ${tone}`}>
                  {tone === "processing" ? <Clock3 size={15} /> : jobIcon(job)}
                </div>
                <div className="job-main">
                  <div className="job-title-line">
                    <strong>{job.original_filename || job.document_id}</strong>
                    <span className={`status-pill ${tone}`}>
                      {jobIcon(job)}
                      {jobLabel(job)}
                    </span>
                  </div>
                  <div className="job-meta">
                    <span>{job.step || "Waiting"}</span>
                    {updatedAt && <span>{formatDate(updatedAt)}</span>}
                  </div>
                  {tone === "processing" && (
                    <div className="job-progress" aria-label={`${progress}% complete`}>
                      <div style={{ width: `${progress}%` }} />
                    </div>
                  )}
                  {job.error && <small>{job.error}</small>}
                </div>
                {isActiveJob(job) && (
                  <button
                    className="job-cancel"
                    type="button"
                    aria-label={`Cancel ${job.original_filename}`}
                    onClick={() => cancel(job.job_id)}
                  >
                    <XCircle size={16} />
                  </button>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
