import { createTheme, alpha } from "@mui/material/styles";

// CAPA brand, sampled from the logo: espresso brown field, white wordmark, and the three triangles
// (concrete orange, asphalt red, pipe blue). Brown carries the chrome; the triangles carry meaning.
export const brand = {
  espresso: "#381F12",
  brown: "#5A3420",
  clay: "#8A5A3B",
  concrete: "#E8961F",   // orange triangle  -> attention / needs a look
  asphalt: "#C83028",    // red triangle     -> errors / destructive
  pipe: "#0068A0",       // blue triangle    -> links / info / primary action accent
  ground: "#F4F5F6",     // cool neutral page background (keeps the brown from turning the app beige)
  ink: "#1F1712",
  validated: "#2E7D4F",
};

// Divisions get a colour each, used for sheet chips and charts alike (a payee looks the same everywhere).
// MVC / UPPER / RIO are the logo triangles; VCP is aqua because brand clay fails colour-blind separation next to
// the red (validated with the dataviz palette checker: adjacent and all-pairs pass).
export const sheetColor = { MVC: brand.concrete, RIO: brand.pipe, UPPER: brand.asphalt, VCP: "#1BAF7A" };

// Chart palette for entities without a fixed colour (validated categorical order; never cycled past 8).
export const chartSeries = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
export const chartGray = "#B5AFA9";        // "Other", de-emphasis, sparklines
export const chartGrid = "#ECE8E4";
export const methodChartColor = { check: chartSeries[0], cash: chartSeries[1], card: chartSeries[2], ach: chartSeries[3], wire: chartSeries[4] };

// Ink or white text on a coloured fill, whichever reads better.
export function inkOn(hex) {
  const n = parseInt(hex.slice(1), 16), c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  const L = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  return (L + 0.05) / 0.05 > 1.05 / (L + 0.05) ? "#1F1712" : "#fff";
}
export const methodColor = { check: brand.brown, cash: brand.validated, card: brand.pipe, ach: "#4B5FA8", wire: "#6B4E9B" };

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: brand.brown, dark: brand.espresso, contrastText: "#fff" },
    secondary: { main: brand.pipe },
    warning: { main: brand.concrete, contrastText: "#2b1a00" },
    error: { main: brand.asphalt },
    success: { main: brand.validated },
    info: { main: brand.pipe },
    background: { default: brand.ground, paper: "#fff" },
    text: { primary: brand.ink, secondary: "#5f5650" },
    divider: "#E3DFDB",
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, sans-serif",
    h1: { fontFamily: "Montserrat, Inter, sans-serif", fontWeight: 700, fontSize: "1.75rem", letterSpacing: "-0.01em" },
    h2: { fontFamily: "Montserrat, Inter, sans-serif", fontWeight: 700, fontSize: "1.3rem" },
    h3: { fontFamily: "Montserrat, Inter, sans-serif", fontWeight: 600, fontSize: "1.05rem" },
    button: { textTransform: "none", fontWeight: 600 },
    body2: { fontSize: "0.875rem" },
  },
  components: {
    MuiAppBar: { styleOverrides: { root: { backgroundColor: brand.espresso, boxShadow: "none" } } },
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: "1px solid #E3DFDB" } } },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiTextField: { defaultProps: { size: "small", fullWidth: true } },
    MuiSelect: { defaultProps: { size: "small" } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiTableCell: { styleOverrides: { root: { fontVariantNumeric: "tabular-nums" }, head: { fontWeight: 700, color: "#5f5650", whiteSpace: "nowrap" } } },
    MuiTooltip: { defaultProps: { arrow: true } },
    MuiTab: { styleOverrides: { root: { minHeight: 48, fontWeight: 600 } } },
    MuiOutlinedInput: { styleOverrides: { root: { backgroundColor: "#fff" } } },
  },
});
theme.components.MuiFormLabel = { styleOverrides: { root: { fontSize: "0.82rem" } } };
export const warnBg = alpha(brand.concrete, 0.12);
export default theme;
