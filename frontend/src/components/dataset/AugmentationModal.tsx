import { Wand2, X } from "lucide-react";
import { Button, Card, Col, Input, Modal, Row, Slider, Space } from "antd";

import type {
  AugmentationMethod,
  AugmentationSettings,
} from "../../lib/types";

const augmentationOptions: Array<{ value: AugmentationMethod; label: string }> =
  [
    { value: "flip", label: "翻转" },
    { value: "rotate", label: "旋转" },
    { value: "crop", label: "裁切" },
    { value: "color_jitter", label: "颜色抖动" },
    { value: "blur", label: "模糊" },
    { value: "noise", label: "噪声" },
    { value: "occlusion", label: "遮挡" },
    { value: "perspective", label: "透视" },
  ];

interface AugmentationModalProps {
  open: boolean;
  onClose: () => void;
  multiplier: number;
  onMultiplierChange: (value: number) => void;
  augmentationMethods: AugmentationMethod[];
  onAugmentationMethodsChange: (methods: AugmentationMethod[]) => void;
  augmentationSettings: AugmentationSettings;
  onAugmentationSettingsChange: (settings: AugmentationSettings) => void;
  selectedOriginalCount: number;
  isCreatingAugmentationTask: boolean;
  onCreate: () => void;
}

export function AugmentationModal({
  open,
  onClose,
  multiplier,
  onMultiplierChange,
  augmentationMethods,
  onAugmentationMethodsChange,
  augmentationSettings,
  onAugmentationSettingsChange,
  selectedOriginalCount,
  isCreatingAugmentationTask,
  onCreate,
}: AugmentationModalProps) {
  function toggleMethod(method: AugmentationMethod) {
    onAugmentationMethodsChange(
      augmentationMethods.includes(method)
        ? augmentationMethods.filter((item) => item !== method)
        : [...augmentationMethods, method],
    );
  }

  function updateSettings(partial: Partial<AugmentationSettings>) {
    onAugmentationSettingsChange({ ...augmentationSettings, ...partial });
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closeIcon={<X className="h-5 w-5 text-neutral-500" />}
      title={
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            <Wand2 className="h-4 w-4" />
            Augmentation
          </div>
          <div className="mt-2 text-xl">增强</div>
        </div>
      }
      width={800}
    >
      <p className="mb-4 text-sm leading-6 text-neutral-500 dark:text-neutral-400">
        为已保留的原图生成更多训练图片，完成后会加入当前数据集。
      </p>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            增强倍率
          </div>
          <Input
            type="number"
            min={2}
            max={20}
            value={multiplier}
            onChange={(event) => onMultiplierChange(Number(event.target.value))}
          />
        </Col>
        <Col xs={24} md={12}>
          <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
            可增强原始样本
          </div>
          <div className="rounded-lg border border-neutral-200 bg-neutral-100 px-4 py-3 text-sm dark:border-white/10 dark:bg-white/[0.03]">
            {selectedOriginalCount} 张
          </div>
        </Col>
      </Row>

      <div className="mt-5">
        <div className="mb-2 text-xs uppercase tracking-[0.2em] text-neutral-500">
          增强方法
        </div>
        <Space wrap size="small">
          {augmentationOptions.map((option) => (
            <Button
              key={option.value}
              type={
                augmentationMethods.includes(option.value) ? "primary" : "default"
              }
              onClick={() => toggleMethod(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </Space>
      </div>

      {augmentationMethods.length > 0 ? (
        <Card className="mt-5 bg-neutral-50 dark:bg-white/[0.03]">
          <div className="mb-3 text-xs uppercase tracking-[0.2em] text-neutral-500">
            参数调节
          </div>
          <Row gutter={[16, 16]}>
            {augmentationMethods.includes("flip") ? (
              <Col xs={24} md={12}>
                <div className="text-sm font-medium">翻转模式</div>
                <Space wrap className="mt-2">
                  {(["random", "horizontal", "vertical"] as const).map((mode) => (
                    <Button
                      key={mode}
                      size="small"
                      type={
                        augmentationSettings.flip.mode === mode ? "primary" : "default"
                      }
                      onClick={() => updateSettings({ flip: { mode } })}
                    >
                      {mode === "random" ? "随机" : mode === "horizontal" ? "水平" : "垂直"}
                    </Button>
                  ))}
                </Space>
              </Col>
            ) : null}

            {augmentationMethods.includes("rotate") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>最大旋转角度</span>
                  <span className="text-neutral-400">{augmentationSettings.rotate.max_angle}°</span>
                </div>
                <Slider
                  min={0}
                  max={20}
                  step={0.5}
                  value={augmentationSettings.rotate.max_angle}
                  onChange={(value) => updateSettings({ rotate: { max_angle: value } })}
                />
              </Col>
            ) : null}

            {augmentationMethods.includes("crop") ? (
              <Col xs={24} md={12}>
                <div className="text-sm font-medium">
                  裁切范围{" "}
                  <span className="text-neutral-400">
                    {augmentationSettings.crop.min_scale} –{" "}
                    {augmentationSettings.crop.max_scale}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <Slider
                    min={0.6}
                    max={0.98}
                    step={0.01}
                    value={augmentationSettings.crop.min_scale}
                    onChange={(value) =>
                      updateSettings({
                        crop: { ...augmentationSettings.crop, min_scale: value },
                      })
                    }
                  />
                  <Slider
                    min={0.6}
                    max={0.99}
                    step={0.01}
                    value={augmentationSettings.crop.max_scale}
                    onChange={(value) =>
                      updateSettings({
                        crop: { ...augmentationSettings.crop, max_scale: value },
                      })
                    }
                  />
                </div>
              </Col>
            ) : null}

            {augmentationMethods.includes("color_jitter") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>颜色抖动强度</span>
                  <span className="text-neutral-400">{augmentationSettings.color_jitter.strength}</span>
                </div>
                <Slider
                  min={0}
                  max={0.4}
                  step={0.01}
                  value={augmentationSettings.color_jitter.strength}
                  onChange={(value) => updateSettings({ color_jitter: { strength: value } })}
                />
              </Col>
            ) : null}

            {augmentationMethods.includes("blur") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>最大模糊半径</span>
                  <span className="text-neutral-400">{augmentationSettings.blur.max_radius}</span>
                </div>
                <Slider
                  min={0}
                  max={4}
                  step={0.1}
                  value={augmentationSettings.blur.max_radius}
                  onChange={(value) => updateSettings({ blur: { max_radius: value } })}
                />
              </Col>
            ) : null}

            {augmentationMethods.includes("noise") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>最大噪声强度</span>
                  <span className="text-neutral-400">{augmentationSettings.noise.max_sigma}</span>
                </div>
                <Slider
                  min={0}
                  max={40}
                  step={1}
                  value={augmentationSettings.noise.max_sigma}
                  onChange={(value) => updateSettings({ noise: { max_sigma: value } })}
                />
              </Col>
            ) : null}

            {augmentationMethods.includes("occlusion") ? (
              <Col xs={24} md={12}>
                <div className="text-sm font-medium">
                  遮挡比例{" "}
                  <span className="text-neutral-400">
                    {augmentationSettings.occlusion.min_ratio} –{" "}
                    {augmentationSettings.occlusion.max_ratio}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <Slider
                    min={0.05}
                    max={0.35}
                    step={0.01}
                    value={augmentationSettings.occlusion.min_ratio}
                    onChange={(value) =>
                      updateSettings({
                        occlusion: {
                          ...augmentationSettings.occlusion,
                          min_ratio: value,
                        },
                      })
                    }
                  />
                  <Slider
                    min={0.05}
                    max={0.4}
                    step={0.01}
                    value={augmentationSettings.occlusion.max_ratio}
                    onChange={(value) =>
                      updateSettings({
                        occlusion: {
                          ...augmentationSettings.occlusion,
                          max_ratio: value,
                        },
                      })
                    }
                  />
                </div>
              </Col>
            ) : null}

            {augmentationMethods.includes("perspective") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>最大透视畸变</span>
                  <span className="text-neutral-400">{augmentationSettings.perspective.max_warp}</span>
                </div>
                <Slider
                  min={0}
                  max={0.15}
                  step={0.005}
                  value={augmentationSettings.perspective.max_warp}
                  onChange={(value) => updateSettings({ perspective: { max_warp: value } })}
                />
              </Col>
            ) : null}
          </Row>
        </Card>
      ) : null}

      <Card className="mt-5 bg-neutral-50 dark:bg-white/[0.03]">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
              预计结果
            </div>
            <div className="mt-1 text-lg">
              预计新增 {selectedOriginalCount * multiplier} 张增强样本
            </div>
          </div>
          <Space>
            <Button onClick={onClose} disabled={isCreatingAugmentationTask}>
              取消
            </Button>
            <Button
              type="primary"
              icon={<Wand2 className="h-4 w-4" />}
              onClick={() => void onCreate()}
              loading={isCreatingAugmentationTask}
              disabled={
                isCreatingAugmentationTask ||
                augmentationMethods.length === 0 ||
                selectedOriginalCount === 0
              }
            >
              增强
            </Button>
          </Space>
        </div>
      </Card>
    </Modal>
  );
}
