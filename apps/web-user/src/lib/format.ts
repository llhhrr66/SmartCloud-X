import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";

dayjs.extend(relativeTime);
dayjs.locale("zh-cn");

export function formatDate(value?: string | number | Date | null, fmt = "YYYY-MM-DD HH:mm") {
  if (!value) return "—";
  const d = dayjs(value);
  return d.isValid() ? d.format(fmt) : "—";
}

export function formatDateOnly(value?: string | number | Date | null) {
  return formatDate(value, "YYYY-MM-DD");
}

export function formatRelative(value?: string | number | Date | null) {
  if (!value) return "—";
  const d = dayjs(value);
  return d.isValid() ? d.fromNow() : "—";
}

export function formatMoney(amount: string | number | null | undefined, currency = "CNY") {
  if (amount === null || amount === undefined || amount === "") return "—";
  const n = typeof amount === "string" ? Number(amount) : amount;
  if (!Number.isFinite(n)) return String(amount);
  const symbol = currency === "CNY" ? "¥" : currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatNumber(n: number | null | undefined, digits = 0) {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function formatPercent(n: number | null | undefined, digits = 1) {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

export function maskMobile(mobile?: string) {
  if (!mobile) return "";
  return mobile.replace(/(\d{3})\d{4}(\d{4})/, "$1****$2");
}

export function maskEmail(email?: string) {
  if (!email) return "";
  const [u, domain] = email.split("@");
  if (!domain) return email;
  if (u.length <= 2) return `${u[0]}*@${domain}`;
  return `${u.slice(0, 2)}${"*".repeat(Math.max(1, u.length - 3))}${u.slice(-1)}@${domain}`;
}

export function fileSize(bytes?: number) {
  if (!bytes && bytes !== 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}
