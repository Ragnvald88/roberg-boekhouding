/* global React, Ic, StatusChip, fmtEuro, fmtDateNL, fmtDateShort, APPDATA */

const { useState, useMemo } = React;
/* shadow-safe: data.jsx destructures useState from React in top scope too; rename is via prefixing logic below — actually, Babel errors on redeclare at script level. data.jsx is the offender. */

// ============ WERKDAGEN ============
const Werkdagen = ({ setRoute }) => {
  const [selected, setSelected] = useState(new Set());
  const [filter, setFilter] = useState('all');
  const rows = useMemo(() => {
    const r = APPDATA.WERKDAGEN;
    if (filter === 'uninvoiced') return r.filter(w => !w.factuurnummer);
    if (filter === 'anw') return r.filter(w => w.code === 'ANW');
    return r;
  }, [filter]);

  const toggle = (id) => {
    const n = new Set(selected);
    n.has(id) ? n.delete(id) : n.add(id);
    setSelected(n);
  };
  const selTotal = rows.filter(r => selected.has(r.id)).reduce((a, r) => a + r.uren * r.tarief + r.km * r.km_tarief, 0);
  const selUren = rows.filter(r => selected.has(r.id)).reduce((a, r) => a + r.uren, 0);

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1 className="page-title">Werkdagen</h1>
          <div className="page-sub">{APPDATA.WERKDAGEN.length} dagen geregistreerd · {APPDATA.UREN_GEBOEKT.toFixed(0)} uur telt voor urencriterium</div>
        </div>
        <div className="row gap-8">
          <button className="btn"><Ic.upload/> Import CSV</button>
          <button className="btn btn-primary"><Ic.plus/> Nieuwe werkdag<span className="kbd">N</span></button>
        </div>
      </div>

      {/* Filter strip */}
      <div className="row gap-8 mb-20" style={{ flexWrap: 'wrap' }}>
        <div className="seg" style={{ border: '1px solid var(--line)', borderRadius: 7, display: 'flex', overflow: 'hidden' }}>
          {[
            { k: 'all', l: 'Alle' },
            { k: 'uninvoiced', l: 'Ongefactureerd' },
            { k: 'anw', l: 'ANW' },
          ].map(f => (
            <button key={f.k} onClick={() => setFilter(f.k)} className={filter === f.k ? 'on' : ''} style={{
              padding: '7px 14px', border: 0, borderRight: '1px solid var(--line)',
              background: filter === f.k ? 'var(--ink)' : 'var(--bg-elev)',
              color: filter === f.k ? 'var(--bg)' : 'var(--ink-2)',
              fontSize: 12, cursor: 'pointer', fontFamily: 'var(--f-mono)',
            }}>{f.l}</button>
          ))}
        </div>
        <select className="input" style={{ width: 160 }}>
          <option>Alle klanten</option>
          {APPDATA.KLANTEN.map(k => <option key={k.id}>{k.naam}</option>)}
        </select>
        <select className="input" style={{ width: 120 }}><option>2026</option><option>2025</option></select>
        <div style={{ marginLeft: 'auto', fontFamily: 'var(--f-mono)', fontSize: 12, color: 'var(--ink-3)' }}>
          {rows.length} rijen · ∑ {rows.reduce((a, r) => a + r.uren, 0).toFixed(1)} u
        </div>
      </div>

      {/* Selection action bar */}
      {selected.size > 0 && (
        <div style={{
          position: 'sticky', top: 60, zIndex: 5,
          background: 'var(--ink)', color: 'var(--bg)',
          padding: '10px 20px', borderRadius: 10, marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 16, boxShadow: 'var(--shadow-md)',
        }}>
          <span className="mono" style={{ fontSize: 13 }}>{selected.size} geselecteerd</span>
          <span className="mono" style={{ fontSize: 12, opacity: 0.7 }}>{selUren.toFixed(1)} uur · {fmtEuro(selTotal)}</span>
          <div style={{ flex: 1 }}/>
          <button onClick={() => setRoute('factuur_new')} className="btn btn-accent"><Ic.invoice/> Maak factuur</button>
          <button className="btn" style={{ background: 'transparent', color: 'var(--bg)', borderColor: 'var(--ink-3)' }} onClick={() => setSelected(new Set())}>
            <Ic.x/>
          </button>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th>Datum</th>
              <th>Klant</th>
              <th>Code</th>
              <th className="num">Uren</th>
              <th className="num">Km</th>
              <th className="num">Tarief</th>
              <th className="num">Bedrag</th>
              <th>Factuur</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 24).map(r => {
              const bedrag = r.uren * r.tarief + r.km * r.km_tarief;
              return (
                <tr key={r.id} onClick={() => toggle(r.id)} className={selected.has(r.id) ? 'selected' : ''}>
                  <td><input type="checkbox" checked={selected.has(r.id)} onChange={() => toggle(r.id)}/></td>
                  <td className="mono" style={{ fontSize: 12 }}>{fmtDateNL(r.datum)}</td>
                  <td>
                    <div>{r.klant_naam}</div>
                    <div className="tiny muted">{r.locatie}</div>
                  </td>
                  <td>
                    <span className={`chip ${r.code === 'ANW' ? 'info' : r.code === 'ACH' ? '' : 'pos'}`}>{r.code}</span>
                  </td>
                  <td className="num">{r.uren.toFixed(2)}</td>
                  <td className="num">{r.km}</td>
                  <td className="num">{fmtEuro(r.tarief)}</td>
                  <td className="num">{fmtEuro(bedrag)}</td>
                  <td className="mono" style={{ fontSize: 11, color: r.factuurnummer ? 'var(--ink-3)' : 'var(--neg)' }}>
                    {r.factuurnummer || '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ============ FACTUREN ============
const Facturen = ({ setRoute }) => {
  const [filter, setFilter] = useState('all');
  const [q, setQ] = useState('');
  const { FACTUREN } = APPDATA;
  const rows = useMemo(() => {
    let r = FACTUREN;
    if (filter === 'open') r = r.filter(f => f.status === 'verstuurd');
    if (filter === 'verlopen') r = r.filter(f => f.overdue);
    if (filter === 'concept') r = r.filter(f => f.status === 'concept');
    if (q) r = r.filter(f => f.klant_naam.toLowerCase().includes(q.toLowerCase()) || f.nummer.includes(q));
    return r;
  }, [filter, q]);

  const totals = {
    all: FACTUREN.reduce((a, f) => a + f.totaal, 0),
    open: FACTUREN.filter(f => f.status === 'verstuurd').reduce((a, f) => a + f.totaal, 0),
    verlopen: FACTUREN.filter(f => f.overdue).reduce((a, f) => a + f.totaal, 0),
    concept: FACTUREN.filter(f => f.status === 'concept').reduce((a, f) => a + f.totaal, 0),
  };

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1 className="page-title">Facturen</h1>
          <div className="page-sub">{FACTUREN.length} facturen in 2026 · {fmtEuro(totals.all)} totaal</div>
        </div>
        <div className="row gap-8">
          <button className="btn"><Ic.upload/> Importeer PDF</button>
          <button className="btn btn-primary" onClick={() => setRoute('factuur_new')}><Ic.plus/> Nieuwe factuur<span className="kbd">F</span></button>
        </div>
      </div>

      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, background: 'var(--line)', border: '1px solid var(--line)', borderRadius: 10, overflow: 'hidden', marginBottom: 20 }}>
        {[
          { k: 'all', l: 'Gefactureerd', v: totals.all, sub: `${FACTUREN.length} facturen` },
          { k: 'open', l: 'Openstaand', v: totals.open, sub: `${FACTUREN.filter(f => f.status === 'verstuurd').length} verstuurd`, color: 'var(--info)' },
          { k: 'verlopen', l: 'Verlopen', v: totals.verlopen, sub: `${FACTUREN.filter(f => f.overdue).length} > 14 dagen`, color: 'var(--neg)' },
          { k: 'concept', l: 'Concept', v: totals.concept, sub: `${FACTUREN.filter(f => f.status === 'concept').length} concept`, color: 'var(--ink-3)' },
        ].map(k => (
          <button key={k.k} onClick={() => setFilter(k.k)} style={{
            padding: '18px 20px', border: 0, textAlign: 'left', cursor: 'pointer',
            background: filter === k.k ? 'var(--bg-sunk)' : 'var(--bg-elev)',
            borderBottom: filter === k.k ? `2px solid ${k.color || 'var(--ink)'}` : '2px solid transparent',
          }}>
            <div className="eyebrow">{k.l}</div>
            <div className="num" style={{ fontSize: 22, fontWeight: 500, marginTop: 6, color: k.color || 'var(--ink)' }}>{fmtEuro(k.v)}</div>
            <div className="tiny muted mono mt-4">{k.sub}</div>
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="row gap-8 mb-20">
        <div style={{ flex: 1, position: 'relative' }}>
          <Ic.search style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', width: 14, height: 14, color: 'var(--ink-4)' }}/>
          <input className="input" placeholder="Zoek op klant of factuurnummer…" style={{ paddingLeft: 34 }} value={q} onChange={e => setQ(e.target.value)}/>
        </div>
        <select className="input" style={{ width: 140 }}><option>Alle types</option><option>Dagpraktijk</option><option>ANW</option></select>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Factuur</th>
              <th>Klant</th>
              <th>Datum</th>
              <th>Vervalt</th>
              <th>Status</th>
              <th className="num">Uren</th>
              <th className="num">Bedrag</th>
              <th style={{ width: 40 }}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(f => (
              <tr key={f.id}>
                <td className="mono" style={{ color: 'var(--ink)' }}>{f.nummer}</td>
                <td>
                  <div>{f.klant_naam}</div>
                  {f.type === 'anw' && <div className="tiny muted mono">ANW · geïmporteerd</div>}
                </td>
                <td className="mono" style={{ fontSize: 12 }}>{fmtDateNL(f.datum)}</td>
                <td className="mono" style={{ fontSize: 12, color: f.overdue ? 'var(--neg)' : 'var(--ink-3)' }}>{fmtDateNL(f.verval)}</td>
                <td><StatusChip status={f.status} overdue={f.overdue}/></td>
                <td className="num">{f.uren}</td>
                <td className="num" style={{ fontWeight: 500 }}>{fmtEuro(f.totaal)}</td>
                <td><button className="btn btn-ghost" style={{ padding: 4 }}><Ic.more style={{ width: 14, height: 14 }}/></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ============ KOSTEN (smart inbox) ============
const Kosten = () => {
  const [dragHot, setDragHot] = useState(false);
  const { UITGAVEN } = APPDATA;
  const total = UITGAVEN.reduce((a, u) => a + u.bedrag * (u.zakelijk || 100) / 100, 0);

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1 className="page-title">Kosten</h1>
          <div className="page-sub">{UITGAVEN.length} uitgaven in 2026 · {fmtEuro(total)} zakelijk aftrekbaar</div>
        </div>
        <div className="row gap-8">
          <button className="btn"><Ic.upload/> Import archief</button>
          <button className="btn btn-primary"><Ic.plus/> Nieuwe uitgave</button>
        </div>
      </div>

      {/* Smart inbox dropzone */}
      <div
        className={`dropzone ${dragHot ? 'hot' : ''}`}
        style={{ marginBottom: 24 }}
        onDragOver={e => { e.preventDefault(); setDragHot(true); }}
        onDragLeave={() => setDragHot(false)}
        onDrop={e => { e.preventDefault(); setDragHot(false); }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: 'var(--accent-soft)', color: 'var(--accent-ink)', display: 'grid', placeItems: 'center' }}>
            <Ic.sparkles style={{ width: 18, height: 18 }}/>
          </div>
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 14, color: 'var(--ink)', fontWeight: 500 }}>Smart inbox — sleep bonnetjes hierheen</div>
            <div className="tiny muted mono mt-4">PDF, JPG of PNG · auto-categorisering op basis van leveranciersnaam</div>
          </div>
          <div style={{ flex: 1, minWidth: 80 }}/>
          <button className="btn btn-accent"><Ic.upload/> Of kies bestand</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 20 }}>
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Datum</th>
                <th>Categorie</th>
                <th>Omschrijving</th>
                <th className="num">Bedrag</th>
                <th>Bon</th>
              </tr>
            </thead>
            <tbody>
              {UITGAVEN.map(u => (
                <tr key={u.id}>
                  <td className="mono" style={{ fontSize: 12 }}>{fmtDateNL(u.datum)}</td>
                  <td><span className="chip">{u.categorie}</span></td>
                  <td>
                    <div>{u.omschrijving}</div>
                    {u.investering && <div className="tiny muted mono">Investering · {u.levensduur}j afschr. · {u.zakelijk}% zakelijk</div>}
                  </td>
                  <td className="num">{fmtEuro(u.bedrag)}</td>
                  <td>
                    {u.bon ? <span style={{ color: 'var(--pos)' }}><Ic.check style={{ width: 14, height: 14 }}/></span> :
                      <span style={{ color: 'var(--neg)' }} className="tiny mono">ontbreekt</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Category breakdown */}
        <div className="card">
          <div className="eyebrow mb-12">Per categorie</div>
          {Object.entries(UITGAVEN.reduce((acc, u) => {
            acc[u.categorie] = (acc[u.categorie] || 0) + u.bedrag * (u.zakelijk || 100) / 100;
            return acc;
          }, {})).sort((a, b) => b[1] - a[1]).map(([cat, sum]) => {
            const pct = (sum / total) * 100;
            return (
              <div key={cat} style={{ marginBottom: 10 }}>
                <div className="flex justify-between mb-4">
                  <span style={{ fontSize: 12 }}>{cat}</span>
                  <span className="mono tiny">{fmtEuro(sum)}</span>
                </div>
                <div style={{ height: 4, background: 'var(--bg-sunk)', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${pct}%`, background: 'var(--accent)' }}/>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// ============ BANK ============
const Bank = () => {
  const { BANKTRX, FACTUREN } = APPDATA;
  const [selected, setSelected] = useState(null);
  const unmatched = BANKTRX.filter(t => t.matched && !t.koppeling);
  const uncategorized = BANKTRX.filter(t => !t.categorie && !t.matched);

  const saldo = BANKTRX.reduce((a, t) => a + t.bedrag, 0);

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1 className="page-title">Bank</h1>
          <div className="page-sub">{BANKTRX.length} transacties · saldo {fmtEuro(saldo)}</div>
        </div>
        <div className="row gap-8">
          <button className="btn"><Ic.upload/> Rabobank CSV</button>
        </div>
      </div>

      {/* Match proposals banner */}
      {unmatched.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 16,
          padding: '14px 20px', border: '1px solid var(--accent)', background: 'var(--accent-soft)',
          borderRadius: 10, marginBottom: 20,
        }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--accent)', color: 'white', display: 'grid', placeItems: 'center' }}>
            <Ic.link style={{ width: 16, height: 16 }}/>
          </div>
          <div>
            <div style={{ fontSize: 13, color: 'var(--accent-ink)', fontWeight: 500 }}>{unmatched.length} match-voorstel{unmatched.length > 1 ? 'len' : ''} klaar</div>
            <div className="tiny mono" style={{ color: 'var(--accent-ink)', opacity: 0.8 }}>Hoge zekerheid · op factuurnummer gematched</div>
          </div>
          <div style={{ flex: 1 }}/>
          <button className="btn" style={{ background: 'white' }}>Bekijken</button>
          <button className="btn btn-accent">Alles toepassen</button>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: 20 }}>
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Datum</th>
                <th>Tegenpartij</th>
                <th>Categorie</th>
                <th className="num">Bedrag</th>
              </tr>
            </thead>
            <tbody>
              {BANKTRX.map(t => (
                <tr key={t.id} onClick={() => setSelected(t.id)} className={selected === t.id ? 'selected' : ''}>
                  <td className="mono" style={{ fontSize: 12 }}>{fmtDateNL(t.datum)}</td>
                  <td>
                    <div>{t.tegenpartij}</div>
                    <div className="tiny muted mono">{t.omschrijving}</div>
                  </td>
                  <td>
                    {t.matched && !t.koppeling ? (
                      <span className="chip info">→ match {t.matched.confidence}</span>
                    ) : t.koppeling ? (
                      <span className="chip pos mono">{t.koppeling}</span>
                    ) : t.categorie ? (
                      <span className="chip">{t.categorie}</span>
                    ) : (
                      <span className="chip neg">niet gecat.</span>
                    )}
                  </td>
                  <td className="num" style={{ color: t.bedrag < 0 ? 'var(--neg)' : 'var(--pos)', fontWeight: 500 }}>
                    {t.bedrag > 0 ? '+' : ''}{fmtEuro(t.bedrag, 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Reconcile panel */}
        <div className="card" style={{ position: 'sticky', top: 80, alignSelf: 'flex-start' }}>
          <div className="eyebrow mb-12">Koppel transactie</div>
          {selected ? (() => {
            const t = BANKTRX.find(x => x.id === selected);
            const suggestions = FACTUREN.filter(f =>
              Math.abs(f.totaal - Math.abs(t.bedrag)) < 50 ||
              t.omschrijving.includes(f.nummer)
            ).slice(0, 3);
            return (
              <div>
                <div className="card-tight" style={{ background: 'var(--bg-sunk)', padding: 12, borderRadius: 8, marginBottom: 12 }}>
                  <div className="tiny mono muted">{fmtDateNL(t.datum)}</div>
                  <div style={{ fontSize: 13, marginTop: 4 }}>{t.tegenpartij}</div>
                  <div className="num" style={{ fontSize: 18, fontWeight: 500, marginTop: 4, color: t.bedrag < 0 ? 'var(--neg)' : 'var(--pos)' }}>
                    {t.bedrag > 0 ? '+' : ''}{fmtEuro(t.bedrag, 2)}
                  </div>
                </div>
                {suggestions.length > 0 ? (
                  <>
                    <div className="eyebrow mb-8">Voorstellen</div>
                    {suggestions.map(f => (
                      <div key={f.id} className="bank-item" style={{ marginBottom: 6 }}>
                        <Ic.invoice style={{ width: 14, height: 14, color: 'var(--ink-3)' }}/>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13 }}>{f.nummer}</div>
                          <div className="tiny muted">{f.klant_naam}</div>
                        </div>
                        <div className="num" style={{ fontSize: 12 }}>{fmtEuro(f.totaal)}</div>
                      </div>
                    ))}
                  </>
                ) : (
                  <>
                    <div className="eyebrow mb-8">Categoriseer</div>
                    <select className="input mb-8"><option>Kies categorie…</option><option>Vakliteratuur</option><option>Reiskosten</option><option>Telefoon</option><option>Representatie</option></select>
                    <button className="btn btn-accent" style={{ width: '100%', justifyContent: 'center' }}>
                      <Ic.sparkles style={{ width: 13, height: 13 }}/> Slim voorstel gebruiken
                    </button>
                  </>
                )}
              </div>
            );
          })() : (
            <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--ink-4)' }} className="mono tiny">
              Selecteer een transactie
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

window.Werkdagen = Werkdagen;
window.Facturen = Facturen;
window.Kosten = Kosten;
window.Bank = Bank;
