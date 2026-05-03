import { ApiError, classifyApiError, describeApiError } from "@smartcloud-x/frontend-sdk/core";
import toast from "react-hot-toast";

export function toMessage(error: unknown, fallback = "操作失败，请稍后再试"): string {
  if (error instanceof ApiError) return error.message || fallback;
  if (error instanceof Error) return error.message || fallback;
  return describeApiError(error, fallback).message;
}

export function notifyError(error: unknown, fallback?: string) {
  const info = describeApiError(error, fallback ?? "操作失败");
  const kind = classifyApiError(error);
  let title = info.message;
  if (kind === "unauthorized") title = "登录态已失效，请重新登录";
  else if (kind === "forbidden") title = "无权限：" + info.message;
  else if (kind === "rate_limited") title = "请求过于频繁，请稍后再试";
  else if (kind === "timeout") title = "请求超时，请稍后再试";
  toast.error(title);
}

export function notifySuccess(message: string) {
  toast.success(message);
}
