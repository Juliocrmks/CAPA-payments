import { useEffect, useRef, useState } from "react";
import { Box, Stack, IconButton, Tooltip, ToggleButton, Typography, Tabs, Tab } from "@mui/material";
import ZoomInIcon from "@mui/icons-material/ZoomIn";
import ZoomOutIcon from "@mui/icons-material/ZoomOut";
import FitScreenIcon from "@mui/icons-material/FitScreen";
import RotateRightIcon from "@mui/icons-material/RotateRight";
import SearchIcon from "@mui/icons-material/Search";
import OpenInFullIcon from "@mui/icons-material/OpenInFull";
import LockIcon from "@mui/icons-material/Lock";
import { kindLabel } from "./common";

const LENS = 190;       // magnifier diameter (px)
const LENS_ZOOM = 2.6;  // magnifier power over what's on screen

// The scanned page shown large next to the form: zoom, drag to pan, rotate, and a magnifier lens that follows the cursor.
export default function DocViewer({ pages, height = 560, onFullscreen }) {
  const [i, setI] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [rot, setRot] = useState(0);
  const [lensOn, setLensOn] = useState(false);
  const [lens, setLens] = useState(null);
  const box = useRef(); const img = useRef(); const drag = useRef(null);
  useEffect(() => { setZoom(1); setRot(0); setLens(null); }, [i]);
  useEffect(() => { if (i >= (pages?.length || 0)) setI(0); }, [pages, i]);
  if (!pages?.length) return <Box sx={{ height, display: "grid", placeItems: "center", bgcolor: "#F1EEEB", borderRadius: 1, color: "text.secondary" }}>No document for this payment</Box>;
  const p = pages[Math.min(i, pages.length - 1)];
  const sideways = rot % 180 !== 0;

  const move = (e) => {
    if (drag.current) {   // drag to pan when zoomed in
      box.current.scrollLeft = drag.current.sl - (e.clientX - drag.current.x);
      box.current.scrollTop = drag.current.st - (e.clientY - drag.current.y);
      return;
    }
    if (!lensOn || !img.current || rot) return setLens(null);
    const r = img.current.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    if (x < 0 || y < 0 || x > r.width || y > r.height) return setLens(null);
    const b = box.current.getBoundingClientRect();
    setLens({ x: e.clientX - b.left + box.current.scrollLeft, y: e.clientY - b.top + box.current.scrollTop, fx: x, fy: y, w: r.width, h: r.height });
  };
  const down = (e) => { if (zoom > 1 && !lensOn) drag.current = { x: e.clientX, y: e.clientY, sl: box.current.scrollLeft, st: box.current.scrollTop }; };
  const up = () => { drag.current = null; };

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mb: 0.75 }}>
        {pages.length > 1 ? (
          <Tabs value={Math.min(i, pages.length - 1)} onChange={(_, v) => setI(v)} variant="scrollable" sx={{ flex: 1, minHeight: 36, "& .MuiTab-root": { minHeight: 36, py: 0, px: 1.25, fontSize: 13 } }}>
            {pages.map((pg, k) => <Tab key={pg.id} value={k} label={`${k + 1} · ${kindLabel(pg.kind)}`} />)}
          </Tabs>
        ) : <Typography variant="body2" color="text.secondary" sx={{ flex: 1, pl: 0.5 }}>{kindLabel(p.kind)}</Typography>}
        <Tooltip title="Magnifier: point at anything to read it"><ToggleButton size="small" value="lens" selected={lensOn} onChange={() => { setLensOn(!lensOn); setLens(null); }} aria-label="Magnifier" sx={{ border: 0 }}><SearchIcon fontSize="small" /></ToggleButton></Tooltip>
        <Tooltip title="Zoom out"><span><IconButton size="small" aria-label="Zoom out" disabled={zoom <= 1} onClick={() => setZoom((z) => Math.max(1, z - 0.5))}><ZoomOutIcon fontSize="small" /></IconButton></span></Tooltip>
        <Typography variant="caption" sx={{ width: 38, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>{Math.round(zoom * 100)}%</Typography>
        <Tooltip title="Zoom in"><span><IconButton size="small" aria-label="Zoom in" disabled={zoom >= 4} onClick={() => setZoom((z) => Math.min(4, z + 0.5))}><ZoomInIcon fontSize="small" /></IconButton></span></Tooltip>
        <Tooltip title="Fit"><IconButton size="small" aria-label="Fit to box" onClick={() => { setZoom(1); setRot(0); }}><FitScreenIcon fontSize="small" /></IconButton></Tooltip>
        <Tooltip title="Rotate"><IconButton size="small" aria-label="Rotate" onClick={() => setRot((r) => (r + 90) % 360)}><RotateRightIcon fontSize="small" /></IconButton></Tooltip>
        {onFullscreen && <Tooltip title="Full screen"><IconButton size="small" aria-label="Full screen" onClick={() => onFullscreen(i)}><OpenInFullIcon fontSize="small" /></IconButton></Tooltip>}
      </Stack>
      <Box ref={box} onMouseMove={move} onMouseLeave={() => { setLens(null); up(); }} onMouseDown={down} onMouseUp={up}
        onWheel={(e) => { if (e.ctrlKey || e.metaKey) { e.preventDefault(); setZoom((z) => Math.min(4, Math.max(1, z - Math.sign(e.deltaY) * 0.25))); } }}
        sx={{ position: "relative", height, overflow: zoom > 1 ? "auto" : "hidden", bgcolor: "#2A1A10", borderRadius: 1.5,
          cursor: lensOn ? "none" : zoom > 1 ? (drag.current ? "grabbing" : "grab") : "default", userSelect: "none" }}>
        {p.sensitive ? (
          <Stack alignItems="center" justifyContent="center" spacing={1} sx={{ height: "100%", color: "#fff" }}><LockIcon /><Typography variant="body2">ID or card photo, hidden to protect personal data.</Typography></Stack>
        ) : (
          <Box sx={{ minHeight: "100%", display: "flex", alignItems: zoom > 1 ? "flex-start" : "center", justifyContent: zoom > 1 ? "flex-start" : "center", p: 1 }}>
            <img ref={img} src={p.image} alt={kindLabel(p.kind)} draggable={false}
              style={{ display: "block", background: "#fff", borderRadius: 4, transform: `rotate(${rot}deg)`, transition: "transform .15s",
                ...(zoom > 1 ? { width: `${zoom * 100}%`, maxWidth: "none" } : sideways ? { maxWidth: height - 16, maxHeight: "100%" } : { maxWidth: "100%", maxHeight: height - 16 }) }} />
          </Box>
        )}
        {lens && (
          <Box aria-hidden sx={{ position: "absolute", left: lens.x - LENS / 2, top: lens.y - LENS / 2, width: LENS, height: LENS, borderRadius: "50%", pointerEvents: "none",
            border: "3px solid #fff", boxShadow: "0 6px 24px rgba(0,0,0,.45)", backgroundColor: "#fff", backgroundRepeat: "no-repeat",
            backgroundImage: `url(${p.image})`, backgroundSize: `${lens.w * LENS_ZOOM}px ${lens.h * LENS_ZOOM}px`,
            backgroundPosition: `${-(lens.fx * LENS_ZOOM - LENS / 2)}px ${-(lens.fy * LENS_ZOOM - LENS / 2)}px` }} />
        )}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        {lensOn ? "Magnifier on: point at the page. " : ""}{zoom > 1 ? "Drag to move around. " : ""}Ctrl / ⌘ + scroll to zoom.
      </Typography>
    </Box>
  );
}
