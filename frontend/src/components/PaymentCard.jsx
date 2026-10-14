import { memo, useEffect, useRef, useState } from "react";
import { Paper, Box, Stack, TextField, MenuItem, Button, Chip, Alert, Autocomplete, IconButton, Menu, Typography, Tooltip, InputAdornment } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ScheduleIcon from "@mui/icons-material/Schedule";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { api, METHODS } from "../api";
import { brand, warnBg } from "../theme";
import { Thumbs, Lightbox, SheetChip, kindLabel } from "./common";

// Which fields each payment method shows (beyond the common ones).
const EXTRA = {
  check: [["check_no", "Check #"], ["doc_date", "Check date", "date"], ["routing", "Routing #", "mono"], ["account", "Account #", "mono"], ["bank", "Bank (drawn on)"]],
  card: [["card_brand", "Card"], ["last4", "Last 4"], ["confirmation", "Confirmation #", "mono"], ["invoice", "Invoice #"], ["doc_date", "Paid on", "date"]],
  ach: [["last4", "Account last 4"], ["confirmation", "Confirmation #", "mono"], ["invoice", "Invoice #"], ["doc_date", "Paid on", "date"]],
  wire: [["memo", "Bank posting text", "wide"]],
  cash: [],
};
const SOURCE = { check: "check", confirmation: "e-mail confirmation", receipt: "receipt slip", bankpost: "bank posting", manual: "typed in" };

function PaymentCard({ p, meta, onChange, onRemove, onMovePage }) {
  const [f, setF] = useState(p.fields);
  const [warns, setWarns] = useState(p.warns);
  const [busy, setBusy] = useState(false);
  const [lb, setLb] = useState(null);
  const [menu, setMenu] = useState(null);
  const timers = useRef({});
  useEffect(() => { setF(p.fields); setWarns(p.warns); }, [p.id]);  // local edits win; the server copy only seeds the form

  const save = async (patch) => {
    try { const r = await api.patch(`/api/payments/${p.id}`, { fields: patch }); setWarns(r.warns); setF((x) => ({ ...x, ...pick(r.fields, Object.keys(patch).concat(["sheet", "bank", "payref"])) })); onChange(r, true); }
    catch (e) { setWarns((w) => ({ ...w, [Object.keys(patch)[0]]: e.message })); }
  };
  const set = (k, v, now) => {
    setF((x) => ({ ...x, [k]: v })); setWarns((w) => { const n = { ...w }; delete n[k]; return n; });
    clearTimeout(timers.current[k]);
    timers.current[k] = setTimeout(() => save({ [k]: v }), now ? 0 : 600);
  };
  const status = async (s) => {
    setBusy(true);
    try { const r = await api.patch(`/api/payments/${p.id}`, { status: s }); onChange(r); } finally { setBusy(false); }
  };
  const validated = p.status === "validated";
  const W = (k) => warns?.[k];
  const fieldSx = (k) => W(k) ? { "& .MuiOutlinedInput-root": { bgcolor: warnBg }, "& .MuiOutlinedInput-notchedOutline": { borderColor: brand.concrete } } : {};
  const tf = (k, label, type, rest = {}) => (
    <TextField key={k} label={label} value={f[k] || ""} onChange={(e) => set(k, e.target.value)} type={type === "date" ? "date" : "text"}
      InputLabelProps={type === "date" ? { shrink: true } : undefined} error={false} helperText={W(k) || " "}
      FormHelperTextProps={{ title: W(k) || "", sx: { ...hint, color: W(k) ? "#8a5300" : undefined } }}
      inputProps={type === "mono" ? { style: { fontFamily: "ui-monospace, Menlo, monospace" } } : undefined}
      sx={{ ...fieldSx(k), gridColumn: type === "wide" ? "1 / -1" : undefined }} {...rest} />
  );
  const other = Object.entries(warns || {}).filter(([k]) => !["duplicate", ...allKeys].includes(k));
  const sources = (p.sources || []).map((s) => SOURCE[s] || s).join(" + ");

  return (
    <Paper sx={{ p: { xs: 1.5, md: 2 }, borderWidth: 2, borderColor: validated ? brand.validated : "divider", transition: "border-color .2s" }}>
      {W("duplicate") && <Alert severity="error" sx={{ mb: 1.5 }}>{W("duplicate")}</Alert>}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "260px 1fr" }, gap: 2 }}>
        <Box>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
            <Typography variant="h3" sx={{ flex: 1 }}>#{p.id}</Typography>
            <SheetChip sheet={f.sheet} />
            {p.pages?.length > 0 && <IconButton size="small" aria-label="Page actions" onClick={(e) => setMenu(e.currentTarget)}><MoreVertIcon fontSize="small" /></IconButton>}
          </Stack>
          <Thumbs pages={p.pages} onOpen={setLb} height={150} max={3} />
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.75 }}>
            {p.pages?.length ? `${p.pages.length} page${p.pages.length > 1 ? "s" : ""}` : "No pages"}{sources ? ` · read from ${sources}` : ""}
          </Typography>
          <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
            <MenuItem disabled><Typography variant="caption">Move a page into its own new payment</Typography></MenuItem>
            {(p.pages || []).map((pg, i) => (
              <MenuItem key={pg.id} disabled={p.pages.length < 2} onClick={() => { setMenu(null); onMovePage(p.id, pg.id); }}>
                Page {i + 1}: {kindLabel(pg.kind)}</MenuItem>))}
          </Menu>
        </Box>
        <Box>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", sm: "repeat(3, 1fr)", lg: "repeat(4, 1fr)" }, columnGap: 1.5, rowGap: 0.25 }}>
            <Autocomplete freeSolo options={meta.customers || []} value={f.customer || ""} sx={{ gridColumn: { xs: "1 / -1", sm: "span 2" } }}
              onInputChange={(_, v, reason) => reason !== "reset" && set("customer", (v || "").toUpperCase())}
              renderInput={(params) => <TextField {...params} label="Customer (as in the sheet)" helperText={W("customer") || (f.customer_raw && f.customer_raw.toUpperCase() !== f.customer ? `Read as: ${f.customer_raw}` : " ")}
                FormHelperTextProps={{ title: W("customer") || "", sx: { ...hint, color: W("customer") ? "#8a5300" : undefined } }} sx={fieldSx("customer")} />} />
            <TextField select label="Payment method" value={f.method || "check"} onChange={(e) => set("method", e.target.value, true)} helperText={W("method") || " "}
              FormHelperTextProps={{ title: W("method") || "", sx: { ...hint, color: W("method") ? "#8a5300" : undefined } }} sx={fieldSx("method")}>
              {Object.entries(METHODS).map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}
            </TextField>
            {tf("amount", "Amount", null, { InputProps: { startAdornment: <InputAdornment position="start">$</InputAdornment> } })}
            <TextField select label="Payee sheet" value={f.sheet || ""} onChange={(e) => set("sheet", e.target.value, true)} helperText={W("sheet") || " "}
              FormHelperTextProps={{ title: W("sheet") || "", sx: { ...hint, color: W("sheet") ? "#8a5300" : undefined } }} sx={fieldSx("sheet")}>
              {(meta.sheets || []).concat(f.sheet && !(meta.sheets || []).includes(f.sheet) ? [f.sheet] : []).map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
            </TextField>
            {tf("received", "Date received", "date")}
            {tf("ticket", "Ticket ref (receipt #)")}
            {tf("payref", f.method === "check" ? "Payment ref (check #)" : f.method === "wire" ? "Payment ref (blank = date)" : "Payment ref")}
            {tf("order", "Order # (quote)")}
            <TextField select label="Taxable" value={f.taxable || ""} onChange={(e) => set("taxable", e.target.value, true)} helperText=" ">
              <MenuItem value="">Not set</MenuItem><MenuItem value="Yes">Yes</MenuItem><MenuItem value="No">No</MenuItem>
            </TextField>
            <Autocomplete freeSolo options={meta.deposit_banks || []} value={f.deposit_bank || ""}
              onInputChange={(_, v, reason) => reason !== "reset" && set("deposit_bank", (v || "").toUpperCase())}
              renderInput={(params) => <TextField {...params} label="Deposit bank (optional)" helperText=" " />} />
            {(EXTRA[f.method] || []).map(([k, l, t]) => tf(k, l, t))}
          </Box>
          {other.length > 0 && (
            <Stack spacing={0.5} sx={{ mb: 1 }}>{other.map(([k, v]) => <Typography key={k} variant="body2" sx={{ color: "#8a5300", display: "flex", gap: 0.5, alignItems: "center" }}><WarningAmberIcon fontSize="inherit" />{v}</Typography>)}</Stack>
          )}
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip size="small" icon={validated ? <CheckCircleIcon /> : <ScheduleIcon />} label={validated ? "Validated" : "Not validated"}
              color={validated ? "success" : "default"} variant={validated ? "filled" : "outlined"} />
            {Object.keys(warns || {}).length > 0 && <Chip size="small" label={`${Object.keys(warns).length} to check`} sx={{ bgcolor: warnBg, color: "#8a5300" }} />}
            <Box sx={{ flex: 1 }} />
            <Tooltip title="Remove this payment from CheckFlow"><IconButton aria-label="Remove" onClick={() => onRemove(p)} disabled={busy}><DeleteOutlineIcon /></IconButton></Tooltip>
            <Button variant="outlined" onClick={() => status("pending")} disabled={busy}>Pending</Button>
            <Button variant={validated ? "contained" : "outlined"} color="success" startIcon={<CheckCircleIcon />} disabled={busy}
              onClick={() => status(validated ? "review" : "validated")}>{validated ? "Validated" : "Validate"}</Button>
          </Stack>
        </Box>
      </Box>
      {lb !== null && <Lightbox pages={p.pages} index={lb} onClose={() => setLb(null)} />}
    </Paper>
  );
}
// one-line hints so a long warning never runs into the next row; full text on hover
const hint = { mx: 0.5, minHeight: 20, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" };
const allKeys = ["customer", "method", "amount", "sheet", "received", "ticket", "payref", "order", "taxable", "deposit_bank",
  "check_no", "doc_date", "routing", "account", "bank", "card_brand", "last4", "confirmation", "invoice", "memo"];
const pick = (o, ks) => Object.fromEntries(ks.filter((k) => k in o).map((k) => [k, o[k]]));
export default memo(PaymentCard);
