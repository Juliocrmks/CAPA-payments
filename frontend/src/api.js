// Tiny fetch wrapper: JSON in/out, readable errors, and a hook to bounce to the sign-in screen on 401.
let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function request(path, opt = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opt });
  let body = null;
  try { body = await r.json(); } catch { /* empty */ }
  if (r.status === 401 && !path.startsWith("/api/login") && !path.startsWith("/api/me")) onUnauthorized();
  if (!r.ok) {
    const d = body && body.detail;
    const msg = Array.isArray(d) ? d.map((x) => x.msg).join(", ") : d || `Something went wrong (${r.status})`;
    throw new Error(msg);
  }
  return body;
}
const json = (method) => (path, data) =>
  request(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) });

export const api = {
  get: (path) => request(path),
  post: json("POST"),
  patch: json("PATCH"),
  put: json("PUT"),
  del: (path) => request(path, { method: "DELETE" }),
  upload: (path, form) => request(path, { method: "POST", body: form }),
};

export const money = (v) => {
  const n = typeof v === "number" ? v : parseFloat(String(v || "").replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n.toLocaleString("en-US", { style: "currency", currency: "USD" }) : "—";
};
// Taxable, not taxable and not-set parts of one payment. A payment split by invoice is 'Partial' with taxable_amount.
export const taxParts = (f) => {
  const a = num(f.amount);
  if (f.taxable === "Partial") { const t = num(f.taxable_amount); return { tax: t, non: a - t, unset: 0 }; }
  return f.taxable === "Yes" ? { tax: a, non: 0, unset: 0 } : f.taxable === "No" ? { tax: 0, non: a, unset: 0 } : { tax: 0, non: 0, unset: a };
};
// 'Affects daily total': on unless turned off; a negative amount deposited to BPS is off unless turned on.
export const inDaily = (f) => {
  if (f.daily_total === "Yes" || f.daily_total === "No") return f.daily_total === "Yes";
  return !(num(f.amount) < 0 && String(f.deposit_bank || "").trim().toUpperCase().startsWith("BPS"));
};
export const num = (v) => { const n = parseFloat(String(v ?? "").replace(/[^0-9.-]/g, "")); return Number.isFinite(n) ? n : 0; };
export const fdate = (iso, opts) => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y) return iso;
  return new Date(y, m - 1, d).toLocaleDateString("en-US", opts || { month: "short", day: "numeric", year: "numeric" });
};
export const todayIso = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
export const METHODS = { check: "Check", cash: "Cash", card: "Credit card", ach: "ACH / e-check", wire: "Wire transfer" };

// POST that returns a file (e.g. the ledger as .xlsx): saves it with the name the server suggests.
export async function downloadPost(path, data, fallbackName) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) });
  if (!r.ok) { let m = `Download failed (${r.status})`; try { m = (await r.json()).detail || m; } catch { /* empty */ } throw new Error(m); }
  const name = (r.headers.get("content-disposition") || "").match(/filename="([^"]+)"/)?.[1] || fallbackName;
  const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click();
}
