import { Cpu, Play } from "lucide-react";
import { Button, Col, Input, Row, Space } from "antd";

import type { Dataset } from "../../../lib/types";

interface TrainingFormProps {
  dataset: Dataset;
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
  trainingRunning: boolean;
  onStart: () => void;
}

export function TrainingForm({
  dataset,
  trainingModel,
  onTrainingModelChange,
  trainingEpochs,
  onTrainingEpochsChange,
  trainingImageSize,
  onTrainingImageSizeChange,
  trainingBatchSize,
  onTrainingBatchSizeChange,
  trainingPatience,
  onTrainingPatienceChange,
  trainingDropout,
  onTrainingDropoutChange,
  trainingMixup,
  onTrainingMixupChange,
  trainingWeightDecay,
  onTrainingWeightDecayChange,
  trainingClassIndices,
  onTrainingClassIndicesChange,
  isCreatingTrainingJob,
  trainingRunning,
  onStart,
}: TrainingFormProps) {
  const trainingClassIndexSet = new Set(trainingClassIndices);

  function toggleClass(index: number) {
    onTrainingClassIndicesChange(
      trainingClassIndices.includes(index)
        ? trainingClassIndices.filter((item) => item !== index)
        : [...trainingClassIndices, index].sort((a, b) => a - b),
    );
  }

  return (
    <div>
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
        <Cpu className="h-4 w-4" />
        YOLOv8 模型训练
      </div>
      <div className="mt-2 text-2xl">训练参数</div>

      <Row gutter={[12, 12]} className="mt-6">
        <Col xs={24} md={12} lg={8} xl={8}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500">模型</div>
          <Input
            value={trainingModel}
            onChange={(event) => onTrainingModelChange(event.target.value)}
          />
        </Col>
        <Col xs={24} md={12} lg={8} xl={4}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500">训练轮数</div>
          <Input
            type="number"
            min={1}
            max={500}
            value={trainingEpochs}
            onChange={(event) => onTrainingEpochsChange(Number(event.target.value))}
          />
        </Col>
        <Col xs={24} md={12} lg={8} xl={4}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500">输入尺寸</div>
          <Input
            type="number"
            min={64}
            max={2048}
            step={32}
            value={trainingImageSize}
            onChange={(event) => onTrainingImageSizeChange(Number(event.target.value))}
          />
        </Col>
        <Col xs={24} md={12} lg={8} xl={4}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500">每批图片数</div>
          <Input
            type="number"
            min={1}
            max={256}
            value={trainingBatchSize}
            onChange={(event) => onTrainingBatchSizeChange(Number(event.target.value))}
          />
        </Col>
      </Row>

      <div className="mt-4">
        <div className="mb-2 text-xs uppercase tracking-[0.18em] text-neutral-500">训练类别</div>
        <Space wrap size="small">
          <Button
            size="small"
            type={trainingClassIndices.length === 0 ? "primary" : "default"}
            onClick={() => onTrainingClassIndicesChange([])}
          >
            全部
          </Button>
          {dataset.categories.map((category, index) => (
            <Button
              key={`${index}-${category}`}
              size="small"
              type={trainingClassIndexSet.has(index) ? "primary" : "default"}
              onClick={() => toggleClass(index)}
            >
              {index}: {category}
            </Button>
          ))}
        </Space>
      </div>

      <Row gutter={[12, 12]} className="mt-4">
        <Col xs={12} md={6} lg={4}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500" title="指标连续多少轮没有改善后提前停止">提前停止等待轮数</div>
          <Input
            type="number"
            min={0}
            max={200}
            value={trainingPatience}
            onChange={(event) => onTrainingPatienceChange(Number(event.target.value))}
          />
        </Col>
        <Col xs={12} md={6} lg={4}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500" title="训练时随机忽略部分特征的比例">随机失活比例</div>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={trainingDropout}
            onChange={(event) => onTrainingDropoutChange(Number(event.target.value))}
          />
        </Col>
        <Col xs={12} md={6} lg={4}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500" title="混合两张训练图片的比例">混合增强比例</div>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.01}
            value={trainingMixup}
            onChange={(event) => onTrainingMixupChange(Number(event.target.value))}
          />
        </Col>
        <Col xs={12} md={6} lg={4}>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-neutral-500" title="用于抑制模型过拟合的正则化强度">权重衰减</div>
          <Input
            type="number"
            min={0}
            max={1}
            step={0.0001}
            value={trainingWeightDecay}
            onChange={(event) => onTrainingWeightDecayChange(Number(event.target.value))}
          />
        </Col>
      </Row>

      <Space className="mt-4">
        <Button
          type="primary"
          icon={<Play className="h-4 w-4" />}
          onClick={() => void onStart()}
          loading={isCreatingTrainingJob}
          disabled={
            isCreatingTrainingJob || dataset.selectedCount === 0 || trainingRunning
          }
        >
          开始训练
        </Button>
        {dataset.selectedCount === 0 ? (
          <span className="text-sm text-neutral-500">请先保留样本后再训练。</span>
        ) : null}
      </Space>
    </div>
  );
}
