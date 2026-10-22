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

// ------------------------------------------------------------------ workbooks
const kb = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const whenText = (iso) => (iso ? `${fdate(iso.slice(0, 10))} ${iso.slice(11, 16)}` : "");
function suggestName(cur, year) {
  const base = (cur || "").split(/[\\/]/).pop() || "";
  if (/Practice_Workbook/i.test(base) || !base) return `Payments ${year}.xlsx`;
  return /(19|20)\d{2}/.test(base) ? base.replace(/(19|20)\d{2}/, String(year)) : base.replace(/\.(xlsx|xlsm)$/i, ` ${year}.$1`);
}

function Workbooks({ s, draft, set, save, say, onSettings }) {
  const [books, setBooks] = useState(null); const [folder, setFolder] = useState("");
  const [mk, setMk] = useState(null); const [busy, setBusy] = useState(false); const [typed, setTyped] = useState(false);
  const load = useCallback(async () => { const r = await api.get("/api/workbooks"); setBooks(r.workbooks); setFolder(r.new_folder); }, []);
  useEffect(() => { load(); }, [load, s.workbook]);
  const use = async (b) => {
    try { const r = await api.post("/api/workbooks/select", { path: b.path }); onSettings(r.settings); setBooks(r.workbooks); say(`Now writing to ${b.name}.`); }
    catch (e) { say(e.message, "error"); }
  };
  const upload = async (file) => {
    if (!file) return;
    const fd = new FormData(); fd.append("file", file); setBusy(true);
    try { const r = await api.upload("/api/workbooks/upload", fd); setBooks(r.workbooks); say(`Uploaded ${r.path.split(/[\\/]/).pop()}. Click "Use this" to write to it.`); }
    catch (e) { say(e.message, "error"); } finally { setBusy(false); }
  };
  const openNew = () => {
    const y = new Date().getFullYear(); const year = (s.workbook || "").includes(String(y)) ? y + 1 : y;
    setMk({ name: suggestName(s.workbook, year), year: String(year), source: "current", use: true });
  };
  const create = async () => {
    setBusy(true);
    try {
      const r = await api.post("/api/workbooks/new", { name: mk.name, year: mk.year ? Number(mk.year) : null, source: mk.source, use: mk.use });
      onSettings(r.settings); setBooks(r.workbooks); setMk(null);
      say(`Created ${r.path.split(/[\\/]/).pop()}: ${r.sheets.join(", ")}${mk.use ? ". New payments go there now." : "."}`);
    } catch (e) { say(e.message, "error"); } finally { setBusy(false); }
  };
  const cur = books?.find((b) => b.current);
  return (
    <Section title="Workbook" help="The Excel file payments are written to. CheckFlow saves a backup next to it (checkflow_backups) before every change. Payments stay linked to the workbook they were written to, so corrections to last year's payments still go to last year's file.">
      <Stack spacing={2}>
        <Box>
          <Typography variant="caption" color="text.secondary">Writing to</Typography>
          <Typography sx={{ fontWeight: 600, wordBreak: "break-all" }}>{(s.workbook || "").split(/[\\/]/).pop()}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ wordBreak: "break-all" }}>{(s.workbook || "").replace(/[\\/][^\\/]*$/, "")}</Typography>
        </Box>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
          {s.workbook_exists ? <Chip icon={<CheckCircleIcon />} color="success" variant="outlined" label="Found" /> : <Chip icon={<ErrorIcon />} color="error" variant="outlined" label="File not found" />}
          {s.workbook_open && <Chip color="warning" label="Open in Excel right now" />}
          {s.sheets.map((x) => <SheetChip key={x} sheet={x} />)}
          {/Practice_Workbook/.test(s.workbook) && <Chip variant="outlined" label="Practice workbook" />}
        </Stack>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Button variant="contained" onClick={openNew}>New workbook</Button>
          <Button component="label" variant="outlined" disabled={busy}>Upload workbook
            <input hidden type="file" accept=".xlsx,.xlsm" onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} /></Button>
          {cur?.exists && <Button component="a" href={`/api/workbooks/download?path=${encodeURIComponent(cur.path)}`}>Download</Button>}
          <Button onClick={async () => { if (window.confirm("Switch to a fresh practice workbook? Your real workbook isn't touched.")) { const r = await api.post("/api/settings/practice"); onSettings(r); } }}>Use a practice workbook</Button>
        </Stack>

        <Box>
          <Typography variant="subtitle2" sx={{ mb: .5 }}>Available workbooks</Typography>
          {!books ? <Typography variant="body2" color="text.secondary">Loading…</Typography> : (
            <Box sx={{ overflowX: "auto" }}>
              <Table size="small">
                <TableHead><TableRow><TableCell>Workbook</TableCell><TableCell>Changed</TableCell><TableCell align="right">Size</TableCell>
                  <TableCell align="right">Payments sent</TableCell><TableCell /></TableRow></TableHead>
                <TableBody>{books.map((b) => (
                  <TableRow key={b.path} selected={b.current}>
                    <TableCell sx={{ maxWidth: 340 }}>
                      <Typography variant="body2" sx={{ fontWeight: b.current ? 600 : 400, wordBreak: "break-all" }}>{b.name}</Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ wordBreak: "break-all" }}>{b.folder}</Typography>
                    </TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{b.exists ? whenText(b.modified) : <Typography variant="body2" color="error">Missing</Typography>}</TableCell>
                    <TableCell align="right">{b.exists ? kb(b.size) : ""}</TableCell>
                    <TableCell align="right">{b.payments || ""}</TableCell>
                    <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                      {b.open && <Chip size="small" color="warning" label="Open in Excel" sx={{ mr: 1 }} />}
                      {b.current ? <Chip size="small" color="success" label="In use" /> : b.exists && <Button size="small" onClick={() => use(b)}>Use this</Button>}
                      {b.exists && <Button size="small" component="a" href={`/api/workbooks/download?path=${encodeURIComponent(b.path)}`}>Download</Button>}
                    </TableCell>
                  </TableRow>))}
                </TableBody>
              </Table>
            </Box>)}
        </Box>

        <TextField label="Sheets that aren't payee sheets (hidden)" value={draft.ignore_sheets || ""} onChange={set("ignore_sheets")} helperText="Comma separated, e.g. Sheet1, Sheet2, CARLOS OBISPO" />
        {typed && <TextField label="Full path to the workbook" value={draft.workbook || ""} onChange={set("workbook")}
          helperText="On a Mac: right-click the file in Finder, hold Option, choose 'Copy … as Pathname', paste here." />}
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" onClick={() => save(typed ? ["workbook", "ignore_sheets"] : ["ignore_sheets"])}>Save</Button>
          {!typed && <Button onClick={() => setTyped(true)}>Type a path instead</Button>}
        </Stack>
      </Stack>

      <Dialog open={!!mk} onClose={() => setMk(null)} maxWidth="sm" fullWidth>
        <DialogTitle>New workbook</DialogTitle>
        {mk && <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            An empty workbook for a new period. Each payee sheet keeps its columns, colors, subtotal labels and spacing, with no payments in it.
            Other sheets (client sheets, Sheet1…) are copied as they are. The workbook in use isn't changed.
          </Typography>
          <TextField label="Name" value={mk.name} onChange={(e) => setMk({ ...mk, name: e.target.value })} helperText={`Saved in ${folder}`} />
          <TextField label="Year in the sheet titles" value={mk.year} onChange={(e) => setMk({ ...mk, year: e.target.value.replace(/\D/g, "").slice(0, 4) })}
            helperText="Replaces the year in title rows like 'MAGIC VALLEY CONCRETE 2026'. Leave empty to keep them." />
          <Box>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: .5 }}>Layout</Typography>
            <ToggleButtonGroup size="small" exclusive value={mk.source} onChange={(_, v) => v && setMk({ ...mk, source: v })}>
              <ToggleButton value="current">Like the workbook in use</ToggleButton>
              <ToggleButton value="standard">Standard MVC / UVM / RVP / VCP</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <FormControlLabel control={<Switch checked={mk.use} onChange={(e) => setMk({ ...mk, use: e.target.checked })} />} label="Write new payments to it from now on" />
        </Stack></DialogContent>}
        <DialogActions><Button onClick={() => setMk(null)}>Cancel</Button>
          <Button variant="contained" disabled={busy || !mk?.name?.trim()} onClick={create}>{busy ? "Creating…" : "Create workbook"}</Button></DialogActions>
      </Dialog>
    </Section>
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

      <Workbooks s={s} draft={draft} set={set} save={save} say={say} onSettings={(r) => { setS(r); setDraft(r); }} />

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

const ROLES = [["admin", "Admin", "Everything: payments, ledger edits and deletes, attachments, analytics, settings, users"],
  ["ar", "AR", "Ledger and daily totals, view and download images, add attachments, set Taxable"],
  ["readonly", "Read only", "Ledger and daily totals, view images (no download), no changes"]];
const roleName = (r) => (ROLES.find(([k]) => k === r) || [r, r])[1];

function Users({ me, say }) {
  const [users, setUsers] = useState([]); const [reqs, setReqs] = useState([]);
  const [add, setAdd] = useState(null); const [bulk, setBulk] = useState(null); const [reset, setReset] = useState(null); const [shown, setShown] = useState(null);
  const load = useCallback(async () => { setUsers(await api.get("/api/users")); setReqs(await api.get("/api/password-requests")); }, []);
  useEffect(() => { load(); }, [load]);
  const patch = async (u, body) => { try { setUsers(await api.patch(`/api/users/${u.id}`, body)); } catch (e) { say(e.message, "error"); } };
  const create = async () => {
    try { const r = await api.post("/api/users", add); setUsers(r.users); setAdd(null); setShown([{ name: add.display_name, email: add.email, role: add.role, ok: true, password: add.password ? "" : r.password }]); }
    catch (e) { say(e.message, "error"); }
  };
  const createMany = async () => {
    try { const r = await api.post("/api/users/bulk", { text: bulk }); setUsers(r.users); setBulk(null); setShown(r.results); }
    catch (e) { say(e.message, "error"); }
  };
  const doReset = async () => {
    try { const r = await api.post(`/api/users/${reset.u.id}/password`, { password: reset.password, must_change: reset.must_change }); setUsers(r.users);
      setReqs(await api.get("/api/password-requests"));
      setShown([{ name: reset.u.display_name, email: reset.u.email || reset.u.username, role: reset.u.role, ok: true, password: reset.password ? "" : r.password, reset: true }]); setReset(null); }
    catch (e) { say(e.message, "error"); }
  };
  const openReset = (u) => setReset({ u, password: "", must_change: true });
  return (
    <Section title="Users" help="Who can sign in and what they can do. People sign in with their email. New users and password resets get a temporary password; they choose their own at their next sign-in.">
      <Stack spacing={2}>
        {reqs.map((q) => (
          <Alert key={q.id} severity="warning" action={<Stack direction="row" spacing={1}>
            {q.user_id && <Button color="inherit" size="small" onClick={() => openReset(users.find((u) => u.id === q.user_id) || { id: q.user_id, username: q.username, email: q.email, display_name: q.display_name })}>Reset password</Button>}
            <Button color="inherit" size="small" onClick={async () => setReqs(await api.post(`/api/password-requests/${q.id}/dismiss`))}>Dismiss</Button></Stack>}>
            <b>{q.display_name || q.email || q.login}</b> asked for a password reset ({fdate(q.created_at.slice(0, 10))}).
          </Alert>))}
        <Box sx={{ overflowX: "auto" }}><Table size="small">
          <TableHead><TableRow><TableCell>Person</TableCell><TableCell>Role</TableCell><TableCell>Last sign-in</TableCell><TableCell /></TableRow></TableHead>
          <TableBody>{users.map((u) => (
            <TableRow key={u.id} sx={{ opacity: u.active ? 1 : .5 }}>
              <TableCell>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>{u.display_name || u.username}
                  {!u.active && <Chip size="small" label="disabled" sx={{ ml: 1 }} />}
                  {u.active && u.must_change ? <Chip size="small" color="warning" variant="outlined" label="temporary password" sx={{ ml: 1 }} /> : null}</Typography>
                <Typography variant="caption" color="text.secondary">{u.email || u.username}{u.source === "ldap" ? " · Active Directory" : ""}</Typography>
              </TableCell>
              <TableCell>
                <TextField select value={u.role} onChange={(e) => patch(u, { role: e.target.value })} disabled={u.id === me.id || u.source === "ldap"} sx={{ minWidth: 150 }}>
                  {ROLES.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}</TextField>
              </TableCell>
              <TableCell>{u.last_login ? fdate(u.last_login.slice(0, 10)) : "never"}</TableCell>
              <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                {u.source === "local" && <Button size="small" onClick={() => openReset(u)}>Reset password</Button>}
                {u.id !== me.id && <Button size="small" color={u.active ? "error" : "primary"} onClick={() => patch(u, { active: !u.active })}>{u.active ? "Disable" : "Enable"}</Button>}
              </TableCell>
            </TableRow>))}
          </TableBody>
        </Table></Box>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(3, 1fr)" }, gap: 1 }}>
          {ROLES.map(([k, l, d]) => <Box key={k} sx={{ border: 1, borderColor: "divider", borderRadius: 1.5, p: 1.25 }}>
            <Typography variant="body2" sx={{ fontWeight: 700 }}>{l}</Typography><Typography variant="caption" color="text.secondary">{d}</Typography></Box>)}
        </Box>
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" onClick={() => setAdd({ display_name: "", email: "", role: "ar", password: "" })}>Add user</Button>
          <Button onClick={() => setBulk("")}>Add several</Button>
        </Stack>
      </Stack>

      <Dialog open={!!add} onClose={() => setAdd(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Add a user</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="Name" value={add?.display_name || ""} onChange={(e) => setAdd({ ...add, display_name: e.target.value })} autoFocus />
          <TextField label="Email (they sign in with it)" value={add?.email || ""} onChange={(e) => setAdd({ ...add, email: e.target.value })} />
          <TextField select label="Role" value={add?.role || "ar"} onChange={(e) => setAdd({ ...add, role: e.target.value })} helperText={ROLES.find(([k]) => k === add?.role)?.[2]}>
            {ROLES.map(([k, l]) => <MenuItem key={k} value={k}>{l}</MenuItem>)}</TextField>
          <TextField label="Temporary password (optional)" value={add?.password || ""} onChange={(e) => setAdd({ ...add, password: e.target.value })}
            helperText="Leave empty to generate one. They choose their own at first sign-in." />
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setAdd(null)}>Cancel</Button><Button variant="contained" onClick={create} disabled={!add?.email}>Add user</Button></DialogActions>
      </Dialog>

      <Dialog open={bulk !== null} onClose={() => setBulk(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Add several users</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2" color="text.secondary">One person per line: <b>Name, email, role</b>. Role is Admin, AR or Read only. Each gets a temporary password, shown once on the next screen.</Typography>
          <TextField multiline minRows={8} value={bulk || ""} onChange={(e) => setBulk(e.target.value)} placeholder={"Sandy Marks, cashier@company.com, Admin\nMichelle Ebert, collections@company.com, AR\nRichard Escalera, rescalera@company.com, Read only"}
            InputProps={{ sx: { fontFamily: "ui-monospace, Menlo, monospace", fontSize: 13 } }} />
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setBulk(null)}>Cancel</Button><Button variant="contained" onClick={createMany} disabled={!bulk?.trim()}>Add users</Button></DialogActions>
      </Dialog>

      <Dialog open={!!reset} onClose={() => setReset(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Reset password for {reset?.u.display_name || reset?.u.email || reset?.u.username}</DialogTitle>
        <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
          <TextField label="New password (optional)" value={reset?.password || ""} onChange={(e) => setReset({ ...reset, password: e.target.value })} helperText="Leave empty to generate a temporary one." autoFocus />
          <FormControlLabel control={<Switch checked={!!reset?.must_change} onChange={(e) => setReset({ ...reset, must_change: e.target.checked })} />} label="Ask them to choose their own at next sign-in" />
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => setReset(null)}>Cancel</Button><Button variant="contained" onClick={doReset}>Reset password</Button></DialogActions>
      </Dialog>

      <Dialog open={!!shown} onClose={() => setShown(null)} maxWidth="md" fullWidth>
        <DialogTitle>{shown?.[0]?.reset ? "Password reset" : "Users added"}</DialogTitle>
        <DialogContent>
          {shown?.some((r) => r.password) && <Alert severity="info" sx={{ mb: 2 }}>Give each person their temporary password. It is shown only now; they'll choose their own when they sign in.</Alert>}
          <Table size="small"><TableHead><TableRow><TableCell>Name</TableCell><TableCell>Email</TableCell><TableCell>Role</TableCell><TableCell>Temporary password</TableCell></TableRow></TableHead>
            <TableBody>{(shown || []).map((r, i) => (
              <TableRow key={i}><TableCell>{r.name}</TableCell><TableCell>{r.email}</TableCell><TableCell>{roleName(r.role)}</TableCell>
                <TableCell sx={{ fontFamily: "ui-monospace, Menlo, monospace" }}>{r.ok ? (r.password || "the one you typed") : <Typography variant="body2" color="error">{r.error}</Typography>}</TableCell></TableRow>))}
            </TableBody></Table>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => navigator.clipboard?.writeText((shown || []).filter((r) => r.ok && r.password).map((r) => `${r.name}\t${r.email}\t${roleName(r.role)}\t${r.password}`).join("\n"))}>Copy all</Button>
          <Button variant="contained" onClick={() => setShown(null)}>Done</Button>
        </DialogActions>
      </Dialog>
    </Section>
  );
}

const ACTION = { login: "Signed in", uploaded: "Uploaded", submitted: "Sent to Excel", ledger_edit: "Changed in ledger", status_validated: "Validated", status_pending: "Set pending",
  status_review: "Back to review", payment_deleted: "Removed payment", payment_added: "Added payment", settings_changed: "Changed settings", user_added: "Added user",
  user_changed: "Changed user", password_changed: "Changed password", password_reset: "Reset a password", password_reset_requested: "Asked for a password reset",
  ledger_deleted: "Deleted from ledger", ledger_restored: "Restored to ledger", attachment_added: "Added attachment", attachment_removed: "Removed attachment",
  image_downloaded: "Downloaded image", pdf_downloaded: "Downloaded PDF", ledger_exported: "Exported ledger", import_excel: "Imported spreadsheet" };
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
