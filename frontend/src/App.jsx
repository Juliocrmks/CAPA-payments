import { useCallback, useEffect, useState, lazy, Suspense } from "react";
import { AppBar, Toolbar, Box, Tabs, Tab, Button, Menu, MenuItem, Typography, Alert, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, Stack, CircularProgress, ListItemIcon } from "@mui/material";
import AccountCircleIcon from "@mui/icons-material/AccountCircle";
import LogoutIcon from "@mui/icons-material/Logout";
import KeyIcon from "@mui/icons-material/Key";
import { api, setUnauthorizedHandler } from "./api";
import Login from "./pages/Login";
import Inbox from "./pages/Inbox";
import Ledger from "./pages/Ledger";
import Learned from "./pages/Learned";
import Settings from "./pages/Settings";
const Analytics = lazy(() => import("./pages/Analytics"));     // charts load only when this tab opens

const ADMIN_TABS = [["inbox", "Payments"], ["ledger", "Ledger"], ["analytics", "Analytics"], ["learned", "Learned data"], ["settings", "Settings"]];
const AR_TABS = [["ledger", "Ledger"]];
export const ROLE_LABEL = { admin: "Admin", ar: "AR · images and Taxable", readonly: "Read only" };

function useHashRoute(def) {
  const read = () => (window.location.hash.replace(/^#\/?/, "") || def);
  const [r, setR] = useState(read);
  useEffect(() => { const h = () => setR(read()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); });
  return [r, (x) => { window.location.hash = "/" + x; }];
}

export default function App() {
  const [me, setMe] = useState(undefined);
  const [route, go] = useHashRoute("inbox");
  const [menu, setMenu] = useState(null);
  const [pwOpen, setPwOpen] = useState(false);

  const load = useCallback(async () => {
    try { const m = await api.get("/api/me"); setMe(m.user || null); } catch { setMe(null); }
  }, []);
  useEffect(() => { load(); setUnauthorizedHandler(() => setMe(null)); }, [load]);

  if (me === undefined) return <Box sx={{ height: "100vh", display: "grid", placeItems: "center" }}><CircularProgress /></Box>;
  if (!me) return <Login onDone={load} />;

  const tabs = me.role === "admin" ? ADMIN_TABS : AR_TABS;
  const current = tabs.some(([k]) => k === route) ? route : tabs[0][0];

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppBar position="sticky">
        <Toolbar sx={{ gap: 2, minHeight: { xs: 56, md: 64 } }}>
          <Box component="img" src="/capa-logo.png" alt="CAPA" sx={{ height: 46, width: 46, objectFit: "cover", borderRadius: 1 }} />
          <Typography sx={{ fontFamily: "Montserrat", fontWeight: 700, letterSpacing: ".02em", display: { xs: "none", sm: "block" } }}>
            CheckFlow</Typography>
          <Tabs value={current} onChange={(_, v) => go(v)} textColor="inherit" TabIndicatorProps={{ sx: { bgcolor: "#E8961F", height: 3 } }}
            sx={{ flex: 1, "& .MuiTab-root": { color: "rgba(255,255,255,.72)" }, "& .Mui-selected": { color: "#fff" } }} variant="scrollable">
            {tabs.map(([k, l]) => <Tab key={k} value={k} label={l} />)}
          </Tabs>
          <Button color="inherit" startIcon={<AccountCircleIcon />} onClick={(e) => setMenu(e.currentTarget)} sx={{ whiteSpace: "nowrap" }}>
            {me.display_name || me.username}
          </Button>
          <Menu anchorEl={menu} open={!!menu} onClose={() => setMenu(null)}>
            <MenuItem disabled><Typography variant="body2">{me.email || me.username} · {ROLE_LABEL[me.role] || me.role}</Typography></MenuItem>
            {me.source === "local" && <MenuItem onClick={() => { setMenu(null); setPwOpen(true); }}><ListItemIcon><KeyIcon fontSize="small" /></ListItemIcon>Change password</MenuItem>}
            <MenuItem onClick={async () => { await api.post("/api/logout"); setMe(null); }}><ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <PasswordDialog open={me.must_change && me.source === "local"} forced onClose={() => {}} onDone={load} />
      <Box component="main" sx={{ flex: 1, width: "100%", maxWidth: ["ledger", "inbox", "analytics"].includes(current) ? 1680 : 1320, mx: "auto", px: { xs: 1.5, md: 3 }, py: 3 }}>
        {current === "inbox" && <Inbox />}
        {current === "ledger" && <Ledger me={me} />}
        {current === "analytics" && <Suspense fallback={<CircularProgress />}><Analytics /></Suspense>}
        {current === "learned" && <Learned />}
        {current === "settings" && <Settings me={me} />}
      </Box>
      <PasswordDialog open={pwOpen} onClose={() => setPwOpen(false)} onDone={() => { setPwOpen(false); load(); }} />
    </Box>
  );
}

function PasswordDialog({ open, onClose, onDone, forced }) {
  const [cur, setCur] = useState(""); const [n1, setN1] = useState(""); const [n2, setN2] = useState(""); const [err, setErr] = useState("");
  useEffect(() => { if (open) { setCur(""); setN1(""); setN2(""); setErr(""); } }, [open]);
  const save = async () => {
    if (!n1) return setErr("Enter a new password.");
    if (n1 !== n2) return setErr("The new passwords don't match.");
    try { await api.post("/api/me/password", { current: cur, new: n1 }); onDone(); } catch (e) { setErr(e.message); }
  };
  return (
    <Dialog open={open} onClose={forced ? undefined : onClose} maxWidth="xs" fullWidth disableEscapeKeyDown={forced}>
      <DialogTitle>{forced ? "Choose your password" : "Change password"}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        {forced && <Alert severity="info">You signed in with a temporary password. Choose your own to continue.</Alert>}
        <TextField type="password" label={forced ? "Temporary password" : "Current password"} value={cur} onChange={(e) => setCur(e.target.value)} autoFocus />
        <TextField type="password" label="New password" value={n1} onChange={(e) => setN1(e.target.value)} />
        <TextField type="password" label="Repeat new password" value={n2} onChange={(e) => setN2(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
        {err && <Alert severity="error">{err}</Alert>}
      </Stack></DialogContent>
      <DialogActions>
        {forced ? <Button onClick={async () => { await api.post("/api/logout"); window.location.reload(); }}>Sign out</Button> : <Button onClick={onClose}>Cancel</Button>}
        <Button variant="contained" onClick={save}>{forced ? "Save and continue" : "Change password"}</Button>
      </DialogActions>
    </Dialog>
  );
}
