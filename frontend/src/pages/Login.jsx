import { useState } from "react";
import { Box, Paper, Stack, TextField, Button, Typography, Alert } from "@mui/material";
import { api } from "../api";
import { brand } from "../theme";

export default function Login({ onDone }) {
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const go = async (e) => {
    e?.preventDefault(); setBusy(true); setErr("");
    try { await api.post("/api/login", { username: u, password: p }); onDone(); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <Box sx={{ minHeight: "100vh", display: "grid", gridTemplateColumns: { xs: "1fr", md: "1.1fr 1fr" } }}>
      <Box sx={{ bgcolor: brand.espresso, color: "#fff", display: { xs: "none", md: "flex" }, flexDirection: "column", justifyContent: "center", px: 8 }}>
        <Box component="img" src="/capa-logo.png" alt="CAPA: concrete, asphalt, pipe, aggregates" sx={{ width: 300, maxWidth: "80%" }} />
        <Typography sx={{ mt: 4, maxWidth: 420, opacity: .82, lineHeight: 1.6 }}>
          Scan the day's payments, check what the scanner read, and send them to the payee sheets in one pass.
        </Typography>
      </Box>
      <Box sx={{ display: "grid", placeItems: "center", p: 3 }}>
        <Paper component="form" onSubmit={go} sx={{ p: 4, width: "100%", maxWidth: 380 }}>
          <Box component="img" src="/capa-logo.png" alt="CAPA" sx={{ width: 64, borderRadius: 1, display: { md: "none" }, mb: 2 }} />
          <Typography variant="h2" sx={{ mb: .5 }}>Sign in to CheckFlow</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>Use your company account, or the local account an admin gave you.</Typography>
          <Stack spacing={2}>
            <TextField label="Username" value={u} onChange={(e) => setU(e.target.value)} autoFocus autoComplete="username" />
            <TextField label="Password" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" />
            {err && <Alert severity="error">{err}</Alert>}
            <Button type="submit" variant="contained" size="large" disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</Button>
          </Stack>
        </Paper>
      </Box>
    </Box>
  );
}
