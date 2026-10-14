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

// Divisions get a triangle colour each, used for sheet chips everywhere.
export const sheetColor = { MVC: brand.concrete, RIO: brand.pipe, UPPER: brand.asphalt, VCP: brand.clay };
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
