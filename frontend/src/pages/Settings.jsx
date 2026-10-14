import { useCallback, useEffect, useState } from "react";
import { Box, Paper, Stack, Typography, TextField, Button, Alert, MenuItem, Switch, FormControlLabel, Table, TableHead, TableBody,
  TableRow, TableCell, Chip, Dialog, DialogTitle, DialogContent, DialogActions, ToggleButtonGroup, ToggleButton, Divider } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import { api, METHODS, fdate } from "../api";
import { Triangles, SheetChip, useToast } from "../components/common";

function Section({ title, help, children }) {
  return (
    <Paper sx={{ p: { xs: 2, md: 3 } }}>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "260px 1fr" }, gap: 3 }}>
        <Box><Typography variant="h3">{title}</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{help}</Typography></Box>
        <Box>{children}</Box>
      </Box>
    </Paper>
  );
}

export default function Settings({ me }) {
  const [s, setS] = useState(null);
  const [draft, setDraft] = useState({});
  const [toast, say] = useToast();
  const load = useCallback(async () => { const r = await api.get("/api/settings"); setS(r); setDraft(r); }, []);
  useEffect(() => { load(); }, [load]);
  const set = (k) => (e) => setDraft((d) => ({ ...d, [k]: e?.target ? e.target.value : e }));
  const save = async (keys) => {
    try { const r = await api.post("/api/settings", Object.fromEntries(keys.map((k) => [k, draft[k] ?? ""]))); setS(r); setDraft(r); say("Saved."); }
    catch (e) { say(e.message, "error"); }
  };
  if (!s) return null;
  const banks = (draft.deposit_banks || "").split(",").map((x) => x.trim()).filter(Boolean);

  return (
    <Stack spacing={2.5}>
      <Box><Typography variant="h1">Settings <Triangles /></Typography><Typography color="text.secondary">Where payments are written, who can sign in, and how.</Typography></Box>

      <Section title="Workbook" help="The Excel file the payee sheets live in. CheckFlow saves a backup next to it (checkflow_backups) before every change.">
        <Stack spacing={2}>
          <TextField label="Full path to the workbook" value={draft.workbook || ""} onChange={set("workbook")}
            helperText="On a Mac: right-click the file in Finder, hold Option, choose 'Copy … as Pathname', paste here." />
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            {s.workbook_exists ? <Chip icon={<CheckCircleIcon />} color="success" variant="outlined" label="Found" /> : <Chip icon={<ErrorIcon />} color="error" variant="outlined" label="File not found" />}
            {s.workbook_open && <Chip color="warning" label="Open in Excel right now" />}
            {s.sheets.map((x) => <SheetChip key={x} sheet={x} />)}
            {/Practice_Workbook/.test(s.workbook) && <Chip variant="outlined" label="Practice workbook" />}
          </Stack>
          <TextField label="Sheets that aren't payee sheets (hidden)" value={draft.ignore_sheets || ""} onChange={set("ignore_sheets")} helperText="Comma separated, e.g. Sheet1, Sheet2, CARLOS OBISPO" />
          <Stack direction="row" spacing={1}>
            <Button variant="contained" onClick={() => save(["workbook", "ignore_sheets"])}>Save workbook</Button>
            <Button onClick={async () => { if (window.confirm("Switch to a fresh practice workbook? Your real workbook isn't touched.")) { const r = await api.post("/api/settings/practice"); setS(r); setDraft(r); } }}>Use a practice workbook</Button>
          </Stack>
        </Stack>
      </Section>

      <Section title="Deposit banks" help="Banks payments are deposited into, and the default for each payment method. Shown as choices on payments and in the ledger.">
        <Stack spacing={2}>
          <TextField label="Deposit banks" value={draft.deposit_banks || ""} onChange={set("deposit_banks")} helperText="Comma separated, e.g. TNB, LSB, LONE STAR, BPS, MID" />
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(5, 1fr)" }, gap: 1.5 }}>
            {Object.entries(METHODS).map(([k, l]) => (
              <TextField key={k} select label={`${l} default`} value={draft["deposit_bank_" + k] || ""} onChange={set("deposit_bank_" + k)}>
                <MenuItem value="">None</MenuItem>{banks.map((b) => <MenuItem key={b} value={b}>{b}</MenuItem>)}
              </TextField>))}
          </Box>
          <FormControlLabel control={<Switch checked={draft.keep_sensitive_pages === "1"} onChange={(e) => set("keep_sensitive_pages")(e.target.checked ? "1" : "0")} />}
            label="Keep ID and card photos readable (off: they're stored blurred)" />
          <Box><Button variant="contained" onClick={() => save(["deposit_banks", ...Object.keys(METHODS).map((k) => "deposit_bank_" + k), "keep_sensitive_pages"])}>Save</Button></Box>
        </Stack>
      </Section>

      <SignIn draft={draft} set={set} save={save} say={say} />
      <Users me={me} say={say} />
      <Audit />
      {toast}
    </Stack>
  );
}

function SignIn({ draft, set, save, say }) {
  const [test, setTest] = useState(null); const [tu, setTu] = useState(""); const [tp, setTp] = useState(""); const [res, setRes] = useState(null);
  const keys = ["auth_mode", "ldap_server", "ldap_upn_suffix", "ldap_domain", "ldap_base_dn", "ldap_admin_group", "ldap_ar_group"];
  const run = async () => {
    try { setRes(await api.post("/api/settings/test-ldap", { username: tu, password: tp, settings: Object.fromEntries(keys.map((k) => [k, draft[k] || ""])) })); }
    catch (e) { setRes({ ok: false, message: e.message }); }
  };
  return (
    <Section title="Sign-in" help="Company accounts (Active Directory) or local accounts. With AD on, local accounts still work, so admin can always get in if the domain controller is down.">
      <Stack spacing={2}>
        <ToggleButtonGroup exclusive value={draft.auth_mode || "local"} onChange={(_, v) => v && set("auth_mode")(v)} size="small">
          <ToggleButton value="local">Local accounts only</ToggleButton><ToggleButton value="ldap">Active Directory + local fallback</ToggleButton>
        </ToggleButtonGroup>
        {draft.auth_mode === "ldap" && <>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2 }}>
            <TextField label="AD server" placeholder="ldaps://dc01.capa.local" value={draft.ldap_server || ""} onChange={set("ldap_server")} helperText="ldap:// or ldaps:// (port 636)" />
            <TextField label="Sign-in suffix" placeholder="capa.local" value={draft.ldap_upn_suffix || ""} onChange={set("ldap_upn_suffix")} helperText="Users sign in as name → name@capa.local" />
            <TextField label="Domain (if no suffix)" placeholder="CAPA" value={draft.ldap_domain || ""} onChange={set("ldap_domain")} helperText="Binds as CAPA\name" />
            <TextField label="Search base" placeholder="DC=capa,DC=local" value={draft.ldap_base_dn || ""} onChange={set("ldap_base_dn")} helperText="Needed to read group membership" />
            <TextField label="Admin group" placeholder="CN=CheckFlow Admins,OU=Groups,DC=capa,DC=local" value={draft.ldap_admin_group || ""} onChange={set("ldap_admin_group")} helperText="Members become admins" />
            <TextField label="Accounts receivable group" placeholder="CN=Accounts Receivable,…" value={draft.ldap_ar_group || ""} onChange={set("ldap_ar_group")} helperText="Empty: every domain user may sign in as AR" />
          </Box>
        </>}
        <Stack direction="row" spacing={1}>
          <Button variant="contained" onClick={() => save(keys)}>Save sign-in</Button>
          {draft.auth_mode === "ldap" && <Button onClick={() => { setTest(true); setRes(null); }}>Test with an account…</Button>}
        </Stack>
      </Stack>
      <Dialog open={!!test} onClose={() => setTest(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Test Active Directory</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Domain username" value={tu} onChange={(e) => setTu(e.target.value)} />
          <TextField type="password" label="Password" value={tp} onChange={(e) => setTp(e.target.value)} />
          {res && <Alert severity={res.ok ? "success" : "error"}>{res.message}</Alert>}
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setTest(null)}>Close</Button><Button variant="contained" onClick={run}>Test</Button></DialogActions>
      </Dialog>
    </Section>
  );
}

function Users({ me, say }) {
  const [users, setUsers] = useState([]); const [add, setAdd] = useState(null);
  const load = useCallback(async () => setUsers(await api.get("/api/users")), []);
  useEffect(() => { load(); }, [load]);
  const patch = async (u, body) => { try { setUsers(await api.patch(`/api/users/${u.id}`, body)); } catch (e) { say(e.message, "error"); } };
  const create = async () => { try { setUsers(await api.post("/api/users", add)); setAdd(null); say("User added."); } catch (e) { say(e.message, "error"); } };
  return (
    <Section title="Users" help="Admins load, review and send payments and change settings. Accounts receivable only open the ledger and set Taxable.">
      <Box sx={{ overflowX: "auto" }}><Table size="small">
        <TableHead><TableRow><TableCell>User</TableCell><TableCell>Role</TableCell><TableCell>Account</TableCell><TableCell>Last sign-in</TableCell><TableCell /></TableRow></TableHead>
        <TableBody>{users.map((u) => (
          <TableRow key={u.id} sx={{ opacity: u.active ? 1 : .5 }}>
            <TableCell><b>{u.username}</b>{u.display_name ? ` · ${u.display_name}` : ""}{u.must_change ? <Chip size="small" color="warning" label="default password" sx={{ ml: 1 }} /> : null}</TableCell>
            <TableCell>
              <TextField select value={u.role} onChange={(e) => patch(u, { role: e.target.value })} disabled={u.id === me.id || u.source === "ldap"} sx={{ minWidth: 190 }}>
                <MenuItem value="admin">Admin</MenuItem><MenuItem value="ar">Accounts receivable</MenuItem></TextField>
            </TableCell>
            <TableCell>{u.source === "ldap" ? "Active Directory" : "Local"}</TableCell>
            <TableCell>{u.last_login ? fdate(u.last_login.slice(0, 10)) : "never"}</TableCell>
            <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
              {u.source === "local" && <Button size="small" onClick={() => { const p = window.prompt(`New password for ${u.username} (6+ characters)`); if (p) patch(u, { password: p }); }}>Reset password</Button>}
              {u.id !== me.id && <Button size="small" color={u.active ? "error" : "primary"} onClick={() => patch(u, { active: !u.active })}>{u.active ? "Disable" : "Enable"}</Button>}
            </TableCell>
          </TableRow>))}
        </TableBody>
      </Table></Box>
      <Button sx={{ mt: 2 }} variant="outlined" onClick={() => setAdd({ username: "", password: "", role: "ar" })}>Add local user</Button>
      <Dialog open={!!add} onClose={() => setAdd(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Add a local user</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Username" value={add?.username || ""} onChange={(e) => setAdd({ ...add, username: e.target.value })} />
          <TextField type="password" label="Password (6+ characters)" value={add?.password || ""} onChange={(e) => setAdd({ ...add, password: e.target.value })} />
          <TextField select label="Role" value={add?.role || "ar"} onChange={(e) => setAdd({ ...add, role: e.target.value })}>
            <MenuItem value="ar">Accounts receivable: ledger only, sets Taxable</MenuItem><MenuItem value="admin">Admin: everything</MenuItem></TextField>
          <Divider /><Typography variant="caption" color="text.secondary">Domain users don't need to be added: with Active Directory on, they appear here after their first sign-in.</Typography>
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setAdd(null)}>Cancel</Button><Button variant="contained" onClick={create}>Add user</Button></DialogActions>
      </Dialog>
    </Section>
  );
}

const ACTION = { login: "Signed in", uploaded: "Uploaded", submitted: "Sent to Excel", ledger_edit: "Changed in ledger", status_validated: "Validated", status_pending: "Set pending",
  status_review: "Back to review", payment_deleted: "Removed payment", payment_added: "Added payment", settings_changed: "Changed settings", user_added: "Added user",
  user_changed: "Changed user", password_changed: "Changed password" };
function Audit() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/api/audit?limit=150").then(setRows); }, []);
  return (
    <Section title="Activity" help="Who did what, most recent first. Kept in CheckFlow's database.">
      <Box sx={{ maxHeight: 360, overflow: "auto" }}><Table size="small" stickyHeader>
        <TableHead><TableRow><TableCell>When</TableCell><TableCell>Who</TableCell><TableCell>What</TableCell><TableCell>Details</TableCell></TableRow></TableHead>
        <TableBody>{rows.map((r) => (
          <TableRow key={r.id}><TableCell sx={{ whiteSpace: "nowrap" }}>{r.ts.replace("T", " ").slice(0, 16)}</TableCell><TableCell>{r.username}</TableCell>
            <TableCell>{ACTION[r.action] || r.action.replace(/_/g, " ")}{r.payment_id ? ` #${r.payment_id}` : ""}</TableCell>
            <TableCell sx={{ color: "text.secondary", fontSize: 12, maxWidth: 420, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.detail === "{}" ? "" : r.detail}</TableCell></TableRow>))}
        </TableBody></Table></Box>
    </Section>
  );
}
