import { Wand2, X } from "lucide-react";
import { Button, Card, Col, Input, Modal, Row, Slider, Space } from "antd";

import type {
  AugmentationMethod,
  AugmentationSettings,
} from "../../lib/types";

const augmentationOptions: Array<{
  value: AugmentationMethod;
  label: string;
  description: string;
}> = [
  { value: "flip", label: "水平翻转", description: "学习左右方向不变性" },
  { value: "affine", label: "仿射变化", description: "缩放、平移、旋转和轻微剪切" },
  { value: "safe_crop", label: "目标安全裁切", description: "裁切时同步保护检测框" },
  { value: "target_occlusion", label: "目标内遮挡", description: "优先在目标框内模拟遮挡" },
  { value: "lighting", label: "真实光照", description: "曝光、Gamma、饱和度和色温" },
  { value: "degradation", label: "成像退化", description: "压缩、低清、噪声、运动与失焦" },
];

function formatProbability(value: number) {
  return `${Math.round(value * 100)}%`;
}

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
        <div className="mt-3 grid gap-2 text-xs text-neutral-500 sm:grid-cols-2">
          {augmentationOptions
            .filter((option) => augmentationMethods.includes(option.value))
            .map((option) => (
              <div key={option.value}>
                <span className="font-medium text-neutral-700 dark:text-neutral-300">
                  {option.label}
                </span>
                ：{option.description}
              </div>
            ))}
        </div>
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
                      onClick={() =>
                        updateSettings({
                          flip: { ...augmentationSettings.flip, mode },
                        })
                      }
                    >
                      {mode === "random" ? "随机" : mode === "horizontal" ? "水平" : "垂直"}
                    </Button>
                  ))}
                </Space>
                <div className="mt-3 flex items-center justify-between text-sm font-medium">
                  <span>执行概率</span>
                  <span className="text-neutral-400">
                    {formatProbability(augmentationSettings.flip.probability)}
                  </span>
                </div>
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={augmentationSettings.flip.probability}
                  onChange={(value) =>
                    updateSettings({
                      flip: { ...augmentationSettings.flip, probability: value },
                    })
                  }
                />
              </Col>
            ) : null}

            {augmentationMethods.includes("affine") ? (
              <Col xs={24}>
                <div className="text-sm font-medium">
                  仿射缩放范围{" "}
                  <span className="text-neutral-400">
                    {augmentationSettings.affine.min_scale} –{" "}
                    {augmentationSettings.affine.max_scale}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <Slider
                    min={0.7}
                    max={1}
                    step={0.01}
                    value={augmentationSettings.affine.min_scale}
                    onChange={(value) =>
                      updateSettings({
                        affine: { ...augmentationSettings.affine, min_scale: value },
                      })
                    }
                  />
                  <Slider
                    min={1}
                    max={1.3}
                    step={0.01}
                    value={augmentationSettings.affine.max_scale}
                    onChange={(value) =>
                      updateSettings({
                        affine: { ...augmentationSettings.affine, max_scale: value },
                      })
                    }
                  />
                </div>
                <div className="grid gap-4 sm:grid-cols-4">
                  <div>
                    <div className="flex justify-between text-xs">
                      <span>平移</span>
                      <span>{augmentationSettings.affine.max_translate}</span>
                    </div>
                    <Slider
                      min={0}
                      max={0.1}
                      step={0.005}
                      value={augmentationSettings.affine.max_translate}
                      onChange={(value) =>
                        updateSettings({
                          affine: { ...augmentationSettings.affine, max_translate: value },
                        })
                      }
                    />
                  </div>
                  <div>
                    <div className="flex justify-between text-xs">
                      <span>旋转</span>
                      <span>{augmentationSettings.affine.max_rotate}°</span>
                    </div>
                    <Slider
                      min={0}
                      max={20}
                      step={0.5}
                      value={augmentationSettings.affine.max_rotate}
                      onChange={(value) =>
                        updateSettings({
                          affine: { ...augmentationSettings.affine, max_rotate: value },
                        })
                      }
                    />
                  </div>
                  <div>
                    <div className="flex justify-between text-xs">
                      <span>剪切</span>
                      <span>{augmentationSettings.affine.max_shear}°</span>
                    </div>
                    <Slider
                      min={0}
                      max={10}
                      step={0.5}
                      value={augmentationSettings.affine.max_shear}
                      onChange={(value) =>
                        updateSettings({
                          affine: { ...augmentationSettings.affine, max_shear: value },
                        })
                      }
                    />
                  </div>
                  <div>
                    <div className="flex justify-between text-xs">
                      <span>执行概率</span>
                      <span>{formatProbability(augmentationSettings.affine.probability)}</span>
                    </div>
                    <Slider
                      min={0}
                      max={1}
                      step={0.05}
                      value={augmentationSettings.affine.probability}
                      onChange={(value) =>
                        updateSettings({
                          affine: { ...augmentationSettings.affine, probability: value },
                        })
                      }
                    />
                  </div>
                </div>
              </Col>
            ) : null}

            {augmentationMethods.includes("safe_crop") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>安全裁切执行概率</span>
                  <span className="text-neutral-400">
                    {formatProbability(augmentationSettings.safe_crop.probability)}
                  </span>
                </div>
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={augmentationSettings.safe_crop.probability}
                  onChange={(value) =>
                    updateSettings({
                      safe_crop: { ...augmentationSettings.safe_crop, probability: value },
                    })
                  }
                />
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>边界侵蚀</span>
                  <span className="text-neutral-400">
                    {augmentationSettings.safe_crop.erosion_rate}
                  </span>
                </div>
                <Slider
                  min={0}
                  max={0.2}
                  step={0.01}
                  value={augmentationSettings.safe_crop.erosion_rate}
                  onChange={(value) =>
                    updateSettings({
                      safe_crop: { ...augmentationSettings.safe_crop, erosion_rate: value },
                    })
                  }
                />
                <div className="text-xs text-neutral-400">设为 0 时完整保留所有检测框。</div>
              </Col>
            ) : null}

            {augmentationMethods.includes("target_occlusion") ? (
              <Col xs={24} md={12}>
                <div className="text-sm font-medium">
                  目标内遮挡比例{" "}
                  <span className="text-neutral-400">
                    {augmentationSettings.target_occlusion.min_ratio} –{" "}
                    {augmentationSettings.target_occlusion.max_ratio}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <Slider
                    min={0.05}
                    max={0.5}
                    step={0.01}
                    value={augmentationSettings.target_occlusion.min_ratio}
                    onChange={(value) =>
                      updateSettings({
                        target_occlusion: {
                          ...augmentationSettings.target_occlusion,
                          min_ratio: value,
                        },
                      })
                    }
                  />
                  <Slider
                    min={0.05}
                    max={0.6}
                    step={0.01}
                    value={augmentationSettings.target_occlusion.max_ratio}
                    onChange={(value) =>
                      updateSettings({
                        target_occlusion: {
                          ...augmentationSettings.target_occlusion,
                          max_ratio: value,
                        },
                      })
                    }
                  />
                </div>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>执行概率</span>
                  <span className="text-neutral-400">
                    {formatProbability(augmentationSettings.target_occlusion.probability)}
                  </span>
                </div>
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={augmentationSettings.target_occlusion.probability}
                  onChange={(value) =>
                    updateSettings({
                      target_occlusion: {
                        ...augmentationSettings.target_occlusion,
                        probability: value,
                      },
                    })
                  }
                />
              </Col>
            ) : null}

            {augmentationMethods.includes("lighting") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>光照变化强度</span>
                  <span className="text-neutral-400">{augmentationSettings.lighting.strength}</span>
                </div>
                <Slider
                  min={0}
                  max={0.4}
                  step={0.01}
                  value={augmentationSettings.lighting.strength}
                  onChange={(value) =>
                    updateSettings({
                      lighting: { ...augmentationSettings.lighting, strength: value },
                    })
                  }
                />
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>执行概率</span>
                  <span className="text-neutral-400">
                    {formatProbability(augmentationSettings.lighting.probability)}
                  </span>
                </div>
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={augmentationSettings.lighting.probability}
                  onChange={(value) =>
                    updateSettings({
                      lighting: { ...augmentationSettings.lighting, probability: value },
                    })
                  }
                />
              </Col>
            ) : null}

            {augmentationMethods.includes("degradation") ? (
              <Col xs={24} md={12}>
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>成像退化强度</span>
                  <span className="text-neutral-400">{augmentationSettings.degradation.strength}</span>
                </div>
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={augmentationSettings.degradation.strength}
                  onChange={(value) =>
                    updateSettings({
                      degradation: { ...augmentationSettings.degradation, strength: value },
                    })
                  }
                />
                <div className="flex items-center justify-between text-sm font-medium">
                  <span>执行概率</span>
                  <span className="text-neutral-400">
                    {formatProbability(augmentationSettings.degradation.probability)}
                  </span>
                </div>
                <Slider
                  min={0}
                  max={1}
                  step={0.05}
                  value={augmentationSettings.degradation.probability}
                  onChange={(value) =>
                    updateSettings({
                      degradation: {
                        ...augmentationSettings.degradation,
                        probability: value,
                      },
                    })
                  }
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
