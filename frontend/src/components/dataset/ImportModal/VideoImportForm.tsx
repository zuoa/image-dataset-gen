import { useRef } from "react";
import { FileVideo, Loader, Play, Upload } from "lucide-react";
import { Button, Card, Col, Input, Row, Segmented, Slider } from "antd";

import type {
  VideoFrameIntervalMode,
  VideoOutputFormat,
  VideoTargetSize,
} from "../types";

const videoTargetSizeOptions: Array<{ value: VideoTargetSize; label: string }> =
  [
    { value: "original", label: "原图" },
    { value: "1080p", label: "1080p" },
    { value: "720p", label: "720p" },
    { value: "640", label: "640" },
  ];

interface VideoImportFormProps {
  selectedVideoFile: File | null;
  onVideoSelect: (file: File | null) => void;
  onVideoImport: () => Promise<void>;
  isImportingVideo: boolean;
  isAnyImporting: boolean;
  videoFrameIntervalMode: VideoFrameIntervalMode;
  onVideoFrameIntervalModeChange: (mode: VideoFrameIntervalMode) => void;
  videoFrameInterval: number;
  onVideoFrameIntervalChange: (value: number) => void;
  videoFrameIntervalSeconds: number;
  onVideoFrameIntervalSecondsChange: (value: number) => void;
  videoOutputFormat: VideoOutputFormat;
  onVideoOutputFormatChange: (format: VideoOutputFormat) => void;
  videoJpegQuality: number;
  onVideoJpegQualityChange: (value: number) => void;
  videoFilenamePrefix: string;
  onVideoFilenamePrefixChange: (value: string) => void;
  videoTargetSize: VideoTargetSize;
  onVideoTargetSizeChange: (size: VideoTargetSize) => void;
}

export function VideoImportForm(props: VideoImportFormProps) {
  const videoInputRef = useRef<HTMLInputElement>(null);

  const normalizedVideoFrameInterval = Math.max(
    1,
    Math.min(10000, Math.round(props.videoFrameInterval) || 30),
  );
  const normalizedVideoFrameIntervalSeconds = Math.max(
    0.01,
    Math.min(3600, Number(props.videoFrameIntervalSeconds) || 5),
  );
  const videoFrameIntervalHint =
    props.videoFrameIntervalMode === "seconds"
      ? `每 ${normalizedVideoFrameIntervalSeconds.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 秒取一张`
      : `每 ${normalizedVideoFrameInterval} 帧取一张`;
  const videoFilenamePrefixPreview = props.videoFilenamePrefix
    .trim()
    .replace(/[^A-Za-z0-9_-]/g, "") || "frame";
  const videoOutputExample = `${videoFilenamePrefixPreview}_000000.${props.videoOutputFormat}`;
  const selectedVideoFileSize = props.selectedVideoFile
    ? `${(props.selectedVideoFile.size / 1024 / 1024).toLocaleString("zh-CN", { maximumFractionDigits: 1 })} MB`
    : "";
  const videoTargetSizeLabel =
    videoTargetSizeOptions.find((option) => option.value === props.videoTargetSize)?.label ?? "原图";

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (!file) return;
    props.onVideoSelect(file);
    event.target.value = "";
  }

  return (
    <Card className="bg-neutral-50 dark:bg-white/[0.03]">
      <input
        ref={videoInputRef}
        type="file"
        accept="video/*,.mp4,.mov,.avi,.mkv,.webm,.dav,.mpg,.mpeg,.ps"
        className="hidden"
        onChange={handleFileChange}
      />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <FileVideo className="h-4 w-4 text-neutral-500" />
            本地视频
          </div>
          <p className="mt-2 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
            按固定帧数或时间间隔从视频中提取图片，并加入当前数据集。
          </p>
        </div>
        <Button
          type="primary"
          onClick={() => videoInputRef.current?.click()}
          disabled={props.isAnyImporting}
          icon={<Upload className="h-4 w-4" />}
        >
          {props.selectedVideoFile ? "更换视频" : "选择视频"}
        </Button>
      </div>

      <Row gutter={[16, 16]} className="mt-5">
        <Col xs={24} lg={16}>
          <div className="space-y-4">
            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
                抽帧方式
              </div>
              <Segmented
                value={props.videoFrameIntervalMode}
                onChange={(value) =>
                  props.onVideoFrameIntervalModeChange(value as VideoFrameIntervalMode)
                }
                options={[
                  { value: "frames", label: "按帧数" },
                  { value: "seconds", label: "按秒数" },
                ]}
                disabled={props.isAnyImporting}
              />
            </div>

            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
                {props.videoFrameIntervalMode === "seconds"
                  ? "抽帧间隔（秒）"
                  : "抽帧间隔（帧）"}
              </div>
              {props.videoFrameIntervalMode === "seconds" ? (
                <Input
                  type="number"
                  min={0.01}
                  max={3600}
                  step={0.1}
                  value={props.videoFrameIntervalSeconds}
                  onChange={(event) =>
                    props.onVideoFrameIntervalSecondsChange(
                      Number(event.target.value) || 0,
                    )
                  }
                  disabled={props.isAnyImporting}
                />
              ) : (
                <Input
                  type="number"
                  min={1}
                  max={10000}
                  value={props.videoFrameInterval}
                  onChange={(event) =>
                    props.onVideoFrameIntervalChange(Number(event.target.value) || 0)
                  }
                  disabled={props.isAnyImporting}
                />
              )}
              <div className="mt-1 text-xs text-neutral-500">{videoFrameIntervalHint}</div>
            </div>

            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
                文件名前缀
              </div>
              <Input
                value={props.videoFilenamePrefix}
                onChange={(event) => props.onVideoFilenamePrefixChange(event.target.value)}
                placeholder="frame"
                disabled={props.isAnyImporting}
              />
              <div className="mt-1 text-xs text-neutral-500">
                输出文件名格式：{videoOutputExample}
              </div>
            </div>
          </div>
        </Col>

        <Col xs={24} lg={8}>
          <Card className="bg-white dark:bg-black/20">
            <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
              已选视频
            </div>
            <div className="mt-2 rounded-lg border border-neutral-200 px-3 py-2 text-sm dark:border-white/10">
              {props.selectedVideoFile ? (
                <>
                  <div className="truncate">{props.selectedVideoFile.name}</div>
                  <div className="mt-1 text-xs text-neutral-500">{selectedVideoFileSize}</div>
                </>
              ) : (
                <span className="text-neutral-500">尚未选择视频</span>
              )}
            </div>

            <div className="mt-4 text-xs uppercase tracking-[0.2em] text-neutral-500">
              输出格式
            </div>
            <Segmented
              className="mt-2 w-full"
              value={props.videoOutputFormat}
              onChange={(value) =>
                props.onVideoOutputFormatChange(value as VideoOutputFormat)
              }
              options={[
                { value: "jpg", label: "JPG" },
                { value: "png", label: "PNG" },
              ]}
              disabled={props.isAnyImporting}
              block
            />

            {props.videoOutputFormat === "jpg" ? (
              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-[0.2em] text-neutral-500">
                  <span>JPEG 质量</span>
                  <span>{props.videoJpegQuality}</span>
                </div>
                <Slider
                  min={1}
                  max={100}
                  value={props.videoJpegQuality}
                  onChange={props.onVideoJpegQualityChange}
                  disabled={props.isAnyImporting}
                />
              </div>
            ) : (
              <div className="mt-4 rounded-lg border border-neutral-200 px-3 py-2 text-xs text-neutral-500 dark:border-white/10">
                PNG 会保留无损帧图像，文件体积通常更大。
              </div>
            )}

            <div className="mt-4 text-xs uppercase tracking-[0.2em] text-neutral-500">
              图片尺寸
            </div>
            <Segmented
              className="mt-2 w-full"
              value={props.videoTargetSize}
              onChange={(value) =>
                props.onVideoTargetSizeChange(value as VideoTargetSize)
              }
              options={videoTargetSizeOptions}
              disabled={props.isAnyImporting}
              block
            />
            <div className="mt-2 text-xs text-neutral-500">长边超过目标时等比缩小</div>

            <Button
              type="primary"
              className="mt-4 w-full"
              onClick={() => void props.onVideoImport()}
              disabled={!props.selectedVideoFile || props.isAnyImporting}
              icon={
                props.isImportingVideo ? (
                  <Loader className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )
              }
            >
              {props.isImportingVideo ? "正在提取图片…" : "开始提取图片"}
            </Button>
          </Card>
        </Col>
      </Row>
    </Card>
  );
}
