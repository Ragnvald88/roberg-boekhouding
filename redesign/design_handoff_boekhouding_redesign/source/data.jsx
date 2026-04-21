/* global React */
// Shared data, icons, formatters for Boekhouding redesign

const { useState, useEffect, useRef, useMemo, createContext, useContext } = React;

// ============ FORMATTERS ============
const fmtEuro = (n, decimals = 0) => {
  const s = Math.abs(n).toLocaleString('nl-NL', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return (n < 0 ? '-' : '') + '€\u00A0' + s;
};
const fmtEuroPlain = (n) => n.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtDateNL = (iso) => {
  const [y, m, d] = iso.split('-');
  return `${d}-${m}-${y}`;
};
const fmtDateShort = (iso) => {
  const [, m, d] = iso.split('-');
  const months = ['jan', 'feb', 'mrt', 'apr', 'mei', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec'];
  return `${parseInt(d)} ${months[parseInt(m) - 1]}`;
};

window.fmtEuro = fmtEuro;
window.fmtEuroPlain = fmtEuroPlain;
window.fmtDateNL = fmtDateNL;
window.fmtDateShort = fmtDateShort;

// ============ ICONS (single-line stroke, minimal) ============
const Ic = {
  dashboard: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/></svg>,
  calendar: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><rect x="2" y="3" width="12" height="11" rx="1.5"/><path d="M2 6h12M5 2v3M11 2v3"/></svg>,
  invoice: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M3 2h10v12l-2-1-2 1-2-1-2 1-2-1V2z"/><path d="M6 6h4M6 9h4"/></svg>,
  cost: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M3 5h10l-1 9H4L3 5z"/><path d="M6 5V3a2 2 0 014 0v2"/></svg>,
  bank: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M2 6l6-3.5L14 6M3 6v6M13 6v6M6 6v6M10 6v6M2 13h12"/></svg>,
  docs: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M3 2h6l3 3v9H3V2z"/><path d="M9 2v3h3"/></svg>,
  archive: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><rect x="2" y="3" width="12" height="3"/><path d="M3 6v8h10V6M6 9h4"/></svg>,
  tax: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M3 2h10v12H3V2z"/><path d="M6 5l4 6M6 11l4-6"/><circle cx="6" cy="5" r="0.8"/><circle cx="10" cy="11" r="0.8"/></svg>,
  users: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><circle cx="6" cy="6" r="2.5"/><path d="M2 13c0-2.2 1.8-4 4-4s4 1.8 4 4"/><circle cx="11" cy="5" r="2"/><path d="M10 10c2-0.3 4 1 4 3"/></svg>,
  settings: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M2 5h8M12 5h2M2 11h2M6 11h8"/><circle cx="11" cy="5" r="1.5"/><circle cx="5" cy="11" r="1.5"/></svg>,
  plus: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" {...p}><path d="M8 3v10M3 8h10"/></svg>,
  search: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>,
  arrowUp: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" {...p}><path d="M4 9l4-4 4 4M8 5v8"/></svg>,
  arrowDown: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" {...p}><path d="M4 7l4 4 4-4M8 11V3"/></svg>,
  arrowRight: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M3 8h10M9 4l4 4-4 4"/></svg>,
  clock: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><circle cx="8" cy="8" r="6"/><path d="M8 5v3l2 2"/></svg>,
  check: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" {...p}><path d="M3 8l3.5 3.5L13 5"/></svg>,
  x: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" {...p}><path d="M4 4l8 8M4 12l8-8"/></svg>,
  warn: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M8 2l6 11H2L8 2z"/><path d="M8 7v3M8 11.5v0.5"/></svg>,
  car: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M2 10V8l1.5-4h9L14 8v2"/><rect x="2" y="10" width="12" height="3" rx="1"/><circle cx="5" cy="13" r="1"/><circle cx="11" cy="13" r="1"/></svg>,
  upload: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M8 11V2M4 6l4-4 4 4M2 11v2a1 1 0 001 1h10a1 1 0 001-1v-2"/></svg>,
  link: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M6 10l4-4M6 4H4a3 3 0 100 6h2M10 12h2a3 3 0 100-6h-2"/></svg>,
  sparkles: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" {...p}><path d="M5 2v3M3.5 3.5h3M11 9v4M9 11h4M8 4l1.5 3L12 8l-2.5 1L8 12l-1.5-3L4 8l2.5-1L8 4z"/></svg>,
  inbox: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M2 9l2-6h8l2 6v4a1 1 0 01-1 1H3a1 1 0 01-1-1V9z"/><path d="M2 9h3l1 2h4l1-2h3"/></svg>,
  menu: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M3 4h10M3 8h10M3 12h10"/></svg>,
  more: (p) => <svg viewBox="0 0 16 16" fill="currentColor" {...p}><circle cx="4" cy="8" r="1"/><circle cx="8" cy="8" r="1"/><circle cx="12" cy="8" r="1"/></svg>,
  filter: (p) => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" {...p}><path d="M2 3h12l-4.5 6v4l-3 1V9L2 3z"/></svg>,
};
window.Ic = Ic;

// ============ DATA ============

const KLANTEN = [
  { id: 1, naam: 'Huisartsenpraktijk De Linden', plaats: 'Amsterdam', tarief: 95, km: 12, email: 'info@delinden.nl' },
  { id: 2, naam: 'Medisch Centrum Westerpark', plaats: 'Amsterdam', tarief: 92, km: 8, email: 'praktijk@mcwp.nl' },
  { id: 3, naam: 'HAP Noord-Holland', plaats: 'Zaandam', tarief: 110, km: 24, email: 'planning@hapnh.nl' },
  { id: 4, naam: 'Praktijk Van der Berg', plaats: 'Haarlem', tarief: 88, km: 18, email: 'info@pvdb.nl' },
  { id: 5, naam: 'Gezondheidscentrum De Pijp', plaats: 'Amsterdam', tarief: 94, km: 6, email: 'info@gcdepijp.nl' },
  { id: 6, naam: 'Spoedpost Amstelland', plaats: 'Amstelveen', tarief: 115, km: 14, email: 'admin@spoedpost-amstelland.nl' },
];

// Generate werkdagen: ~18/month for current year
const genWerkdagen = () => {
  const rows = [];
  let id = 1;
  const codes = [
    { code: 'DAG', label: 'Waarneming dagpraktijk', norm: true },
    { code: 'DAG', label: 'Waarneming dagpraktijk', norm: true },
    { code: 'DAG', label: 'Waarneming dagpraktijk', norm: true },
    { code: 'ANW', label: 'ANW dienst', norm: true },
    { code: 'ACH', label: 'Achterwacht', norm: false },
  ];
  for (let m = 1; m <= 4; m++) {
    for (let d = 1; d <= 28; d++) {
      if (Math.random() > 0.55) continue;
      const k = KLANTEN[Math.floor(Math.random() * KLANTEN.length)];
      const c = codes[Math.floor(Math.random() * codes.length)];
      const uren = c.norm ? (c.code === 'ANW' ? 10 + Math.random() * 4 : 6 + Math.random() * 3) : 0;
      const factuurnummer = m < 4 || (m === 4 && d < 10) ? `2026-${String(Math.floor(id / 3) + 10).padStart(3, '0')}` : '';
      rows.push({
        id: id++,
        datum: `2026-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`,
        klant_id: k.id,
        klant_naam: k.naam,
        code: c.code,
        activiteit: c.label,
        locatie: k.plaats,
        uren: Math.round(uren * 4) / 4,
        km: c.code === 'ACH' ? 0 : k.km,
        tarief: c.code === 'ANW' ? k.tarief + 20 : k.tarief,
        km_tarief: c.code === 'ANW' ? 0 : 0.23,
        factuurnummer,
        urennorm: c.norm,
      });
    }
  }
  return rows.sort((a, b) => b.datum.localeCompare(a.datum));
};
const WERKDAGEN = genWerkdagen();

const FACTUREN = [
  { id: 1, nummer: '2026-042', klant_id: 1, klant_naam: 'Huisartsenpraktijk De Linden', datum: '2026-04-08', totaal: 3420, status: 'verstuurd', verval: '2026-04-22', type: 'factuur', uren: 34, dagen: 5 },
  { id: 2, nummer: '2026-041', klant_id: 3, klant_naam: 'HAP Noord-Holland', datum: '2026-04-01', totaal: 2860, status: 'betaald', betaald: '2026-04-12', verval: '2026-04-15', type: 'factuur', uren: 24, dagen: 3 },
  { id: 3, nummer: '2026-040', klant_id: 2, klant_naam: 'Medisch Centrum Westerpark', datum: '2026-03-28', totaal: 2208, status: 'betaald', betaald: '2026-04-02', verval: '2026-04-11', type: 'factuur', uren: 22, dagen: 3 },
  { id: 4, nummer: '2026-039', klant_id: 4, klant_naam: 'Praktijk Van der Berg', datum: '2026-03-20', totaal: 1584, status: 'verstuurd', verval: '2026-04-03', type: 'factuur', uren: 16, dagen: 2, overdue: true },
  { id: 5, nummer: '2026-038', klant_id: 5, klant_naam: 'Gezondheidscentrum De Pijp', datum: '2026-03-18', totaal: 1692, status: 'betaald', betaald: '2026-03-30', verval: '2026-04-01', type: 'factuur', uren: 18, dagen: 2 },
  { id: 6, nummer: '2026-037', klant_id: 6, klant_naam: 'Spoedpost Amstelland', datum: '2026-03-15', totaal: 4600, status: 'betaald', betaald: '2026-03-28', verval: '2026-03-29', type: 'anw', uren: 40, dagen: 4 },
  { id: 7, nummer: '2026-036', klant_id: 1, klant_naam: 'Huisartsenpraktijk De Linden', datum: '2026-03-10', totaal: 2565, status: 'verstuurd', verval: '2026-03-24', type: 'factuur', uren: 27, dagen: 4, overdue: true },
  { id: 8, nummer: '2026-CON', klant_id: 2, klant_naam: 'Medisch Centrum Westerpark', datum: '2026-04-15', totaal: 1840, status: 'concept', verval: '2026-04-29', type: 'factuur', uren: 20, dagen: 3 },
];

const UITGAVEN = [
  { id: 1, datum: '2026-04-10', categorie: 'Vakliteratuur', omschrijving: 'NHG abonnement 2026', bedrag: 285, investering: false, bon: true },
  { id: 2, datum: '2026-04-08', categorie: 'Reiskosten', omschrijving: 'Parkeren Amsterdam (4x)', bedrag: 24, investering: false, bon: true },
  { id: 3, datum: '2026-04-02', categorie: 'Kantoor', omschrijving: 'MacBook Pro M4', bedrag: 2499, investering: true, levensduur: 5, zakelijk: 80, bon: true },
  { id: 4, datum: '2026-03-28', categorie: 'Telefoon', omschrijving: 'KPN zakelijk', bedrag: 52, investering: false, bon: true },
  { id: 5, datum: '2026-03-22', categorie: 'Verzekering', omschrijving: 'SPH pensioenpremie Q1', bedrag: 1850, investering: false, bon: true },
  { id: 6, datum: '2026-03-20', categorie: 'Nascholing', omschrijving: 'Congres Huisartsen Utrecht', bedrag: 480, investering: false, bon: true },
  { id: 7, datum: '2026-03-12', categorie: 'Representatie', omschrijving: 'Lunch klant (80% aftrek)', bedrag: 68, investering: false, bon: true },
  { id: 8, datum: '2026-03-05', categorie: 'Software', omschrijving: 'Microsoft 365 jaar', bedrag: 99, investering: false, bon: false },
];

const BANKTRX = [
  { id: 1, datum: '2026-04-14', bedrag: 3420, tegenpartij: 'Huisartsenpraktijk De Linden', omschrijving: '2026-042 factuurnr', categorie: '', matched: { type: 'factuur', id: 1, confidence: 'high' } },
  { id: 2, datum: '2026-04-12', bedrag: 2860, tegenpartij: 'HAP Noord-Holland', omschrijving: 'Betaling fact 2026-041', categorie: 'Omzet', koppeling: '2026-041' },
  { id: 3, datum: '2026-04-10', bedrag: -285, tegenpartij: 'NHG', omschrijving: 'Abonnement 2026', categorie: 'Vakliteratuur' },
  { id: 4, datum: '2026-04-08', bedrag: -24, tegenpartij: 'Q-Park Amsterdam', omschrijving: 'Parkeerkosten', categorie: '' },
  { id: 5, datum: '2026-04-05', bedrag: -1200, tegenpartij: 'Belastingdienst', omschrijving: 'VA IB 2026 — 7208.33.234.V.26', categorie: 'Belasting' },
  { id: 6, datum: '2026-04-02', bedrag: 2208, tegenpartij: 'MC Westerpark BV', omschrijving: '2026-040', categorie: 'Omzet', koppeling: '2026-040' },
  { id: 7, datum: '2026-04-02', bedrag: -2499, tegenpartij: 'Apple Store Online', omschrijving: 'MacBook Pro 14', categorie: '' },
  { id: 8, datum: '2026-03-30', bedrag: 1692, tegenpartij: 'GC De Pijp', omschrijving: '20260038', categorie: 'Omzet', koppeling: '2026-038' },
  { id: 9, datum: '2026-03-28', bedrag: -52, tegenpartij: 'KPN BV', omschrijving: 'Mobiel abo', categorie: 'Telefoon' },
  { id: 10, datum: '2026-03-28', bedrag: 4600, tegenpartij: 'Spoedpost Amstelland', omschrijving: 'ANW diensten maart', categorie: 'Omzet', koppeling: '2026-037' },
  { id: 11, datum: '2026-03-22', bedrag: -1850, tegenpartij: 'SPH', omschrijving: 'Pensioenpremie Q1', categorie: 'Verzekering' },
  { id: 12, datum: '2026-03-20', bedrag: -68, tegenpartij: 'Restaurant Toscanini', omschrijving: 'Lunch', categorie: '' },
];

// Monthly revenue 2026 & 2025
const MONTHLY_2026 = [8200, 7400, 10100, 4500, 0, 0, 0, 0, 0, 0, 0, 0];
const MONTHLY_2025 = [6800, 7200, 8500, 9200, 7800, 5400, 2100, 4200, 8800, 9600, 10200, 11400];

// Urencriterium
const UREN_GEBOEKT = WERKDAGEN.filter(w => w.urennorm).reduce((s, w) => s + w.uren, 0);
const UREN_TARGET = 1225;

window.APPDATA = {
  KLANTEN, WERKDAGEN, FACTUREN, UITGAVEN, BANKTRX,
  MONTHLY_2026, MONTHLY_2025, UREN_GEBOEKT, UREN_TARGET,
};

// ============ SPARKLINE ============
const Sparkline = ({ data, color, height = 44, fill = false }) => {
  const w = 220, h = height, pad = 2;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = pad + (1 - (v - min) / range) * (h - pad * 2);
    return [x, y];
  });
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const fillD = fill ? `${d} L${pts[pts.length-1][0]} ${h} L${pts[0][0]} ${h} Z` : '';
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      {fill && <path d={fillD} fill={color} opacity="0.08"/>}
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
};
window.Sparkline = Sparkline;

// ============ BAR CHART ============
const BarChart = ({ data2026, data2025, height = 240 }) => {
  const months = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'];
  const max = Math.max(...data2026, ...data2025, 1);
  const niceMax = Math.ceil(max / 2500) * 2500;
  const gridLines = 4;
  return (
    <div style={{ position: 'relative', height }}>
      {/* Y-axis grid */}
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', pointerEvents: 'none' }}>
        {Array.from({ length: gridLines + 1 }).map((_, i) => {
          const val = niceMax * (1 - i / gridLines);
          return (
            <div key={i} style={{ borderTop: i === gridLines ? 'none' : '1px dashed var(--line)', position: 'relative', height: 0 }}>
              <span style={{ position: 'absolute', left: 0, top: -8, fontFamily: 'var(--f-mono)', fontSize: 10, color: 'var(--ink-4)' }}>
                €{(val / 1000).toFixed(0)}k
              </span>
            </div>
          );
        })}
      </div>
      {/* Bars */}
      <div style={{ position: 'absolute', left: 36, right: 0, top: 0, bottom: 18, display: 'flex', alignItems: 'flex-end', gap: 4 }}>
        {months.map((m, i) => (
          <div key={m} style={{ flex: 1, display: 'flex', gap: 2, height: '100%', alignItems: 'flex-end' }}>
            <div style={{
              flex: 1,
              height: `${(data2025[i] / niceMax) * 100}%`,
              background: 'var(--bg-sunk)',
              border: '1px solid var(--line)',
              borderBottom: 'none',
              borderRadius: '3px 3px 0 0',
            }} title={`2025 ${m}: ${fmtEuro(data2025[i])}`}/>
            <div style={{
              flex: 1,
              height: `${(data2026[i] / niceMax) * 100}%`,
              background: data2026[i] ? 'var(--accent)' : 'transparent',
              borderRadius: '3px 3px 0 0',
              opacity: data2026[i] ? 1 : 0,
            }} title={`2026 ${m}: ${fmtEuro(data2026[i])}`}/>
          </div>
        ))}
      </div>
      {/* X-axis labels */}
      <div style={{ position: 'absolute', left: 36, right: 0, bottom: 0, display: 'flex', gap: 4 }}>
        {months.map(m => (
          <div key={m} style={{ flex: 1, textAlign: 'center', fontFamily: 'var(--f-mono)', fontSize: 10, color: 'var(--ink-4)', textTransform: 'uppercase' }}>{m}</div>
        ))}
      </div>
    </div>
  );
};
window.BarChart = BarChart;

// ============ STATUS CHIP ============
const StatusChip = ({ status, overdue }) => {
  if (overdue) return <span className="chip neg">verlopen</span>;
  if (status === 'concept') return <span className="chip">concept</span>;
  if (status === 'verstuurd') return <span className="chip info">verstuurd</span>;
  if (status === 'betaald') return <span className="chip pos">betaald</span>;
  return <span className="chip">{status}</span>;
};
window.StatusChip = StatusChip;
