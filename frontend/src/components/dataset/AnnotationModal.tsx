import { Tag, X } from "lucide-react";
import { Button, Card, Checkbox, Col, Input, Modal, Row, Space } from "antd";

import type { Dataset } from "../../lib/types";

interface AnnotationModalProps {
  open: boolean;
  onClose: () => void;
  dataset: Dataset;
  confidenceThreshold: number;
  onConfidenceThresholdChange: (value: number) => void;
  skipAnnotated: boolean;
  onSkipAnnotatedChange: (value: boolean) => void;
  isSubmittingAnnotation: boolean;
  onSubmit: () => void;
}

export function AnnotationModal({
  open,
  onClose,
  dataset,
  confidenceThreshold,
  onConfidenceThresholdChange,
  skipAnnotated,
  onSkipAnnotatedChange,
  isSubmittingAnnotation,
  onSubmit,
}: AnnotationModalProps) {
  const annotationRunning = dataset.annotation?.status === "running";
  const annotationStatus = String(dataset.annotation?.status ?? "idle");

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closeIcon={<X className="h-5 w-5 text-neutral-500" />}
      title={
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            <Tag className="h-4 w-4" />
            Auto Annotation
          </div>
          <div className="mt-2 text-xl">自动标注</div>
        </div>
      }
      width={600}
    >
      <p className="mb-4 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
        AI 将识别图片中的目标并生成检测框，完成后可以继续复核和修改。
      </p>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={14}>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            最低置信度
          </div>
          <Input
            type="number"
            min={0.3}
            max={0.95}
            step={0.05}
            value={confidenceThreshold}
            onChange={(event) =>
              onConfidenceThresholdChange(Number(event.target.value))
            }
          />
        </Col>
        <Col xs={24} md={10}>
          <Card className="bg-neutral-50 dark:bg-white/[0.03]">
            <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">范围</div>
            <div className="mt-2 text-lg">{dataset.imageCount} 张样本</div>
            <div className="mt-1 text-sm text-neutral-500">
              当前状态：
              {annotationRunning
                ? "运行中"
                : annotationStatus === "completed"
                  ? "已完成"
                  : "尚未开始"}
            </div>
          </Card>
        </Col>
      </Row>

      <Checkbox
        className="mt-5"
        checked={skipAnnotated}
        onChange={(event) => onSkipAnnotatedChange(event.target.checked)}
      >
        跳过已标注的样本，仅标注未标注的图片
      </Checkbox>

      <Space className="mt-6">
        <Button onClick={onClose} disabled={isSubmittingAnnotation}>取消</Button>
        <Button
          type="primary"
          onClick={() => void onSubmit()}
          loading={isSubmittingAnnotation}
          disabled={isSubmittingAnnotation || dataset.imageCount === 0}
        >
          自动标注
        </Button>
      </Space>
    </Modal>
  );
}
