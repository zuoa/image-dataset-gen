import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { Download, ImageUp, ScanSearch, SlidersHorizontal, Target } from "lucide-react";

import { createTrainingInferenceTest, getTrainingInferenceTest } from "../api/datasets";
import type { TrainingArtifact, TrainingInferenceTest, TrainingJob } from "../lib/types";
import { Button } from "./ui/Button";
import { Input } from "./ui/Input";

type TrainingModelTestPanelProps = {
  job: TrainingJob;
  token: string | null;
};

const activeTestStatuses = new Set(["queued", "assigned", "running"]);

export function TrainingModelTestPanel({ job, token }: TrainingModelTestPanelProps) {
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const modelArtifacts = useMemo(() => job.artifacts.filter(isModelArtifact), [job.artifacts]);
  const [artifactId, setArtifactId] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.25);
  const [imageSize, setImageSize] = useState(job.config.imageSize || 640);
  const [testJob, setTestJob] = useState<TrainingInferenceTest | null>(null);
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

    const interval = window.setInterval(() => {
      void poll();
    }, 2000);
    void poll();

    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, [job.datasetId, job.id, testJob?.id, testJob?.status, token]);

  const result = testJob?.result ?? null;
  const isTesting = isSubmitting || Boolean(testJob && activeTestStatuses.has(testJob.status));
  const canRun = Boolean(token && job.status === "completed" && modelArtifacts.length > 0 && imageFile && !isTesting);

  async function runModelTest() {
    if (!token || !imageFile || !canRun) return;
    setIsSubmitting(true);
    setError(null);
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
    setError(null);
  }

  function downloadAnnotatedImage() {
    if (!result) return;
    const anchor = document.createElement("a");
    anchor.href = result.annotatedImage;
    anchor.download = `model-test-${job.id}.jpg`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
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
            创建测试任务后由已注册的训练 worker 领取推理，完成后返回检测框和带标注的结果图。
          </p>
        </div>
        {result ? (
          <Button variant="secondary" onClick={downloadAnnotatedImage}>
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
                <span>置信度</span>
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
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="overflow-hidden rounded-[16px] border border-neutral-200 bg-white dark:border-white/10 dark:bg-neutral-950">
                <img src={result.annotatedImage} alt="模型测试结果" className="max-h-[560px] w-full object-contain" />
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm text-neutral-900 dark:text-white">检测结果</div>
                  <span className="text-xs text-neutral-500">{result.detections.length} 个目标</span>
                </div>
                <div className="max-h-[500px] space-y-2 overflow-y-auto pr-1">
                  {result.detections.length > 0 ? (
                    result.detections.map((detection, index) => (
                      <div
                        key={`${detection.category}-${index}`}
                        className="rounded-[16px] border border-neutral-200 bg-white px-3 py-2 text-sm dark:border-white/10 dark:bg-neutral-950"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-neutral-900 dark:text-white">{detection.category}</span>
                          <span className="text-xs text-neutral-500">{detection.confidence.toFixed(2)}</span>
                        </div>
                        <div className="mt-1 text-xs text-neutral-500">class {detection.classId}</div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-[16px] border border-dashed border-neutral-200 px-3 py-6 text-center text-sm text-neutral-500 dark:border-white/10">
                      当前阈值下没有检测到目标。
                    </div>
                  )}
                </div>
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
