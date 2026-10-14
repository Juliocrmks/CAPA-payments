import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Paper, Stack, Typography, Button, TextField, MenuItem, Tabs, Tab, LinearProgress, Chip, Dialog, DialogTitle,
  DialogContent, DialogActions, Alert, Divider, Badge, Table, TableBody, TableRow, TableCell } from "@mui/material";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import AddIcon from "@mui/icons-material/Add";
import SendIcon from "@mui/icons-material/Send";
import DescriptionIcon from "@mui/icons-material/Description";
import { api, money, num, fdate, METHODS } from "../api";
import { brand } from "../theme";
import PaymentCard from "../components/PaymentCard";
import { SheetChip, Triangles, useToast } from "../components/common";

export default function Inbox() {
  const [meta, setMeta] = useState({ sheets: [], customers: [], deposit_banks: [] });
  const [list, setList] = useState([]);
  const [pending, setPending] = useState([]);
  const [tab, setTab] = useState("review");
  const [files, setFiles] = useState([]);
  const [received, setReceived] = useState("");
  const [sheet, setSheet] = useState("");
  const [jobs, setJobs] = useState([]);
  const [over, setOver] = useState(false);
  const [summary, setSummary] = useState(false);
  const [result, setResult] = useState(null);
  const [toast, say] = useToast();
  const input = useRef();

  const load = useCallback(async () => {
    const [m, a, b] = await Promise.all([api.get("/api/meta"), api.get("/api/payments?status=review,validated"), api.get("/api/payments?status=pending")]);
    setMeta(m); setList(a); setPending(b);
  }, []);
  useEffect(() => { load(); }, [load]);

  // poll running extraction jobs
  useEffect(() => {
    if (!jobs.some((j) => j.status === "queued" || j.status === "processing")) return;
    const t = setInterval(async () => {
      const upd = await Promise.all(jobs.map((j) => (j.status === "done" || j.status === "error") ? j : api.get(`/api/documents/${j.id}`)));
      setJobs(upd);
      if (upd.some((j, i) => j.status === "done" && jobs[i].status !== "done")) { load(); setTab("review"); }
    }, 1500);
    return () => clearInterval(t);
  }, [jobs, load]);

  const addFiles = (fl) => {
    const ok = [...fl].filter((f) => /\.(pdf|jpe?g|png|tiff?|heic|webp|bmp)$/i.test(f.name));
    if (ok.length < fl.length) say("Only PDF and image files can be read.", "warning");
    setFiles((x) => [...x, ...ok]);
  };
  const upload = async () => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("received", received); fd.append("sheet", sheet);
    try { const docs = await api.upload("/api/documents", fd); setJobs((j) => [...docs, ...j]); setFiles([]); }
    catch (e) { say(e.message, "error"); }
  };
  const onChange = (r) => {
    if (r.status === "pending") { setList((l) => l.filter((x) => x.id !== r.id)); setPending((l) => [...l, r]); return; }
    setPending((l) => l.filter((x) => x.id !== r.id));
    setList((l) => l.some((x) => x.id === r.id) ? l.map((x) => (x.id === r.id ? r : x)) : [...l, r]);
  };
  const remove = async (p) => {
    if (!window.confirm(`Remove payment #${p.id}? Its scanned pages stay in the upload history.`)) return;
    try { await api.del(`/api/payments/${p.id}`); setList((l) => l.filter((x) => x.id !== p.id)); setPending((l) => l.filter((x) => x.id !== p.id)); }
    catch (e) { say(e.message, "error"); }
  };
  const movePage = async (pid, pageId) => { await api.post(`/api/payments/${pid}/move-page`, { page_id: pageId }); load(); say("Page moved into a new payment."); };
  const addManual = async () => { const r = await api.post("/api/payments", { fields: { method: "cash" } }); setList((l) => [...l, r]); setTab("review"); };

  const review = list.filter((p) => p.status === "review");
  const validated = list.filter((p) => p.status === "validated");
  const shown = tab === "review" ? review : tab === "validated" ? validated : pending;
  const total = validated.reduce((s, p) => s + num(p.fields.amount), 0);
  const running = jobs.filter((j) => j.status === "queued" || j.status === "processing");

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h1">Payments <Triangles /></Typography>
        <Typography color="text.secondary">Load the day's scans, check what was read, then send everything to the payee sheets.</Typography>
      </Box>

      <Paper sx={{ p: 2.5 }}>
        <Box onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files); }}
          sx={{ border: "2px dashed", borderColor: over ? "secondary.main" : "divider", bgcolor: over ? "rgba(0,104,160,.05)" : "#FBFAF9",
            borderRadius: 2, p: { xs: 2.5, md: 4 }, textAlign: "center", transition: ".15s" }}>
          <CloudUploadIcon sx={{ fontSize: 40, color: brand.clay }} />
          <Typography sx={{ fontWeight: 600, mt: 1 }}>Drop scanned PDFs or photos here</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>A whole day's packet in one PDF is fine: checks, receipt slips, card confirmations and wire postings are told apart automatically.</Typography>
          <Button variant="contained" onClick={() => input.current.click()}>Choose files</Button>
          <input ref={input} type="file" multiple hidden accept=".pdf,image/*" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
        </Box>
        {files.length > 0 && (
          <Stack spacing={2} sx={{ mt: 2 }}>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {files.map((f, i) => <Chip key={i} icon={<DescriptionIcon />} label={f.name} onDelete={() => setFiles((x) => x.filter((_, k) => k !== i))} />)}
            </Stack>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2} alignItems={{ sm: "flex-start" }}>
              <TextField type="date" label="Date received" value={received} onChange={(e) => setReceived(e.target.value)} InputLabelProps={{ shrink: true }}
                helperText="Leave empty to use the date in the file name (MVC OCT_09-26.pdf) or today" sx={{ maxWidth: 300 }} />
              <TextField select label="Payee sheet" value={sheet} onChange={(e) => setSheet(e.target.value)} helperText="Auto uses the file name and what's printed"
                sx={{ maxWidth: 260 }}>
                <MenuItem value="">Auto-detect</MenuItem>{meta.sheets.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
              </TextField>
              <Box sx={{ flex: 1 }} />
              <Button variant="contained" color="secondary" size="large" onClick={upload}>Read {files.length} file{files.length > 1 ? "s" : ""}</Button>
            </Stack>
          </Stack>
        )}
        {jobs.length > 0 && (
          <Stack spacing={1.25} sx={{ mt: 2 }}>
            {jobs.slice(0, 6).map((j) => (
              <Box key={j.id} sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "minmax(160px, 320px) 1fr 160px" }, gap: { xs: .5, sm: 2 }, alignItems: "center" }}>
                <Typography variant="body2" noWrap title={j.filename}>{j.filename}</Typography>
                <LinearProgress variant="determinate" value={Math.round((j.progress || 0) * 100)} color={j.status === "error" ? "error" : j.status === "done" ? "success" : "secondary"} sx={{ height: 8, borderRadius: 4 }} />
                <Typography variant="body2" color={j.status === "error" ? "error" : "text.secondary"} noWrap title={j.error || ""}>
                  {j.status === "done" ? `Done · ${j.pages} pages` : j.status === "error" ? "Couldn't read" : j.status === "queued" ? "Waiting" : `Reading${j.pages ? ` ${j.pages} pages` : ""}…`}</Typography>
              </Box>))}
          </Stack>
        )}
      </Paper>

      <Box>
        <Stack direction="row" alignItems="center" sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ flex: 1 }} variant="scrollable">
            <Tab value="review" label={<Badge color="warning" badgeContent={review.length} sx={{ pr: 1.5 }}>To review</Badge>} />
            <Tab value="validated" label={<Badge color="success" badgeContent={validated.length} sx={{ pr: 1.5 }}>Validated</Badge>} />
            <Tab value="pending" label={<Badge color="default" badgeContent={pending.length} sx={{ pr: 1.5, "& .MuiBadge-badge": { bgcolor: "#ddd" } }}>Pending</Badge>} />
          </Tabs>
          <Button startIcon={<AddIcon />} onClick={addManual} aria-label="Add payment by hand"><Box component="span" sx={{ display: { xs: "none", sm: "inline" } }}>Add payment by hand</Box></Button>
        </Stack>
        <Stack spacing={2} sx={{ mt: 2, pb: 10 }}>
          {running.length > 0 && shown.length === 0 && <Typography color="text.secondary">Reading documents… payments appear here as soon as they're ready.</Typography>}
          {shown.length === 0 && !running.length && (
            <Paper sx={{ p: 4, textAlign: "center", color: "text.secondary" }}>
              {tab === "review" ? "Nothing to review. Load the day's scans above." : tab === "validated" ? "Validate payments in To review and they collect here, ready to send." :
                "No pending payments. Use Pending on a card to set it aside for later."}
            </Paper>)}
          {shown.map((p) => <PaymentCard key={p.id} p={p} meta={meta} onChange={onChange} onRemove={remove} onMovePage={movePage} />)}
        </Stack>
      </Box>

      <Paper sx={{ position: "fixed", left: 0, right: 0, bottom: 0, borderRadius: 0, borderLeft: 0, borderRight: 0, px: 3, py: 1.5, zIndex: 10,
        display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
        <Typography sx={{ flex: 1 }}><b>{validated.length}</b> validated · <b>{money(total)}</b> · {review.length} still to review · {pending.length} pending</Typography>
        <Button variant="contained" size="large" endIcon={<SendIcon />} disabled={!validated.length} onClick={() => setSummary(true)}>Continue</Button>
      </Paper>

      <SummaryDialog open={summary} items={validated} left={review.length} onClose={() => setSummary(false)}
        onSent={(r) => { setSummary(false); setResult(r); load(); }} />
      <Dialog open={!!result} onClose={() => setResult(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Sent to Excel</DialogTitle>
        <DialogContent>
          {result && <>
            <Typography sx={{ mb: 2 }}>{result.written} payment{result.written === 1 ? "" : "s"} written. A backup of the workbook was saved first.</Typography>
            {Object.entries(result.sheets).map(([s, n]) => <Stack key={s} direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}><SheetChip sheet={s} /><Typography>{n} row{n > 1 ? "s" : ""} added</Typography></Stack>)}
            {result.skipped.map((s) => <Alert key={s.id} severity="warning" sx={{ mt: 1 }}>#{s.id} not sent: {s.reason}</Alert>)}
          </>}
        </DialogContent>
        <DialogActions><Button onClick={() => { setResult(null); window.location.hash = "/ledger"; }}>Open ledger</Button><Button variant="contained" onClick={() => setResult(null)}>Done</Button></DialogActions>
      </Dialog>
      {toast}
    </Stack>
  );
}

function SummaryDialog({ open, items, left, onClose, onSent }) {
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setErr(""); }, [open]);
  const bySheet = useMemo(() => {
    const m = {};
    items.forEach((p) => { const k = p.fields.sheet || "(no sheet)"; const d = p.fields.received || "";
      m[k] = m[k] || { total: 0, days: new Set(), methods: {} }; m[k].total += num(p.fields.amount); m[k].days.add(d);
      m[k].methods[p.fields.method] = (m[k].methods[p.fields.method] || 0) + num(p.fields.amount); });
    return m;
  }, [items]);
  const flagged = items.filter((p) => Object.keys(p.warns || {}).length);
  const send = async () => {
    setBusy(true); setErr("");
    try { onSent(await api.post("/api/submit", { ids: items.map((p) => p.id) })); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Final check before sending</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2 }}>{items.length} validated payment{items.length === 1 ? "" : "s"} for <b>{money(items.reduce((s, p) => s + num(p.fields.amount), 0))}</b>.
          {left > 0 && ` ${left} not validated yet will stay in To review.`}</Typography>
        <Table size="small"><TableBody>
          {Object.entries(bySheet).map(([s, v]) => (
            <TableRow key={s}>
              <TableCell><SheetChip sheet={s === "(no sheet)" ? "" : s} /></TableCell>
              <TableCell>{[...v.days].map((d) => fdate(d)).join(", ")}</TableCell>
              <TableCell>{Object.entries(v.methods).map(([m, a]) => `${METHODS[m]} ${money(a)}`).join(" · ")}</TableCell>
              <TableCell align="right"><b>{money(v.total)}</b></TableCell>
            </TableRow>))}
        </TableBody></Table>
        {flagged.length > 0 && <Alert severity="warning" sx={{ mt: 2 }}>{flagged.length} validated payment{flagged.length > 1 ? "s still have" : " still has"} highlighted fields. They'll be sent as they are.</Alert>}
        <Divider sx={{ my: 2 }} />
        <Typography variant="body2" color="text.secondary">Each payee sheet gets a block for the day received with CREDIT / CHECKS / CASH subtotals and a total. Close the workbook in Excel first.</Typography>
        {err && <Alert severity="error" sx={{ mt: 2 }}>{err}</Alert>}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Keep reviewing</Button><Button variant="contained" onClick={send} disabled={busy || !items.length}>{busy ? "Writing…" : "Send to Excel"}</Button></DialogActions>
    </Dialog>
  );
}
