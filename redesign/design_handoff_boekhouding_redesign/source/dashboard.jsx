/* global React, Ic, Sparkline, BarChart, StatusChip, fmtEuro, fmtDateNL, fmtDateShort, APPDATA */

const Dashboard = ({ setRoute }) => {
  const { FACTUREN, WERKDAGEN, BANKTRX, UITGAVEN, MONTHLY_2026, MONTHLY_2025, UREN_GEBOEKT, UREN_TARGET } = APPDATA;

  const omzet2026 = MONTHLY_2026.reduce((a, b) => a + b, 0);
  const omzet2025_ytd = MONTHLY_2025.slice(0, 4).reduce((a, b) => a + b, 0);
  const kosten2026 = UITGAVEN.reduce((a, u) => a + u.bedrag * (u.zakelijk || 100) / 100, 0);
  const winst = omzet2026 - kosten2026;
  const openstaand = FACTUREN.filter(f => f.status === 'verstuurd').reduce((a, f) => a + f.totaal, 0);
  const verlopen = FACTUREN.filter(f => f.overdue);
  const uncategorizedBank = BANKTRX.filter(t => !t.categorie && !t.matched).length;
  const pendingMatches = BANKTRX.filter(t => t.matched && t.matched.confidence).length;
  const urenPct = (UREN_GEBOEKT / UREN_TARGET) * 100;
  const urenRemaining = UREN_TARGET - UREN_GEBOEKT;
  // days left in year
  const today = new Date('2026-04-17');
  const yearEnd = new Date('2026-12-31');
  const daysLeft = Math.floor((yearEnd - today) / 86400000);
  const urenPerWeekNeeded = urenRemaining / (daysLeft / 7);

  const activity = [
    { when: '14 apr', what: 'Betaling ontvangen van De Linden', amount: 3420, ref: '2026-042' },
    { when: '12 apr', what: 'Factuur 2026-042 verstuurd', amount: 3420 },
    { when: '10 apr', what: 'NHG abonnement geboekt', amount: -285 },
    { when: '08 apr', what: 'Werkdag De Linden (7u)', amount: null },
    { when: '05 apr', what: 'VA IB betaald aan Belastingdienst', amount: -1200 },
    { when: '02 apr', what: 'MacBook Pro geboekt als investering', amount: -2499 },
  ];

  return (
    <div className="content">
      {/* Page head */}
      <div className="page-head">
        <div>
          <h1 className="page-title">Goedemiddag, Rogier.</h1>
          <div className="page-sub">Woensdag 17 april 2026 · week 16 · {daysLeft} dagen tot 31 dec</div>
        </div>
        <div className="row gap-8">
          <button className="btn"><Ic.calendar/> Werkdag<span className="kbd">W</span></button>
          <button className="btn btn-primary"><Ic.plus/> Factuur<span className="kbd">F</span></button>
        </div>
      </div>

      {/* HERO — Urencriterium as the main event */}
      <div className="card" style={{ padding: '28px 32px', marginBottom: 20, position: 'relative', overflow: 'hidden' }}>
        <div className="flex items-center justify-between mb-16" style={{ flexWrap: 'wrap', gap: 20 }}>
          <div>
            <div className="eyebrow mb-8">Urencriterium 2026</div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
              <span className="num" style={{ fontSize: 64, fontWeight: 500, letterSpacing: '-0.03em', lineHeight: 1 }}>{UREN_GEBOEKT.toFixed(0)}</span>
              <span className="num" style={{ fontSize: 24, color: 'var(--ink-4)' }}>/ {UREN_TARGET}</span>
              <span className="chip pos" style={{ marginLeft: 8 }}>{urenPct.toFixed(0)}%</span>
            </div>
            <div className="muted tiny mono mt-8">
              Nog {urenRemaining.toFixed(0)} uur · {urenPerWeekNeeded.toFixed(1)} u/week richting doel · achterwacht niet meegeteld
            </div>
          </div>
          <div style={{ textAlign: 'right', minWidth: 200 }}>
            <div className="eyebrow">Status</div>
            <div className="mono" style={{ fontSize: 13, color: urenPct >= (daysLeft / 365 * 100) ? 'var(--pos)' : 'var(--neg)', marginTop: 6 }}>
              {urenPct >= 15 ? '↗ op schema' : '↘ achter schema'}
            </div>
            <div className="tiny muted mt-4">Verwacht eindjaar: {Math.round(UREN_GEBOEKT / ((today - new Date('2026-01-01'))/86400000) * 365)} u</div>
          </div>
        </div>
        {/* Timeline bar */}
        <div style={{ position: 'relative', height: 8, background: 'var(--bg-sunk)', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ position: 'absolute', inset: 0, width: `${urenPct}%`, background: 'var(--accent)', borderRadius: 4 }}/>
          {/* year-progress marker */}
          <div style={{ position: 'absolute', top: -4, bottom: -4, left: `${((today - new Date('2026-01-01'))/(yearEnd - new Date('2026-01-01')))*100}%`, width: 1, background: 'var(--ink)' }}/>
        </div>
        <div className="flex justify-between mono tiny mt-8" style={{ color: 'var(--ink-4)' }}>
          <span>1 jan</span>
          <span style={{ position: 'relative' }}>vandaag · {((today - new Date('2026-01-01'))/(yearEnd - new Date('2026-01-01'))*100).toFixed(0)}% van jaar</span>
          <span>31 dec · 1.225u</span>
        </div>
      </div>

      {/* HERO metrics row */}
      <div className="hero-grid">
        <div className="hero-cell primary">
          <div className="hero-label"><Ic.arrowUp style={{ width: 12, height: 12 }}/> Omzet 2026</div>
          <div className="hero-value num">{fmtEuro(omzet2026)}</div>
          <div className="hero-sub">
            <span className="chip pos">+{(((omzet2026 - omzet2025_ytd) / omzet2025_ytd) * 100).toFixed(0)}%</span>
            <span>vs {fmtEuro(omzet2025_ytd)} t/m apr vorig jaar</span>
          </div>
          <div className="hero-spark">
            <Sparkline data={MONTHLY_2026.slice(0, 4)} color="var(--accent)" height={60} fill={true}/>
          </div>
        </div>
        <div className="hero-cell">
          <div className="hero-label">Bedrijfswinst</div>
          <div className="hero-value num">{fmtEuro(winst)}</div>
          <div className="hero-sub">na kosten {fmtEuro(kosten2026)}</div>
          <div className="hero-spark">
            <Sparkline data={MONTHLY_2026.slice(0, 4).map(v => v * 0.78)} color="var(--ink-2)" height={44}/>
          </div>
        </div>
        <div className="hero-cell">
          <div className="hero-label">Openstaand</div>
          <div className="hero-value num">{fmtEuro(openstaand)}</div>
          <div className="hero-sub">
            {verlopen.length > 0 && <span className="chip neg">{verlopen.length} verlopen</span>}
            <span className="muted">in {FACTUREN.filter(f => f.status === 'verstuurd').length} facturen</span>
          </div>
          <div className="hero-spark" style={{ display: 'flex', alignItems: 'flex-end', gap: 4 }}>
            {FACTUREN.filter(f => f.status === 'verstuurd').slice(0, 6).map((f, i) => (
              <div key={i} style={{ flex: 1, height: `${Math.min(100, f.totaal / 40)}%`, background: f.overdue ? 'var(--neg)' : 'var(--ink-3)', borderRadius: 2, minHeight: 8 }}/>
            ))}
          </div>
        </div>
      </div>

      {/* Chart + Activity */}
      <div className="dash-grid">
        <div className="card chart-card">
          <div className="chart-head">
            <div>
              <div className="eyebrow">Omzet per maand</div>
              <div className="chart-title mt-4">Realisatie {new Date().getFullYear()} vs vorig jaar</div>
            </div>
            <div className="chart-legend">
              <span><span className="legend-dot" style={{ background: 'var(--accent)' }}/>2026</span>
              <span><span className="legend-dot" style={{ background: 'var(--bg-sunk)', border: '1px solid var(--line)' }}/>2025</span>
            </div>
          </div>
          <BarChart data2026={MONTHLY_2026} data2025={MONTHLY_2025} height={220}/>
        </div>

        <div className="card">
          <div className="flex justify-between items-center mb-16">
            <div>
              <div className="eyebrow">Aandacht vereist</div>
            </div>
          </div>
          <div className="col" style={{ gap: 8 }}>
            {verlopen.length > 0 && (
              <AlertRow
                icon={<Ic.warn/>} severity="neg"
                title={`${verlopen.length} verlopen factuur${verlopen.length > 1 ? 'en' : ''}`}
                sub={`${fmtEuro(verlopen.reduce((a, f) => a + f.totaal, 0))} · oudste ${Math.ceil((today - new Date(verlopen[0].verval))/86400000)} dagen`}
                onClick={() => setRoute('facturen')}
              />
            )}
            {pendingMatches > 0 && (
              <AlertRow
                icon={<Ic.link/>} severity="info"
                title={`${pendingMatches} match-voorstel${pendingMatches > 1 ? 'len' : ''}`}
                sub="Bank ↔ factuur koppeling klaar voor bevestiging"
                onClick={() => setRoute('bank')}
              />
            )}
            {uncategorizedBank > 0 && (
              <AlertRow
                icon={<Ic.bank/>} severity="warn"
                title={`${uncategorizedBank} ongecategoriseerde transactie${uncategorizedBank > 1 ? 's' : ''}`}
                sub="Smart-categorie beschikbaar voor 2"
                onClick={() => setRoute('bank')}
              />
            )}
            <AlertRow
              icon={<Ic.calendar/>} severity=""
              title="3 ongefactureerde werkdagen"
              sub={`${fmtEuro(1840)} klaar om te factureren`}
              onClick={() => setRoute('werkdagen')}
            />
          </div>

          <div className="eyebrow mt-24 mb-12">Recente activiteit</div>
          <div className="activity">
            {activity.map((a, i) => (
              <div key={i} className="activity-row">
                <span className="when">{a.when}</span>
                <span className="what">{a.what}</span>
                <span className={`amount ${a.amount < 0 ? 'neg' : ''}`}>
                  {a.amount !== null ? fmtEuro(a.amount) : '—'}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bottom strip — secondary metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20 }}>
        <MiniStat label="KM gereden" value="1.284 km" sub="€ 295,32 aftrekbaar" icon={<Ic.car/>}/>
        <MiniStat label="Dagen gewerkt" value={`${WERKDAGEN.filter(w => new Date(w.datum) >= new Date('2026-01-01')).length}`} sub="sinds 1 jan" icon={<Ic.calendar/>}/>
        <MiniStat label="Gem. dagtarief" value={fmtEuro(omzet2026 / Math.max(1, WERKDAGEN.filter(w => w.uren > 0).length))} sub="alle klanten" icon={<Ic.arrowUp/>}/>
        <MiniStat label="Belasting prognose" value="terug: € 1.999" sub="o.b.v. 4 maanden" icon={<Ic.tax/>} pos/>
      </div>
    </div>
  );
};

const AlertRow = ({ icon, severity, title, sub, onClick }) => (
  <div onClick={onClick} style={{
    display: 'grid', gridTemplateColumns: '28px 1fr auto', gap: 10, alignItems: 'center',
    padding: '10px 12px', border: '1px solid var(--line)', borderRadius: 8, cursor: 'pointer',
    background: 'var(--bg-elev)',
  }}>
    <div style={{
      width: 24, height: 24, borderRadius: 6, display: 'grid', placeItems: 'center',
      background: severity === 'neg' ? '#fef2f2' : severity === 'warn' ? '#fef3c7' : severity === 'info' ? '#e0e7ff' : 'var(--bg-sunk)',
      color: severity === 'neg' ? '#b91c1c' : severity === 'warn' ? '#92400e' : severity === 'info' ? '#3730a3' : 'var(--ink-3)',
    }}>
      {React.cloneElement(icon, { style: { width: 13, height: 13 } })}
    </div>
    <div>
      <div style={{ fontSize: 13, color: 'var(--ink)' }}>{title}</div>
      <div className="tiny muted mono">{sub}</div>
    </div>
    <Ic.arrowRight style={{ width: 14, height: 14, color: 'var(--ink-4)' }}/>
  </div>
);

const MiniStat = ({ label, value, sub, icon, pos }) => (
  <div className="card" style={{ padding: '16px 18px' }}>
    <div className="flex items-center justify-between mb-8">
      <div className="eyebrow">{label}</div>
      <div style={{ color: 'var(--ink-4)' }}>{React.cloneElement(icon, { style: { width: 14, height: 14 } })}</div>
    </div>
    <div className="num" style={{ fontSize: 22, fontWeight: 500, color: pos ? 'var(--pos)' : 'var(--ink)' }}>{value}</div>
    <div className="tiny muted mono mt-4">{sub}</div>
  </div>
);

window.Dashboard = Dashboard;
