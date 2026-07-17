import { useEffect, useMemo, useState, type ReactNode } from "react";
import { LineChart, RefreshCw } from "lucide-react";
import { Alert, Button, Card, Col, Row } from "antd";

import { fetchTextWithToken } from "../api/client";
import { useAuthStore } from "../store/auth";
import type { TrainingArtifact, TrainingJob } from "../lib/types";

type ChartGroup = "quality" | "loss";

type ResultPoint = {
  epoch: number;
  value: number;
};

type ResultSeries = {
  key: string;
  label: string;
  color: string;
  values: ResultPoint[];
};

type SeriesDefinition = {
  key: string;
  label: string;
  color: string;
  group: ChartGroup;
  matches: (normalizedHeader: string) => boolean;
};

type ParsedTrainingResults = {
  rowCount: number;
  firstEpoch: number | null;
  lastEpoch: number | null;
  qualitySeries: ResultSeries[];
  lossSeries: ResultSeries[];
};

const activeTrainingStatuses = new Set(["queued", "assigned", "preparing", "running", "uploading"]);
const chartWidth = 640;
const chartHeight = 240;
const chartPadding = { top: 18, right: 20, bottom: 34, left: 48 };
const plotWidth = chartWidth - chartPadding.left - chartPadding.right;
const plotHeight = chartHeight - chartPadding.top - chartPadding.bottom;

const seriesDefinitions: SeriesDefinition[] = [
  {
    key: "precision",
    label: "Precision",
    color: "#30343a",
    group: "quality",
    matches: (header) => header.includes("precision"),
  },
  {
    key: "recall",
    label: "Recall",
    color: "#626871",
    group: "quality",
    matches: (header) => header.includes("recall"),
  },
  {
    key: "map50",
    label: "mAP50",
    color: "#4f6268",
    group: "quality",
    matches: (header) => header.includes("map50") && !header.includes("map5095"),
  },
  {
    key: "map50_95",
    label: "mAP50-95",
    color: "#7d8884",
    group: "quality",
    matches: (header) => header.includes("map5095"),
  },
  {
    key: "train_box_loss",
    label: "Train box",
    color: "#34383e",
    group: "loss",
    matches: (header) => header.includes("trainboxloss"),
  },
  {
    key: "train_cls_loss",
    label: "Train cls",
    color: "#555b63",
    group: "loss",
    matches: (header) => header.includes("trainclsloss"),
  },
  {
    key: "train_dfl_loss",
    label: "Train dfl",
    color: "#737981",
    group: "loss",
    matches: (header) => header.includes("traindflloss"),
  },
  {
    key: "val_box_loss",
    label: "Val box",
    color: "#8b929a",
    group: "loss",
    matches: (header) => header.includes("valboxloss"),
  },
  {
    key: "val_cls_loss",
    label: "Val cls",
    color: "#566c70",
    group: "loss",
    matches: (header) => header.includes("valclsloss"),
  },
  {
    key: "val_dfl_loss",
    label: "Val dfl",
    color: "#7d8884",
    group: "loss",
    matches: (header) => header.includes("valdflloss"),
  },
];

type TrainingResultsPanelProps = {
  job: TrainingJob;
};

export function TrainingResultsPanel({ job }: TrainingResultsPanelProps) {
  const token = useAuthStore((state) => state.token);
  const resultArtifact = useMemo(() => findResultsArtifact(job.artifacts), [job.artifacts]);
  const artifactUrl = resultArtifact?.downloadUrl ?? "";
  const artifactId = resultArtifact?.id ?? "";
  const [reloadKey, setReloadKey] = useState(0);
  const [csvText, setCsvText] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !artifactUrl) {
      setCsvText("");
      setError(null);
      setIsLoading(false);
      return;
    }

    let disposed = false;
    setIsLoading(true);
    setError(null);
    setCsvText("");

    void fetchTextWithToken(artifactUrl, token)
      .then((text) => {
        if (disposed) return;
        setCsvText(text);
      })
      .catch((nextError) => {
        if (disposed) return;
        setError((nextError as Error).message);
      })
      .finally(() => {
        if (!disposed) {
          setIsLoading(false);
        }
      });

    return () => {
      disposed = true;
    };
  }, [artifactId, artifactUrl, reloadKey, token]);

  const parsedResults = useMemo(() => (csvText ? parseTrainingResultsCsv(csvText) : null), [csvText]);
  const hasChartData = Boolean(
    parsedResults && (parsedResults.qualitySeries.length > 0 || parsedResults.lossSeries.length > 0),
  );

  return (
    <div className="mt-6 border-t border-neutral-200 pt-6 dark:border-white/10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-neutral-500">
            <LineChart className="h-4 w-4" />
            result.csv
          </div>
          <h4 className="mt-2 text-xl text-neutral-900 dark:text-white">训练结果曲线</h4>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            {parsedResults
              ? `已解析 ${parsedResults.rowCount} 个 epoch，来自 ${resultArtifact?.filename ?? "results.csv"}。`
              : resultArtifact
                ? `正在读取 ${resultArtifact.filename}。`
                : activeTrainingStatuses.has(job.status)
                  ? "训练完成并上传结果文件后，这里会显示 mAP、Precision、Recall 和 Loss 曲线。"
                  : "没有找到 result.csv 或 results.csv 训练产物。"}
          </p>
        </div>

        {resultArtifact ? (
          <Button
            onClick={() => setReloadKey((current) => current + 1)}
            disabled={isLoading}
            icon={<RefreshCw className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`} />}
          >
            刷新
          </Button>
        ) : null}
      </div>

      {isLoading ? (
        <TrainingResultsMessage>正在解析训练结果文件...</TrainingResultsMessage>
      ) : error ? (
        <TrainingResultsMessage tone="error">读取 result.csv 失败：{error}</TrainingResultsMessage>
      ) : !resultArtifact ? (
        <TrainingResultsMessage>
          worker 上传 `results.csv` 后会自动读取；也可以继续使用上方产物按钮下载原始文件。
        </TrainingResultsMessage>
      ) : parsedResults && !hasChartData ? (
        <TrainingResultsMessage>
          文件已读取，但没有找到可绘制的 Ultralytics 指标列。
        </TrainingResultsMessage>
      ) : parsedResults ? (
        <Row gutter={[16, 16]} className="mt-5">
          <Col xs={24} xl={12}>
            <TrainingLineChart
              title="精度指标"
              subtitle={formatEpochRange(parsedResults)}
              series={parsedResults.qualitySeries}
              expectedMax={1}
            />
          </Col>
          <Col xs={24} xl={12}>
            <TrainingLineChart
              title="Loss"
              subtitle={formatEpochRange(parsedResults)}
              series={parsedResults.lossSeries}
            />
          </Col>
        </Row>
      ) : null}
    </div>
  );
}

type TrainingResultsMessageProps = {
  children: ReactNode;
  tone?: "default" | "error";
};

function TrainingResultsMessage({
  children,
  tone = "default",
}: TrainingResultsMessageProps) {
  return (
    <Alert
      className="mt-5"
      message={children}
      type={tone === "error" ? "error" : "info"}
      showIcon
    />
  );
}

type TrainingLineChartProps = {
  title: string;
  subtitle: string;
  series: ResultSeries[];
  expectedMax?: number;
};

function TrainingLineChart({ title, subtitle, series, expectedMax }: TrainingLineChartProps) {
  const chartModel = useMemo(() => buildChartModel(series, expectedMax), [expectedMax, series]);

  return (
    <Card className="rounded-[20px] border border-neutral-200 bg-neutral-50 p-4 dark:border-white/10 dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-base">{title}</div>
          <div className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{subtitle}</div>
        </div>
        <div className="flex max-w-full flex-wrap justify-end gap-x-4 gap-y-2 text-xs text-neutral-500 dark:text-neutral-400">
          {series.map((item) => (
            <div key={item.key} className="flex min-w-0 items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} />
              <span className="truncate">{item.label}</span>
              <span className="font-medium text-neutral-800 dark:text-neutral-100">
                {formatChartNumber(latestValue(item.values))}
              </span>
            </div>
          ))}
        </div>
      </div>

      {chartModel ? (
        <div className="mt-4 overflow-x-auto">
          <svg
            className="h-64 min-w-[520px] w-full"
            viewBox={`0 0 ${chartWidth} ${chartHeight}`}
            role="img"
            aria-label={`${title} ${subtitle}`}
          >
            <rect
              x={chartPadding.left}
              y={chartPadding.top}
              width={plotWidth}
              height={plotHeight}
              rx="12"
              className="fill-white dark:fill-neutral-950"
            />
            {chartModel.yTicks.map((tick) => (
              <g key={tick.value}>
                <line
                  x1={chartPadding.left}
                  x2={chartWidth - chartPadding.right}
                  y1={tick.y}
                  y2={tick.y}
                  className="stroke-neutral-200 dark:stroke-white/10"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={chartPadding.left - 10}
                  y={tick.y + 4}
                  textAnchor="end"
                  className="fill-neutral-500 text-[11px] dark:fill-neutral-400"
                >
                  {formatChartNumber(tick.value)}
                </text>
              </g>
            ))}
            <line
              x1={chartPadding.left}
              x2={chartPadding.left}
              y1={chartPadding.top}
              y2={chartHeight - chartPadding.bottom}
              className="stroke-neutral-300 dark:stroke-white/15"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
            <line
              x1={chartPadding.left}
              x2={chartWidth - chartPadding.right}
              y1={chartHeight - chartPadding.bottom}
              y2={chartHeight - chartPadding.bottom}
              className="stroke-neutral-300 dark:stroke-white/15"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
            <text
              x={chartPadding.left}
              y={chartHeight - 10}
              textAnchor="start"
              className="fill-neutral-500 text-[11px] dark:fill-neutral-400"
            >
              epoch {formatEpochLabel(chartModel.xMin)}
            </text>
            <text
              x={chartWidth - chartPadding.right}
              y={chartHeight - 10}
              textAnchor="end"
              className="fill-neutral-500 text-[11px] dark:fill-neutral-400"
            >
              epoch {formatEpochLabel(chartModel.xMax)}
            </text>

            {chartModel.pathSeries.map((item) => (
              <g key={item.key}>
                <path
                  d={item.path}
                  fill="none"
                  stroke={item.color}
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                />
                {item.points.map((point, index) => {
                  const shouldShowPoint = item.points.length <= 48 || index === item.points.length - 1;
                  return shouldShowPoint ? (
                    <circle
                      key={`${item.key}-${index}`}
                      cx={point.x}
                      cy={point.y}
                      r={index === item.points.length - 1 ? 3.6 : 2.4}
                      fill={item.color}
                      className="stroke-white dark:stroke-neutral-950"
                      strokeWidth="1.5"
                      vectorEffect="non-scaling-stroke"
                    />
                  ) : null;
                })}
              </g>
            ))}
          </svg>
        </div>
      ) : (
        <div className="mt-4 rounded-[16px] border border-dashed border-neutral-200 px-4 py-8 text-sm text-neutral-500 dark:border-white/10 dark:text-neutral-400">
          没有找到该图表需要的列。
        </div>
      )}
    </Card>
  );
}

function findResultsArtifact(artifacts: TrainingArtifact[]) {
  return artifacts.find((artifact) => {
    const filename = artifact.filename.trim().toLowerCase();
    return artifact.type === "results_csv" || filename === "results.csv" || filename === "result.csv";
  });
}

function parseTrainingResultsCsv(text: string): ParsedTrainingResults | null {
  const rows = parseCsvRows(text).filter((row) => row.some((cell) => cell.trim() !== ""));
  if (rows.length < 2) return null;

  const headers = rows[0].map((header) => header.trim());
  const normalizedHeaders = headers.map(normalizeHeader);
  const dataRows = rows.slice(1);
  const epochColumn = normalizedHeaders.findIndex((header) => header === "epoch");
  const epochs = dataRows.map((row, index) => {
    const parsedEpoch = epochColumn >= 0 ? parseFiniteNumber(row[epochColumn]) : null;
    return parsedEpoch ?? index + 1;
  });

  const parsedSeries = seriesDefinitions
    .map((definition) => {
      const columnIndex = normalizedHeaders.findIndex(definition.matches);
      if (columnIndex < 0) return null;

      const values = dataRows
        .map((row, index) => {
          const value = parseFiniteNumber(row[columnIndex]);
          return value === null ? null : { epoch: epochs[index], value };
        })
        .filter((point): point is ResultPoint => point !== null);

      if (values.length === 0) return null;
      return {
        key: definition.key,
        label: definition.label,
        color: definition.color,
        values,
        group: definition.group,
      };
    })
    .filter((item): item is ResultSeries & { group: ChartGroup } => item !== null);

  return {
    rowCount: dataRows.length,
    firstEpoch: epochs.length > 0 ? epochs[0] : null,
    lastEpoch: epochs.length > 0 ? epochs[epochs.length - 1] : null,
    qualitySeries: parsedSeries.filter((series) => series.group === "quality"),
    lossSeries: parsedSeries.filter((series) => series.group === "loss"),
  };
}

function parseCsvRows(text: string) {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (inQuotes && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && text[index + 1] === "\n") {
        index += 1;
      }
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }

  return rows;
}

function normalizeHeader(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function parseFiniteNumber(value: string | undefined) {
  if (value === undefined || value.trim() === "") return null;
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) ? parsed : null;
}

function buildChartModel(series: ResultSeries[], expectedMax?: number) {
  const allPoints = series.flatMap((item) => item.values);
  if (allPoints.length === 0) return null;

  let xMin = Number.POSITIVE_INFINITY;
  let xMax = Number.NEGATIVE_INFINITY;
  let yMaxValue = 0;
  for (const point of allPoints) {
    xMin = Math.min(xMin, point.epoch);
    xMax = Math.max(xMax, point.epoch);
    yMaxValue = Math.max(yMaxValue, point.value);
  }

  const fallbackYMax = yMaxValue > 0 ? yMaxValue * 1.08 : 1;
  const yMax = expectedMax && yMaxValue <= expectedMax ? expectedMax : fallbackYMax;
  const xRange = xMax === xMin ? 1 : xMax - xMin;
  const toX = (epoch: number) => chartPadding.left + ((epoch - xMin) / xRange) * plotWidth;
  const toY = (value: number) => chartPadding.top + plotHeight - (value / yMax) * plotHeight;
  const yTicks = Array.from({ length: 5 }, (_, index) => {
    const value = (yMax / 4) * index;
    return {
      value,
      y: toY(value),
    };
  }).reverse();

  const pathSeries = series
    .map((item) => {
      const points = item.values.map((point) => ({
        x: toX(point.epoch),
        y: toY(point.value),
      }));
      return {
        key: item.key,
        color: item.color,
        points,
        path: points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" "),
      };
    })
    .filter((item) => item.points.length > 0);

  return {
    xMin,
    xMax,
    yTicks,
    pathSeries,
  };
}

function latestValue(values: ResultPoint[]) {
  return values.length > 0 ? values[values.length - 1].value : null;
}

function formatChartNumber(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "--";
  if (value === 0) return "0";
  if (Math.abs(value) < 0.001) return value.toExponential(1);
  if (Math.abs(value) < 1) return value.toFixed(3);
  if (Math.abs(value) < 10) return value.toFixed(2);
  return value.toFixed(1);
}

function formatEpochRange(results: ParsedTrainingResults) {
  if (results.firstEpoch === null || results.lastEpoch === null) return "Epoch --";
  if (results.firstEpoch === results.lastEpoch) return `Epoch ${formatEpochLabel(results.lastEpoch)}`;
  return `Epoch ${formatEpochLabel(results.firstEpoch)} - ${formatEpochLabel(results.lastEpoch)}`;
}

function formatEpochLabel(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
