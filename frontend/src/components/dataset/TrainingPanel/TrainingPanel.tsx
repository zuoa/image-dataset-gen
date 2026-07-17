import { X } from "lucide-react";
import { Button, Card, Col, Row } from "antd";

import { TrainingResultsPanel } from "../../TrainingResultsPanel";
import { TrainingModelTestPanel } from "../../TrainingModelTestPanel";
import { TrainingForm } from "./TrainingForm";
import { TrainingJobCard } from "./TrainingJobCard";
import type { Dataset, TrainingArtifact, TrainingJob } from "../../../lib/types";

const activeTrainingStatuses = new Set([
  "queued",
  "assigned",
  "preparing",
  "running",
  "uploading",
]);

interface TrainingPanelProps {
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
  onStartTrainingJob: () => void;
  onRemoveTrainingJob: (job: TrainingJob) => void;
  onDownloadArtifact: (artifact: TrainingArtifact) => void;
  onClose: () => void;
}

export function TrainingPanel(props: TrainingPanelProps) {
  const latestTrainingJob = props.trainingJobs[0] ?? null;
  const trainingRunning = latestTrainingJob
    ? activeTrainingStatuses.has(latestTrainingJob.status)
    : false;

  return (
    <Card className="mt-6">
      <div className="flex items-start justify-between gap-3">
        <div />
        <Button
          type="text"
          shape="circle"
          icon={<X className="h-5 w-5" />}
          onClick={props.onClose}
          aria-label="关闭训练面板"
        />
      </div>

      <Row gutter={[24, 24]}>
        <Col xs={24} xl={16}>
          <TrainingForm
            dataset={props.dataset}
            trainingModel={props.trainingModel}
            onTrainingModelChange={props.onTrainingModelChange}
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
            onStart={props.onStartTrainingJob}
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
    </Card>
  );
}
