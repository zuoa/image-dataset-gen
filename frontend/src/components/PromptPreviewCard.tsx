import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { SectionCard } from "./ui/SectionCard";
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
    <SectionCard className="sticky top-6 h-fit">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="text-sm uppercase tracking-[0.24em] text-neutral-500">Prompt Engine</div>
          <h3 className="mt-2 text-xl text-neutral-900 dark:text-white">实时预览</h3>
        </div>
        <Button variant="secondary" onClick={onCopy}>
          复制 Prompt
        </Button>
      </div>

      {preview ? (
        <div className="space-y-5">
          <div className="rounded-3xl border border-neutral-200 bg-neutral-100 p-4 dark:border-white/10 dark:bg-black/40">
            <div className="mb-3 flex flex-wrap gap-2">
              <Badge>{preview.language === "zh" ? "中文适配" : "英文适配"}</Badge>
              <Badge className={preview.token_safe ? "" : "border-amber-400/30 text-amber-700 dark:text-amber-200"}>
                {preview.token_safe ? "Token Safe" : "Needs Trim"}
              </Badge>
              <Badge>{formatCurrency(preview.estimated_cost)}</Badge>
            </div>
            <p className={`text-sm leading-7 text-neutral-700 dark:text-neutral-200 ${compact ? "line-clamp-6" : ""}`}>
              {preview.positive_prompt}
            </p>
          </div>
          {compact ? (
            <div className="rounded-3xl border border-neutral-200 bg-white p-4 text-sm text-neutral-500 dark:border-white/10 dark:bg-white/[0.03] dark:text-neutral-400">
              当前先展示核心 Prompt 和费用预估。Negative Prompt 与变体会在确认提交步骤完整展开。
            </div>
          ) : (
            <>
              <div className="rounded-3xl border border-neutral-200 bg-white p-4 dark:border-white/10 dark:bg-white/[0.03]">
                <div className="mb-2 text-xs uppercase tracking-[0.24em] text-neutral-500">Negative</div>
                <p className="text-sm leading-7 text-neutral-500 dark:text-neutral-400">{preview.negative_prompt}</p>
              </div>
              <div className="space-y-3">
                {preview.variants.slice(0, 3).map((variant) => (
                  <div key={variant.seed} className="rounded-2xl border border-neutral-100 bg-white p-3 dark:border-white/8 dark:bg-white/[0.02]">
                    <div className="mb-2 flex items-center justify-between text-xs text-neutral-500">
                      <span>Seed {variant.seed}</span>
                      <span>{variant.diversity_vars.composition}</span>
                    </div>
                    <p className="line-clamp-3 text-sm text-neutral-600 dark:text-neutral-300">{variant.prompt}</p>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        <div className="rounded-3xl border border-dashed border-neutral-200 p-6 text-sm text-neutral-500 dark:border-white/10">
          填写完整后自动生成 Prompt 预览。
        </div>
      )}
    </SectionCard>
  );
}
