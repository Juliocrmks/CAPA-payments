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
            <MenuItem disabled><Typography variant="body2">{me.role === "admin" ? "Admin" : "Accounts receivable"} · {me.source === "ldap" ? "company account" : "local account"}</Typography></MenuItem>
            {me.source === "local" && <MenuItem onClick={() => { setMenu(null); setPwOpen(true); }}><ListItemIcon><KeyIcon fontSize="small" /></ListItemIcon>Change password</MenuItem>}
            <MenuItem onClick={async () => { await api.post("/api/logout"); setMe(null); }}><ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>Sign out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      {me.must_change && (
        <Alert severity="warning" action={<Button color="inherit" size="small" onClick={() => setPwOpen(true)}>Change password</Button>} sx={{ borderRadius: 0 }}>
          You're signed in with the default admin password. Change it before other people use CheckFlow on the network.
        </Alert>
      )}
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

function PasswordDialog({ open, onClose, onDone }) {
  const [cur, setCur] = useState(""); const [n1, setN1] = useState(""); const [n2, setN2] = useState(""); const [err, setErr] = useState("");
  useEffect(() => { if (open) { setCur(""); setN1(""); setN2(""); setErr(""); } }, [open]);
  const save = async () => {
    if (n1 !== n2) return setErr("The new passwords don't match.");
    try { await api.post("/api/me/password", { current: cur, new: n1 }); onDone(); } catch (e) { setErr(e.message); }
  };
  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Change password</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        <TextField type="password" label="Current password" value={cur} onChange={(e) => setCur(e.target.value)} autoFocus />
        <TextField type="password" label="New password (6+ characters)" value={n1} onChange={(e) => setN1(e.target.value)} />
        <TextField type="password" label="Repeat new password" value={n2} onChange={(e) => setN2(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
        {err && <Alert severity="error">{err}</Alert>}
      </Stack></DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={save}>Change password</Button></DialogActions>
    </Dialog>
  );
}
