import { useCallback, useEffect, useMemo, useState } from "react";
import { Box, Paper, Stack, Typography, TextField, MenuItem, Chip, Table, TableHead, TableBody, TableRow, TableCell, TableSortLabel, Dialog, DialogTitle, DialogContent, DialogActions,
  IconButton, Button, InputAdornment, Drawer, Divider, Tooltip, Select, ToggleButtonGroup, ToggleButton, Alert, CircularProgress, Menu,
  ListItemText, Checkbox, FormControlLabel } from "@mui/material";
import SyncIcon from "@mui/icons-material/Sync";
import ArrowDropDownIcon from "@mui/icons-material/ArrowDropDown";
import SearchIcon from "@mui/icons-material/Search";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DownloadIcon from "@mui/icons-material/Download";
import CloseIcon from "@mui/icons-material/Close";
import SyncProblemIcon from "@mui/icons-material/SyncProblem";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import RestoreIcon from "@mui/icons-material/Restore";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import ImportExcelDialog from "../components/ImportExcelDialog";
import DayBankTotals from "../components/DayBankTotals";
import { api, money, num, fdate, METHODS, todayIso, downloadPost, taxParts, inDaily } from "../api";
import { brand, warnBg } from "../theme";
import { SheetChip, MethodChip, Thumbs, Lightbox, Stat, Triangles, useToast } from "../components/common";

const PERIODS = [["today", "Today"], ["week", "This week"], ["month", "This month"], ["quarter", "This quarter"], ["year", "This year"], ["all", "All time"]];
const GROUPS = [["day", "Day received"], ["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["customer", "Company"], ["sheet", "Payee sheet"],
  ["method", "Payment method"], ["deposit_bank", "Deposit bank"], ["taxable", "Taxable"], ["posted", "Posted to NetSuite"], ["none", "No grouping"]];
// Ticket ref, payment ref and order # aren't columns (they're optional and rarely filled); they're still searchable,
// in the payment's side panel and in the exports.
const COLS = [["received", "Received"], ["customer", "Customer"], ["sheet", "Sheet"], ["method", "Method"], ["amount", "Amount", "right"], ["taxable", "Taxable"], ["posted", "Posted (NetSuite #)"], ["deposit_bank", "Deposit bank"], ["row", "Excel row", "right"]];

const iso = (d) => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); };
const parse = (s) => { const [y, m, d] = (s || "").split("-").map(Number); return new Date(y, (m || 1) - 1, d || 1); };
const weekStart = (s) => { const d = parse(s); const k = (d.getDay() + 6) % 7; d.setDate(d.getDate() - k); return iso(d); };
function periodRange(p) {
  const t = new Date(); const today = iso(t);
  if (p === "today") return [today, today];
  if (p === "week") return [weekStart(today), today];
  if (p === "month") return [today.slice(0, 8) + "01", today];
  if (p === "quarter") { const q = Math.floor(t.getMonth() / 3) * 3; return [`${t.getFullYear()}-${String(q + 1).padStart(2, "0")}-01`, today]; }
  if (p === "year") return [`${t.getFullYear()}-01-01`, today];
  return ["", ""];
}
function groupKey(r, g) {
  const f = r.fields, d = f.received || "";
  switch (g) {
    case "day": return [d, d ? fdate(d, { weekday: "short", month: "short", day: "numeric", year: "numeric" }) : "No date"];
    case "week": { const w = d ? weekStart(d) : ""; return [w, w ? `Week of ${fdate(w)}` : "No date"]; }
    case "month": return [d.slice(0, 7), d ? parse(d).toLocaleDateString("en-US", { month: "long", year: "numeric" }) : "No date"];
    case "quarter": { if (!d) return ["", "No date"]; const q = Math.floor((+d.slice(5, 7) - 1) / 3) + 1; return [`${d.slice(0, 4)}-Q${q}`, `Q${q} ${d.slice(0, 4)}`]; }
    case "customer": return [f.customer || "", f.customer || "No customer"];
    case "sheet": return [r.sheet || "", r.sheet || "No sheet"];
    case "method": return [f.method, METHODS[f.method] || f.method];
    case "deposit_bank": return [f.deposit_bank || "", f.deposit_bank || "No deposit bank"];
    case "taxable": return [f.taxable || "~", f.taxable === "Yes" ? "Taxable" : f.taxable === "No" ? "Not taxable" : f.taxable === "Partial" ? "Partly taxable (split by invoice)" : "Taxable not set"];
    case "posted": return [f.posted ? "1" : "0", f.posted ? "Posted to NetSuite" : "Not posted yet"];
    default: return ["all", "All payments"];
  }
}
const DATE_GROUPS = ["day", "week", "month", "quarter"];
const sortVal = (r, k) => k === "amount" ? num(r.fields.amount) : k === "row" ? (r.row || 0) : k === "sheet" ? (r.sheet || "") : String(r.fields[k] || "").toLowerCase();

export default function Ledger({ me }) {
  const isAdmin = me.role === "admin";
  const canTax = isAdmin || me.role === "ar";                 // AR: read, download images, set Taxable
  const canDownload = isAdmin || me.role === "ar";            // read-only: view only
  const canPost = isAdmin || (me.perms || []).includes("posted.edit");   // AR marks payments posted in NetSuite
  const canAttach = isAdmin || me.role === "ar";              // add / remove attachments (never scanned pages)
  const [deletedOpen, setDeletedOpen] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);
  const [splitFor, setSplitFor] = useState(null);
  const [xlMenu, setXlMenu] = useState(null);
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [period, setPeriod] = useState("month");
  const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  const [sheets, setSheets] = useState([]);
  const [methods, setMethods] = useState([]);
  const [tax, setTax] = useState("any");
  const [posted, setPosted] = useState("any");
  const [onlyPending, setOnlyPending] = useState(false);
  const [group, setGroup] = useState("day");
  const [importing, setImporting] = useState(false);
  const [sort, setSort] = useState(["received", "desc"]);
  const [closed, setClosed] = useState({});
  const [more, setMore] = useState({});
  const [detail, setDetail] = useState(null);
  const [toast, say] = useToast();

  const load = useCallback(async () => { try { setData(await api.get("/api/ledger")); } catch (e) { say(e.message, "error"); } }, [say]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { // keep 'Excel pending' tags fresh while a workbook is open somewhere
    if (!data?.rows?.some((r) => r.pending)) return;
    const t = setInterval(load, 30000); return () => clearInterval(t);
  }, [data, load]);
  useEffect(() => { const [a, b] = periodRange(period); if (period !== "custom") { setFrom(a); setTo(b); } }, [period]);
  useEffect(() => { if (data) setDetail((d) => (d ? data.rows.find((x) => x.id === d.id) || null : d)); }, [data]);   // drawer follows reloads (row, sheet)

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    return data.rows.filter((r) => {
      const f = r.fields, d = f.received || "";
      if (from && d < from) return false;
      if (to && d > to) return false;
      if (sheets.length && !sheets.includes(r.sheet)) return false;
      if (methods.length && !methods.includes(f.method)) return false;
      if (tax === "yes" && f.taxable !== "Yes" && f.taxable !== "Partial") return false;
      if (tax === "no" && f.taxable !== "No" && f.taxable !== "Partial") return false;
      if (tax === "unset" && f.taxable) return false;
      if (posted === "yes" && !f.posted) return false;
      if (posted === "no" && f.posted) return false;
      if (onlyPending && !r.pending) return false;
      if (!needle) return true;
      return [f.customer, r.sheet, f.ticket, f.payref, f.check_no, f.order, f.amount, money(f.amount), f.deposit_bank, f.bank, f.confirmation,
        f.invoice, f.last4, METHODS[f.method], fdate(d), f.memo, f.posted !== "Yes" ? f.posted : ""].join(" ").toLowerCase().includes(needle);
    });
  }, [data, q, from, to, sheets, methods, tax, posted, onlyPending]);

  const groups = useMemo(() => {
    const m = new Map();
    for (const r of rows) { const [k, label] = groupKey(r, group); if (!m.has(k)) m.set(k, { key: k, label, rows: [] }); m.get(k).rows.push(r); }
    const [sk, dir] = sort; const mul = dir === "asc" ? 1 : -1;
    const out = [...m.values()];
    out.forEach((g) => g.rows.sort((a, b) => { const x = sortVal(a, sk), y = sortVal(b, sk); return (x > y ? 1 : x < y ? -1 : a.id - b.id) * mul; }));
    out.sort((a, b) => DATE_GROUPS.includes(group) ? (a.key < b.key ? 1 : -1) : a.label.localeCompare(b.label));
    return out;
  }, [rows, group, sort]);

  const dayRows = useMemo(() => (data ? data.rows.filter((r) => (!sheets.length || sheets.includes(r.sheet)) && (!methods.length || methods.includes(r.fields.method))) : []),
    [data, sheets, methods]);

  const totals = useMemo(() => {
    const t = { all: 0, taxable: 0, notTaxable: 0, unset: 0, byBank: {} };
    rows.forEach((r) => { const a = num(r.fields.amount); t.all += a; const p = taxParts(r.fields);
      if (p.tax) { t.taxable += p.tax; const b = r.fields.deposit_bank || "No bank"; t.byBank[b] = (t.byBank[b] || 0) + p.tax; }
      t.notTaxable += p.non; if (p.unset) t.unset += 1; });
    return t;
  }, [rows]);

  // One road for every ledger edit (AR: Taxable; admin: any field): saved at once, Excel follows (now, or once the workbook is closed).
  const edit = async (r, k, v) => {
    const prev = r.fields[k];
    const patch = (val) => (x) => x.id === r.id ? { ...x, fields: { ...x.fields, [k]: val }, ...(k === "sheet" ? { sheet: val } : {}) } : x;
    setData((d) => ({ ...d, rows: d.rows.map(patch(v)) }));
    try {
      const res = await api.patch(`/api/ledger/${r.id}`, { [k]: v });
      if (k === "posted") say(v ? `NetSuite # ${v} saved: posted.` : "NetSuite # removed: not posted.");
      else if (k === "daily_total") say(v === "Yes" ? "Counted in the daily total." : "Left out of the daily total.");
      else if (res.excel !== "unchanged") say(res.excel === "pending" ? "Saved. Excel updates by itself once the workbook is closed." : res.excel === "skipped" ? "Saved in CheckFlow (this row isn't in the workbook)." : "Saved and updated in Excel.",
        res.excel === "pending" ? "warning" : "success");
      load();
      return true;
    } catch (e) {
      setData((d) => ({ ...d, rows: d.rows.map(patch(prev)) }));
      say(e.message, "error");
      return false;
    }
  };

  const exportCsv = () => {
    const head = ["Received", "Customer", "Sheet", "Method", "Ticket ref", "Payment ref", "Order", "Amount", "Taxable", "Taxable amount", "Deposit bank", "Check date", "Bank", "Invoice", "Excel row", "Taxable set by", "NetSuite #", "Posted by"];
    const lines = [head].concat(groups.flatMap((g) => g.rows).map((r) => { const f = r.fields;
      return [f.received, f.customer, r.sheet, METHODS[f.method], f.ticket, f.payref, f.order, f.amount, f.taxable, f.taxable ? taxParts(f).tax.toFixed(2) : "", f.deposit_bank, f.doc_date, f.bank, f.invoice, r.row, f.taxable_by, f.posted || "", f.posted ? f.posted_by : ""]; }));
    const csv = lines.map((l) => l.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `checkflow-ledger-${todayIso()}.csv`; a.click();
  };

  if (!data) return <Box sx={{ display: "grid", placeItems: "center", py: 10 }}><CircularProgress /></Box>;
  const toggle = (arr, set, v) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const pendingCount = data.rows.filter((r) => r.pending).length;

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", md: "row" }} alignItems={{ md: "flex-end" }} spacing={1}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h1">Ledger <Triangles /></Typography>
          <Typography color="text.secondary">Every payment received: the ledger is the record, and the payee workbook is kept in step with it. {isAdmin ? "Click a payment to correct it, add attachments or delete it." : canTax ? "Click a payment to see and download its pages, add attachments, set Taxable." : "Click a payment to see its pages."}</Typography>
        </Box>
        {isAdmin && <Button startIcon={<UploadFileIcon />} variant="outlined" onClick={() => setImporting(true)}>Import Excel</Button>}
        {isAdmin && <Button startIcon={<DeleteOutlineIcon />} onClick={() => setDeletedOpen(true)}>Deleted</Button>}
        {isAdmin && <Button startIcon={<SyncIcon />} onClick={() => setSyncOpen(true)}>Sync workbook</Button>}
        <Button startIcon={<DownloadIcon />} endIcon={<ArrowDropDownIcon />} onClick={(e) => setXlMenu(e.currentTarget)}>Export Excel</Button>
        <Menu anchorEl={xlMenu} open={!!xlMenu} onClose={() => setXlMenu(null)}>
          <MenuItem component="a" href="/api/workbook/download" onClick={() => setXlMenu(null)}>
            <ListItemText primary="Workbook" secondary="The payee workbook as it is in Excel: MVC, UVM, RVP, VCP day blocks" /></MenuItem>
          <MenuItem disabled={!data.rows.length} onClick={() => { setXlMenu(null); downloadPost("/api/ledger/export", {}, "checkflow-ledger.xlsx").catch((e) => say(e.message, "error")); }}>
            <ListItemText primary="Ledger table" secondary="Every payment, one row each, plus daily bank totals" /></MenuItem>
        </Menu>
        <Tooltip title="Just the rows on screen (search and filters applied)"><span><Button startIcon={<DownloadIcon />} onClick={exportCsv} disabled={!rows.length}>CSV</Button></span></Tooltip>
      </Stack>

      {pendingCount > 0 && <Alert severity="warning" icon={<SyncProblemIcon />}>{pendingCount} change{pendingCount > 1 ? "s are" : " is"} waiting to be written to Excel. Close the workbook and they'll go through within 30 seconds.</Alert>}

      <Paper sx={{ display: "flex", flexWrap: "wrap", gap: 1, py: 1 }}>
        <Stat label="Payments" value={rows.length.toLocaleString()} />
        <Stat label="Total received" value={money(totals.all)} color={brand.espresso} />
        <Stat label="Taxable" value={money(totals.taxable)} color={brand.concrete}
          sub={Object.entries(totals.byBank).sort((a, b) => b[1] - a[1]).map(([b, v]) => `${money(v)} ${b}`).join(" · ") || "—"} />
        <Stat label="Not taxable" value={money(totals.notTaxable)} color={brand.pipe} />
        <Stat label="Taxable not set" value={totals.unset.toLocaleString()} color={brand.asphalt} sub={totals.unset ? "needs a decision" : "all decided"} />
      </Paper>

      <DayBankTotals rows={dayRows} banks={data.deposit_banks} />

      <Paper sx={{ p: 2 }}>
        <Stack spacing={1.5}>
          <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} alignItems={{ lg: "center" }}>
            <TextField placeholder="Search customer, check #, amount, ticket, bank, invoice…" value={q} onChange={(e) => setQ(e.target.value)} sx={{ flex: 1, minWidth: 240 }}
              InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment>, endAdornment: q && <IconButton size="small" aria-label="Clear search" onClick={() => setQ("")}><CloseIcon fontSize="small" /></IconButton> }} />
            <TextField select label="Group by" value={group} onChange={(e) => { setGroup(e.target.value); setClosed({}); }} sx={{ width: { lg: 200 } }}>
              {GROUPS.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
            </TextField>
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            {PERIODS.map(([k, l]) => <Chip key={k} label={l} clickable color={period === k ? "primary" : "default"} variant={period === k ? "filled" : "outlined"} onClick={() => setPeriod(k)} />)}
            <Chip label="Custom" clickable color={period === "custom" ? "primary" : "default"} variant={period === "custom" ? "filled" : "outlined"} onClick={() => setPeriod("custom")} />
            {period === "custom" && <>
              <TextField type="date" label="From" value={from} onChange={(e) => setFrom(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ width: 160 }} />
              <TextField type="date" label="To" value={to} onChange={(e) => setTo(e.target.value)} InputLabelProps={{ shrink: true }} sx={{ width: 160 }} />
            </>}
          </Stack>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            {data.sheets.map((s) => <Chip key={s} label={s} clickable variant={sheets.includes(s) ? "filled" : "outlined"} color={sheets.includes(s) ? "secondary" : "default"} onClick={() => toggle(sheets, setSheets, s)} />)}
            <Divider orientation="vertical" flexItem />
            {Object.entries(METHODS).map(([k, l]) => <Chip key={k} label={l} clickable variant={methods.includes(k) ? "filled" : "outlined"} color={methods.includes(k) ? "secondary" : "default"} onClick={() => toggle(methods, setMethods, k)} />)}
            <Divider orientation="vertical" flexItem />
            <ToggleButtonGroup size="small" exclusive value={tax} onChange={(_, v) => v && setTax(v)}>
              <ToggleButton value="any">Any</ToggleButton><ToggleButton value="yes">Taxable</ToggleButton><ToggleButton value="no">Not taxable</ToggleButton><ToggleButton value="unset">Not set</ToggleButton>
            </ToggleButtonGroup>
            <ToggleButtonGroup size="small" exclusive value={posted} onChange={(_, v) => v && setPosted(v)} aria-label="Posted to NetSuite">
              <ToggleButton value="any">Any</ToggleButton><ToggleButton value="yes">Posted</ToggleButton><ToggleButton value="no">Not posted</ToggleButton>
            </ToggleButtonGroup>
            {pendingCount > 0 && <Chip label="Excel pending" clickable color={onlyPending ? "warning" : "default"} variant={onlyPending ? "filled" : "outlined"} onClick={() => setOnlyPending(!onlyPending)} />}
            {(sheets.length || methods.length || tax !== "any" || posted !== "any" || onlyPending || q) ? <Button size="small" onClick={() => { setSheets([]); setMethods([]); setTax("any"); setPosted("any"); setOnlyPending(false); setQ(""); }}>Clear filters</Button> : null}
          </Stack>
        </Stack>
      </Paper>

      <Paper sx={{ overflowX: "auto" }}>
        {!rows.length ? <Box sx={{ p: 5, textAlign: "center", color: "text.secondary" }}>{data.rows.length ? "No payments match these filters." : "Nothing has been sent to Excel yet. Validate payments and send them from the Payments tab."}</Box> :
        <Table size="small" stickyHeader sx={{ minWidth: 1180 }}>
          <TableHead><TableRow>
            <TableCell sx={{ width: 64 }} />
            {COLS.map(([k, l, a]) => <TableCell key={k} align={a || "left"} sortDirection={sort[0] === k ? sort[1] : false}>
              <TableSortLabel active={sort[0] === k} direction={sort[0] === k ? sort[1] : "asc"} onClick={() => setSort([k, sort[0] === k && sort[1] === "asc" ? "desc" : "asc"])}>{l}</TableSortLabel>
            </TableCell>)}
          </TableRow></TableHead>
          <TableBody>
            {groups.map((g, gi) => {
              const isClosed = closed[g.key] ?? (groups.length > 14 && gi >= 10);
              const sub = g.rows.reduce((s, r) => s + num(r.fields.amount), 0);
              const subTax = g.rows.reduce((s, r) => s + taxParts(r.fields).tax, 0);
              const limit = more[g.key] ? Infinity : 60;
              return [
                group !== "none" && (
                  <TableRow key={"g" + g.key} hover onClick={() => setClosed((c) => ({ ...c, [g.key]: !isClosed }))} sx={{ cursor: "pointer", "& td": { bgcolor: "#F7F4F1", borderTop: "2px solid #E3DFDB" } }}>
                    <TableCell>{isClosed ? <ChevronRightIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}</TableCell>
                    <TableCell colSpan={4}><b>{g.label}</b> <Typography component="span" variant="body2" color="text.secondary">· {g.rows.length} payment{g.rows.length > 1 ? "s" : ""}{subTax ? ` · taxable ${money(subTax)}` : ""}</Typography></TableCell>
                    <TableCell align="right"><b>{money(sub)}</b></TableCell>
                    <TableCell colSpan={4} />
                  </TableRow>),
                ...(isClosed ? [] : g.rows.slice(0, limit).map((r) => <LedgerRow key={r.id} r={r} isAdmin={isAdmin} canTax={canTax} canPost={canPost} banks={data.deposit_banks} onEdit={edit} onOpen={() => setDetail(r)} onSplit={setSplitFor} />)),
                !isClosed && g.rows.length > limit && <TableRow key={"m" + g.key}><TableCell colSpan={10} align="center"><Button size="small" onClick={() => setMore((m) => ({ ...m, [g.key]: true }))}>Show all {g.rows.length}</Button></TableCell></TableRow>,
              ];
            })}
            <TableRow sx={{ "& td": { borderTop: "2px solid", borderColor: brand.espresso, fontWeight: 700 } }}>
              <TableCell /><TableCell colSpan={4}>Total · {rows.length} payments</TableCell><TableCell align="right">{money(totals.all)}</TableCell><TableCell colSpan={4} />
            </TableRow>
          </TableBody>
        </Table>}
      </Paper>
      <DetailDrawer r={detail} isAdmin={isAdmin} canTax={canTax} canPost={canPost} canDownload={canDownload} canAttach={canAttach} banks={data.deposit_banks} sheets={data.sheets} onClose={() => setDetail(null)} onSplit={setSplitFor}
        say={say} onChanged={load} onDeleted={() => { setDetail(null); load(); }}
        onEdit={async (r, k, v) => { const ok = await edit(r, k, v); if (ok) setDetail((d) => d && { ...d, fields: { ...d.fields, [k]: v }, ...(k === "sheet" ? { sheet: v } : {}) }); return ok; }} />
      {canTax && splitFor && <InvoiceSplitDialog r={splitFor} onClose={() => setSplitFor(null)} onSaved={(m) => { setSplitFor(null); say(m); load(); }} />}
      {isAdmin && syncOpen && <SyncDialog onClose={() => setSyncOpen(false)} onDone={(m) => { say(m); load(); }} />}
      {isAdmin && <DeletedDialog open={deletedOpen} onClose={() => setDeletedOpen(false)} onRestored={(m) => { say(m); load(); }} say={say} />}
      {isAdmin && <ImportExcelDialog open={importing} onClose={() => setImporting(false)}
        onDone={(m, keepOpen) => { if (!keepOpen) { setImporting(false); setPeriod("all"); } say(m); load(); }} />}
      {toast}
    </Stack>
  );
}

const shortWhen = (at) => at ? new Date(at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";

function ByLine({ name, at }) {      // who set it, and when, under the control
  if (!name) return null;
  return (
    <Box title={`${name} · ${shortWhen(at)}`} sx={{ mt: .25, maxWidth: 170, lineHeight: 1.25 }}>
      <Typography variant="caption" color="text.secondary" display="block" noWrap sx={{ lineHeight: 1.25 }}>{name.split("@")[0]}</Typography>
      <Typography variant="caption" color="text.secondary" display="block" noWrap sx={{ lineHeight: 1.25, fontSize: 11 }}>{shortWhen(at)}</Typography>
    </Box>);
}

// Posted = the NetSuite verification number typed in (blank = not posted). Saved on Enter or when leaving the box.
function PostedBox({ r, canPost, onEdit, wide }) {
  const v = r.fields.posted || "";
  const shown = v === "Yes" ? "" : v;                       // 'Yes' = marked posted before numbers were asked for
  const [t, setT] = useState(shown);
  useEffect(() => { setT(shown); }, [shown]);
  if (!canPost) return <Typography variant="body2" color={v ? "success.main" : "text.secondary"} sx={{ fontVariantNumeric: "tabular-nums" }}>
    {v ? (v === "Yes" ? "Posted" : v) : "Not posted"}</Typography>;
  const commit = () => { const n = t.trim(); if (n !== shown) onEdit(r, "posted", n); };
  return (
    <TextField size="small" value={t} onChange={(e) => setT(e.target.value)} onBlur={commit} onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { setT(shown); e.target.blur(); } }}
      placeholder={v === "Yes" ? "Add #" : "NetSuite #"} inputProps={{ "aria-label": "NetSuite verification number", maxLength: 40 }}
      sx={{ width: wide ? 220 : 132, "& .MuiInputBase-input": { py: .6, fontVariantNumeric: "tabular-nums" },
        "& .MuiOutlinedInput-root": v ? { bgcolor: "#EEF6EF", "& fieldset": { borderColor: "success.light" } } : {} }} />);
}

const FIELD_NAMES = { daily_total: "Affects daily total", taxable: "Taxable", posted: "Posted", amount: "Amount", customer: "Customer", received: "Date received", sheet: "Payee sheet",
  method: "Method", ticket: "Ticket ref", payref: "Payment ref", order: "Order #", deposit_bank: "Deposit bank", invoice: "Invoice", taxable_amount: "Taxable amount",
  check_no: "Check #", bank: "Bank", memo: "Memo", confirmation: "Confirmation" };
const show = (k, v) => k === "daily_total" ? (v === "No" ? "off" : v === "Yes" ? "on" : "automatic") : k === "posted" ? (v === "Yes" ? "posted" : v || "not posted") : k === "amount" || k === "taxable_amount" ? (v ? money(v) : "—") : (v || "not set");
function historyText(h) {
  const d = h.detail || {};
  switch (h.action) {
    case "ledger_edit": return Object.entries(d).map(([k, [a, b]]) => k === "posted" ? (b ? `Posted in NetSuite: # ${b === "Yes" ? "(none)" : b}${a && a !== "Yes" ? ` (was ${a})` : ""}` : `NetSuite # removed${a && a !== "Yes" ? ` (was ${a})` : ""}: not posted`)
      : `${FIELD_NAMES[k] || k}: ${show(k, a)} → ${show(k, b)}`).join(" · ");
    case "invoice_split": return d.invoices ? `Split by invoice (${d.invoices} invoices, ${d.taxable === "Partial" ? `${money(d.taxable_amount)} taxable` : `taxable ${d.taxable || "not set"}`})` : "Removed the invoice split";
    case "attachment_added": return `Added ${d.pages || ""} attachment page${d.pages === 1 ? "" : "s"}`;
    case "attachment_removed": return "Removed an attachment";
    case "ledger_deleted": return `Deleted${d.reason ? `: ${d.reason}` : ""}`;
    case "ledger_restored": return "Restored";
    case "pdf_downloaded": return "Downloaded the pages (PDF)";
    case "payment_added": return "Added by hand";
    case "status_validated": return "Validated (checked against the scan)";
    case "status_pending": return "Set to pending";
    case "status_review": return "Back to review";
    default: return h.action.replace(/_/g, " ");
  }
}

function PaymentHistory({ r }) {
  const [h, setH] = useState(null);
  const key = JSON.stringify([r.id, r.fields.taxable, r.fields.posted, r.fields.amount, r.fields.taxable_amount, r.pages?.length]);
  useEffect(() => { api.get(`/api/ledger/${r.id}/history`).then(setH).catch(() => setH([])); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!h) return null;
  const items = h.filter((x) => x.action !== "image_downloaded");
  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="subtitle2" sx={{ mb: .5 }}>History</Typography>
      <Stack spacing={.75}>
        {items.map((x, i) => (
          <Box key={i}><Typography variant="body2">{historyText(x)}</Typography>
            <Typography variant="caption" color="text.secondary">{x.name} · {shortWhen(x.ts)}</Typography></Box>))}
        <Box><Typography variant="body2">Sent to Excel</Typography>
          <Typography variant="caption" color="text.secondary">{r.submitted_by || "?"} · {shortWhen(r.submitted_at)}</Typography></Box>
      </Stack>
    </Box>
  );
}

const taxText = (f) => f.taxable === "Partial" ? `Partial · ${money(f.taxable_amount)}` : (f.taxable || "Not set");

function TaxSelect({ r, onEdit, onSplit }) {
  const f = r.fields;
  const v = f.taxable || "";
  return (
    <Select size="small" value={v} displayEmpty onClick={(e) => e.stopPropagation()}
      onChange={(e) => { if (e.target.value === "__split") onSplit?.(r); else onEdit(r, "taxable", e.target.value); }}
      renderValue={(x) => x === "Partial" ? `Partial · ${money(f.taxable_amount)}` : x || "Not set"}
      sx={{ minWidth: 92, bgcolor: v ? undefined : warnBg, "& .MuiSelect-select": { py: 0.5 } }} inputProps={{ "aria-label": "Taxable" }}>
      <MenuItem value="">Not set</MenuItem><MenuItem value="Yes">Yes</MenuItem><MenuItem value="No">No</MenuItem>
      {v === "Partial" && <MenuItem value="Partial" sx={{ display: "none" }}>Partial</MenuItem>}
      {onSplit && <Divider />}
      {onSplit && <MenuItem value="__split">{f.invoices?.length ? "Edit invoice split…" : "Split by invoice…"}</MenuItem>}
    </Select>
  );
}

function InvoiceTable({ f, onEditSplit }) {
  const p = taxParts(f);
  return (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" alignItems="center" sx={{ mb: .5 }}>
        <Typography variant="subtitle2" sx={{ flex: 1 }}>Invoices paid · taxable {money(p.tax)} · not taxable {money(p.non)}</Typography>
        {onEditSplit && <Button size="small" onClick={onEditSplit}>Edit split</Button>}
      </Stack>
      <Table size="small"><TableBody>{f.invoices.map((l) => (
        <TableRow key={l.invoice}><TableCell>{l.invoice}</TableCell><TableCell align="right">{money(l.amount)}</TableCell>
          <TableCell>{l.taxable === "Yes" ? "Taxable" : "Not taxable"}</TableCell></TableRow>))}
      </TableBody></Table>
    </Box>
  );
}

function InvoiceSplitDialog({ r, onClose, onSaved }) {
  const f = r.fields;
  const blankLine = (inv = "") => ({ invoice: inv, amount: "", taxable: "Yes" });
  const [lines, setLines] = useState(() => f.invoices?.length ? f.invoices.map((l) => ({ ...l }))
    : [blankLine((f.invoice || "").split(",")[0].trim()), blankLine()]);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const pay = num(f.amount);
  const total = lines.reduce((s, l) => s + num(l.amount), 0);
  const left = Math.round((pay - total) * 100) / 100;
  const tax = lines.reduce((s, l) => s + (l.taxable === "Yes" ? num(l.amount) : 0), 0);
  const set = (i, k, v) => setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  const ok = lines.length >= 2 && lines.every((l) => l.invoice.trim() && num(l.amount) > 0) && Math.abs(left) < 0.005;
  const save = async (ls) => {
    setBusy(true); setErr("");
    try {
      const res = await api.post(`/api/ledger/${r.id}/invoices`, { lines: ls });
      onSaved(ls.length ? `Split into ${ls.length} invoices: ${money(ls.reduce((s, l) => s + (l.taxable === "Yes" ? num(l.amount) : 0), 0))} taxable.${res.excel === "pending" ? " Excel updates once the workbook is closed." : ""}`
        : "Invoice split removed. Set Taxable again.");
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="sm" fullWidth onClick={(e) => e.stopPropagation()}>
      <DialogTitle>Split by invoice</DialogTitle>
      <DialogContent>
        <Typography color="text.secondary" sx={{ mb: 2 }}>
          {f.customer} · {money(f.amount)}{f.payref ? ` · ref ${f.payref}` : ""}. When one payment pays several invoices, list each with its amount and
          whether it's taxable. The invoices must add up to the payment.
        </Typography>
        {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
        <Stack spacing={1.25}>
          {lines.map((l, i) => (
            <Stack key={i} direction="row" spacing={1} alignItems="center">
              <TextField size="small" label="Invoice #" value={l.invoice} onChange={(e) => set(i, "invoice", e.target.value)} sx={{ flex: 1.2 }} autoFocus={i === 0} />
              <TextField size="small" label="Amount" value={l.amount} onChange={(e) => set(i, "amount", e.target.value)} sx={{ flex: 1 }}
                InputProps={{ startAdornment: <InputAdornment position="start">$</InputAdornment> }} />
              <ToggleButtonGroup size="small" exclusive value={l.taxable} onChange={(_, v) => v && set(i, "taxable", v)}>
                <ToggleButton value="Yes">Taxable</ToggleButton><ToggleButton value="No">Not taxable</ToggleButton>
              </ToggleButtonGroup>
              <IconButton size="small" aria-label="Remove invoice" disabled={lines.length <= 2} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}><CloseIcon fontSize="small" /></IconButton>
            </Stack>))}
          <Box><Button size="small" onClick={() => setLines((ls) => [...ls, { ...blankLine(), amount: left > 0 ? left.toFixed(2) : "" }])}>
            Add invoice{left > 0 ? ` (${money(left)} left)` : ""}</Button></Box>
        </Stack>
        <Alert severity={Math.abs(left) < 0.005 ? "success" : "warning"} sx={{ mt: 2 }}>
          {Math.abs(left) < 0.005 ? `Adds up to ${money(pay)}.` : left > 0 ? `${money(left)} of ${money(pay)} still to assign.` : `${money(-left)} more than the payment (${money(pay)}).`}
          {" "}Taxable {money(tax)} · not taxable {money(total - tax)}.
        </Alert>
      </DialogContent>
      <DialogActions>
        {f.invoices?.length > 0 && <Button color="error" disabled={busy} onClick={() => save([])} sx={{ mr: "auto" }}>Remove split</Button>}
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button variant="contained" disabled={!ok || busy} onClick={() => save(lines.map((l) => ({ invoice: l.invoice, amount: String(l.amount), taxable: l.taxable })))}>
          {busy ? "Saving…" : "Save split"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function BankSelect({ r, banks, onEdit }) {
  const v = r.fields.deposit_bank || "";
  const opts = banks.includes(v) || !v ? banks : [v, ...banks];
  return (
    <Select size="small" value={v} displayEmpty onClick={(e) => e.stopPropagation()} onChange={(e) => onEdit(r, "deposit_bank", e.target.value)}
      sx={{ minWidth: 110, "& .MuiSelect-select": { py: 0.5 } }} inputProps={{ "aria-label": "Deposit bank" }}>
      <MenuItem value="">None</MenuItem>{opts.map((b) => <MenuItem key={b} value={b}>{b}</MenuItem>)}
    </Select>
  );
}

function LedgerRow({ r, isAdmin, canTax, canPost, banks, onEdit, onOpen, onSplit }) {
  const f = r.fields;
  return (
    <TableRow hover onClick={onOpen} sx={{ cursor: "pointer" }}>
      <TableCell sx={{ py: 0.5 }}>
        {r.pages?.length ? (
          <Tooltip placement="right" enterDelay={250} slotProps={{ tooltip: { sx: { bgcolor: "#fff", p: .5, maxWidth: "none", boxShadow: 6, border: "1px solid #E3DFDB" } } }}
            title={<Box component="img" src={r.pages[0].thumb || r.pages[0].image} alt="" sx={{ display: "block", width: 420, maxWidth: "70vw" }} />}>
            <Box component="img" src={r.pages[0].thumb || r.pages[0].image} alt="Document" loading="lazy"
              sx={{ width: 92, height: 44, objectFit: "cover", objectPosition: "top", bgcolor: "#fff", borderRadius: .5, border: "1px solid #D6D0CA", display: "block", cursor: "zoom-in" }} />
          </Tooltip>)
          : <Box sx={{ width: 92, height: 44, borderRadius: .5, bgcolor: "#F1EEEB", fontSize: 11, color: "text.secondary", display: "grid", placeItems: "center" }}>{r.imported ? "imported" : "—"}</Box>}
      </TableCell>
      <TableCell sx={{ whiteSpace: "nowrap" }}>{fdate(f.received)}</TableCell>
      <TableCell sx={{ fontWeight: 600 }}>{f.customer}</TableCell>
      <TableCell><SheetChip sheet={r.sheet} /></TableCell>
      <TableCell><MethodChip method={f.method} /></TableCell>
      <TableCell align="right" sx={{ fontWeight: 600 }}>{money(f.amount)}
        {!inDaily(f) && <Typography variant="caption" color="text.secondary" display="block" sx={{ fontWeight: 400, whiteSpace: "nowrap" }}>not in daily total</Typography>}</TableCell>
      <TableCell>{canTax ? <TaxSelect r={r} onEdit={onEdit} onSplit={onSplit} /> : taxText(f)}<ByLine name={f.taxable && f.taxable_by} at={f.taxable_at} /></TableCell>
      <TableCell onClick={(e) => e.stopPropagation()} sx={{ whiteSpace: "nowrap" }}>
        <PostedBox r={r} canPost={canPost} onEdit={onEdit} />
        <ByLine name={f.posted && f.posted_by} at={f.posted_at} />
      </TableCell>
      <TableCell>{isAdmin ? <BankSelect r={r} banks={banks} onEdit={onEdit} /> : f.deposit_bank}</TableCell>
      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
        {r.pending ? <Tooltip title={r.note || "Waiting for the workbook to be closed"}><Chip size="small" label="pending" sx={{ bgcolor: warnBg, color: "#8a5300" }} /></Tooltip> : r.row}
      </TableCell>
    </TableRow>
  );
}

// Admins correct any detail here; each field saves on its own (Enter or leaving the field), like the Taxable dropdown.
function EditField({ label, value, onSave, type = "text", options, help }) {
  const [v, setV] = useState(value || "");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setV(value || ""); }, [value]);
  const commit = async (nv = v) => {
    if ((nv || "") === (value || "") || busy) return;
    setBusy(true); const ok = await onSave(nv); setBusy(false);
    if (!ok) setV(value || "");
  };
  if (options) return (
    <TextField select label={label} value={v} disabled={busy} helperText={help} onChange={(e) => { setV(e.target.value); commit(e.target.value); }}>
      {options.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}</TextField>);
  return (
    <TextField label={label} type={type} value={v} disabled={busy} helperText={help} InputLabelProps={type === "date" ? { shrink: true } : undefined}
      onChange={(e) => setV(e.target.value)} onBlur={() => commit()}
      onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { setV(value || ""); } }} />);
}

function DetailDrawer({ r, isAdmin, canTax, canPost, canDownload, canAttach, onSplit, banks, sheets, onClose, onEdit, say, onChanged, onDeleted }) {
  const [lb, setLb] = useState(null);
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState(null);
  if (!r) return null;
  const attach = async (list) => {
    const files = [...(list || [])];   // copy: the input is cleared right after, which empties the live FileList
    if (!files.length) return;
    const fd = new FormData(); files.forEach((x) => fd.append("files", x));
    setBusy(true);
    try { await api.upload(`/api/payments/${r.id}/attachments`, fd); say(`${files.length} file${files.length > 1 ? "s" : ""} attached.`); onChanged(); }
    catch (e) { say(e.message, "error"); } finally { setBusy(false); }
  };
  const unattach = async (p) => {
    if (!window.confirm("Remove this attachment?")) return;
    try { await api.del(`/api/payments/${r.id}/attachments/${p.id}`); onChanged(); } catch (e) { say(e.message, "error"); }
  };
  const remove = async () => {
    try { const res = await api.post(`/api/ledger/${r.id}/delete`, { reason: del || "" });
      say(res.excel === "pending" ? "Moved to Deleted. Its workbook row is removed once the workbook is closed." : "Moved to Deleted and removed from the workbook.", res.excel === "pending" ? "warning" : "success");
      setDel(null); onDeleted(); }
    catch (e) { say(e.message, "error"); }
  };
  const f = r.fields;
  const save = (k) => (v) => onEdit(r, k, v);
  const info = [["Received", fdate(f.received)], ["Customer", f.customer], ["Method", METHODS[f.method]], ["Amount", money(f.amount)], ["Ticket ref", f.ticket],
    ["Payment ref", f.payref], ["Order #", f.order], ["Check #", f.check_no], ["Check / paid date", fdate(f.doc_date)], ["Bank (drawn on)", f.bank],
    ["Routing", f.routing], ["Account", f.account], ["Card", f.card_brand && `${f.card_brand} ****${f.last4}`], ["Confirmation", f.confirmation],
    ["Invoice", f.invoice], ["Bank posting", f.memo], ["Sent to Excel", `${fdate((r.submitted_at || "").slice(0, 10))} by ${r.submitted_by || "?"}${r.workbook ? ` · ${r.workbook}` : ""}`]].filter(([, v]) => v);
  const readOnly = isAdmin ? info.filter(([k]) => ["Check / paid date", "Routing", "Account", "Card", "Bank posting", "Sent to Excel"].includes(k)) : info;
  const sheetOpts = (sheets.includes(r.sheet) || !r.sheet ? sheets : [r.sheet, ...sheets]).map((s) => [s, s]);
  return (
    <Drawer anchor="right" open onClose={onClose} PaperProps={{ sx: { width: { xs: "100%", sm: 520 }, p: 3, border: 0, "& > *": { flexShrink: 0 } } }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <Typography variant="h2" sx={{ flex: 1 }}>{f.customer || "Payment"}</Typography>
        <IconButton aria-label="Close" onClick={onClose}><CloseIcon /></IconButton>
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }}><SheetChip sheet={r.sheet} /><MethodChip method={f.method} />{r.row && <Chip size="small" variant="outlined" label={`Row ${r.row}`} />}</Stack>
      <Thumbs pages={r.pages} onOpen={setLb} height={140} max={8} canDownload={canDownload} onRemove={canAttach ? unattach : undefined} />
      {(canDownload || canAttach) && <Stack direction="row" spacing={1} sx={{ mt: 1 }} useFlexGap flexWrap="wrap">
        {canDownload && r.pages?.length > 0 && <Button size="small" startIcon={<PictureAsPdfIcon />} component="a" href={`/api/payments/${r.id}/document.pdf`}>Download all pages (PDF)</Button>}
        {canAttach && <Button size="small" startIcon={<AttachFileIcon />} component="label" disabled={busy}>{busy ? "Attaching…" : "Add attachment"}
          <input hidden type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.webp,.bmp" onChange={(e) => { attach(e.target.files); e.target.value = ""; }} /></Button>}
      </Stack>}
      <Stack direction="row" spacing={2} useFlexGap flexWrap="wrap" sx={{ my: 2 }}>
        <Box><Typography variant="caption" color="text.secondary" display="block">Taxable</Typography>{canTax ? <TaxSelect r={r} onEdit={onEdit} onSplit={onSplit} /> : <Typography>{taxText(f)}</Typography>}
          <ByLine name={f.taxable && f.taxable_by} at={f.taxable_at} /></Box>
        <Box><Typography variant="caption" color="text.secondary" display="block">Posted to NetSuite (verification #)</Typography><PostedBox r={r} canPost={canPost} onEdit={onEdit} wide />
          <ByLine name={f.posted && f.posted_by} at={f.posted_at} /></Box>
        {isAdmin && <Box><Typography variant="caption" color="text.secondary" display="block">Deposit bank</Typography><BankSelect r={r} banks={banks} onEdit={onEdit} /></Box>}
        <Box><Typography variant="caption" color="text.secondary" display="block">Daily total</Typography>
          {isAdmin ? <FormControlLabel sx={{ m: 0 }} label="Affects daily total"
            control={<Checkbox size="small" checked={inDaily(f)} onChange={(e) => onEdit(r, "daily_total", e.target.checked ? "Yes" : "No")} />} />
            : <Typography variant="body2">{inDaily(f) ? "Counted" : "Left out"}</Typography>}
          {!f.daily_total && !inDaily(f) && <Typography variant="caption" color="text.secondary" display="block">Off: a withdrawal to BPS</Typography>}</Box>
      </Stack>
      {f.invoices?.length > 0 && <InvoiceTable f={f} onEditSplit={canTax ? () => onSplit(r) : null} />}
      {r.pending && <Alert severity="warning" sx={{ mb: 2 }}>{r.note || "Waiting to be written to Excel."}</Alert>}
      {isAdmin && <>
        <Divider sx={{ mb: 2 }} />
        <Typography variant="h3" sx={{ mb: .5 }}>Correct this payment</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Each change saves on its own and is written to the workbook.
          {r.row ? " Changing the date, payee or method moves it to that day's block; its old row is emptied and the day's subtotals stay right." : " This row came from an import, so only CheckFlow changes."}</Typography>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2, mb: 2 }}>
          <EditField label="Date received" type="date" value={f.received} onSave={save("received")} />
          <EditField label="Payee sheet" value={r.sheet} options={sheetOpts} onSave={save("sheet")} />
          <Box sx={{ gridColumn: { sm: "1 / -1" } }}><EditField label="Customer" value={f.customer} onSave={save("customer")} /></Box>
          <EditField label="Method" value={f.method} options={Object.entries(METHODS)} onSave={save("method")} />
          <EditField label="Amount" value={f.amount} onSave={save("amount")} />
          <EditField label="Ticket ref" value={f.ticket} onSave={save("ticket")} />
          <EditField label="Payment ref / check #" value={f.payref} onSave={save("payref")} />
          <EditField label="Order #" value={f.order} onSave={save("order")} />
          <EditField label="Invoice" value={f.invoice} onSave={save("invoice")} />
          <Box sx={{ gridColumn: { sm: "1 / -1" } }}><EditField label="Bank (drawn on)" value={f.bank} onSave={save("bank")} /></Box>
        </Box>
      </>}
      <Divider sx={{ mb: 1 }} />
      <Table size="small"><TableBody>{readOnly.map(([k, v]) => <TableRow key={k}><TableCell sx={{ color: "text.secondary", width: 150, border: 0 }}>{k}</TableCell><TableCell sx={{ border: 0 }}>{v}</TableCell></TableRow>)}</TableBody></Table>
      <PaymentHistory r={r} />
      {isAdmin && <Box sx={{ mt: 3 }}><Button color="error" startIcon={<DeleteOutlineIcon />} onClick={() => setDel("")}>Delete this payment</Button></Box>}
      {lb !== null && <Lightbox pages={r.pages} index={lb} onClose={() => setLb(null)} canDownload={canDownload} />}
      <Dialog open={del !== null} onClose={() => setDel(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete this payment?</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2">{f.customer} · {money(f.amount)} · {fdate(f.received)}</Typography>
          <Typography variant="body2" color="text.secondary">It leaves the ledger, the totals and the workbook, and goes to Deleted, where it can be restored.</Typography>
          <TextField label="Why (optional)" value={del || ""} onChange={(e) => setDel(e.target.value)} placeholder="e.g. entered twice, wrong amount" autoFocus />
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setDel(null)}>Cancel</Button><Button color="error" variant="contained" onClick={remove}>Delete</Button></DialogActions>
      </Dialog>
    </Drawer>
  );
}

function SyncDialog({ onClose, onDone }) {
  const [p, setP] = useState(null); const [err, setErr] = useState(""); const [keep, setKeep] = useState(true);
  const [busy, setBusy] = useState(false); const [done, setDone] = useState(null);
  useEffect(() => { api.get("/api/workbooks/sync").then(setP).catch((e) => setErr(e.message)); }, []);
  const go = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.post("/api/workbooks/sync", { year: p.year, keep_workbook_rows: keep });
      setDone(r); onDone(`${r.workbook} now matches the ledger: ${r.written.toLocaleString()} payments for ${r.year}.`);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const n = (v) => (v || 0).toLocaleString();
  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>Sync the workbook with the ledger</DialogTitle>
      <DialogContent>
        {err && <Alert severity="error" sx={{ mb: 2 }}>{err}</Alert>}
        {!p && !err && <Stack direction="row" spacing={1.5} alignItems="center" sx={{ py: 3 }}><CircularProgress size={22} /><Typography>Comparing the workbook with the ledger…</Typography></Stack>}
        {done && <Alert severity="success" sx={{ mb: 2 }}>
          Done. {done.workbook} has {n(done.written)} payments for {done.year}
          {done.added_to_ledger ? `, and ${n(done.added_to_ledger)} row${done.added_to_ledger === 1 ? " that was" : "s that were"} only in the workbook ${done.added_to_ledger === 1 ? "is" : "are"} now in the ledger too` : ""}.
          A copy of the workbook from before is in checkflow_backups.</Alert>}
        {p && !done && <Stack spacing={2}>
          <Typography color="text.secondary">
            <b>{p.workbook}</b> · {p.year}. Every payee sheet is rewritten from the ledger's {p.year} payments in the workbook's own format:
            same columns, colors, day blocks, subtotals and totals. A copy of the workbook is saved in checkflow_backups first.
          </Typography>
          {p.in_sync ? <Alert severity="success">The workbook already matches the ledger.</Alert> : null}
          <Table size="small">
            <TableHead><TableRow><TableCell>Sheet</TableCell><TableCell align="right">Ledger</TableCell><TableCell align="right">Workbook now</TableCell>
              <TableCell align="right">Missing in workbook</TableCell><TableCell align="right">Only in workbook</TableCell></TableRow></TableHead>
            <TableBody>{p.sheets.map((s) => (
              <TableRow key={s.sheet}><TableCell><SheetChip sheet={s.sheet} /></TableCell>
                <TableCell align="right">{n(s.ledger)}<Typography variant="caption" display="block" color="text.secondary">{money(s.ledger_total)}</Typography></TableCell>
                <TableCell align="right">{n(s.workbook)}<Typography variant="caption" display="block" color="text.secondary">{money(s.workbook_total)}</Typography></TableCell>
                <TableCell align="right" sx={{ fontWeight: s.add ? 600 : 400 }}>{s.add ? n(s.add) : "–"}</TableCell>
                <TableCell align="right" sx={{ fontWeight: s.remove ? 600 : 400 }}>{s.remove ? n(s.remove) : "–"}</TableCell></TableRow>))}
            </TableBody>
          </Table>
          {p.add > 0 && <Typography variant="body2">{n(p.add)} ledger payment{p.add === 1 ? " is" : "s are"} missing from the workbook and will be written into {p.add === 1 ? "its" : "their"} day blocks.</Typography>}
          {p.remove > 0 && <Box>
            <Alert severity="warning" sx={{ mb: 1 }}>{n(p.remove)} row{p.remove === 1 ? " is" : "s are"} in the workbook but not in the ledger (typed straight into Excel, or changed there).</Alert>
            <Box sx={{ maxHeight: 180, overflow: "auto", border: 1, borderColor: "divider", borderRadius: 1 }}>
              <Table size="small" stickyHeader><TableHead><TableRow><TableCell>Sheet</TableCell><TableCell>Row</TableCell><TableCell>Received</TableCell><TableCell>Customer</TableCell><TableCell align="right">Amount</TableCell></TableRow></TableHead>
                <TableBody>{p.only_in_workbook.map((r, i) => (
                  <TableRow key={i}><TableCell>{r.sheet}</TableCell><TableCell>{r.row}</TableCell><TableCell>{fdate(r.received)}</TableCell><TableCell>{r.customer}</TableCell><TableCell align="right">{money(r.amount)}</TableCell></TableRow>))}
                </TableBody></Table>
            </Box>
            <FormControlLabel sx={{ mt: 1 }} control={<Checkbox checked={keep} onChange={(e) => setKeep(e.target.checked)} />}
              label={keep ? "Add them to the ledger first, so they stay in the workbook (recommended)" : "Leave them out: they'll be removed from the workbook"} />
          </Box>}
          {Object.keys(p.unmapped || {}).length > 0 && <Alert severity="info">Ledger payments for payees that aren't sheets in this workbook are left out: {Object.entries(p.unmapped).map(([k, v]) => `${k} (${v})`).join(", ")}.</Alert>}
          {p.undated?.length > 0 && <Alert severity="info">{p.undated.length} workbook row{p.undated.length === 1 ? " has" : "s have"} no date and can't be placed: {p.undated.map((r) => `${r.sheet} row ${r.row}`).join(", ")}.</Alert>}
        </Stack>}
      </DialogContent>
      <DialogActions>
        {done ? <><Button component="a" href="/api/workbook/download">Download workbook</Button><Button variant="contained" onClick={onClose}>Close</Button></>
          : <><Button onClick={onClose} disabled={busy}>Cancel</Button>
            <Button variant="contained" startIcon={busy ? <CircularProgress size={16} color="inherit" /> : <SyncIcon />} disabled={!p || busy || p.in_sync} onClick={go}>
              {busy ? "Syncing…" : "Sync workbook"}</Button></>}
      </DialogActions>
    </Dialog>
  );
}

function DeletedDialog({ open, onClose, onRestored, say }) {
  const [rows, setRows] = useState(null);
  const load = useCallback(async () => { try { setRows(await api.get("/api/ledger/deleted")); } catch (e) { say(e.message, "error"); } }, [say]);
  useEffect(() => { if (open) load(); }, [open, load]);
  const restore = async (r) => {
    try { const res = await api.post(`/api/ledger/${r.id}/restore`);
      onRestored(res.excel === "pending" ? "Restored. It goes back into the workbook once the workbook is closed." : "Restored to the ledger and the workbook."); load(); }
    catch (e) { say(e.message, "error"); }
  };
  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Deleted payments</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Payments taken out of the ledger. They don't count in any total or in the workbook until restored.</Typography>
        {!rows ? <CircularProgress size={24} /> : !rows.length ? <Typography color="text.secondary">Nothing deleted.</Typography> :
        <Box sx={{ overflowX: "auto" }}><Table size="small">
          <TableHead><TableRow><TableCell>Received</TableCell><TableCell>Customer</TableCell><TableCell>Payee</TableCell><TableCell align="right">Amount</TableCell><TableCell>Deleted</TableCell><TableCell>Why</TableCell><TableCell /></TableRow></TableHead>
          <TableBody>{rows.map((r) => (
            <TableRow key={r.id}>
              <TableCell sx={{ whiteSpace: "nowrap" }}>{fdate(r.fields.received)}</TableCell><TableCell sx={{ fontWeight: 600 }}>{r.fields.customer}</TableCell>
              <TableCell><SheetChip sheet={r.sheet} /></TableCell><TableCell align="right">{money(r.fields.amount)}</TableCell>
              <TableCell sx={{ whiteSpace: "nowrap" }}>{fdate((r.deleted_at || "").slice(0, 10))}<Typography variant="caption" display="block" color="text.secondary">by {r.deleted_by}</Typography></TableCell>
              <TableCell>{r.reason}</TableCell>
              <TableCell align="right"><Button size="small" startIcon={<RestoreIcon />} onClick={() => restore(r)}>Restore</Button></TableCell>
            </TableRow>))}
          </TableBody></Table></Box>}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}
