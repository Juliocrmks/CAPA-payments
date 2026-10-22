import { useState } from "react";
import { Box, Paper, Stack, TextField, Button, Typography, Alert, Link } from "@mui/material";
import { api } from "../api";
import { brand } from "../theme";

export default function Login({ onDone }) {
  const [u, setU] = useState(""); const [p, setP] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false); const [sent, setSent] = useState("");
  const ask = async (e) => {
    e?.preventDefault(); setBusy(true); setErr("");
    try { setSent((await api.post("/api/password-reset-request", { login: u })).message); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
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
        <Paper component="form" onSubmit={forgot ? ask : go} sx={{ p: 4, width: "100%", maxWidth: 380 }}>
          <Box component="img" src="/capa-logo.png" alt="CAPA" sx={{ width: 64, borderRadius: 1, display: { md: "none" }, mb: 2 }} />
          <Typography variant="h2" sx={{ mb: .5 }}>{forgot ? "Forgot your password?" : "Sign in to CheckFlow"}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            {forgot ? "Enter your email. An administrator will set a temporary password for you; you'll choose your own when you sign in."
              : "Sign in with your email and password."}</Typography>
          <Stack spacing={2}>
            <TextField label="Email" value={u} onChange={(e) => setU(e.target.value)} autoFocus autoComplete="username" />
            {!forgot && <TextField label="Password" type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" />}
            {err && <Alert severity="error">{err}</Alert>}
            {sent && <Alert severity="success">{sent}</Alert>}
            {forgot ? <Button type="submit" variant="contained" size="large" disabled={busy || !u || !!sent}>{busy ? "Sending…" : "Ask for a reset"}</Button>
              : <Button type="submit" variant="contained" size="large" disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</Button>}
            <Link component="button" type="button" variant="body2" onClick={() => { setForgot(!forgot); setErr(""); setSent(""); }} sx={{ alignSelf: "center" }}>
              {forgot ? "Back to sign in" : "Forgot your password?"}</Link>
          </Stack>
        </Paper>
      </Box>
    </Box>
  );
}
