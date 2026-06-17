import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { Download, ImageUp, ScanSearch, SlidersHorizontal, Target } from "lucide-react";

import { createTrainingInferenceTest, getTrainingInferenceTest } from "../api/datasets";
import { detectionStyle } from "../lib/annotation";
import type { TrainingArtifact, TrainingInferenceResult, TrainingInferenceTest, TrainingJob } from "../lib/types";
import { cn } from "../lib/utils";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";

type TrainingModelTestPanelProps = {
  job: TrainingJob;
  token: string | null;
};

type TrainingInferenceDetection = TrainingInferenceResult["detections"][number];
type DisplayDetection = {
  detection: TrainingInferenceDetection;
  index: number;
};

const activeTestStatuses = new Set(["queued", "assigned", "running"]);
const detectionPalette = ["#38bdf8", "#f59e0b", "#84cc16", "#fb7185", "#a78bfa", "#2dd4bf", "#f97316", "#e879f9", "#94a3b8"];
const TEST_STATUS_POLL_INITIAL_DELAY_MS = 1000;
const TEST_STATUS_POLL_INTERVAL_MS = 4000;
const TEST_STATUS_POLL_HIDDEN_INTERVAL_MS = 15000;

export function TrainingModelTestPanel({ job, token }: TrainingModelTestPanelProps) {
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const modelArtifacts = useMemo(() => job.artifacts.filter(isModelArtifact), [job.artifacts]);
  const [artifactId, setArtifactId] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.25);
  const [displayThreshold, setDisplayThreshold] = useState(0.25);
  const [imageSize, setImageSize] = useState(job.config.imageSize || 640);
  const [testJob, setTestJob] = useState<TrainingInferenceTest | null>(null);
  const [selectedDetectionIndex, setSelectedDetectionIndex] = useState<number | null>(null);
  const [showDownloadConfidence, setShowDownloadConfidence] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (artifactId && modelArtifacts.some((artifact) => artifact.id === artifactId)) return;
    setArtifactId(modelArtifacts[0]?.id ?? "");
  }, [artifactId, modelArtifacts]);

  useEffect(() => {
    setImageSize(job.config.imageSize || 640);
  }, [job.config.imageSize, job.id]);

  useEffect(() => {
    if (!token || !testJob || !activeTestStatuses.has(testJob.status)) return;

    let disposed = false;
    const testId = testJob.id;
    const poll = async () => {
      try {
        const response = await getTrainingInferenceTest(job.datasetId, job.id, testId, token);
        if (!disposed) {
          setTestJob(response.test);
          if (response.test.status === "failed") {
            setError(response.test.error || "模型测试失败。");
          }
        }
      } catch (nextError) {
        if (!disposed) {
          setError((nextError as Error).message);
        }
      }
    };

    let timeoutId: number | undefined;
    const schedule = (delay: number) => {
      if (disposed) return;
      timeoutId = window.setTimeout(() => {
        void poll().finally(() => {
          const nextDelay =
            document.visibilityState === "hidden"
              ? TEST_STATUS_POLL_HIDDEN_INTERVAL_MS
              : TEST_STATUS_POLL_INTERVAL_MS;
          schedule(nextDelay);
        });
      }, delay);
    };

    schedule(TEST_STATUS_POLL_INITIAL_DELAY_MS);

    return () => {
      disposed = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [job.datasetId, job.id, testJob?.id, testJob?.status, token]);

  const result = testJob?.result ?? null;
  const filteredDetections = useMemo<DisplayDetection[]>(() => {
    if (!result) return [];
    return result.detections
      .map((detection, index) => ({ detection, index }))
      .filter(({ detection }) => detection.confidence >= displayThreshold);
  }, [displayThreshold, result]);
  const selectedDetection = selectedDetectionIndex !== null ? result?.detections[selectedDetectionIndex] ?? null : null;
  const isTesting = isSubmitting || Boolean(testJob && activeTestStatuses.has(testJob.status));
  const canRun = Boolean(token && job.status === "completed" && modelArtifacts.length > 0 && imageFile && !isTesting);

  useEffect(() => {
    if (!result) {
      setSelectedDetectionIndex(null);
      return;
    }
    setDisplayThreshold(result.confidenceThreshold);
    setSelectedDetectionIndex(null);
  }, [result?.confidenceThreshold, testJob?.id]);

  useEffect(() => {
    if (selectedDetectionIndex === null) return;
    if (filteredDetections.some(({ index }) => index === selectedDetectionIndex)) return;
    setSelectedDetectionIndex(null);
  }, [filteredDetections, selectedDetectionIndex]);

  async function runModelTest() {
    if (!token || !imageFile || !canRun) return;
    setIsSubmitting(true);
    setError(null);
    setSelectedDetectionIndex(null);
    try {
      const response = await createTrainingInferenceTest(job.datasetId, job.id, token, {
        image: imageFile,
        artifactId,
        confidenceThreshold,
        imageSize,
      });
      setTestJob(response.test);
    } catch (nextError) {
      setError((nextError as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleImageChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0] ?? null;
    setImageFile(nextFile);
    setTestJob(null);
    setSelectedDetectionIndex(null);
    setError(null);
  }

  async function downloadAnnotatedImage() {
    if (!result) return;
    const filename = `model-test-${job.id}.jpg`;
    if (!result.sourceImage) {
      triggerDownload(result.annotatedImage, filename);
      return;
    }

    try {
      const href = await renderDownloadImage(result.sourceImage, filteredDetections, showDownloadConfidence);
      triggerDownload(href, filename);
    } catch {
      triggerDownload(result.annotatedImage, filename);
    }
  }

  return (
    <div className="mt-6 border-t border-neutral-200 pt-6 dark:border-white/10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-neutral-500">
            <ScanSearch className="h-4 w-4" />
            Model test
          </div>
          <h4 className="mt-2 text-xl text-neutral-900 dark:text-white">上传图片测试模型</h4>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            创建测试任务后由已注册的训练 worker 领取推理，完成后可点击检测框定位目标并按阈值筛选结果图。
          </p>
        </div>
        {result ? (
          <Button variant="secondary" onClick={() => void downloadAnnotatedImage()}>
            <Download className="mr-2 h-4 w-4" />
            下载结果图
          </Button>
        ) : null}
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="rounded-[20px] border border-neutral-200 bg-neutral-50 p-4 dark:border-white/10 dark:bg-white/[0.03]">
          <div className="space-y-4">
            <label className="block space-y-2">
              <span className="text-[11px] uppercase tracking-[0.24em] text-neutral-500">模型产物</span>
              <select
                value={artifactId}
                onChange={(event) => setArtifactId(event.target.value)}
                disabled={modelArtifacts.length === 0 || isTesting}
                className="w-full rounded-[18px] border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-400 dark:border-white/10 dark:bg-neutral-950 dark:text-white"
              >
                {modelArtifacts.length > 0 ? (
                  modelArtifacts.map((artifact) => (
                    <option key={artifact.id} value={artifact.id}>
                      {artifact.filename}
                    </option>
                  ))
                ) : (
                  <option value="">没有可用模型</option>
                )}
              </select>
            </label>

            <div>
              <input
                ref={imageInputRef}
                type="file"
                accept="image/*,.jpg,.jpeg,.png,.webp"
                className="hidden"
                onChange={handleImageChange}
              />
              <Button
                variant="secondary"
                className="w-full justify-center"
                onClick={() => imageInputRef.current?.click()}
                disabled={isTesting}
              >
                <ImageUp className="mr-2 h-4 w-4" />
                <span className="min-w-0 truncate">{imageFile ? imageFile.name : "选择测试图片"}</span>
              </Button>
            </div>

            <label className="block space-y-2">
              <span className="flex items-center justify-between text-[11px] uppercase tracking-[0.24em] text-neutral-500">
                <span>推理阈值</span>
                <span>{confidenceThreshold.toFixed(2)}</span>
              </span>
              <input
                type="range"
                min={0.01}
                max={1}
                step={0.01}
                value={confidenceThreshold}
                onChange={(event) => setConfidenceThreshold(Number(event.target.value))}
                disabled={isTesting}
                className="h-2 w-full accent-neutral-900 dark:accent-white"
              />
            </label>

            <label className="block space-y-2">
              <span className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-neutral-500">
                <SlidersHorizontal className="h-3.5 w-3.5" />
                Image size
              </span>
              <Input
                type="number"
                min={64}
                max={2048}
                step={32}
                value={imageSize}
                onChange={(event) => setImageSize(Number(event.target.value) || 640)}
                disabled={isTesting}
              />
            </label>

            <Button className="w-full justify-center" onClick={() => void runModelTest()} disabled={!canRun}>
              <ScanSearch className="mr-2 h-4 w-4" />
              {isTesting ? "测试中..." : "开始测试"}
            </Button>

            {testJob ? (
              <div className="rounded-[16px] border border-neutral-200 px-3 py-2 text-xs leading-5 text-neutral-500 dark:border-white/10">
                当前状态：{testStatusLabel(testJob.status)}
                {testJob.workerId ? `，worker ${testJob.workerId}` : ""}
              </div>
            ) : null}
            {job.status !== "completed" ? (
              <div className="rounded-[16px] border border-neutral-200 px-3 py-2 text-xs text-neutral-500 dark:border-white/10">
                训练完成并上传模型产物后才能测试。
              </div>
            ) : modelArtifacts.length === 0 ? (
              <div className="rounded-[16px] border border-neutral-200 px-3 py-2 text-xs text-neutral-500 dark:border-white/10">
                没有找到 best.pt 或 last.pt。
              </div>
            ) : null}
            {error ? (
              <div className="rounded-[16px] border border-red-300/50 bg-red-50 px-3 py-2 text-xs leading-5 text-red-700 dark:border-red-400/20 dark:bg-red-950/20 dark:text-red-100">
                {error}
              </div>
            ) : null}
          </div>
        </div>

        <div className="min-h-[320px] rounded-[20px] border border-neutral-200 bg-neutral-50 p-4 dark:border-white/10 dark:bg-white/[0.03]">
          {result ? (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
              <div className="overflow-hidden rounded-[16px] border border-neutral-200 bg-white dark:border-white/10 dark:bg-neutral-950">
                <div className="flex min-h-[320px] items-center justify-center p-3">
                  <div className="relative inline-block max-h-[560px] max-w-full">
                    <img
                      src={result.sourceImage || result.annotatedImage}
                      alt="模型测试结果"
                      className="block max-h-[560px] max-w-full object-contain"
                      draggable={false}
                    />
                    {result.sourceImage ? (
                      <div className="absolute inset-0" onClick={() => setSelectedDetectionIndex(null)}>
                        {filteredDetections.map(({ detection, index }) => {
                          const selected = selectedDetectionIndex === index;
                          const color = selected ? "#bef264" : detectionColor(index);
                          return (
                            <button
                              key={`${detection.category}-${index}`}
                              type="button"
                              aria-label={`选择 ${detection.category}，置信度 ${formatConfidence(detection.confidence)}`}
                              className={cn(
                                "absolute rounded-lg border-2 text-left shadow-[0_0_0_1px_rgba(0,0,0,0.35)] transition focus:outline-none focus:ring-2 focus:ring-lime-300",
                                selected ? "z-10 shadow-[0_0_0_9999px_rgba(0,0,0,0.10)]" : "hover:shadow-[0_0_0_2px_rgba(0,0,0,0.28)]",
                              )}
                              style={{ ...detectionStyle(detection.bbox), borderColor: color }}
                              onClick={(event) => {
                                event.stopPropagation();
                                setSelectedDetectionIndex(index);
                              }}
                            >
                              <span
                                className="absolute left-0 top-0 max-w-full -translate-y-full truncate rounded-t-md px-2 py-1 text-[11px] font-medium text-neutral-950"
                                style={{ backgroundColor: color }}
                              >
                                #{index + 1} {detection.category} · {formatConfidence(detection.confidence)}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
              <div className="space-y-4">
                <div className="rounded-[16px] border border-neutral-200 bg-white px-3 py-3 dark:border-white/10 dark:bg-neutral-950">
                  <label className="block space-y-2">
                    <span className="flex items-center justify-between text-[11px] uppercase tracking-[0.2em] text-neutral-500">
                      <span>显示阈值</span>
                      <span>{displayThreshold.toFixed(2)}</span>
                    </span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.01}
                      value={displayThreshold}
                      onChange={(event) => setDisplayThreshold(Number(event.target.value))}
                      className="h-2 w-full accent-neutral-900 dark:accent-white"
                    />
                  </label>
                  <label className="mt-3 flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300">
                    <input
                      type="checkbox"
                      checked={showDownloadConfidence}
                      onChange={(event) => setShowDownloadConfidence(event.target.checked)}
                      className="h-4 w-4 rounded border-neutral-300 accent-neutral-900 dark:border-white/20 dark:accent-white"
                    />
                    下载图显示置信度
                  </label>
                </div>

                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm text-neutral-900 dark:text-white">检测结果</div>
                  <span className="text-xs text-neutral-500">
                    {filteredDetections.length} / {result.detections.length} 个目标
                  </span>
                </div>
                <div className="max-h-[500px] space-y-2 overflow-y-auto pr-1">
                  {filteredDetections.length > 0 ? (
                    filteredDetections.map(({ detection, index }) => {
                      const selected = selectedDetectionIndex === index;
                      return (
                        <button
                          key={`${detection.category}-${index}`}
                          type="button"
                          className={cn(
                            "w-full rounded-[16px] border bg-white px-3 py-2 text-left text-sm transition focus:outline-none focus:ring-2 focus:ring-lime-300 dark:bg-neutral-950",
                            selected
                              ? "border-lime-300 shadow-[0_0_0_1px_rgba(190,242,100,0.45)] dark:border-lime-300"
                              : "border-neutral-200 hover:border-neutral-300 dark:border-white/10 dark:hover:border-white/20",
                          )}
                          onClick={() => setSelectedDetectionIndex(index)}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="flex min-w-0 items-center gap-2 text-neutral-900 dark:text-white">
                              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: detectionColor(index) }} />
                              <span className="truncate">
                                #{index + 1} {detection.category}
                              </span>
                            </span>
                            <span className="text-xs text-neutral-500">{detection.confidence.toFixed(2)}</span>
                          </div>
                          <div className="mt-1 text-xs text-neutral-500">class {detection.classId}</div>
                          {selected ? <div className="mt-2 break-all text-[11px] text-neutral-500">bbox {formatBbox(detection.bbox)}</div> : null}
                        </button>
                      );
                    })
                  ) : (
                    <div className="rounded-[16px] border border-dashed border-neutral-200 px-3 py-6 text-center text-sm text-neutral-500 dark:border-white/10">
                      当前显示阈值下没有检测框。
                    </div>
                  )}
                </div>
                {selectedDetection ? (
                  <div className="rounded-[16px] border border-neutral-200 bg-white px-3 py-2 text-xs leading-5 text-neutral-500 dark:border-white/10 dark:bg-neutral-950">
                    已选中 #{selectedDetectionIndex! + 1} {selectedDetection.category}，置信度 {selectedDetection.confidence.toFixed(2)}
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="flex min-h-[288px] flex-col items-center justify-center rounded-[16px] border border-dashed border-neutral-200 px-6 text-center dark:border-white/10">
              <Target className="h-8 w-8 text-neutral-400" />
              <div className="mt-3 text-sm text-neutral-900 dark:text-white">等待测试图片</div>
              <div className="mt-2 max-w-md text-sm leading-6 text-neutral-500 dark:text-neutral-400">
                测试任务完成后这里会显示 worker 返回的带框图片。
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function detectionColor(index: number) {
  return detectionPalette[index % detectionPalette.length];
}

function formatConfidence(value: number) {
  return value.toFixed(2);
}

function formatBbox(bbox: [number, number, number, number]) {
  return bbox.map((value) => value.toFixed(3)).join(", ");
}

function triggerDownload(href: string, filename: string) {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

async function renderDownloadImage(sourceImage: string, detections: DisplayDetection[], showConfidence: boolean) {
  const image = await loadImage(sourceImage);
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  if (width <= 0 || height <= 0) {
    throw new Error("Invalid image size");
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Canvas is not available");
  }

  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);

  const lineWidth = Math.max(2, Math.round(Math.min(width, height) * 0.006));
  const fontSize = Math.min(28, Math.max(12, Math.round(Math.min(width, height) * 0.025)));
  context.lineJoin = "round";
  context.textBaseline = "top";
  context.font = `${fontSize}px sans-serif`;

  detections.forEach(({ detection, index }) => {
    const xCenter = clamp01(detection.bbox[0]);
    const yCenter = clamp01(detection.bbox[1]);
    const boxWidth = clamp01(detection.bbox[2]);
    const boxHeight = clamp01(detection.bbox[3]);
    const left = Math.max(0, (xCenter - boxWidth / 2) * width);
    const top = Math.max(0, (yCenter - boxHeight / 2) * height);
    const right = Math.min(width, (xCenter + boxWidth / 2) * width);
    const bottom = Math.min(height, (yCenter + boxHeight / 2) * height);
    if (right <= left || bottom <= top) return;

    const color = detectionColor(index);
    context.strokeStyle = color;
    context.lineWidth = lineWidth;
    context.strokeRect(left, top, right - left, bottom - top);

    const rawLabel = showConfidence ? `${detection.category} ${formatConfidence(detection.confidence)}` : detection.category;
    const paddingX = Math.max(6, lineWidth * 2);
    const paddingY = Math.max(4, lineWidth);
    const label = fitCanvasLabel(context, rawLabel, Math.max(24, width - paddingX * 2));
    const textWidth = context.measureText(label).width;
    const labelWidth = Math.min(width, textWidth + paddingX * 2);
    const labelHeight = fontSize + paddingY * 2;
    const labelLeft = Math.min(Math.max(0, left), Math.max(0, width - labelWidth));
    const labelTop = top - labelHeight >= 0 ? top - labelHeight : Math.min(height - labelHeight, top);

    context.fillStyle = color;
    context.fillRect(labelLeft, Math.max(0, labelTop), labelWidth, labelHeight);
    context.fillStyle = "#ffffff";
    context.fillText(label, labelLeft + paddingX, Math.max(0, labelTop) + paddingY);
  });

  return canvas.toDataURL("image/jpeg", 0.92);
}

function loadImage(source: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Image load failed"));
    image.src = source;
  });
}

function fitCanvasLabel(context: CanvasRenderingContext2D, label: string, maxWidth: number) {
  if (context.measureText(label).width <= maxWidth) return label;
  let nextLabel = label;
  while (nextLabel.length > 1 && context.measureText(`${nextLabel}...`).width > maxWidth) {
    nextLabel = nextLabel.slice(0, -1);
  }
  return `${nextLabel}...`;
}

function clamp01(value: number) {
  return Math.min(Math.max(value, 0), 1);
}

function isModelArtifact(artifact: TrainingArtifact) {
  return artifact.type === "best_model" || artifact.type === "last_model" || artifact.filename.toLowerCase().endsWith(".pt");
}

function testStatusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    assigned: "已分配",
    running: "推理中",
    completed: "已完成",
    failed: "失败",
  };
  return labels[status] ?? status;
}
