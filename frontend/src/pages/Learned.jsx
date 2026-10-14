import { useCallback, useEffect, useMemo, useState } from "react";
import { Box, Paper, Stack, Typography, Tabs, Tab, Table, TableHead, TableBody, TableRow, TableCell, TextField, IconButton, Button,
  InputAdornment, Dialog, DialogTitle, DialogContent, DialogActions, Alert, MenuItem, Chip } from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import AddIcon from "@mui/icons-material/Add";
import SearchIcon from "@mui/icons-material/Search";
import CloudDownloadIcon from "@mui/icons-material/CloudDownload";
import { api } from "../api";
import { SheetChip, Triangles, useToast } from "../components/common";

// What CheckFlow remembers so the second time is faster. Everything here is editable.
const TABLES = {
  customers: { title: "Customers", key: (r) => r.name, help: "Names exactly as the sheets write them. Scanned names snap to these. Defaults fill Taxable / Deposit bank on new payments.",
    cols: [["name", "Customer"], ["sheets", "Sheets"], ["taxable_default", "Taxable default", "tax"], ["deposit_bank_default", "Deposit bank default"], ["source", "From", "ro"]] },
  accounts: { title: "Bank accounts", key: (r) => `${r.routing}|${r.account}`, help: "Learned from checks you confirmed: the same routing + account is the same customer next time.",
    cols: [["customer", "Customer"], ["routing", "Routing #"], ["account", "Account #"], ["updated_at", "Last seen", "ro"]] },
  payees: { title: "Payees → sheets", key: (r) => String(r.id), help: "Which workbook sheet each division's payments go to. Aliases match file names like 'RVP OCT_09_26.pdf'.",
    cols: [["name", "Division (as printed)"], ["sheet", "Sheet", "sheet"], ["aliases", "Aliases (comma separated)"]] },
  banks: { title: "Banks", key: (r) => r.routing, help: "Bank names by routing number, shown on checks.", cols: [["name", "Bank"], ["routing", "Routing #"]] },
  memos: { title: "Wire postings", key: (r) => r.pattern, help: "Bank posting text that identifies who sent a wire (e.g. 'VENDOR PAY ACH Entry').",
    cols: [["pattern", "Posting text contains"], ["customer", "Customer"]] },
};

export default function Learned() {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("customers");
  const [q, setQ] = useState("");
  const [edit, setEdit] = useState(null);
  const [imp, setImp] = useState(false);
  const [sheets, setSheets] = useState([]);
  const [toast, say] = useToast();
  const load = useCallback(async () => { setData(await api.get("/api/learned")); setSheets((await api.get("/api/meta")).sheets); }, []);
  useEffect(() => { load(); }, [load]);
  const T = TABLES[tab];
  const rows = useMemo(() => (data?.[tab] || []).filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q.toLowerCase())), [data, tab, q]);

  const save = async () => {
    try { setData(await api.put(`/api/learned/${tab}` + (edit.key ? `?key=${encodeURIComponent(edit.key)}` : ""), edit.row)); setEdit(null); say("Saved."); }
    catch (e) { say(e.message, "error"); }
  };
  const del = async (r) => {
    if (!window.confirm("Delete this entry?")) return;
    setData(await api.del(`/api/learned/${tab}?key=${encodeURIComponent(T.key(r))}`));
  };

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", md: "row" }} alignItems={{ md: "flex-end" }} spacing={1}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h1">Learned data <Triangles /></Typography>
          <Typography color="text.secondary">What CheckFlow remembers from the payments you confirm. Fix anything here and the next scan uses it.</Typography>
        </Box>
        <Button startIcon={<CloudDownloadIcon />} variant="outlined" onClick={() => setImp(true)}>Import from workbook</Button>
      </Stack>
      <Paper>
        <Tabs value={tab} onChange={(_, v) => { setTab(v); setQ(""); }} variant="scrollable" sx={{ px: 1, borderBottom: 1, borderColor: "divider" }}>
          {Object.entries(TABLES).map(([k, t]) => <Tab key={k} value={k} label={`${t.title} (${data?.[k]?.length ?? "…"})`} />)}
        </Tabs>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ p: 2 }} alignItems={{ sm: "center" }}>
          <Typography variant="body2" color="text.secondary" sx={{ flex: 1 }}>{T.help}</Typography>
          <TextField placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} sx={{ maxWidth: 260 }}
            InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> }} />
          <Button startIcon={<AddIcon />} variant="contained" onClick={() => setEdit({ key: null, row: {} })}>Add</Button>
        </Stack>
        <Box sx={{ overflowX: "auto", maxHeight: "62vh" }}>
          <Table size="small" stickyHeader>
            <TableHead><TableRow>{T.cols.map(([k, l]) => <TableCell key={k}>{l}</TableCell>)}<TableCell /></TableRow></TableHead>
            <TableBody>
              {rows.slice(0, 500).map((r) => (
                <TableRow key={T.key(r)} hover>
                  {T.cols.map(([k, , t]) => <TableCell key={k}>{t === "sheet" ? <SheetChip sheet={r[k]} /> : k === "sheets" ? (r[k] || "").split(",").filter(Boolean).map((s) => <SheetChip key={s} sheet={s} />) :
                    t === "tax" ? (r[k] ? <Chip size="small" label={r[k]} /> : "") : r[k]}</TableCell>)}
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    <IconButton size="small" aria-label="Edit" onClick={() => setEdit({ key: T.key(r), row: { ...r } })}><EditIcon fontSize="small" /></IconButton>
                    <IconButton size="small" aria-label="Delete" onClick={() => del(r)}><DeleteOutlineIcon fontSize="small" /></IconButton>
                  </TableCell>
                </TableRow>))}
              {!rows.length && <TableRow><TableCell colSpan={9} sx={{ textAlign: "center", color: "text.secondary", py: 4 }}>
                {tab === "customers" ? "No customers yet. Import them from the workbook so scanned names match the sheets." : "Nothing learned yet. It fills in as you confirm payments."}</TableCell></TableRow>}
              {rows.length > 500 && <TableRow><TableCell colSpan={9} sx={{ color: "text.secondary" }}>Showing 500 of {rows.length}. Search to narrow it down.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </Box>
      </Paper>

      <Dialog open={!!edit} onClose={() => setEdit(null)} maxWidth="xs" fullWidth>
        <DialogTitle>{edit?.key ? "Edit" : "Add"} {T.title.toLowerCase()}</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          {edit && T.cols.filter(([, , t]) => t !== "ro").map(([k, l, t]) => t === "tax" ?
            <TextField key={k} select label={l} value={edit.row[k] || ""} onChange={(e) => setEdit({ ...edit, row: { ...edit.row, [k]: e.target.value } })}>
              <MenuItem value="">None</MenuItem><MenuItem value="Yes">Yes</MenuItem><MenuItem value="No">No</MenuItem></TextField> :
            t === "sheet" ? <TextField key={k} select label={l} value={edit.row[k] || ""} onChange={(e) => setEdit({ ...edit, row: { ...edit.row, [k]: e.target.value } })}>
              {sheets.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}</TextField> :
            <TextField key={k} label={l} value={edit.row[k] || ""} onChange={(e) => setEdit({ ...edit, row: { ...edit.row, [k]: e.target.value } })} />)}
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="contained" onClick={save}>Save</Button></DialogActions>
      </Dialog>
      <ImportDialog open={imp} sheets={sheets} onClose={() => setImp(false)} onDone={(m) => { setImp(false); say(m); load(); }} />
      {toast}
    </Stack>
  );
}

function ImportDialog({ open, sheets, onClose, onDone }) {
  const [what, setWhat] = useState("customers"); const [pick, setPick] = useState([]); const [since, setSince] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  useEffect(() => { if (open) { setPick(sheets.filter((s) => ["MVC", "UPPER", "RIO", "VCP"].includes(s))); setErr(""); } }, [open, sheets]);
  const go = async () => {
    setBusy(true); setErr("");
    try { const r = await api.post("/api/import", { what, sheets: pick, since }); onDone(what === "customers" ? `${r.imported} customer names imported.` : `${r.imported} past payments added to the ledger.`); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Import from the workbook</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        <TextField select label="What to import" value={what} onChange={(e) => setWhat(e.target.value)}>
          <MenuItem value="customers">Customer names only (recommended)</MenuItem>
          <MenuItem value="history">Past payments into the ledger (one-time migration)</MenuItem>
        </TextField>
        <Box><Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Sheets</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>{sheets.map((s) => <Chip key={s} label={s} clickable color={pick.includes(s) ? "secondary" : "default"}
            variant={pick.includes(s) ? "filled" : "outlined"} onClick={() => setPick(pick.includes(s) ? pick.filter((x) => x !== s) : [...pick, s])} />)}</Stack></Box>
        {what === "history" && <>
          <TextField type="date" label="Only days received since" value={since} onChange={(e) => setSince(e.target.value)} InputLabelProps={{ shrink: true }} helperText="Leave empty for everything in the workbook" />
          <Alert severity="info">Past rows come in without scans and are marked "import". Running it again skips rows already imported. Taxable edits on imported rows stay in CheckFlow and don't touch Excel.</Alert>
        </>}
        {err && <Alert severity="error">{err}</Alert>}
      </Stack></DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={go} disabled={busy || !pick.length}>{busy ? "Reading workbook…" : "Import"}</Button></DialogActions>
    </Dialog>
  );
}
