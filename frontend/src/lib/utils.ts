import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatCurrency(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatDate(value?: string | null) {
  if (!value) return "未开始";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatProviderLabel(providerId: string) {
  if (providerId === "gemini") return "Nano Banana 2";
  if (providerId === "jimeng") return "即梦 AI";
  if (providerId === "stability") return "Stability AI";
  if (providerId === "custom") return "Custom Adapter";
  return providerId;
}
