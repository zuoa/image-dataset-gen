import { Cpu } from "lucide-react";
import { Col, Modal, Row } from "antd";

import { TrainingResultsPanel } from "../../TrainingResultsPanel";
import { TrainingModelTestPanel } from "../../TrainingModelTestPanel";
import { TrainingForm } from "./TrainingForm";
import { TrainingJobCard } from "./TrainingJobCard";
import type { Dataset, TrainingArtifact, TrainingJob } from "../../../lib/types";
import {
  fallbackTrainingModelCatalog,
  useTrainingModels,
} from "../../../hooks/useTrainingModels";

const activeTrainingStatuses = new Set([
  "queued",
  "assigned",
  "preparing",
  "running",
  "uploading",
]);

interface TrainingPanelProps {
  open: boolean;
  dataset: Dataset;
  trainingJobs: TrainingJob[];
  trainingModel: string;
  onTrainingModelChange: (value: string) => void;
  trainingEpochs: number;
  onTrainingEpochsChange: (value: number) => void;
  trainingImageSize: number;
  onTrainingImageSizeChange: (value: number) => void;
  trainingBatchSize: number;
  onTrainingBatchSizeChange: (value: number) => void;
  trainingPatience: number;
  onTrainingPatienceChange: (value: number) => void;
  trainingDropout: number;
  onTrainingDropoutChange: (value: number) => void;
  trainingMixup: number;
  onTrainingMixupChange: (value: number) => void;
  trainingWeightDecay: number;
  onTrainingWeightDecayChange: (value: number) => void;
  trainingClassIndices: number[];
  onTrainingClassIndicesChange: (indices: number[]) => void;
  isCreatingTrainingJob: boolean;
  deletingTrainingJobId: string | null;
  onStartTrainingJob: (model: string) => void;
  onRemoveTrainingJob: (job: TrainingJob) => void;
  onDownloadArtifact: (artifact: TrainingArtifact) => void;
  onClose: () => void;
}

export function TrainingPanel(props: TrainingPanelProps) {
  const trainingModelsQuery = useTrainingModels();
  const trainingModelCatalog = trainingModelsQuery.data?.models.length
    ? trainingModelsQuery.data
    : fallbackTrainingModelCatalog;
  const effectiveTrainingModel = trainingModelCatalog.models.some(
    (model) => model.id === props.trainingModel,
  )
    ? props.trainingModel
    : (trainingModelCatalog.models.find((model) => model.recommended)?.id ??
      trainingModelCatalog.models[0].id);
  const trainingModelHint = trainingModelsQuery.isLoading
    ? "正在读取训练器支持的模型。"
    : trainingModelsQuery.error
      ? "无法读取训练器能力，当前显示系统预置型号。"
      : trainingModelCatalog.source === "preset"
        ? trainingModelCatalog.onlineWorkerCount > 0
          ? "在线训练器尚未上报型号，当前显示系统预置型号。"
          : "当前没有在线训练器，任务将排队等待兼容节点。"
        : `${trainingModelCatalog.onlineWorkerCount} 个在线训练器已上报可用型号。`;
  const latestTrainingJob = props.trainingJobs[0] ?? null;
  const trainingRunning = latestTrainingJob
    ? activeTrainingStatuses.has(latestTrainingJob.status)
    : false;

  return (
    <Modal
      open={props.open}
      onCancel={props.onClose}
      footer={null}
      width={1180}
      title={
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--df-color-primary)] text-[var(--df-color-text-light-solid)]">
            <Cpu className="h-4 w-4" />
          </span>
          <span>模型训练</span>
        </div>
      }
      styles={{
        body: {
          maxHeight: "calc(100vh - 160px)",
          overflowY: "auto",
          paddingTop: 12,
        },
      }}
    >
      <Row gutter={[24, 24]}>
        <Col xs={24} xl={16}>
          <TrainingForm
            dataset={props.dataset}
            trainingModel={effectiveTrainingModel}
            onTrainingModelChange={props.onTrainingModelChange}
            trainingModels={trainingModelCatalog.models}
            trainingModelsLoading={trainingModelsQuery.isFetching}
            trainingModelHint={trainingModelHint}
            trainingEpochs={props.trainingEpochs}
            onTrainingEpochsChange={props.onTrainingEpochsChange}
            trainingImageSize={props.trainingImageSize}
            onTrainingImageSizeChange={props.onTrainingImageSizeChange}
            trainingBatchSize={props.trainingBatchSize}
            onTrainingBatchSizeChange={props.onTrainingBatchSizeChange}
            trainingPatience={props.trainingPatience}
            onTrainingPatienceChange={props.onTrainingPatienceChange}
            trainingDropout={props.trainingDropout}
            onTrainingDropoutChange={props.onTrainingDropoutChange}
            trainingMixup={props.trainingMixup}
            onTrainingMixupChange={props.onTrainingMixupChange}
            trainingWeightDecay={props.trainingWeightDecay}
            onTrainingWeightDecayChange={props.onTrainingWeightDecayChange}
            trainingClassIndices={props.trainingClassIndices}
            onTrainingClassIndicesChange={props.onTrainingClassIndicesChange}
            isCreatingTrainingJob={props.isCreatingTrainingJob}
            trainingRunning={trainingRunning}
            onStart={() => props.onStartTrainingJob(effectiveTrainingModel)}
          />
        </Col>
        <Col xs={24} xl={8}>
          <TrainingJobCard
            job={latestTrainingJob}
            deletingJobId={props.deletingTrainingJobId}
            onRemove={props.onRemoveTrainingJob}
            onDownloadArtifact={props.onDownloadArtifact}
          />
        </Col>
      </Row>

      {latestTrainingJob ? (
        <>
          <TrainingResultsPanel job={latestTrainingJob} />
          <TrainingModelTestPanel job={latestTrainingJob} />
        </>
      ) : null}
    </Modal>
  );
}
