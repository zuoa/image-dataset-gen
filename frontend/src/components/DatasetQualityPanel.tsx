import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Microscope, RefreshCw, X } from "lucide-react";
import { Link } from "react-router-dom";

import {
  createDatasetQualityRun,
  listDatasetQualityIssues,
  listDatasetQualityRuns,
  updateDatasetQualityIssue,
} from "../api/datasets";
import type { QualityIssue, QualityRun } from "../lib/types";
import { formatDate } from "../lib/utils";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { SectionCard } from "./ui/SectionCard";

const issueLabels: Record<string, string> = {
  missing_annotation: "缺少标注",
  empty_annotation: "空标注",
  out_of_bounds_box: "框越界",
  tiny_box: "极小目标",
  large_box: "极大目标",
  extreme_aspect_ratio: "异常比例",
  duplicate_box: "重复框",
  exact_duplicate_image: "重复图片",
  missing_image_asset: "图片文件缺失",
  corrupt_image_asset: "图片文件损坏",
  false_positive: "误检",
  false_negative: "漏检",
  class_confusion: "类别混淆",
  low_iou: "定位偏差",
};

type DatasetQualityPanelProps = {
  datasetId: string;
  token: string | null;
  imageCount: number;
};

function latestRun(runs: QualityRun[], type: "dataset" | "model") {
  return runs.find((run) => run.runType === type);
}

export function DatasetQualityPanel({ datasetId, token, imageCount }: DatasetQualityPanelProps) {
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [issues, setIssues] = useState<QualityIssue[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dataRun = latestRun(runs, "dataset");
  const modelRun = latestRun(runs, "model");
  const issueRun = dataRun?.status === "completed" ? dataRun : modelRun?.status === "completed" ? modelRun : undefined;
  const hasActiveRun = runs.some((run) => run.status === "queued" || run.status === "running");

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      const response = await listDatasetQualityRuns(datasetId, token);
      setRuns(response.qualityRuns);
      const nextDataRun = latestRun(response.qualityRuns, "dataset");
      const nextModelRun = latestRun(response.qualityRuns, "model");
      const nextIssueRun = nextDataRun?.status === "completed" ? nextDataRun : nextModelRun?.status === "completed" ? nextModelRun : undefined;
      if (nextIssueRun) {
        const issueResponse = await listDatasetQualityIssues(datasetId, nextIssueRun.id, token, {
          status: "open",
          limit: 8,
        });
        setIssues(issueResponse.issues);
      } else {
        setIssues([]);
      }
      setError(null);
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setIsLoading(false);
    }
  }, [datasetId, token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!hasActiveRun) return;
    const timeoutId = window.setTimeout(() => void refresh(), 4000);
    return () => window.clearTimeout(timeoutId);
  }, [hasActiveRun, refresh, runs]);

  async function startQualityRun() {
    if (!token || imageCount === 0) return;
    setIsStarting(true);
    try {
      await createDatasetQualityRun(datasetId, token);
      await refresh();
    } catch (startError) {
      setError((startError as Error).message);
    } finally {
      setIsStarting(false);
    }
  }

  async function dismissIssue(issueId: string) {
    if (!token) return;
    try {
      await updateDatasetQualityIssue(datasetId, issueId, token, "dismissed");
      setIssues((current) => current.filter((issue) => issue.id !== issueId));
    } catch (dismissError) {
      setError((dismissError as Error).message);
    }
  }

  const severityCounts = dataRun?.summary.issuesBySeverity ?? {};
  const severityTotal = Math.max(
    1,
    (severityCounts.error ?? 0) + (severityCounts.warning ?? 0) + (severityCounts.info ?? 0),
  );
  const qualityScore = dataRun?.summary.qualityScore;
  const topIssueTypes = useMemo(
    () => Object.entries(dataRun?.summary.issuesByType ?? {}).sort((left, right) => right[1] - left[1]).slice(0, 5),
    [dataRun?.summary.issuesByType],
  );
  const modelMetrics = modelRun?.summary.metrics ?? {};

  return (
    <SectionCard className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-neutral-500">
            <Microscope className="h-4 w-4" />
            Quality loop
          </div>
          <h3 className="mt-2 text-2xl text-neutral-900 dark:text-white">数据与模型质量</h3>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            检查标注结构、样本分布和重复数据；训练完成后自动把误检与漏检送回复核。
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => void startQualityRun()}
          disabled={imageCount === 0 || isStarting || hasActiveRun}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${isStarting || hasActiveRun ? "animate-spin" : ""}`} />
          {hasActiveRun ? "检查中" : dataRun ? "重新检查" : "开始检查"}
        </Button>
      </div>

      {error ? <div className="mt-4 text-sm text-red-600 dark:text-red-300">{error}</div> : null}

      <div className="mt-6 grid gap-4 xl:grid-cols-[240px_minmax(0,1fr)_300px]">
        <div className="rounded-[24px] border border-neutral-200 bg-neutral-950 p-5 text-white dark:border-white/10">
          <div className="text-xs uppercase tracking-[0.22em] text-neutral-400">数据质量分</div>
          <div className="mt-4 flex items-end gap-2">
            <span className="text-5xl font-medium tracking-tight">{qualityScore ?? "—"}</span>
            {qualityScore !== undefined ? <span className="pb-1 text-sm text-neutral-400">/ 100</span> : null}
          </div>
          <div className="mt-5 flex h-2 overflow-hidden rounded-full bg-white/10" aria-label="问题严重度分布">
            <span className="bg-rose-500" style={{ width: `${((severityCounts.error ?? 0) / severityTotal) * 100}%` }} />
            <span className="bg-amber-400" style={{ width: `${((severityCounts.warning ?? 0) / severityTotal) * 100}%` }} />
            <span className="bg-sky-400" style={{ width: `${((severityCounts.info ?? 0) / severityTotal) * 100}%` }} />
          </div>
          <div className="mt-3 flex justify-between text-xs text-neutral-400">
            <span>{dataRun?.issueCounts.open ?? 0} 个待处理</span>
            <span>{dataRun?.completedAt ? formatDate(dataRun.completedAt) : isLoading ? "读取中" : "尚未检查"}</span>
          </div>
        </div>

        <div className="rounded-[24px] border border-neutral-200 p-5 dark:border-white/10">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium text-neutral-900 dark:text-white">主要问题</div>
            {dataRun?.supervisionVersion ? <Badge>Supervision {dataRun.supervisionVersion}</Badge> : null}
          </div>
          <div className="mt-4 space-y-3">
            {topIssueTypes.length ? topIssueTypes.map(([type, count]) => (
              <div key={type} className="flex items-center justify-between gap-4 text-sm">
                <span className="text-neutral-600 dark:text-neutral-300">{issueLabels[type] ?? type}</span>
                <span className="tabular-nums text-neutral-900 dark:text-white">{count}</span>
              </div>
            )) : (
              <div className="flex min-h-24 items-center text-sm text-neutral-500">
                {dataRun?.status === "completed" ? "没有发现结构性问题。" : "运行一次检查后，这里会显示问题分布。"}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-[24px] border border-neutral-200 p-5 dark:border-white/10">
          <div className="text-sm font-medium text-neutral-900 dark:text-white">最近模型评测</div>
          {modelRun?.status === "completed" ? (
            <div className="mt-4 grid grid-cols-2 gap-3">
              <Metric label="mAP50" value={modelMetrics.mAP50} />
              <Metric label="mAP50–95" value={modelMetrics.mAP50_95} />
              <Metric label="问题样本" value={modelRun.summary.issueCount} integer />
              <Metric label="评测集" value={modelRun.summary.split ?? "val"} text />
            </div>
          ) : (
            <div className="mt-4 min-h-24 text-sm leading-6 text-neutral-500">
              训练完成后自动生成评测，结果与错误样本会显示在这里。
            </div>
          )}
        </div>
      </div>

      {issueRun && issues.length ? (
        <div className="mt-6 border-t border-neutral-200 pt-5 dark:border-white/10">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium text-neutral-900 dark:text-white">待复核样本</div>
            <Link to={`/datasets/${datasetId}/annotate`} className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-white">
              进入标注模式
            </Link>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
            {issues.map((issue) => (
              <div key={issue.id} className="flex items-center gap-3 rounded-2xl bg-neutral-100 px-3 py-3 dark:bg-white/[0.04]">
                {issue.severity === "error" ? <AlertTriangle className="h-4 w-4 shrink-0 text-rose-500" /> : <CheckCircle2 className="h-4 w-4 shrink-0 text-amber-500" />}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-neutral-800 dark:text-neutral-200">样本 #{issue.image?.ordinal ?? "—"}</div>
                  <div className="truncate text-xs text-neutral-500">{issueLabels[issue.issueType] ?? issue.issueType}</div>
                </div>
                <button type="button" className="rounded-full p-1 text-neutral-400 hover:bg-neutral-200 hover:text-neutral-800 dark:hover:bg-white/10 dark:hover:text-white" onClick={() => void dismissIssue(issue.id)} aria-label="忽略此问题">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

function Metric({ label, value, integer = false, text = false }: { label: string; value: unknown; integer?: boolean; text?: boolean }) {
  let display = "—";
  if (text && typeof value === "string") display = value;
  else if (typeof value === "number") display = integer ? String(Math.round(value)) : value.toFixed(3);
  return (
    <div className="rounded-2xl bg-neutral-100 p-3 dark:bg-white/[0.04]">
      <div className="text-[10px] uppercase tracking-[0.18em] text-neutral-500">{label}</div>
      <div className="mt-2 text-lg tabular-nums text-neutral-900 dark:text-white">{display}</div>
    </div>
  );
}
