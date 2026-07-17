import { Button, Card, Space, Tag, Typography } from "antd";

import type { PromptPreview } from "../lib/types";
import { formatCurrency } from "../lib/utils";

export function PromptPreviewCard({
  preview,
  onCopy,
  compact = false,
}: {
  preview: PromptPreview | null;
  onCopy: () => void;
  compact?: boolean;
}) {
  return (
    <Card
      className="sticky top-6 h-fit"
      title={
        <div>
          <Typography.Text className="block text-xs uppercase tracking-[0.24em] text-neutral-500">
            Prompt Engine
          </Typography.Text>
          <Typography.Title level={3} className="!mb-0 !mt-2 !text-xl !font-medium">
            实时预览
          </Typography.Title>
        </div>
      }
      extra={
        <Button type="default" onClick={onCopy}>
          复制 Prompt
        </Button>
      }
    >
      {preview ? (
        <div className="space-y-5">
          <Card className="rounded-2xl" size="small" bordered>
            <Space wrap className="mb-3">
              <Tag color={preview.language === "zh" ? "blue" : "default"}>
                {preview.language === "zh" ? "中文适配" : "英文适配"}
              </Tag>
              <Tag color={preview.token_safe ? "success" : "warning"}>
                {preview.token_safe ? "Token Safe" : "Needs Trim"}
              </Tag>
              <Tag>{formatCurrency(preview.estimated_cost)}</Tag>
            </Space>
            <Typography.Paragraph
              className={`!mb-0 text-sm leading-7 text-neutral-700 dark:text-neutral-200 ${compact ? "line-clamp-6" : ""}`}
            >
              {preview.positive_prompt}
            </Typography.Paragraph>
          </Card>

          {compact ? (
            <Card className="rounded-2xl" size="small" bordered>
              <Typography.Text className="text-sm text-neutral-500 dark:text-neutral-400">
                当前先展示核心 Prompt 和费用预估。Negative Prompt 与变体会在确认提交步骤完整展开。
              </Typography.Text>
            </Card>
          ) : (
            <>
              <Card className="rounded-2xl" size="small" bordered>
                <Typography.Text className="block text-xs uppercase tracking-[0.24em] text-neutral-500">
                  Negative
                </Typography.Text>
                <Typography.Paragraph className="!mb-0 mt-2 text-sm leading-7 text-neutral-500 dark:text-neutral-400">
                  {preview.negative_prompt}
                </Typography.Paragraph>
              </Card>
              <div className="space-y-3">
                {preview.variants.slice(0, 3).map((variant) => (
                  <Card key={variant.seed} className="rounded-2xl" size="small" bordered>
                    <div className="mb-2 flex items-center justify-between text-xs text-neutral-500">
                      <span>Seed {variant.seed}</span>
                      <span>
                        {variant.diversity_vars.composition} / {variant.diversity_vars.occlusion}
                      </span>
                    </div>
                    <Typography.Paragraph className="!mb-0 line-clamp-3 text-sm text-neutral-600 dark:text-neutral-300">
                      {variant.prompt}
                    </Typography.Paragraph>
                  </Card>
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-neutral-200 p-6 text-sm text-neutral-500 dark:border-white/12 dark:bg-neutral-900/60 dark:text-neutral-400">
          填写完整后自动生成 Prompt 预览。
        </div>
      )}
    </Card>
  );
}
