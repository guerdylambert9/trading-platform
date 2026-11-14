const MINUS = "−";

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const dollarsCents = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const price = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function withMinus(text: string): string {
  return text.replace("-", MINUS);
}

export function money(value: number | null | undefined, cents = false): string {
  if (value == null || !Number.isFinite(value)) return "–";
  return withMinus((cents ? dollarsCents : dollars).format(value));
}

export function signedMoney(value: number): string {
  const text = money(Math.abs(value), true);
  if (value > 0) return `+${text}`;
  if (value < 0) return `${MINUS}${text}`;
  return text;
}

export function px(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "–";
  return withMinus(price.format(value));
}

export function pct(value: number | null | undefined, digits = 1, signed = false): string {
  if (value == null || !Number.isFinite(value)) return "–";
  const text = Math.abs(value).toFixed(digits);
  if (value < 0 && Number(text) !== 0) return `${MINUS}${text}%`;
  return `${signed && value > 0 ? "+" : ""}${text}%`;
}

export function qty(value: number): string {
  return Number.isInteger(value) ? value.toLocaleString("en-US") : value.toFixed(2);
}

export function day(isoDate: string): string {
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Times are shown in New York time, the market's clock, to match the job schedule.
const MARKET_ZONE = "America/New_York";

function lowerDayPeriod(text: string): string {
  return text.replace(/(AM|PM)$/, (period) => period.toLowerCase());
}

/** "Nov 13, 9:50 am ET"; pass zone=false where a column header already says ET. */
export function moment(iso: string | null | undefined, zone = true): string {
  if (!iso) return "–";
  const text = new Date(iso).toLocaleString("en-US", {
    timeZone: MARKET_ZONE,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return lowerDayPeriod(text) + (zone ? " ET" : "");
}

/** "8:16 pm ET" */
export function clockTime(date: Date): string {
  const text = date.toLocaleTimeString("en-US", { timeZone: MARKET_ZONE, hour: "numeric", minute: "2-digit" });
  return `${lowerDayPeriod(text)} ET`;
}

export function trend(value: number | null | undefined): "up" | "down" | "" {
  if (value == null || value === 0) return "";
  return value > 0 ? "up" : "down";
}

export function sentence(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
