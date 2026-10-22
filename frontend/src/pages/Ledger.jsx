import { useCallback, useEffect, useMemo, useState } from "react";
import { Box, Paper, Stack, Typography, TextField, MenuItem, Chip, Table, TableHead, TableBody, TableRow, TableCell, TableSortLabel, Dialog, DialogTitle, DialogContent, DialogActions,
  IconButton, Button, InputAdornment, Drawer, Divider, Tooltip, Select, ToggleButtonGroup, ToggleButton, Alert, CircularProgress } from "@mui/material";
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
import { api, money, num, fdate, METHODS, todayIso, downloadPost } from "../api";
import { brand, warnBg } from "../theme";
import { SheetChip, MethodChip, Thumbs, Lightbox, Stat, Triangles, useToast } from "../components/common";

const PERIODS = [["today", "Today"], ["week", "This week"], ["month", "This month"], ["quarter", "This quarter"], ["year", "This year"], ["all", "All time"]];
const GROUPS = [["day", "Day received"], ["week", "Week"], ["month", "Month"], ["quarter", "Quarter"], ["customer", "Company"], ["sheet", "Payee sheet"],
  ["method", "Payment method"], ["deposit_bank", "Deposit bank"], ["taxable", "Taxable"], ["none", "No grouping"]];
const COLS = [["received", "Received"], ["customer", "Customer"], ["sheet", "Sheet"], ["method", "Method"], ["ticket", "Ticket ref"],
  ["payref", "Payment ref"], ["order", "Order #"], ["amount", "Amount", "right"], ["taxable", "Taxable"], ["deposit_bank", "Deposit bank"], ["row", "Excel row", "right"]];

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
    case "taxable": return [f.taxable || "~", f.taxable === "Yes" ? "Taxable" : f.taxable === "No" ? "Not taxable" : "Taxable not set"];
    default: return ["all", "All payments"];
  }
}
const DATE_GROUPS = ["day", "week", "month", "quarter"];
const sortVal = (r, k) => k === "amount" ? num(r.fields.amount) : k === "row" ? (r.row || 0) : k === "sheet" ? (r.sheet || "") : String(r.fields[k] || "").toLowerCase();

export default function Ledger({ me }) {
  const isAdmin = me.role === "admin";
  const canTax = isAdmin || me.role === "ar";                 // AR: read, download images, set Taxable
  const canDownload = isAdmin || me.role === "ar";            // read-only: view only
  const canAttach = isAdmin || me.role === "ar";              // add / remove attachments (never scanned pages)
  const [deletedOpen, setDeletedOpen] = useState(false);
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [period, setPeriod] = useState("month");
  const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  const [sheets, setSheets] = useState([]);
  const [methods, setMethods] = useState([]);
  const [tax, setTax] = useState("any");
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
      if (tax === "yes" && f.taxable !== "Yes") return false;
      if (tax === "no" && f.taxable !== "No") return false;
      if (tax === "unset" && f.taxable) return false;
      if (onlyPending && !r.pending) return false;
      if (!needle) return true;
      return [f.customer, r.sheet, f.ticket, f.payref, f.check_no, f.order, f.amount, money(f.amount), f.deposit_bank, f.bank, f.confirmation,
        f.invoice, f.last4, METHODS[f.method], fdate(d), f.memo].join(" ").toLowerCase().includes(needle);
    });
  }, [data, q, from, to, sheets, methods, tax, onlyPending]);

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
    rows.forEach((r) => { const a = num(r.fields.amount); t.all += a;
      if (r.fields.taxable === "Yes") { t.taxable += a; const b = r.fields.deposit_bank || "No bank"; t.byBank[b] = (t.byBank[b] || 0) + a; }
      else if (r.fields.taxable === "No") t.notTaxable += a; else t.unset += 1; });
    return t;
  }, [rows]);

  // One road for every ledger edit (AR: Taxable; admin: any field): saved at once, Excel follows (now, or once the workbook is closed).
  const edit = async (r, k, v) => {
    const prev = r.fields[k];
    const patch = (val) => (x) => x.id === r.id ? { ...x, fields: { ...x.fields, [k]: val }, ...(k === "sheet" ? { sheet: val } : {}) } : x;
    setData((d) => ({ ...d, rows: d.rows.map(patch(v)) }));
    try {
      const res = await api.patch(`/api/ledger/${r.id}`, { [k]: v });
      if (res.excel !== "unchanged") say(res.excel === "pending" ? "Saved. Excel updates by itself once the workbook is closed." : res.excel === "skipped" ? "Saved in CheckFlow (this row isn't in the workbook)." : "Saved and updated in Excel.",
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
    const head = ["Received", "Customer", "Sheet", "Method", "Ticket ref", "Payment ref", "Order", "Amount", "Taxable", "Deposit bank", "Check date", "Bank", "Excel row"];
    const lines = [head].concat(groups.flatMap((g) => g.rows).map((r) => { const f = r.fields;
      return [f.received, f.customer, r.sheet, METHODS[f.method], f.ticket, f.payref, f.order, f.amount, f.taxable, f.deposit_bank, f.doc_date, f.bank, r.row]; }));
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
        <Tooltip title="The whole ledger, every payment, plus daily bank totals"><span><Button startIcon={<DownloadIcon />} disabled={!data.rows.length}
          onClick={() => downloadPost("/api/ledger/export", {}, "checkflow-ledger.xlsx").catch((e) => say(e.message, "error"))}>Export Excel</Button></span></Tooltip>
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
            {pendingCount > 0 && <Chip label="Excel pending" clickable color={onlyPending ? "warning" : "default"} variant={onlyPending ? "filled" : "outlined"} onClick={() => setOnlyPending(!onlyPending)} />}
            {(sheets.length || methods.length || tax !== "any" || onlyPending || q) ? <Button size="small" onClick={() => { setSheets([]); setMethods([]); setTax("any"); setOnlyPending(false); setQ(""); }}>Clear filters</Button> : null}
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
              const subTax = g.rows.filter((r) => r.fields.taxable === "Yes").reduce((s, r) => s + num(r.fields.amount), 0);
              const limit = more[g.key] ? Infinity : 60;
              return [
                group !== "none" && (
                  <TableRow key={"g" + g.key} hover onClick={() => setClosed((c) => ({ ...c, [g.key]: !isClosed }))} sx={{ cursor: "pointer", "& td": { bgcolor: "#F7F4F1", borderTop: "2px solid #E3DFDB" } }}>
                    <TableCell>{isClosed ? <ChevronRightIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}</TableCell>
                    <TableCell colSpan={7}><b>{g.label}</b> <Typography component="span" variant="body2" color="text.secondary">· {g.rows.length} payment{g.rows.length > 1 ? "s" : ""}{subTax ? ` · taxable ${money(subTax)}` : ""}</Typography></TableCell>
                    <TableCell align="right"><b>{money(sub)}</b></TableCell>
                    <TableCell colSpan={3} />
                  </TableRow>),
                ...(isClosed ? [] : g.rows.slice(0, limit).map((r) => <LedgerRow key={r.id} r={r} isAdmin={isAdmin} canTax={canTax} banks={data.deposit_banks} onEdit={edit} onOpen={() => setDetail(r)} />)),
                !isClosed && g.rows.length > limit && <TableRow key={"m" + g.key}><TableCell colSpan={12} align="center"><Button size="small" onClick={() => setMore((m) => ({ ...m, [g.key]: true }))}>Show all {g.rows.length}</Button></TableCell></TableRow>,
              ];
            })}
            <TableRow sx={{ "& td": { borderTop: "2px solid", borderColor: brand.espresso, fontWeight: 700 } }}>
              <TableCell /><TableCell colSpan={7}>Total · {rows.length} payments</TableCell><TableCell align="right">{money(totals.all)}</TableCell><TableCell colSpan={3} />
            </TableRow>
          </TableBody>
        </Table>}
      </Paper>
      <DetailDrawer r={detail} isAdmin={isAdmin} canTax={canTax} canDownload={canDownload} canAttach={canAttach} banks={data.deposit_banks} sheets={data.sheets} onClose={() => setDetail(null)}
        say={say} onChanged={load} onDeleted={() => { setDetail(null); load(); }}
        onEdit={async (r, k, v) => { const ok = await edit(r, k, v); if (ok) setDetail((d) => d && { ...d, fields: { ...d.fields, [k]: v }, ...(k === "sheet" ? { sheet: v } : {}) }); return ok; }} />
      {isAdmin && <DeletedDialog open={deletedOpen} onClose={() => setDeletedOpen(false)} onRestored={(m) => { say(m); load(); }} say={say} />}
      {isAdmin && <ImportExcelDialog open={importing} onClose={() => setImporting(false)}
        onDone={(m, keepOpen) => { if (!keepOpen) { setImporting(false); setPeriod("all"); } say(m); load(); }} />}
      {toast}
    </Stack>
  );
}

function TaxSelect({ r, onEdit }) {
  const v = r.fields.taxable || "";
  return (
    <Select size="small" value={v} displayEmpty onClick={(e) => e.stopPropagation()} onChange={(e) => onEdit(r, "taxable", e.target.value)}
      sx={{ minWidth: 92, bgcolor: v ? undefined : warnBg, "& .MuiSelect-select": { py: 0.5 } }} inputProps={{ "aria-label": "Taxable" }}>
      <MenuItem value="">Not set</MenuItem><MenuItem value="Yes">Yes</MenuItem><MenuItem value="No">No</MenuItem>
    </Select>
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

function LedgerRow({ r, isAdmin, canTax, banks, onEdit, onOpen }) {
  const f = r.fields;
  return (
    <TableRow hover onClick={onOpen} sx={{ cursor: "pointer" }}>
      <TableCell sx={{ py: 0.5 }}>
        {r.pages?.length ? <Box component="img" src={r.pages[0].image} alt="" loading="lazy" sx={{ width: 48, height: 34, objectFit: "cover", objectPosition: "top", borderRadius: .5, border: "1px solid #E3DFDB", display: "block" }} />
          : <Box sx={{ width: 48, height: 34, borderRadius: .5, bgcolor: "#F1EEEB", fontSize: 10, color: "text.secondary", display: "grid", placeItems: "center" }}>{r.imported ? "import" : "—"}</Box>}
      </TableCell>
      <TableCell sx={{ whiteSpace: "nowrap" }}>{fdate(f.received)}</TableCell>
      <TableCell sx={{ fontWeight: 600 }}>{f.customer}</TableCell>
      <TableCell><SheetChip sheet={r.sheet} /></TableCell>
      <TableCell><MethodChip method={f.method} /></TableCell>
      <TableCell>{f.ticket}</TableCell>
      <TableCell>{f.payref || (f.method === "wire" ? fdate(f.received, { month: "short", day: "numeric" }) : "")}</TableCell>
      <TableCell>{f.order}</TableCell>
      <TableCell align="right" sx={{ fontWeight: 600 }}>{money(f.amount)}</TableCell>
      <TableCell>{canTax ? <TaxSelect r={r} onEdit={onEdit} /> : (f.taxable || "Not set")}</TableCell>
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

function DetailDrawer({ r, isAdmin, canTax, canDownload, canAttach, banks, sheets, onClose, onEdit, say, onChanged, onDeleted }) {
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
    <Drawer anchor="right" open onClose={onClose} PaperProps={{ sx: { width: { xs: "100%", sm: 520 }, p: 3, border: 0 } }}>
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
      <Stack direction="row" spacing={2} sx={{ my: 2 }}>
        <Box><Typography variant="caption" color="text.secondary" display="block">Taxable</Typography>{canTax ? <TaxSelect r={r} onEdit={onEdit} /> : <Typography>{f.taxable || "Not set"}</Typography>}</Box>
        {isAdmin && <Box><Typography variant="caption" color="text.secondary" display="block">Deposit bank</Typography><BankSelect r={r} banks={banks} onEdit={onEdit} /></Box>}
      </Stack>
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
