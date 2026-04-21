/* global React, Ic, StatusChip, fmtEuro, fmtEuroPlain, fmtDateNL, APPDATA */

const { useState: useSt } = React;

const FactuurBuilder = ({ setRoute }) => {
  const [klantId, setKlantId] = useSt(1);
  const [lines, setLines] = useSt([
    { desc: 'Waarneming dagpraktijk 02-04-2026', qty: 8, price: 95 },
    { desc: 'Waarneming dagpraktijk 05-04-2026', qty: 7.5, price: 95 },
    { desc: 'Kilometervergoeding (4x24km)', qty: 96, price: 0.23 },
  ]);
  const klant = APPDATA.KLANTEN.find(k => k.id === parseInt(klantId));
  const subtotaal = lines.reduce((a, l) => a + l.qty * l.price, 0);

  const updateLine = (i, field, val) => {
    const n = [...lines];
    n[i][field] = field === 'desc' ? val : parseFloat(val) || 0;
    setLines(n);
  };

  return (
    <div className="content" style={{ maxWidth: 'none' }}>
      <div className="page-head">
        <div className="row gap-12">
          <button className="btn btn-ghost" onClick={() => setRoute('facturen')}><Ic.arrowRight style={{ transform: 'rotate(180deg)' }}/> Terug</button>
          <div>
            <h1 className="page-title">Nieuwe factuur</h1>
            <div className="page-sub">Concept · 2026-043</div>
          </div>
        </div>
        <div className="row gap-8">
          <button className="btn">Opslaan als concept</button>
          <button className="btn btn-primary">Genereer & verstuur</button>
        </div>
      </div>

      <div className="builder">
        {/* LEFT — form */}
        <div className="col" style={{ gap: 16 }}>
          <div className="card">
            <div className="eyebrow mb-12">Klant</div>
            <select className="input mb-12" value={klantId} onChange={e => setKlantId(e.target.value)}>
              {APPDATA.KLANTEN.map(k => <option key={k.id} value={k.id}>{k.naam}</option>)}
            </select>
            <div className="row gap-12">
              <div style={{ flex: 1 }}>
                <div className="eyebrow">Datum</div>
                <input className="input mt-4" defaultValue="2026-04-17" type="date"/>
              </div>
              <div style={{ flex: 1 }}>
                <div className="eyebrow">Vervaldatum</div>
                <input className="input mt-4" defaultValue="2026-05-01" type="date"/>
              </div>
            </div>
          </div>

          {/* Unbilled werkdagen suggestions */}
          <div className="card" style={{ background: 'var(--accent-soft)', border: '1px solid transparent' }}>
            <div className="row items-center mb-8">
              <Ic.sparkles style={{ width: 14, height: 14, color: 'var(--accent-ink)' }}/>
              <div className="eyebrow" style={{ color: 'var(--accent-ink)' }}>3 ongefactureerde werkdagen voor deze klant</div>
            </div>
            <button className="btn btn-accent" style={{ marginTop: 8 }}>
              <Ic.plus/> Importeer als regels
            </button>
          </div>

          <div className="card">
            <div className="flex justify-between mb-12">
              <div className="eyebrow">Regels</div>
              <button className="btn btn-ghost tiny" onClick={() => setLines([...lines, { desc: '', qty: 1, price: 0 }])}>
                <Ic.plus style={{ width: 12, height: 12 }}/> Regel
              </button>
            </div>
            <div className="line-item mono tiny muted" style={{ borderBottom: '1px solid var(--line)', paddingBottom: 6 }}>
              <div>OMSCHRIJVING</div>
              <div style={{ textAlign: 'right' }}>AANTAL</div>
              <div style={{ textAlign: 'right' }}>PRIJS</div>
              <div style={{ textAlign: 'right' }}>TOTAAL</div>
              <div></div>
            </div>
            {lines.map((l, i) => (
              <div key={i} className="line-item">
                <input value={l.desc} onChange={e => updateLine(i, 'desc', e.target.value)} placeholder="Omschrijving…"/>
                <input className="num" value={l.qty} onChange={e => updateLine(i, 'qty', e.target.value)} type="number" step="0.25"/>
                <input className="num" value={l.price} onChange={e => updateLine(i, 'price', e.target.value)} type="number" step="0.01"/>
                <div className="num" style={{ padding: '4px 6px', fontSize: 13 }}>{fmtEuro(l.qty * l.price, 2)}</div>
                <button className="btn btn-ghost" style={{ padding: 2 }} onClick={() => setLines(lines.filter((_, j) => j !== i))}>
                  <Ic.x style={{ width: 12, height: 12, color: 'var(--ink-4)' }}/>
                </button>
              </div>
            ))}
            <div className="flex justify-between mt-16" style={{ paddingTop: 12, borderTop: '1px solid var(--line)' }}>
              <div className="mono" style={{ fontSize: 12, color: 'var(--ink-3)' }}>BTW vrijgesteld (art. 11 Wet OB)</div>
              <div className="num" style={{ fontSize: 20, fontWeight: 500 }}>{fmtEuro(subtotaal, 2)}</div>
            </div>
          </div>
        </div>

        {/* RIGHT — preview */}
        <div style={{ position: 'sticky', top: 80, alignSelf: 'flex-start' }}>
          <div className="eyebrow mb-8" style={{ textAlign: 'center' }}>Live preview</div>
          <div className="preview-doc">
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 32 }}>
              <div>
                <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.02em' }}>R.P. Berg</div>
                <div style={{ fontSize: 9, color: '#666', marginTop: 4, lineHeight: 1.5 }}>
                  Huisarts Waarnemer<br/>
                  Herengracht 123, 1015 BG Amsterdam<br/>
                  KvK 12345678 · NL91 RABO 0123 4567 89
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontFamily: 'var(--f-mono)', fontSize: 20, letterSpacing: '-0.02em' }}>FACTUUR</div>
                <div style={{ fontFamily: 'var(--f-mono)', fontSize: 10, color: '#666', marginTop: 4 }}>2026-043</div>
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 24, fontSize: 10 }}>
              <div>
                <div style={{ color: '#888', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', fontSize: 8, marginBottom: 4 }}>Factureren aan</div>
                <div style={{ fontWeight: 500 }}>{klant?.naam}</div>
                <div style={{ color: '#666' }}>{klant?.plaats}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ color: '#888', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', fontSize: 8, marginBottom: 4 }}>Datum · Vervalt</div>
                <div style={{ fontFamily: 'var(--f-mono)' }}>17-04-2026 · 01-05-2026</div>
              </div>
            </div>

            <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #000' }}>
                  <th style={{ textAlign: 'left', padding: '6px 0', fontSize: 8, textTransform: 'uppercase', fontFamily: 'var(--f-mono)' }}>Omschrijving</th>
                  <th style={{ textAlign: 'right', padding: '6px 0', fontSize: 8, textTransform: 'uppercase', fontFamily: 'var(--f-mono)' }}>Aantal</th>
                  <th style={{ textAlign: 'right', padding: '6px 0', fontSize: 8, textTransform: 'uppercase', fontFamily: 'var(--f-mono)' }}>Prijs</th>
                  <th style={{ textAlign: 'right', padding: '6px 0', fontSize: 8, textTransform: 'uppercase', fontFamily: 'var(--f-mono)' }}>Totaal</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                    <td style={{ padding: '8px 0' }}>{l.desc || <em style={{ color: '#999' }}>—</em>}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--f-mono)' }}>{l.qty}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--f-mono)' }}>{fmtEuroPlain(l.price)}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--f-mono)' }}>{fmtEuroPlain(l.qty * l.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16, paddingTop: 12, borderTop: '2px solid #000' }}>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontFamily: 'var(--f-mono)', fontSize: 8, color: '#888', textTransform: 'uppercase' }}>Totaal te betalen</div>
                <div style={{ fontFamily: 'var(--f-mono)', fontSize: 20, fontWeight: 500, marginTop: 2 }}>€ {fmtEuroPlain(subtotaal)}</div>
              </div>
            </div>

            <div style={{ marginTop: 40, fontSize: 8, color: '#888', fontFamily: 'var(--f-mono)', lineHeight: 1.6 }}>
              Vrijgesteld van BTW op grond van artikel 11 lid 1 onderdeel g Wet OB 1968.<br/>
              Gelieve te voldoen binnen 14 dagen op NL91 RABO 0123 4567 89 o.v.v. {klant ? '2026-043' : ''}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

window.FactuurBuilder = FactuurBuilder;
