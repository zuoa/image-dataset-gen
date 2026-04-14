import { Check } from "lucide-react";

import { wizardSteps } from "../lib/constants";
import { cn } from "../lib/utils";

export function StepRail({ currentStep }: { currentStep: number }) {
  return (
    <div className="space-y-3">
      {wizardSteps.map((step, index) => {
        const active = index === currentStep;
        const completed = index < currentStep;
        return (
          <div
            key={step.id}
            className={cn(
              "flex items-center gap-3 rounded-2xl border px-3 py-3 transition",
              active && "border-neutral-300 bg-neutral-100 dark:border-white/20 dark:bg-neutral-900",
              !active && "border-neutral-100 bg-white dark:border-white/12 dark:bg-neutral-950",
            )}
          >
            <div
              className={cn(
                "flex h-8 w-8 items-center justify-center rounded-full border text-xs",
                completed &&
                  "border-neutral-900 bg-neutral-900 text-white dark:border-white/12 dark:bg-neutral-100 dark:text-neutral-950",
                active && !completed && "border-neutral-400 text-neutral-900 dark:border-white/40 dark:text-white",
                !active && !completed && "border-neutral-200 text-neutral-400 dark:border-white/10 dark:text-neutral-500",
              )}
            >
              {completed ? <Check className="h-4 w-4" /> : index + 1}
            </div>
            <div>
              <div className="text-sm text-neutral-900 dark:text-white">{step.label}</div>
              <div className="text-xs text-neutral-500">Step {index + 1}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
