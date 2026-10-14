import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Box, Paper, Stack, Typography, TextField, MenuItem, Chip, Button, ToggleButtonGroup, ToggleButton, Autocomplete, Alert,
  Table, TableHead, TableBody, TableRow, TableCell, Tooltip, Tabs, Tab, InputAdornment, LinearProgress, Select, Checkbox, ListItemText } from "@mui/material";
import Grid from "@mui/material/Grid";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import InsightsIcon from "@mui/icons-material/Insights";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import SearchIcon from "@mui/icons-material/Search";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { LineChart } from "@mui/x-charts/LineChart";
import { BarChart } from "@mui/x-charts/BarChart";
import { useXScale, useYScale } from "@mui/x-charts/hooks";
import { api, money, fdate } from "../api";
import { brand, sheetColor, chartSeries, chartGray, chartGrid, methodChartColor, inkOn } from "../theme";
import { SheetChip, Triangles } from "../components/common";

// Admin -> Analytics. One filter row scopes everything below it: KPIs, the trend + projection, the breakdown and the
// storylines (written server-side from the same numbers). Payees and methods keep the same colour on every chart.
const PRESETS = [["30d", "Last 30 days"], ["90d", "Last 90 days"], ["qtd", "This quarter"], ["ytd", "Year to date"], ["12m", "Last 12 months"],
  ["ly", "Last calendar year"], ["all", "All time"], ["custom", "Custom dates"]];
const GRAINS = [["day", "Day"], ["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["year", "Year"]];
const DIMS = [["sheet", "Payee"], ["customer", "Client"], ["method", "Method"], ["bank", "Deposit bank"]];
const DIM_NOUN = { sheet: "payee", customer: "client", method: "method", bank: "deposit bank" };
const METHOD_NAMES = { check: "Check", cash: "Cash", card: "Credit card", ach: "ACH", wire: "Wire" };
const PER = { day: "day", week: "week", month: "month", quarter: "quarter", year: "year" };

// ---------------------------------------------------------------- formatting + dates
const compact = (v) => {
  if (v == null || !Number.isFinite(v)) return "";
  const a = Math.abs(v);
  if (a >= 1e6) return `$${(v / 1e6).toFixed(a >= 1e7 ? 1 : 2).replace(/\.0+$/, "")}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace(/\.0$/, "")}K`;
  return `$${Math.round(v)}`;
};
const fmt = (v) => (v == null ? null : money(v));
const D = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const I = (dt) => dt.toISOString().slice(0, 10);
const addDays = (iso, n) => { const d = D(iso); d.setUTCDate(d.getUTCDate() + n); return I(d); };
const addMonths = (iso, n) => { const d = D(iso); return I(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1))); };

function presetRange(p, asOf, first) {
  const y = asOf.slice(0, 4), m = Number(asOf.slice(5, 7));
  switch (p) {
    case "30d": return [addDays(asOf, -29), asOf, "day"];
    case "90d": return [addDays(asOf, -89), asOf, "week"];
    case "qtd": return [`${y}-${String(3 * Math.floor((m - 1) / 3) + 1).padStart(2, "0")}-01`, asOf, "week"];
    case "ytd": return [`${y}-01-01`, asOf, "month"];
    case "ly": return [`${Number(y) - 1}-01-01`, `${Number(y) - 1}-12-31`, "month"];
    case "all": { const months = (D(asOf) - D(first)) / 2.63e9; return [first, asOf, months > 36 ? "quarter" : "month"]; }
    default: return [addMonths(asOf.slice(0, 8) + "01", -11), asOf, "month"];
  }
}

function useWidth() {
  const ref = useRef(null); const [w, setW] = useState(800);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width)); ro.observe(ref.current); return () => ro.disconnect();
  }, []);
  return [ref, w];
}

// Payees and methods have fixed colours; deposit banks take palette slots in their settings order.
function colorFor(by, key, i, banks) {
  if (by === "sheet") return sheetColor[key] || chartSeries[4 + (i % 4)];
  if (by === "method") return methodChartColor[key] || chartGray;
  if (by === "bank") { const k = banks.indexOf(key); return key === "(none)" ? chartGray : chartSeries[k >= 0 && k < 8 ? k : 7]; }
  return brand.pipe;
}

// ---------------------------------------------------------------- page
export default function Analytics() {
  const [f, setF] = useState({ preset: "12m", start: "", end: "", grain: "month", by: "sheet", sheets: [], customer: "", methods: [] });
  const [data, setData] = useState(null);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const seq = useRef(0);
  const set = (patch) => setF((x) => ({ ...x, ...patch }));

  const range = useMemo(() => {
    if (!meta) return null;
    if (f.preset === "custom") return [f.start || meta.first, f.end || meta.as_of];
    const [a, b] = presetRange(f.preset, meta.as_of, meta.first); return [a, b];
  }, [f.preset, f.start, f.end, meta]);

  const load = useCallback(async () => {
    const my = ++seq.current; setLoading(true); setErr("");
    const q = new URLSearchParams({ grain: f.grain, by: f.by });
    if (range) { q.set("start", range[0]); q.set("end", range[1]); }
    if (f.sheets.length) q.set("sheets", f.sheets.join(","));
    if (f.methods.length) q.set("methods", f.methods.join(","));
    if (f.customer) q.set("customer", f.customer);
    try {
      const r = await api.get("/api/analytics?" + q.toString());
      if (my !== seq.current) return;
      setData(r);
      if (!meta && !r.empty) setMeta({ as_of: r.as_of, first: r.options.first, options: r.options });
    } catch (e) { if (my === seq.current) setErr(e.message); } finally { if (my === seq.current) setLoading(false); }
  }, [f, range, meta]);
  useEffect(() => { const t = setTimeout(load, 120); return () => clearTimeout(t); }, [load]);

  const choosePreset = (p) => {
    if (p === "custom") return set({ preset: p, start: range?.[0] || "", end: range?.[1] || "" });
    const g = meta ? presetRange(p, meta.as_of, meta.first)[2] : f.grain;
    set({ preset: p, grain: g });
  };
  const focus = (fc) => {
    if (!fc) return;
    if (fc.customer) set({ customer: fc.customer, by: f.by === "customer" ? "sheet" : f.by });
    else if (fc.sheet) set({ sheets: [fc.sheet] });
    else if (fc.method) set({ methods: [fc.method] });
    else if (fc.bank) set({ by: "bank" });
  };

  if (!data && !err) return <LinearProgress />;
  if (data?.empty) return (
    <Stack spacing={2} alignItems="flex-start">
      <Typography variant="h1">Analytics <Triangles /></Typography>
      <Alert severity="info">{data.message}</Alert>
      <Button variant="contained" startIcon={<UploadFileIcon />} onClick={() => { window.location.hash = "/ledger"; }}>Go to the Ledger to import a spreadsheet</Button>
    </Stack>);

  const opts = meta?.options || data?.options || {};
  const banks = opts.banks || [];
  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", md: "row" }} alignItems={{ md: "flex-end" }} spacing={1}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h1">Analytics <Triangles /></Typography>
          <Typography color="text.secondary">Receipts from the ledger, scanned and imported. Data through {fdate(meta?.as_of || data?.as_of)}.</Typography>
        </Box>
      </Stack>

      {/* one filter row scopes everything below */}
      <Paper sx={{ p: 1.5 }}>
        <Stack direction="row" spacing={1.5} useFlexGap flexWrap="wrap" alignItems="center">
          <TextField select label="Dates" value={f.preset} onChange={(e) => choosePreset(e.target.value)} sx={{ width: 190 }}>
            {PRESETS.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}</TextField>
          {f.preset === "custom" && <>
            <TextField type="date" label="From" value={f.start} onChange={(e) => set({ start: e.target.value })} sx={{ width: 160 }} InputLabelProps={{ shrink: true }} />
            <TextField type="date" label="To" value={f.end} onChange={(e) => set({ end: e.target.value })} sx={{ width: 160 }} InputLabelProps={{ shrink: true }} />
          </>}
          <ToggleButtonGroup size="small" exclusive value={f.grain} onChange={(_, v) => v && set({ grain: v })} aria-label="Group by period">
            {GRAINS.map(([k, l]) => <ToggleButton key={k} value={k} sx={{ px: 1.5 }}>{l}</ToggleButton>)}</ToggleButtonGroup>
          <Stack direction="row" spacing={.5} alignItems="center" aria-label="Payees">
            {(opts.sheets || []).filter((s) => s !== "(none)").map((s) => {
              const on = f.sheets.includes(s);
              return <Chip key={s} label={s} clickable onClick={() => set({ sheets: on ? f.sheets.filter((x) => x !== s) : [...f.sheets, s] })}
                variant={on ? "filled" : "outlined"} sx={on ? { bgcolor: sheetColor[s] || brand.brown, color: inkOn(sheetColor[s] || brand.brown) } : { borderColor: sheetColor[s] || "divider" }} />;
            })}
          </Stack>
          <Autocomplete size="small" options={opts.customers || []} value={f.customer || null} onChange={(_, v) => set({ customer: v || "", by: v && f.by === "customer" ? "sheet" : f.by })}
            sx={{ width: 280 }} renderInput={(p) => <TextField {...p} label="Client" placeholder="All clients" />} />
          <Select size="small" multiple displayEmpty value={f.methods} onChange={(e) => set({ methods: e.target.value })} sx={{ minWidth: 150, bgcolor: "#fff" }}
            renderValue={(v) => (v.length ? v.map((m) => METHOD_NAMES[m]).join(", ") : "All methods")} inputProps={{ "aria-label": "Payment methods" }}>
            {Object.entries(METHOD_NAMES).map(([k, l]) => <MenuItem key={k} value={k}><Checkbox size="small" checked={f.methods.includes(k)} /><ListItemText primary={l} /></MenuItem>)}
          </Select>
          {(f.sheets.length || f.methods.length || f.customer) ? <Button size="small" onClick={() => set({ sheets: [], methods: [], customer: "" })}>Clear filters</Button> : null}
          <Box sx={{ flex: 1 }} />
          {data && <Typography variant="body2" color="text.secondary">{data.range.label}</Typography>}
        </Stack>
        {loading && <LinearProgress sx={{ mt: 1, height: 2 }} />}
      </Paper>
      {err && <Alert severity="error">{err}</Alert>}

      {data && <Box sx={{ opacity: loading ? .55 : 1, transition: "opacity .15s" }}>
        <Stack spacing={2.5}>
          {f.customer && <Alert severity="info" icon={false} action={<Button color="inherit" size="small" onClick={() => set({ customer: "" })}>Show all clients</Button>}>
            Showing one client: <b>{f.customer}</b></Alert>}
          <KpiRow k={data.kpis} grain={data.grain} />
          <Grid container spacing={2.5}>
            <Grid size={{ xs: 12, lg: 8 }}><TrendCard data={data} /></Grid>
            <Grid size={{ xs: 12, lg: 4 }}><Storylines items={data.storylines} onFocus={focus} f={f} /></Grid>
          </Grid>
          <BreakdownCard data={data} by={f.by} setBy={(by) => set({ by })} banks={banks} customerSet={!!f.customer}
            onPick={(r) => (data.by === "customer" ? set({ customer: r.key, by: "sheet" }) : data.by === "sheet" ? set({ sheets: [r.key] }) : data.by === "method" ? set({ methods: [r.key] }) : null)} />
        </Stack>
      </Box>}
    </Stack>
  );
}

// ---------------------------------------------------------------- KPIs
function KpiRow({ k }) {
  const c = k.current, d = k.delta;
  const prev = `vs ${fdate(k.prev_range.start)} – ${fdate(k.prev_range.end)}`;
  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 6, md: 3 }}><Kpi label="Received" value={compact(c.total)} full={money(c.total)} delta={d.total} prev={prev} prevValue={money(k.previous.total)} spark={k.spark.total} /></Grid>
      <Grid size={{ xs: 6, md: 3 }}><Kpi label="Payments" value={c.count.toLocaleString()} delta={d.count} prev={prev} prevValue={k.previous.count.toLocaleString()} spark={k.spark.count} /></Grid>
      <Grid size={{ xs: 6, md: 3 }}><Kpi label="Average payment" value={money(c.avg).replace(/\.\d\d$/, "")} delta={d.avg} prev={prev} prevValue={money(k.previous.avg)} spark={k.spark.avg} /></Grid>
      <Grid size={{ xs: 6, md: 3 }}><Kpi label="Clients who paid" value={c.clients.toLocaleString()} delta={d.clients} prev={prev} prevValue={k.previous.clients.toLocaleString()} spark={k.spark.clients} /></Grid>
    </Grid>
  );
}

function Kpi({ label, value, full, delta, prev, prevValue, spark }) {
  const up = delta != null && delta >= 0;
  return (
    <Paper sx={{ p: 2, height: "100%" }}>
      <Typography variant="body2" color="text.secondary">{label}</Typography>
      <Tooltip title={full || ""} placement="top-start"><Typography sx={{ fontFamily: "Montserrat", fontWeight: 700, fontSize: { xs: "1.35rem", md: "1.7rem" }, lineHeight: 1.25 }}>{value}</Typography></Tooltip>
      <Stack direction="row" spacing={.5} alignItems="center" sx={{ mt: .25, minHeight: 22 }}>
        {delta == null ? <Typography variant="caption" color="text.secondary">No earlier data to compare</Typography> : <>
          {up ? <ArrowUpwardIcon sx={{ fontSize: 15, color: "success.main" }} /> : <ArrowDownwardIcon sx={{ fontSize: 15, color: "error.main" }} />}
          <Tooltip title={`${prev}: ${prevValue}`}><Typography variant="caption" sx={{ fontWeight: 700, color: up ? "success.main" : "error.main" }}>
            {up ? "+" : "−"}{Math.abs(delta).toFixed(Math.abs(delta) < 10 ? 1 : 0)}%</Typography></Tooltip>
          <Typography variant="caption" color="text.secondary">vs previous period</Typography></>}
      </Stack>
      <Spark values={spark} height={30} />
    </Paper>
  );
}

function Spark({ values, height = 24, width = "100%" }) {
  if (!values || values.length < 2) return <Box sx={{ height }} />;
  const max = Math.max(...values), min = Math.min(0, ...values), n = values.length;
  const pts = values.map((v, i) => [(i / (n - 1)) * 100, height - 3 - ((v - min) / (max - min || 1)) * (height - 6)]);
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" aria-hidden="true" style={{ display: "block", marginTop: 6 }}>
      <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke={chartGray} strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r="2.6" fill={brand.pipe} stroke="#fff" strokeWidth="1" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// ---------------------------------------------------------------- trend + projection
function Band({ keys, low, high, from }) {
  const x = useXScale(); const y = useYScale();
  const idx = keys.map((_, i) => i).filter((i) => i >= from && low[i] != null && high[i] != null);
  if (idx.length < 2) return null;
  const top = idx.map((i) => `${x(keys[i])},${y(high[i])}`); const bot = idx.slice().reverse().map((i) => `${x(keys[i])},${y(low[i])}`);
  return <path d={`M${top.join("L")}L${bot.join("L")}Z`} fill={brand.pipe} fillOpacity={0.1} stroke="none" pointerEvents="none" />;
}

function TrendCard({ data }) {
  const [view, setView] = useState("chart");
  const P = data.periods, pr = data.projection, n = P.length, m = pr.points.length;
  const pace = data.range.in_progress && pr.pace ? pr.pace : null;
  const keys = [...P.map((p) => p.key), ...pr.points.map((p) => p.key)];
  const labelOf = Object.fromEntries([...P, ...pr.points].map((p) => [p.key, p.label]));
  const lastIdx = pace ? n - 2 : n - 1;
  const actual = keys.map((_, i) => (i < n && !(pace && i === n - 1) ? data.totals[i] : null));
  const pv = (i) => (i === lastIdx ? actual[lastIdx] : pace && i === n - 1 ? pace.value : i >= n ? pr.points[i - n].value : null);
  const has = m > 0 || !!pace;
  const proj = keys.map((_, i) => (has && i >= lastIdx ? pv(i) : null));
  const lo = keys.map((_, i) => (i >= n ? pr.points[i - n].low : has && i >= lastIdx ? pv(i) : null));
  const hi = keys.map((_, i) => (i >= n ? pr.points[i - n].high : has && i >= lastIdx ? pv(i) : null));
  const sofar = keys.map((_, i) => (pace && i === n - 1 ? pace.so_far : null));
  const after = (k) => (v, { dataIndex }) => (v == null || dataIndex < k ? null : money(v));
  const series = [
    { id: "actual", label: "Received", data: actual, color: brand.pipe, showMark: n <= 36, valueFormatter: fmt, curve: "linear" },
    { id: "proj", label: pace ? "On pace / projected" : "Projected", data: proj, color: brand.pipe, showMark: ({ index }) => index > lastIdx, valueFormatter: after(lastIdx + 1), curve: "linear" },
    { id: "high", label: "Range high (80%)", data: hi, color: brand.pipe, showMark: false, valueFormatter: after(n) },
    { id: "low", label: "Range low (80%)", data: lo, color: brand.pipe, showMark: false, valueFormatter: after(n) },
  ];
  if (pace) series.push({ id: "sofar", label: "Received so far", data: sofar, color: chartGray, showMark: true, valueFormatter: fmt });
  const title = `Receipts by ${PER[data.grain]}`;

  return (
    <Paper sx={{ p: 2, height: "100%" }}>
      <Stack direction="row" alignItems="flex-start" spacing={1}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h3">{title}{m ? " and projection" : ""}</Typography>
          <Legend items={[["line", brand.pipe, "Received"], ...(has ? [["dash", brand.pipe, pace ? "On pace / projected" : "Projected"]] : []), ...(m ? [["band", brand.pipe, "80% range"]] : []),
            ...(pace ? [["dot", chartGray, "Received so far"]] : [])]} />
        </Box>
        <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)} aria-label="View">
          <ToggleButton value="chart">Chart</ToggleButton><ToggleButton value="table">Table</ToggleButton></ToggleButtonGroup>
      </Stack>
      {view === "chart" ? (
        <Box sx={{ mx: -1 }}>
          <LineChart height={330} series={series} hideLegend grid={{ horizontal: true }} skipAnimation
            xAxis={[{ scaleType: "point", data: keys, valueFormatter: (k) => labelOf[k], tickLabelStyle: { fontSize: 11, fill: "#5f5650" }, disableTicks: true }]}
            yAxis={[{ valueFormatter: compact, width: 64, tickLabelStyle: { fontSize: 11, fill: "#5f5650" }, disableLine: true, disableTicks: true, min: 0 }]}
            margin={{ top: 12, right: 36, bottom: 4, left: 0 }}
            sx={{
              "& .MuiChartsGrid-line": { stroke: chartGrid },
              "& .MuiChartsAxis-line": { stroke: chartGrid },
              "& .MuiLineElement-root[data-series='proj']": { strokeDasharray: "6 5" },
              "& .MuiLineElement-root[data-series='high'], & .MuiLineElement-root[data-series='low']": { display: "none" },
              "& .MuiMarkElement-root[data-series='actual']": { fill: brand.pipe, stroke: "#fff", strokeWidth: 2 },
              "& .MuiMarkElement-root[data-series='proj']": { fill: "#fff", stroke: brand.pipe, strokeWidth: 2 },
              "& .MuiMarkElement-root[data-series='sofar']": { fill: chartGray, stroke: "#fff", strokeWidth: 2 },
            }}>
            {m > 0 && <Band keys={keys} low={lo} high={hi} from={lastIdx} />}
          </LineChart>
        </Box>
      ) : (
        <Box sx={{ maxHeight: 330, overflow: "auto", mt: 1 }}>
          <Table size="small" stickyHeader>
            <TableHead><TableRow><TableCell>{PER[data.grain][0].toUpperCase() + PER[data.grain].slice(1)}</TableCell><TableCell align="right">Received</TableCell>
              <TableCell align="right">Payments</TableCell><TableCell align="right">Projected</TableCell><TableCell align="right">80% range</TableCell></TableRow></TableHead>
            <TableBody>
              {P.map((p, i) => <TableRow key={p.key}><TableCell>{p.label}{pace && i === n - 1 ? " (so far)" : ""}</TableCell><TableCell align="right">{money(data.totals[i])}</TableCell>
                <TableCell align="right">{data.counts[i].toLocaleString()}</TableCell><TableCell align="right">{pace && i === n - 1 ? money(pace.value) : ""}</TableCell><TableCell /></TableRow>)}
              {pr.points.map((p) => <TableRow key={p.key} sx={{ "& td": { color: "text.secondary" } }}><TableCell>{p.label}</TableCell><TableCell /><TableCell />
                <TableCell align="right">{money(p.value)}</TableCell><TableCell align="right">{money(p.low)} – {money(p.high)}</TableCell></TableRow>)}
            </TableBody>
          </Table>
        </Box>
      )}
      <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: .5 }}>
        {pace ? `${pace.label}: ${money(pace.so_far)} in ${pace.days_done} of ${pace.days_total} business days, on pace for ${money(pace.value)}. ` : ""}
        {data.range.partial_start ? "The first period starts mid-way, so it looks smaller. " : ""}{pr.method}</Typography>
    </Paper>
  );
}

function Legend({ items }) {
  return (
    <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" sx={{ mt: .5 }}>
      {items.map(([kind, c, l]) => (
        <Stack key={l} direction="row" spacing={.75} alignItems="center">
          <svg width="22" height="12" aria-hidden="true">
            {kind === "line" && <line x1="1" y1="6" x2="21" y2="6" stroke={c} strokeWidth="2" strokeLinecap="round" />}
            {kind === "dash" && <line x1="1" y1="6" x2="21" y2="6" stroke={c} strokeWidth="2" strokeDasharray="5 4" />}
            {kind === "band" && <rect x="1" y="1" width="20" height="10" rx="2" fill={c} fillOpacity=".15" />}
            {kind === "dot" && <circle cx="11" cy="6" r="4.5" fill={c} />}
            {kind === "rect" && <rect x="3" y="1" width="16" height="10" rx="2" fill={c} />}
          </svg>
          <Typography variant="caption" color="text.secondary">{l}</Typography>
        </Stack>))}
    </Stack>
  );
}

// ---------------------------------------------------------------- storylines
const TONE = { up: [TrendingUpIcon, "success.main"], down: [TrendingDownIcon, "error.main"], warn: [WarningAmberIcon, "warning.dark"], info: [InsightsIcon, "secondary.main"] };
function Storylines({ items, onFocus, f }) {
  return (
    <Paper sx={{ p: 2, height: "100%", display: "flex", flexDirection: "column" }}>
      <Typography variant="h3">Storylines</Typography>
      <Typography variant="caption" color="text.secondary">Written from the numbers on this page. They change with every filter.</Typography>
      <Stack spacing={1.5} sx={{ mt: 1.5, overflowY: "auto", maxHeight: { lg: 420 }, pr: .5 }}>
        {items.map((s) => {
          const [Icon, color] = TONE[s.tone] || TONE.info;
          const applied = s.focus && ((s.focus.customer && s.focus.customer === f.customer) || (s.focus.sheet && f.sheets.length === 1 && f.sheets[0] === s.focus.sheet)
            || (s.focus.method && f.methods.length === 1 && f.methods[0] === s.focus.method));
          const target = s.focus && !applied && (s.focus.customer || s.focus.sheet || METHOD_NAMES[s.focus.method] || s.focus.bank);
          return (
            <Stack key={s.id} direction="row" spacing={1.25}>
              <Icon sx={{ color, fontSize: 20, mt: .2 }} aria-label={s.tone === "up" ? "Up" : s.tone === "down" ? "Down" : s.tone === "warn" ? "Needs attention" : "Note"} />
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>{s.title}</Typography>
                <Typography variant="body2" color="text.secondary">{s.text}</Typography>
                {target && <Button size="small" sx={{ px: 0, minWidth: 0 }} onClick={() => onFocus(s.focus)}>Show {String(target).length > 28 ? "this one" : String(target)}</Button>}
              </Box>
            </Stack>);
        })}
      </Stack>
    </Paper>
  );
}

// ---------------------------------------------------------------- breakdown
function BreakdownCard({ data, by, setBy, banks, onPick, customerSet }) {
  const [q, setQ] = useState(""); const [all, setAll] = useState(false);
  const [ref, width] = useWidth();
  const rows = data.breakdown;
  const isClient = data.by === "customer";
  const shown = rows.filter((r) => !q || r.label.toLowerCase().includes(q.toLowerCase()));
  const visible = all ? shown : shown.slice(0, 25);
  const keys = data.periods.map((p) => p.key); const labelOf = Object.fromEntries(data.periods.map((p) => [p.key, p.label]));
  const plotW = Math.max(200, width - 90);
  const gap = Math.min(0.85, Math.max(0.25, 1 - 24 / (plotW / Math.max(keys.length, 1))));    // bars stay <= 24px thick
  const top = rows.slice(0, 10);
  const pickable = isClient || data.by === "sheet" || data.by === "method";
  const hasPrev = data.kpis.previous.total > 0;

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} alignItems={{ sm: "center" }} spacing={1}>
        <Typography variant="h3" sx={{ flex: 1 }}>By {DIM_NOUN[data.by]}</Typography>
        <Tabs value={by} onChange={(_, v) => setBy(v)} sx={{ minHeight: 36, "& .MuiTab-root": { minHeight: 36, py: 0 } }}>
          {DIMS.map(([k, l]) => <Tab key={k} value={k} label={l} disabled={k === "customer" && customerSet} />)}
        </Tabs>
      </Stack>
      <Box ref={ref} sx={{ mt: 1 }}>
        {!isClient && data.series.length > 0 && (
          <BarChart height={300} skipAnimation borderRadius={4} grid={{ horizontal: true }}
            xAxis={[{ scaleType: "band", data: keys, valueFormatter: (k) => labelOf[k], categoryGapRatio: gap, tickLabelStyle: { fontSize: 11, fill: "#5f5650" }, disableTicks: true }]}
            yAxis={[{ valueFormatter: compact, width: 64, tickLabelStyle: { fontSize: 11, fill: "#5f5650" }, disableLine: true, disableTicks: true }]}
            series={data.series.map((s, i) => ({ id: s.key, label: s.label, data: s.values, stack: "a", color: colorFor(data.by, s.key, i, banks), valueFormatter: fmt }))}
            hideLegend={data.series.length < 2} slotProps={{ legend: { direction: "horizontal", position: { vertical: "top", horizontal: "start" } } }}
            margin={{ top: 8, right: 12, bottom: 4, left: 0 }}
            sx={{ "& .MuiBarElement-root": { stroke: "#fff", strokeWidth: 1 }, "& .MuiChartsGrid-line": { stroke: chartGrid }, "& .MuiChartsAxis-line": { stroke: chartGrid } }} />
        )}
        {isClient && top.length > 0 && (
          <BarChart height={34 * top.length + 40} layout="horizontal" skipAnimation borderRadius={4} hideLegend grid={{ vertical: true }}
            yAxis={[{ scaleType: "band", data: top.map((r) => r.key), valueFormatter: (k) => (k.length > 30 ? k.slice(0, 29) + "…" : k), width: 230,
              categoryGapRatio: 0.35, tickLabelStyle: { fontSize: 11.5, fill: "#1F1712" }, disableTicks: true, disableLine: true }]}
            xAxis={[{ valueFormatter: compact, tickNumber: 5, tickLabelStyle: { fontSize: 11, fill: "#5f5650" }, disableTicks: true, disableLine: true, min: 0, max: (top[0]?.total || 1) * 1.14 }]}
            series={[{ id: "total", label: "Received", data: top.map((r) => r.total), color: brand.pipe, valueFormatter: fmt,
              barLabel: (it) => compact(it.value), barLabelPlacement: "outside" }]}
            margin={{ top: 4, right: 72, bottom: 4, left: 4 }}
            sx={{ "& .MuiChartsGrid-line": { stroke: chartGrid }, "& .MuiBarLabel-root": { fill: "#5f5650", fontSize: 11.5 } }} />
        )}
      </Box>

      <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 2, mb: 1 }}>
        <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>
          {rows.length.toLocaleString()} {DIM_NOUN[data.by]}{rows.length !== 1 ? "s" : ""} · {pickable ? "click a row to focus on it" : "change since the previous period of the same length"}</Typography>
        {isClient && <TextField placeholder="Find a client" value={q} onChange={(e) => setQ(e.target.value)} sx={{ maxWidth: 240 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />}
      </Stack>
      <Box sx={{ overflowX: "auto" }}>
        <Table size="small">
          <TableHead><TableRow>
            <TableCell>{DIM_NOUN[data.by][0].toUpperCase() + DIM_NOUN[data.by].slice(1)}</TableCell><TableCell align="right">Received</TableCell><TableCell sx={{ minWidth: 120 }}>Share</TableCell>
            <TableCell align="right">Payments</TableCell><TableCell align="right">Average</TableCell><TableCell align="right">vs previous</TableCell>
            <TableCell sx={{ minWidth: 110 }}>Trend</TableCell><TableCell align="right">Next {PER[data.grain]}</TableCell>
            <TableCell>{isClient ? "Last paid" : "Last payment"}</TableCell></TableRow></TableHead>
          <TableBody>
            {visible.map((r, i) => {
              const late = isClient && r.cadence_days && r.days_since > Math.max(2.5 * r.cadence_days, 30);
              return (
                <TableRow key={r.key} hover={pickable} onClick={pickable ? () => onPick(r) : undefined} sx={{ cursor: pickable ? "pointer" : "default" }}>
                  <TableCell sx={{ maxWidth: 280 }}>
                    {data.by === "sheet" ? <SheetChip sheet={r.key} /> :
                      <Stack direction="row" spacing={1} alignItems="center">
                        {!isClient && <Box sx={{ width: 10, height: 10, borderRadius: "3px", flex: "0 0 auto", bgcolor: colorFor(data.by, r.key, i, banks) }} />}
                        <Typography variant="body2" noWrap sx={{ fontWeight: 600 }}>{r.label}</Typography></Stack>}
                    {isClient && <Typography variant="caption" color="text.secondary">{r.sheets.join(", ")} · mostly {METHOD_NAMES[r.method]?.toLowerCase()}</Typography>}
                  </TableCell>
                  <TableCell align="right" sx={{ fontWeight: 600 }}>{money(r.total)}</TableCell>
                  <TableCell><Stack direction="row" spacing={1} alignItems="center">
                    <Box sx={{ flex: 1, height: 6, bgcolor: "#EFEBE7", borderRadius: 3, overflow: "hidden" }}><Box sx={{ width: `${Math.min(100, r.share)}%`, height: "100%", bgcolor: brand.pipe, borderRadius: 3 }} /></Box>
                    <Typography variant="caption" sx={{ width: 38, textAlign: "right" }}>{r.share.toFixed(r.share < 10 ? 1 : 0)}%</Typography></Stack></TableCell>
                  <TableCell align="right">{r.count.toLocaleString()}</TableCell>
                  <TableCell align="right">{money(r.avg)}</TableCell>
                  <TableCell align="right">{r.change == null ? <Typography variant="caption" color="text.secondary">{hasPrev ? "new" : "—"}</Typography> :
                    <Typography variant="body2" sx={{ color: r.change >= 0 ? "success.main" : "error.main", fontWeight: 600 }}>{r.change >= 0 ? "+" : "−"}{Math.abs(r.change).toFixed(0)}%</Typography>}</TableCell>
                  <TableCell><Spark values={r.spark} height={22} /></TableCell>
                  <TableCell align="right">{!r.next ? "—" : compact(r.next)}</TableCell>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{fdate(r.last)}
                    {isClient && r.cadence_days ? <Typography variant="caption" component="div" sx={{ color: late ? "warning.dark" : "text.secondary", fontWeight: late ? 700 : 400 }}>
                      {late ? `${r.days_since} days ago · usually ${Math.round(r.cadence_days)}` : `usually every ${Math.round(r.cadence_days)} days`}</Typography> : null}</TableCell>
                </TableRow>);
            })}
          </TableBody>
        </Table>
      </Box>
      {shown.length > 25 && <Button size="small" sx={{ mt: 1 }} onClick={() => setAll(!all)}>{all ? "Show top 25" : `Show all ${shown.length.toLocaleString()}`}</Button>}
    </Paper>
  );
}
