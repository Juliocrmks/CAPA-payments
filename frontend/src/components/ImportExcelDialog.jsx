import { useCallback, useEffect, useMemo, useState } from "react";
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, Stack, Box, Typography, Alert, Table, TableHead, TableBody, TableRow,
  TableCell, Checkbox, TextField, MenuItem, RadioGroup, Radio, FormControlLabel, LinearProgress, Chip, Divider, Collapse, IconButton, Tooltip } from "@mui/material";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import UndoIcon from "@mui/icons-material/Undo";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { api, money, fdate, METHODS } from "../api";
import { SheetChip } from "./common";

// Admin: add rows from any spreadsheet to the ledger. Step 1 reads and previews (nothing saved), step 2 adds them as
// one batch that can be undone. Rows already in the ledger (same payee, day, client and amount) are skipped.
export default function ImportExcelDialog({ open, onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [pv, setPv] = useState(null);
  const [pick, setPick] = useState([]);
  const [policy, setPolicy] = useState("fix");
  const [defSheet, setDefSheet] = useState("");
  const [dups, setDups] = useState(false);
  const [batches, setBatches] = useState([]);
  const [showDates, setShowDates] = useState(false);
  const [drag, setDrag] = useState(false);

  const loadBatches = useCallback(async () => { try { setBatches(await api.get("/api/import/batches")); } catch { /* ignore */ } }, []);
  useEffect(() => { if (open) { setFile(null); setPv(null); setErr(""); setPolicy("fix"); setDups(false); setDefSheet(""); loadBatches(); } }, [open, loadBatches]);

  const read = async (f) => {
    setFile(f); setPv(null); setErr(""); setBusy(true);
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await api.upload("/api/import/excel", fd);
      setPv(r);
      const known = new Set(r.known_sheets);
      setPick(r.per_sheet.map((s) => s.sheet).filter((s) => !s || known.has(s)));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const chosen = useMemo(() => (pv ? pv.per_sheet.filter((s) => pick.includes(s.sheet)) : []), [pv, pick]);
  const count = chosen.reduce((a, s) => a + s.new + (dups ? s.duplicates : 0), 0);
  const total = chosen.reduce((a, s) => a + s.total, 0);
  const needsSheet = pv?.needs_sheet && pick.includes("") && !defSheet;
  const flagged = pv ? pv.flagged_dates.filter((d) => pick.includes(d.sheet)) : [];
  const fixable = flagged.filter((d) => d.fix).length;

  const commit = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.post(`/api/import/excel/${pv.token}`, { sheets: pick.map((s) => s || defSheet), default_sheet: defSheet, include_duplicates: dups, date_policy: policy });
      onDone(`${r.imported.toLocaleString()} payments added to the ledger${r.skipped_duplicates ? ` (${r.skipped_duplicates.toLocaleString()} already there, skipped)` : ""}.`);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const undo = async (b) => {
    if (!window.confirm(`Remove the ${b.rows.toLocaleString()} payments imported from "${b.filename}"? Scanned payments are not affected.`)) return;
    try { const r = await api.del(`/api/import/batches/${b.batch}`); setBatches(r.batches); onDone(`${r.removed.toLocaleString()} imported payments removed.`, true); }
    catch (e) { setErr(e.message); }
  };

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>Import a spreadsheet into the ledger</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          {!pv && (
            <Box component="label" onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) read(f); }}
              sx={{ display: "block", border: "2px dashed", borderColor: drag ? "secondary.main" : "divider", borderRadius: 2, p: 4, textAlign: "center",
                cursor: busy ? "progress" : "pointer", bgcolor: drag ? "rgba(0,104,160,.05)" : "transparent" }}>
              <input type="file" hidden accept=".xlsx,.xlsm,.csv" disabled={busy} onChange={(e) => e.target.files[0] && read(e.target.files[0])} />
              <UploadFileIcon sx={{ fontSize: 40, color: "text.secondary" }} />
              <Typography sx={{ fontWeight: 600, mt: 1 }}>{busy ? `Reading ${file?.name}…` : "Drop an Excel or CSV file here, or click to choose"}</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>
                The payee workbook (day blocks, any year) or a plain table with Date, Customer and Amount columns. Method, Check #, Ticket,
                Payee, Deposit bank and Taxable columns are used when present.</Typography>
              {busy && <LinearProgress sx={{ mt: 2 }} />}
            </Box>
          )}
          {err && <Alert severity="error">{err}</Alert>}

          {pv && <>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
              <Box sx={{ flex: 1 }}>
                <Typography sx={{ fontWeight: 700 }}>{pv.filename}</Typography>
                <Typography variant="body2" color="text.secondary">
                  {pv.rows.toLocaleString()} payments found, {fdate(pv.first)} – {fdate(pv.last)}. {pv.duplicates ? `${pv.duplicates.toLocaleString()} are already in the ledger.` : "None are in the ledger yet."}
                </Typography>
              </Box>
              <Button size="small" onClick={() => { setPv(null); setFile(null); }} disabled={busy}>Choose another file</Button>
            </Stack>
            {pv.warnings.map((w) => <Alert key={w} severity="info" sx={{ py: 0 }}>{w}</Alert>)}

            <Box>
              <Typography variant="h3" sx={{ mb: 1 }}>Sheets to import</Typography>
              <Table size="small">
                <TableHead><TableRow><TableCell padding="checkbox" /><TableCell>Payee</TableCell><TableCell>Dates</TableCell>
                  <TableCell align="right">New</TableCell><TableCell align="right">Already in ledger</TableCell><TableCell align="right">New total</TableCell></TableRow></TableHead>
                <TableBody>
                  {pv.per_sheet.map((s) => {
                    const on = pick.includes(s.sheet); const known = !s.sheet || pv.known_sheets.includes(s.sheet);
                    return (
                      <TableRow key={s.sheet || "-"} hover onClick={() => setPick(on ? pick.filter((x) => x !== s.sheet) : [...pick, s.sheet])} sx={{ cursor: "pointer", opacity: on ? 1 : .55 }}>
                        <TableCell padding="checkbox"><Checkbox size="small" checked={on} inputProps={{ "aria-label": `Import ${s.sheet || "rows without a payee"}` }} /></TableCell>
                        <TableCell>{s.sheet ? <Stack direction="row" spacing={1} alignItems="center"><SheetChip sheet={s.sheet} />
                          {!known && <Typography variant="caption" color="text.secondary">not a workbook sheet</Typography>}</Stack>
                          : <Typography variant="body2" color="warning.dark">No payee in the file</Typography>}</TableCell>
                        <TableCell sx={{ whiteSpace: "nowrap" }}>{fdate(s.first, { month: "short", year: "numeric" })} – {fdate(s.last, { month: "short", year: "numeric" })}</TableCell>
                        <TableCell align="right">{s.new.toLocaleString()}</TableCell>
                        <TableCell align="right">{s.duplicates.toLocaleString()}</TableCell>
                        <TableCell align="right">{money(s.total)}</TableCell>
                      </TableRow>);
                  })}
                </TableBody>
              </Table>
            </Box>
            {pv.needs_sheet && pick.includes("") &&
              <TextField select label="Payee for rows that don't name one" value={defSheet} onChange={(e) => setDefSheet(e.target.value)} sx={{ maxWidth: 360 }}>
                {pv.known_sheets.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}</TextField>}

            {flagged.length > 0 && (
              <Box sx={{ border: 1, borderColor: "divider", borderRadius: 2, p: 1.5 }}>
                <Stack direction="row" alignItems="center">
                  <Typography sx={{ flex: 1, fontWeight: 600 }}>{flagged.length} row{flagged.length !== 1 ? "s have dates" : " has a date"} that don't fit the rows around {flagged.length !== 1 ? "them" : "it"}</Typography>
                  <Button size="small" endIcon={<ExpandMoreIcon sx={{ transform: showDates ? "rotate(180deg)" : "none" }} />} onClick={() => setShowDates(!showDates)}>{showDates ? "Hide" : "Show"}</Button>
                </Stack>
                <RadioGroup value={policy} onChange={(e) => setPolicy(e.target.value)}>
                  <FormControlLabel value="fix" control={<Radio size="small" />} label={fixable ? `Correct the year where it's clearly a typo (${fixable} row${fixable !== 1 ? "s" : ""}); keep the others as written` : "Keep them, but check them in the list"} />
                  <FormControlLabel value="skip" control={<Radio size="small" />} label="Leave these rows out" />
                  <FormControlLabel value="keep" control={<Radio size="small" />} label="Import them exactly as written" />
                </RadioGroup>
                <Collapse in={showDates}>
                  <Table size="small"><TableHead><TableRow><TableCell>Sheet · row</TableCell><TableCell>Client</TableCell><TableCell align="right">Amount</TableCell><TableCell>Date in file</TableCell><TableCell>Rows around it</TableCell><TableCell>Correction</TableCell></TableRow></TableHead>
                    <TableBody>{flagged.map((f) => (
                      <TableRow key={f.source + f.row}><TableCell>{f.source} · {f.row}</TableCell><TableCell>{f.customer}</TableCell><TableCell align="right">{money(f.amount)}</TableCell>
                        <TableCell sx={{ whiteSpace: "nowrap" }}>{fdate(f.was)}</TableCell><TableCell sx={{ whiteSpace: "nowrap" }}>{fdate(f.near)}</TableCell><TableCell sx={{ whiteSpace: "nowrap" }}>{f.fix ? fdate(f.fix) : "—"}</TableCell></TableRow>))}</TableBody></Table>
                </Collapse>
              </Box>)}

            <Box>
              <Typography variant="h3" sx={{ mb: 1 }}>First rows</Typography>
              <Box sx={{ overflowX: "auto" }}>
                <Table size="small">
                  <TableHead><TableRow><TableCell>Payee</TableCell><TableCell>Received</TableCell><TableCell>Client</TableCell><TableCell>Method</TableCell><TableCell>Ref</TableCell><TableCell>Ticket</TableCell><TableCell align="right">Amount</TableCell></TableRow></TableHead>
                  <TableBody>{pv.sample.map((r, i) => (
                    <TableRow key={i}><TableCell><SheetChip sheet={r.sheet} /></TableCell><TableCell>{fdate(r.received)}</TableCell><TableCell>{r.customer}</TableCell>
                      <TableCell>{METHODS[r.method]}</TableCell><TableCell>{r.payref}</TableCell><TableCell>{r.ticket}</TableCell><TableCell align="right">{money(r.amount)}</TableCell></TableRow>))}</TableBody>
                </Table>
              </Box>
            </Box>
            {pv.duplicates > 0 && <FormControlLabel control={<Checkbox size="small" checked={dups} onChange={(e) => setDups(e.target.checked)} />}
              label={`Also add the ${pv.duplicates.toLocaleString()} rows that look like payments already in the ledger`} />}
            <Alert severity="info" sx={{ py: 0 }}>Imported rows have no scans and never change the live workbook. Taxable and Deposit bank edits on them stay in CheckFlow.</Alert>
          </>}

          {batches.length > 0 && <>
            <Divider />
            <Typography variant="h3">Previous imports</Typography>
            <Table size="small"><TableBody>{batches.map((b) => (
              <TableRow key={b.batch}>
                <TableCell><Typography variant="body2" sx={{ fontWeight: 600 }}>{b.filename}</Typography>
                  <Typography variant="caption" color="text.secondary">{fdate(b.imported_at)} by {b.by}</Typography></TableCell>
                <TableCell>{b.rows.toLocaleString()} payments</TableCell><TableCell>{fdate(b.first, { month: "short", year: "numeric" })} – {fdate(b.last, { month: "short", year: "numeric" })}</TableCell>
                <TableCell align="right">{money(b.total)}</TableCell>
                <TableCell align="right"><Tooltip title="Remove every payment this import added"><IconButton size="small" aria-label={`Undo import of ${b.filename}`} onClick={() => undo(b)}><UndoIcon fontSize="small" /></IconButton></Tooltip></TableCell>
              </TableRow>))}</TableBody></Table>
          </>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>{pv ? "Cancel" : "Close"}</Button>
        {pv && <Button variant="contained" onClick={commit} disabled={busy || !count || needsSheet}>
          {busy ? "Adding…" : `Add ${count.toLocaleString()} payments${total ? ` (${money(total)})` : ""}`}</Button>}
      </DialogActions>
    </Dialog>
  );
}
