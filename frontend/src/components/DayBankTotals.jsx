import { useEffect, useMemo, useState } from "react";
import { Paper, Stack, Typography, IconButton, TextField, Table, TableHead, TableBody, TableRow, TableCell, ToggleButtonGroup,
  ToggleButton, Button, Box, Tooltip, Collapse } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DownloadIcon from "@mui/icons-material/Download";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { money, num, fdate, taxParts } from "../api";
import { SheetChip } from "./common";

// The cashier's daily view: for one day received, what went into each deposit bank (cash / checks / card-ACH-wire)
// and how much of it is taxable. Computed from the ledger rows on screen, so every Taxable, bank or amount edit
// shows here at once.
const NONE = "No deposit bank";
const COLS = [["count", "Payments"], ["cash", "Cash"], ["check", "Checks"], ["credit", "Card / ACH / wire"], ["total", "Total"],
  ["taxable", "Taxable"], ["notTaxable", "Not taxable"], ["unset", "Taxable not set"]];
const blank = () => ({ count: 0, cash: 0, check: 0, credit: 0, total: 0, taxable: 0, notTaxable: 0, unset: 0, unsetCount: 0 });

export function dayTotals(rows, day, banks, byPayee) {
  const groups = new Map();
  const all = blank();
  for (const r of rows) {
    const f = r.fields;
    if (f.received !== day) continue;
    const bank = f.deposit_bank || NONE;
    const key = byPayee ? `${bank}|${r.sheet || ""}` : bank;
    if (!groups.has(key)) groups.set(key, { bank, sheet: byPayee ? r.sheet || "" : null, ...blank() });
    const a = num(f.amount);
    for (const t of [groups.get(key), all]) {
      t.count += 1; t.total += a;
      t[f.method === "cash" ? "cash" : f.method === "check" ? "check" : "credit"] += a;
      const p = taxParts(f); t.taxable += p.tax; t.notTaxable += p.non; if (p.unset) { t.unset += p.unset; t.unsetCount += 1; }
    }
  }
  const order = (b) => (b === NONE ? 1e6 : banks.indexOf(b) >= 0 ? banks.indexOf(b) : 1000);
  const list = [...groups.values()].sort((x, y) => order(x.bank) - order(y.bank) || x.bank.localeCompare(y.bank) || (x.sheet || "").localeCompare(y.sheet || ""));
  return { list, all };
}

export default function DayBankTotals({ rows, banks }) {
  const days = useMemo(() => [...new Set(rows.map((r) => r.fields.received).filter(Boolean))].sort().reverse(), [rows]);
  const [day, setDay] = useState("");
  const [byPayee, setByPayee] = useState(false);
  const [open, setOpen] = useState(true);
  useEffect(() => { if (!day && days.length) setDay(days[0]); }, [days, day]);
  const { list, all } = useMemo(() => dayTotals(rows, day, banks, byPayee), [rows, day, banks, byPayee]);
  const i = days.indexOf(day);
  const older = i >= 0 ? days[i + 1] : days.find((d) => d < day);
  const newer = i > 0 ? days[i - 1] : i < 0 ? [...days].reverse().find((d) => d > day) : undefined;

  const csv = () => {
    const head = ["Day", "Deposit bank", ...(byPayee ? ["Payee"] : []), ...COLS.map(([, l]) => l)];
    const line = (g, label) => [day, label ?? g.bank, ...(byPayee ? [g.sheet ?? ""] : []), g.count, ...COLS.slice(1).map(([k]) => g[k].toFixed(2))];
    const out = [head, ...list.map((g) => line(g)), line(all, "TOTAL")];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([out.map((l) => l.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n")], { type: "text/csv" }));
    a.download = `checkflow-bank-totals-${day}.csv`; a.click();
  };

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ md: "center" }}>
        <Stack direction="row" alignItems="center" spacing={.5} sx={{ flex: 1, cursor: "pointer" }} onClick={() => setOpen(!open)}>
          <ExpandMoreIcon sx={{ transform: open ? "none" : "rotate(-90deg)", transition: "transform .15s", color: "text.secondary" }} />
          <Box>
            <Typography variant="h3">Daily bank totals</Typography>
            <Typography variant="body2" color="text.secondary">
              {day ? `${fdate(day, { weekday: "long", month: "short", day: "numeric", year: "numeric" })} · ${money(all.total)} in ${all.count} payment${all.count !== 1 ? "s" : ""} · taxable ${money(all.taxable)}` : "No payments yet"}
            </Typography>
          </Box>
        </Stack>
        {open && <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
          <Tooltip title="Previous day with payments"><span><IconButton size="small" aria-label="Previous day" disabled={!older} onClick={() => setDay(older)}><ChevronLeftIcon /></IconButton></span></Tooltip>
          <TextField type="date" size="small" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} sx={{ width: 160 }} inputProps={{ "aria-label": "Day received" }} />
          <Tooltip title="Next day with payments"><span><IconButton size="small" aria-label="Next day" disabled={!newer} onClick={() => setDay(newer)}><ChevronRightIcon /></IconButton></span></Tooltip>
          <ToggleButtonGroup size="small" exclusive value={byPayee ? "payee" : "bank"} onChange={(_, v) => v && setByPayee(v === "payee")}>
            <ToggleButton value="bank">By bank</ToggleButton><ToggleButton value="payee">Bank and payee</ToggleButton>
          </ToggleButtonGroup>
          <Button size="small" startIcon={<DownloadIcon />} onClick={csv} disabled={!all.count}>CSV</Button>
        </Stack>}
      </Stack>
      <Collapse in={open}>
        <Box sx={{ overflowX: "auto", mt: 1.5 }}>
          {!all.count ? <Typography color="text.secondary" sx={{ py: 2 }}>Nothing received on this day{rows.length ? " for the payees and methods selected below" : ""}.</Typography> :
          <Table size="small" sx={{ minWidth: 900 }}>
            <TableHead><TableRow>
              <TableCell>Deposit bank</TableCell>{byPayee && <TableCell>Payee</TableCell>}
              {COLS.map(([k, l]) => <TableCell key={k} align="right">{l}</TableCell>)}
            </TableRow></TableHead>
            <TableBody>
              {list.map((g) => (
                <TableRow key={g.bank + (g.sheet ?? "")}>
                  <TableCell sx={{ fontWeight: 600, color: g.bank === NONE ? "warning.dark" : "inherit" }}>{g.bank}</TableCell>
                  {byPayee && <TableCell><SheetChip sheet={g.sheet} /></TableCell>}
                  <TableCell align="right">{g.count}</TableCell>
                  {COLS.slice(1).map(([k]) => <TableCell key={k} align="right" sx={{ fontWeight: k === "total" || k === "taxable" ? 700 : 400,
                    color: k === "unset" && g.unset ? "warning.dark" : g[k] ? "inherit" : "text.disabled" }}>{g[k] ? money(g[k]) : "—"}</TableCell>)}
                </TableRow>))}
              <TableRow sx={{ "& td": { borderTop: "2px solid", borderColor: "primary.dark", fontWeight: 700 } }}>
                <TableCell>Total</TableCell>{byPayee && <TableCell />}
                <TableCell align="right">{all.count}</TableCell>
                {COLS.slice(1).map(([k]) => <TableCell key={k} align="right">{money(all[k])}</TableCell>)}
              </TableRow>
            </TableBody>
          </Table>}
          {all.unsetCount > 0 && <Typography variant="caption" color="warning.dark" sx={{ display: "block", mt: 1 }}>
            {all.unsetCount} payment{all.unsetCount !== 1 ? "s on this day still need" : " on this day still needs"} Taxable set. The taxable total will change once they are.</Typography>}
        </Box>
      </Collapse>
    </Paper>
  );
}
