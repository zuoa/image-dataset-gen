import { Upload, X, FileVideo, Download } from "lucide-react";
import { Modal, Tabs } from "antd";
import type { TabsProps } from "antd";

import { VideoImportForm } from "./VideoImportForm";
import { ZipImportForm } from "./ZipImportForm";
import { RoboflowImportForm } from "./RoboflowImportForm";
import type {
  VideoFrameIntervalMode,
  VideoOutputFormat,
  VideoTargetSize,
} from "../types";

interface ImportModalProps {
  open: boolean;
  onClose: () => void;
  activeTab: "video" | "zip" | "roboflow";
  onTabChange: (tab: "video" | "zip" | "roboflow") => void;
  actionError: string | null;
  onClearActionError: () => void;
  isAnyImporting: boolean;

  // Video
  selectedVideoFile: File | null;
  onVideoSelect: (file: File | null) => void;
  onVideoImport: () => Promise<void>;
  isImportingVideo: boolean;
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

  // ZIP
  archiveInputRef: React.RefObject<HTMLInputElement>;
  onArchiveSelect: (file: File) => void;
  isImportingZip: boolean;
  archiveImportFile: { name: string; size: number } | null;

  // Roboflow
  roboflowConnections: { id: string; name: string; status: string }[];
  selectedRoboflowConnectionId: string;
  onSelectedRoboflowConnectionIdChange: (id: string) => void;
  onLoadRoboflowConnections: () => Promise<void>;
  onSaveRoboflowConnection: () => Promise<void>;
  onRemoveSelectedRoboflowConnection: () => Promise<void>;
  newRoboflowConnectionName: string;
  onNewRoboflowConnectionNameChange: (value: string) => void;
  newRoboflowApiKey: string;
  onNewRoboflowApiKeyChange: (value: string) => void;
  showRoboflowConnectionForm: boolean;
  onShowRoboflowConnectionFormChange: (show: boolean) => void;
  isLoadingRoboflowConnections: boolean;
  isSavingRoboflowConnection: boolean;
  roboflowWorkspace: string;
  onRoboflowWorkspaceChange: (value: string) => void;
  roboflowProject: string;
  onRoboflowProjectChange: (value: string) => void;
  roboflowVersion: string;
  onRoboflowVersionChange: (value: string) => void;
  onRoboflowImport: () => Promise<void>;
  isImportingRoboflow: boolean;
}

export function ImportModal(props: ImportModalProps) {
  const items: TabsProps["items"] = [
    {
      key: "video",
      label: (
        <span className="inline-flex items-center gap-2">
          <FileVideo className="h-4 w-4" />
          视频抽帧
        </span>
      ),
      children: <VideoImportForm {...props} />,
    },
    {
      key: "zip",
      label: (
        <span className="inline-flex items-center gap-2">
          <Upload className="h-4 w-4" />
          本地 ZIP
        </span>
      ),
      children: <ZipImportForm {...props} />,
    },
    {
      key: "roboflow",
      label: (
        <span className="inline-flex items-center gap-2">
          <Download className="h-4 w-4" />
          Roboflow
        </span>
      ),
      children: <RoboflowImportForm {...props} />,
    },
  ];

  return (
    <Modal
      open={props.open}
      onCancel={props.onClose}
      footer={null}
      closeIcon={<X className="h-5 w-5 text-neutral-500" />}
      title={
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            <Upload className="h-4 w-4" />
            Import
          </div>
          <div className="mt-2 text-xl">导入图片</div>
        </div>
      }
      width={900}
      styles={{ body: { paddingTop: 12 } }}
    >
      <p className="mb-4 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
        从视频、ZIP 压缩包或 Roboflow 导入图片和标注。
      </p>

      {props.actionError ? (
        <div
          className="mb-4 rounded-lg border border-red-300/50 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-400/20 dark:bg-red-950/30 dark:text-red-100"
          role="alert"
        >
          {props.actionError}
        </div>
      ) : null}

      <Tabs
        activeKey={props.activeTab}
        onChange={(key) => props.onTabChange(key as "video" | "zip" | "roboflow")}
        items={items}
      />
    </Modal>
  );
}
