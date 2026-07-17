import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Microscope, RefreshCw, X } from "lucide-react";
import { Link } from "react-router-dom";
import {
  Button,
  Card,
  Col,
  List,
  Progress,
  Row,
  Tag,
  Typography,
} from "antd";

import {
  createDatasetQualityRun,
  listDatasetQualityIssues,
  updateDatasetQualityIssue,
} from "../api/datasets";
import { useQualityRuns } from "../hooks/useQualityRuns";
import { useAuthStore } from "../store/auth";
import type { QualityIssue, QualityRun } from "../lib/types";
import { formatDate } from "../lib/utils";

const { Text } = Typography;

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

interface DatasetQualityPanelProps {
  datasetId: string;
  imageCount: number;
}

function latestRun(runs: QualityRun[], type: "dataset" | "model") {
  return runs.find((run) => run.runType === type);
}

export function DatasetQualityPanel({
  datasetId,
  imageCount,
}: DatasetQualityPanelProps) {
  const token = useAuthStore((state) => state.token);
  const { data: runsData, isLoading: isLoadingRuns, refetch } = useQualityRuns(
    datasetId,
  );
  const [issues, setIssues] = useState<QualityIssue[]>([]);

  const runs = runsData?.qualityRuns ?? [];
  const dataRun = latestRun(runs, "dataset");
  const modelRun = latestRun(runs, "model");
  const issueRun =
    dataRun?.status === "completed"
      ? dataRun
      : modelRun?.status === "completed"
        ? modelRun
        : undefined;
  const hasActiveRun = runs.some(
    (run) => run.status === "queued" || run.status === "running",
  );

  const refresh = useCallback(async () => {
    await refetch();
  }, [refetch]);

  useEffect(() => {
    if (!token || !issueRun) {
      setIssues([]);
      return;
    }
    let disposed = false;
    void listDatasetQualityIssues(datasetId, issueRun.id, token, {
      status: "open",
      limit: 8,
    })
      .then((response) => {
        if (!disposed) setIssues(response.issues);
      })
      .catch(() => {
        if (!disposed) setIssues([]);
      });
    return () => {
      disposed = true;
    };
  }, [datasetId, issueRun, token]);

  async function startQualityRun() {
    if (!token || imageCount === 0) return;
    try {
      await createDatasetQualityRun(datasetId, token);
      await refresh();
    } catch (startError) {
      // eslint-disable-next-line no-console
      console.error(startError);
    }
  }

  async function dismissIssue(issueId: string) {
    if (!token) return;
    try {
      await updateDatasetQualityIssue(datasetId, issueId, token, "dismissed");
      setIssues((current) => current.filter((issue) => issue.id !== issueId));
    } catch (dismissError) {
      // eslint-disable-next-line no-console
      console.error(dismissError);
    }
  }

  const severityCounts = dataRun?.summary.issuesBySeverity ?? {};
  const severityTotal = Math.max(
    1,
    (severityCounts.error ?? 0) +
      (severityCounts.warning ?? 0) +
      (severityCounts.info ?? 0),
  );
  const qualityScore = dataRun?.summary.qualityScore;
  const topIssueTypes = useMemo(
    () =>
      Object.entries(dataRun?.summary.issuesByType ?? {})
        .sort((left, right) => right[1] - left[1])
        .slice(0, 5),
    [dataRun?.summary.issuesByType],
  );
  const modelMetrics = modelRun?.summary.metrics ?? {};

  return (
    <Card className="mt-6 shadow-panel">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            <Microscope className="h-4 w-4" />
            Quality loop
          </div>
          <Typography.Title level={3} className="mt-2 !text-2xl">
            数据与模型质量
          </Typography.Title>
          <Text className="block max-w-2xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            检查标注结构、样本分布和重复数据；训练完成后自动把误检与漏检送回复核。
          </Text>
        </div>
        <Button
          icon={<RefreshCw className="h-4 w-4" />}
          onClick={() => void startQualityRun()}
          disabled={imageCount === 0 || hasActiveRun}
          loading={hasActiveRun}
        >
          {hasActiveRun ? "检查中" : dataRun ? "重新检查" : "开始检查"}
        </Button>
      </div>

      <Row gutter={[16, 16]} className="mt-6">
        <Col xs={24} md={12} xl={6}>
          <Card className="h-full bg-neutral-950 text-white">
            <div className="text-xs uppercase tracking-[0.18em] text-neutral-400">
              数据质量分
            </div>
            <div className="mt-4 flex items-end gap-2">
              <span className="text-5xl font-medium tracking-tight">
                {qualityScore ?? "—"}
              </span>
              {qualityScore !== undefined ? (
                <span className="pb-1 text-sm text-neutral-400">/ 100</span>
              ) : null}
            </div>
            <Progress
              percent={100}
              success={{ percent: ((severityCounts.error ?? 0) / severityTotal) * 100 }}
              className="mt-5"
              showInfo={false}
            />
            <div className="mt-3 flex justify-between text-xs text-neutral-400">
              <span>{dataRun?.issueCounts.open ?? 0} 个待处理</span>
              <span>
                {dataRun?.completedAt
                  ? formatDate(dataRun.completedAt)
                  : isLoadingRuns
                    ? "读取中"
                    : "尚未检查"}
              </span>
            </div>
          </Card>
        </Col>

        <Col xs={24} md={12} xl={12}>
          <Card className="h-full">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium">主要问题</div>
              {dataRun?.supervisionVersion ? (
                <Tag bordered>Supervision {dataRun.supervisionVersion}</Tag>
              ) : null}
            </div>
            <List
              className="mt-4"
              dataSource={topIssueTypes}
              locale={{
                emptyText: (
                  <div className="flex min-h-24 items-center text-sm text-neutral-500">
                    {dataRun?.status === "completed"
                      ? "没有发现结构性问题。"
                      : "运行一次检查后，这里会显示问题分布。"}
                  </div>
                ),
              }}
              renderItem={([type, count]) => (
                <List.Item
                  key={type}
                  className="flex items-center justify-between gap-4 text-sm"
                >
                  <span className="text-neutral-600 dark:text-neutral-300">
                    {issueLabels[type] ?? type}
                  </span>
                  <span className="tabular-nums">{count}</span>
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} md={12} xl={6}>
          <Card className="h-full">
            <div className="text-sm font-medium">最近模型评测</div>
            {modelRun?.status === "completed" ? (
              <Row gutter={[12, 12]} className="mt-4">
                <Col span={12}>
                  <Metric label="mAP50" value={modelMetrics.mAP50} />
                </Col>
                <Col span={12}>
                  <Metric label="mAP50–95" value={modelMetrics.mAP50_95} />
                </Col>
                <Col span={12}>
                  <Metric label="问题样本" value={modelRun.summary.issueCount} />
                </Col>
                <Col span={12}>
                  <Metric label="评测集" value={modelRun.summary.split ?? "val"} />
                </Col>
              </Row>
            ) : (
              <div className="mt-4 min-h-24 text-sm leading-6 text-neutral-500">
                训练完成后自动生成评测，结果与错误样本会显示在这里。
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {issueRun && issues.length > 0 ? (
        <div className="mt-6 border-t border-neutral-200 pt-5 dark:border-white/10">
          <div className="flex items-center justify-between gap-3">
            <div className="text-sm font-medium">待复核样本</div>
            <Link
              to={`/datasets/${datasetId}/annotate`}
              className="text-sm text-neutral-500 hover:text-neutral-900 dark:hover:text-white"
            >
              进入标注模式
            </Link>
          </div>
          <List
            grid={{ gutter: 8, xs: 1, sm: 1, md: 2, lg: 2, xl: 4, xxl: 4 }}
            dataSource={issues}
            locale={{ emptyText: null }}
            renderItem={(issue) => (
              <List.Item key={issue.id}>
                <Card className="w-full">
                  <div className="flex items-center gap-3">
                    {issue.severity === "error" ? (
                      <AlertTriangle className="h-4 w-4 shrink-0 text-rose-500" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4 shrink-0 text-amber-500" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm">
                        样本 #{issue.image?.ordinal ?? "—"}
                      </div>
                      <div className="truncate text-xs text-neutral-500">
                        {issueLabels[issue.issueType] ?? issue.issueType}
                      </div>
                    </div>
                    <Button
                      type="text"
                      size="small"
                      shape="circle"
                      icon={<X className="h-3.5 w-3.5" />}
                      onClick={() => void dismissIssue(issue.id)}
                      aria-label="忽略此问题"
                    />
                  </div>
                </Card>
              </List.Item>
            )}
          />
        </div>
      ) : null}
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: unknown }) {
  let display = "—";
  if (typeof value === "string") display = value;
  else if (typeof value === "number") display = String(value);
  return (
    <div className="rounded-xl bg-neutral-100 p-3 dark:bg-white/[0.04]">
      <div className="text-[10px] uppercase tracking-[0.18em] text-neutral-500">
        {label}
      </div>
      <div className="mt-2 text-lg tabular-nums">{display}</div>
    </div>
  );
}
