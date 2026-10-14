import { useCallback, useEffect, useState } from "react";
import { Box, Chip, Dialog, IconButton, Stack, Typography, Tooltip, Snackbar, Alert } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import ZoomInIcon from "@mui/icons-material/ZoomIn";
import ZoomOutIcon from "@mui/icons-material/ZoomOut";
import LockIcon from "@mui/icons-material/Lock";
import { sheetColor, methodColor, inkOn } from "../theme";
import { METHODS } from "../api";

export function SheetChip({ sheet, size = "small" }) {
  if (!sheet) return <Chip size={size} label="No sheet" variant="outlined" color="warning" />;
  const c = sheetColor[sheet] || "#7a6a60";
  return <Chip size={size} label={sheet} sx={{ bgcolor: c, color: inkOn(c), borderRadius: "6px" }} />;
}

export function MethodChip({ method, size = "small" }) {
  const c = methodColor[method] || "#666";
  return <Chip size={size} label={METHODS[method] || method || "?"} variant="outlined"
    sx={{ borderColor: c, color: c, borderRadius: "6px" }} />;
}

// The three CAPA triangles, used as a quiet brand mark next to section titles.
export function Triangles({ size = 9 }) {
  const t = (c) => <Box component="span" sx={{ width: 0, height: 0, display: "inline-block", borderLeft: `${size / 1.6}px solid transparent`,
    borderRight: `${size / 1.6}px solid transparent`, borderBottom: `${size}px solid ${c}`, mx: "2px" }} />;
  return <Box component="span" sx={{ display: "inline-flex", alignItems: "flex-end" }}>{t("#E8961F")}{t("#C83028")}{t("#0068A0")}</Box>;
}

export function Lightbox({ pages, index, onClose }) {
  const [i, setI] = useState(index || 0);
  const [zoom, setZoom] = useState(1);
  useEffect(() => { setI(index || 0); setZoom(1); }, [index, pages]);
  useEffect(() => {
    const k = (e) => {
      if (e.key === "ArrowRight") setI((x) => Math.min(x + 1, pages.length - 1));
      if (e.key === "ArrowLeft") setI((x) => Math.max(x - 1, 0));
    };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  }, [pages]);
  if (!pages || !pages.length) return null;
  const p = pages[i];
  return (
    <Dialog open fullScreen onClose={onClose} PaperProps={{ sx: { bgcolor: "rgba(20,12,8,.96)", border: 0 } }}>
      <Stack direction="row" alignItems="center" sx={{ px: 2, py: 1, color: "#fff" }} spacing={1}>
        <Typography sx={{ flex: 1 }}>Page {i + 1} of {pages.length} · {kindLabel(p.kind)}</Typography>
        <IconButton aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} sx={{ color: "#fff" }}><ZoomOutIcon /></IconButton>
        <IconButton aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(4, z + 0.25))} sx={{ color: "#fff" }}><ZoomInIcon /></IconButton>
        <IconButton aria-label="Close" onClick={onClose} sx={{ color: "#fff" }}><CloseIcon /></IconButton>
      </Stack>
      <Box sx={{ flex: 1, overflow: "auto", display: "flex", justifyContent: "center", alignItems: zoom > 1 ? "flex-start" : "center", p: 2, position: "relative" }}>
        {p.sensitive ? <SensitiveNote /> :
          <img src={p.image} alt={kindLabel(p.kind)} style={{ width: zoom > 1 ? `${zoom * 90}%` : "auto", maxWidth: zoom > 1 ? "none" : "94%", maxHeight: zoom > 1 ? "none" : "86vh", background: "#fff", borderRadius: 6 }} />}
        {i > 0 && <IconButton aria-label="Previous page" onClick={() => setI(i - 1)} sx={navBtn("left")}><ChevronLeftIcon /></IconButton>}
        {i < pages.length - 1 && <IconButton aria-label="Next page" onClick={() => setI(i + 1)} sx={navBtn("right")}><ChevronRightIcon /></IconButton>}
      </Box>
    </Dialog>
  );
}
const navBtn = (side) => ({ position: "fixed", top: "50%", [side]: 12, bgcolor: "rgba(255,255,255,.15)", color: "#fff", "&:hover": { bgcolor: "rgba(255,255,255,.3)" } });

function SensitiveNote() {
  return <Stack alignItems="center" spacing={1} sx={{ color: "#fff", mt: 10 }}><LockIcon fontSize="large" />
    <Typography>ID or card photo. Hidden to protect personal data.</Typography></Stack>;
}

export const kindLabel = (k) => ({ check: "Check", confirmation: "Payment confirmation", receipt: "Receipt slip", bankpost: "Bank posting",
  email: "E-mail", sensitive: "ID / card photo", support: "Supporting page", sheet: "Day sheet printout", other: "Page" }[k] || "Page");

export function Thumbs({ pages, onOpen, height = 92, max = 6 }) {
  if (!pages?.length) return <Box sx={{ height, display: "grid", placeItems: "center", bgcolor: "#f1eeeb", borderRadius: 1, color: "text.secondary", fontSize: 13 }}>No document</Box>;
  return (
    <Stack direction="row" spacing={1} sx={{ overflowX: "auto", pb: 0.5 }}>
      {pages.slice(0, max).map((p, i) => (
        <Tooltip key={p.id} title={kindLabel(p.kind)}>
          <Box component="button" onClick={() => onOpen(i)} aria-label={`Open ${kindLabel(p.kind)}`}
            sx={{ p: 0, border: "1px solid", borderColor: "divider", borderRadius: 1, bgcolor: "#fff", cursor: "zoom-in", flex: "0 0 auto",
              height, width: height * 0.78, overflow: "hidden", "&:focus-visible": { outline: "2px solid", outlineColor: "secondary.main" } }}>
            {p.sensitive ? <Box sx={{ height: "100%", display: "grid", placeItems: "center", color: "text.secondary" }}><LockIcon fontSize="small" /></Box>
              : <img src={p.image} alt="" loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top" }} />}
          </Box>
        </Tooltip>
      ))}
      {pages.length > max && <Box sx={{ alignSelf: "center", color: "text.secondary", fontSize: 13, px: 1 }}>+{pages.length - max}</Box>}
    </Stack>
  );
}

export function useToast() {
  const [t, setT] = useState(null);
  const node = (
    <Snackbar open={!!t} autoHideDuration={t?.sev === "error" ? 7000 : 3500} onClose={() => setT(null)} anchorOrigin={{ vertical: "bottom", horizontal: "center" }}>
      {t ? <Alert severity={t.sev || "success"} variant="filled" onClose={() => setT(null)} sx={{ maxWidth: 560 }}>{t.msg}</Alert> : <span />}
    </Snackbar>
  );
  const show = useCallback((msg, sev) => setT({ msg, sev }), []);
  return [node, show];
}

export function Stat({ label, value, sub, color }) {
  return (
    <Box sx={{ px: 2, py: 1.25, borderLeft: "3px solid", borderColor: color || "primary.main", minWidth: 130 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography sx={{ fontFamily: "Montserrat", fontWeight: 700, fontSize: "1.15rem", fontVariantNumeric: "tabular-nums" }}>{value}</Typography>
      {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
    </Box>
  );
}
