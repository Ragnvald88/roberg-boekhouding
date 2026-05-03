/* Calendar (month grid w/ week-row income summary + recurring + holidays) and Day Inspector */
const { useState, useMemo } = React;

const clientVars = (cid) => {
  const c = CLIENT_BY_ID[cid];
  return { '--client-color': c.color, '--client-soft': c.color + '1A' };
};
const statusVars = (st) => {
  const m = STATUS_META[st];
  return { '--st-color': m.color, '--st-soft': m.color + '1F' };
};
const blockerVars = (kind) => {
  const m = BLOCKER_META[kind];
  return { '--blocker-color': m.color, '--blocker-soft': m.soft };
};

// Get a unified entry list for a date — real entries + (optionally) expected ghosts
function entriesForDate(d, opts = { includeExpected: true }) {
  const k = dateKey(d);
  if (BLOCKED.has(k)) return { real: [], expected: [], blocker: BLOCKED.get(k) };
  const real = ENTRIES_BY_DATE.get(k) || [];
  const expected = opts.includeExpected ? expectedEntriesForDate(d) : [];
  return { real, expected, blocker: null };
}

// === Month grid v2 — week-row layout with income summary column ===
const MonthGrid = ({ anchor, selected, onSelect, showRecurring }) => {
  const ms = startOfMonth(anchor);
  const gs = startOfWeek(ms);
  // 6 weeks of 7 days
  const weeks = Array.from({length: 6}, (_, w) =>
    Array.from({length: 7}, (_, i) => addDays(gs, w*7 + i))
  );

  const dowLabels = ['Ma','Di','Wo','Do','Vr','Za','Zo'];

  return (
    <div className="mon-wrap">
      {dowLabels.map((d, i) => (
        <div key={'h'+i} className={'mon-dow' + (i>=5?' weekend':'')}>{d}</div>
      ))}
      <div className="mon-week-head">Week</div>

      {weeks.map((wk, wi) => {
        const agg = weekAggregate(wk[0]);
        return (
          <React.Fragment key={'w'+wi}>
            {wk.map((d) => {
              const k = dateKey(d);
              const block = BLOCKED.get(k);
              const real = ENTRIES_BY_DATE.get(k) || [];
              const expected = (showRecurring && !block) ? expectedEntriesForDate(d) : [];
              const all = [...real, ...expected];

              const isOM = d.getMonth() !== anchor.getMonth();
              const dow = d.getDay();
              const isWeekend = dow === 0 || dow === 6;
              const isToday = sameDay(d, TODAY);
              const isSel = selected && sameDay(d, selected);
              const totalHours = real.reduce((a,b)=>a+b.hours, 0);

              const cls = ['day',
                isOM?'other-month':'',
                isWeekend?'weekend':'',
                isToday?'today':'',
                isSel?'selected':'',
                block?'blocked':'',
              ].filter(Boolean).join(' ');

              return (
                <div
                  key={k}
                  className={cls}
                  style={block ? blockerVars(block.kind) : null}
                  onClick={() => onSelect(d)}
                >
                  <div className="day-head">
                    <span className="day-num rounded">{d.getDate()}</span>
                    {real.length > 0 && (
                      <span className="day-meta">{totalHours.toFixed(1).replace('.',',')}u</span>
                    )}
                  </div>

                  {block ? (
                    <>
                      <div className="day-blocker-kind">{BLOCKER_META[block.kind].label}</div>
                      <div className="day-blocker-label" style={{fontSize:11.5}}>{block.label}</div>
                    </>
                  ) : (
                    <div className="day-entries">
                      {all.slice(0,3).map(e => (
                        <div
                          key={e.id}
                          className={'entry-pill' + (e.fromRecurring ? ' expected' : (e.isPlanned ? ' planned' : ''))}
                          style={clientVars(e.clientId)}
                        >
                          <span className="pill-name">{e.client.short}</span>
                          <span className="pill-hours">{e.hours.toFixed(1).replace('.',',')}</span>
                        </div>
                      ))}
                      {all.length > 3 && (
                        <div className="day-overflow">+{all.length-3} meer</div>
                      )}
                    </div>
                  )}

                  {real.length > 0 && (
                    <div className="day-foot-bar">
                      {real.map(e => {
                        const meta = e.invoiceStatus && STATUS_META[e.invoiceStatus];
                        const color = meta ? meta.color : (e.isPlanned ? 'var(--accent)' : STATUS_META.draft.color);
                        return <span key={e.id} style={{background: color, '--w': e.hours}} />;
                      })}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Week summary column */}
            <WeekSummary weekStart={wk[0]} agg={agg} />
          </React.Fragment>
        );
      })}
    </div>
  );
};

const WeekSummary = ({ weekStart, agg }) => {
  const wnum = isoWeekNum(weekStart);
  const total = agg.totalAmt;
  const pcts = total > 0 ? {
    confirmed: (agg.confirmedAmt / total) * 100,
    planned: (agg.plannedAmt / total) * 100,
    expected: (agg.expectedAmt / total) * 100,
  } : { confirmed: 0, planned: 0, expected: 0 };

  const isCurrent = TODAY >= weekStart && TODAY < addDays(weekStart, 7);

  return (
    <div className="week-summary" style={isCurrent ? {background:'linear-gradient(180deg, rgba(0,122,255,0.08), rgba(0,122,255,0.02))'} : null}>
      <div style={{display:'flex', alignItems:'baseline', justifyContent:'space-between'}}>
        <span className="ws-num">W{wnum}</span>
        {isCurrent && <span style={{fontSize:9, fontWeight:700, color:'var(--accent)', textTransform:'uppercase', letterSpacing:'0.05em'}}>Nu</span>}
      </div>
      {total > 0 ? (
        <>
          <div className="ws-total">{fmtEUR.format(total)}</div>
          <div className="ws-bar">
            {pcts.confirmed > 0 && <span style={{width: pcts.confirmed + '%', background: 'var(--green)'}} />}
            {pcts.planned > 0 && <span style={{width: pcts.planned + '%', background: 'var(--accent)'}} />}
            {pcts.expected > 0 && <span style={{width: pcts.expected + '%', background:'repeating-linear-gradient(45deg, var(--accent), var(--accent) 3px, rgba(0,122,255,0.4) 3px, rgba(0,122,255,0.4) 6px)'}} />}
          </div>
          {agg.confirmedAmt > 0 && (
            <div className="ws-row">
              <span className="dot" style={{background:'var(--green)'}} />
              <span className="lbl">Bevestigd</span>
              <span className="val">{fmtEUR.format(agg.confirmedAmt)}</span>
            </div>
          )}
          {agg.plannedAmt > 0 && (
            <div className="ws-row">
              <span className="dot" style={{background:'var(--accent)'}} />
              <span className="lbl">Gepland</span>
              <span className="val">{fmtEUR.format(agg.plannedAmt)}</span>
            </div>
          )}
          {agg.expectedAmt > 0 && (
            <div className="ws-row expected">
              <span className="dot" style={{background:'rgba(0,122,255,0.5)', border:'1px dashed var(--accent)'}} />
              <span className="lbl">Verwacht</span>
              <span className="val">{fmtEUR.format(agg.expectedAmt)}</span>
            </div>
          )}
          <div className="ws-meta">
            {Math.round(agg.totalH)}u · {agg.confirmedD + agg.plannedD + agg.expectedD} dag{(agg.confirmedD + agg.plannedD + agg.expectedD)!==1?'en':''}
            {agg.blockedD > 0 ? ` · ${agg.blockedD} vrij` : ''}
          </div>
        </>
      ) : (
        <div style={{fontSize:11, color:'var(--ink-4)', marginTop:4}}>
          {agg.blockedD === 7 ? '— vakantieweek —' : '— geen werkdagen —'}
        </div>
      )}
    </div>
  );
};

// === Day Inspector (right side) ===
const DayInspector = ({ date, onConfirmExpected }) => {
  const [adding, setAdding] = useState(false);
  const [clientId, setClientId] = useState('c1');
  const [start, setStart] = useState('08:00');
  const [end, setEnd] = useState('17:00');
  const [desc, setDesc] = useState('');

  const k = dateKey(date);
  const block = BLOCKED.get(k);
  const ents = ENTRIES_BY_DATE.get(k) || [];
  const expected = (!block && ents.length === 0) ? expectedEntriesForDate(date) : [];

  const totalH = ents.reduce((a,b)=>a+b.hours, 0);
  const totalAmt = ents.reduce((a,b)=>a+b.billable, 0);
  const totalKm = ents.reduce((a,b)=>a+b.mileage, 0);

  const hoursBetween = (s, e) => {
    const [sh, sm] = s.split(':').map(Number);
    const [eh, em] = e.split(':').map(Number);
    return Math.max(0, (eh*60+em) - (sh*60+sm)) / 60;
  };
  const newHours = hoursBetween(start, end);
  const c = CLIENT_BY_ID[clientId];
  const newAmt = newHours * c.rate + (c.km * 2 * 0.23);

  return (
    <div className="insp-card">
      <div className="insp-header">
        <div className="insp-header-row">
          <div>
            <div className="insp-date rounded">{fmtDateLong(date)}</div>
            <div className="insp-sub">
              {block ? BLOCKER_META[block.kind].label
                : ents.length === 0
                  ? (expected.length > 0 ? `${expected.length} verwacht (vaste dag)` : 'Geen werkdag')
                  : `${ents.length} dienst${ents.length>1?'en':''}`}
            </div>
          </div>
          {!adding && !block && (
            <button className="btn primary" onClick={() => setAdding(true)} style={{padding:'6px 10px'}}>
              <Icon name="plus" size={14} color="white" /> Nieuw
            </button>
          )}
        </div>
      </div>

      {/* BLOCKED day */}
      {block && (
        <div className="insp-blocked" style={blockerVars(block.kind)}>
          <div className="insp-blocked-icon">
            <Icon name={block.kind === 'holiday' ? 'pin' : block.kind === 'vacation' ? 'sparkle' : 'doc'} size={18} color="white" />
          </div>
          <div className="insp-blocked-body">
            <div className="insp-blocked-kind">{BLOCKER_META[block.kind].label}</div>
            <div className="insp-blocked-label">{block.label}</div>
            <div className="insp-blocked-sub">Geen registraties · vaste dagen worden overschreven</div>
          </div>
        </div>
      )}

      {/* CONFIRMED entries — quick stats + list */}
      {!block && ents.length > 0 && (
        <div className="insp-quick">
          <div className="insp-stat">
            <div className="v rounded">{totalH.toFixed(1).replace('.',',')}<span style={{fontSize:11, color:'var(--ink-3)', marginLeft:2}}>u</span></div>
            <div className="l">Uren</div>
          </div>
          <div className="insp-stat">
            <div className="v rounded">{fmtEUR.format(totalAmt)}</div>
            <div className="l">Te factureren</div>
          </div>
          <div className="insp-stat">
            <div className="v rounded">{Math.round(totalKm)}<span style={{fontSize:11, color:'var(--ink-3)', marginLeft:2}}>km</span></div>
            <div className="l">Kilometers</div>
          </div>
        </div>
      )}

      {/* EXPECTED (recurring) — confirm CTA */}
      {!block && ents.length === 0 && expected.length > 0 && expected.map(e => (
        <div key={e.id} className="insp-expected" style={clientVars(e.clientId)}>
          <div className="insp-expected-row">
            <div className="insp-expected-icon">
              <Icon name="calendar" size={16} color="white" />
            </div>
            <div className="insp-expected-body">
              <div className="insp-expected-tag">Verwacht · vaste dag</div>
              <div className="insp-expected-name">{e.client.name}</div>
              <div className="insp-expected-meta">
                {fmtTime(e.start)}–{fmtTime(e.end)} · {e.hours.toFixed(1).replace('.',',')}u · {fmtEUR2.format(e.billable)}
              </div>
            </div>
          </div>
          <div className="insp-expected-actions">
            <button className="btn" onClick={() => setAdding(true)}>Aanpassen</button>
            <button className="btn client" onClick={() => onConfirmExpected && onConfirmExpected(e)}>
              <Icon name="check" size={13} color="white" /> Bevestigen
            </button>
          </div>
        </div>
      ))}

      {/* TRULY EMPTY */}
      {!block && ents.length === 0 && expected.length === 0 && !adding && (
        <div className="insp-empty">
          <div className="insp-empty-icon"><Icon name="calendar" size={20} /></div>
          <div className="insp-empty-title rounded">Geen registratie</div>
          <div className="insp-empty-msg">Voeg een waarneming, dienst of vrije dag toe.</div>
          <button className="btn primary" onClick={() => setAdding(true)}>
            <Icon name="plus" size={14} color="white" /> Werkdag toevoegen
          </button>
        </div>
      )}

      {/* Confirmed entries list */}
      {!block && ents.length > 0 && (
        <div className="insp-list">
          {ents.map(e => {
            const status = e.invoiceStatus || (e.isPlanned ? null : 'draft');
            return (
              <div key={e.id} className="insp-entry" style={clientVars(e.clientId)}>
                <div className="insp-entry-bar"></div>
                <div className="insp-entry-body">
                  <div className="insp-entry-row1">
                    <div className="insp-entry-name">{e.client.name}</div>
                    <div className="insp-entry-time">{fmtTime(e.start)}–{fmtTime(e.end)}</div>
                  </div>
                  <div className="insp-entry-desc">
                    {e.description}{e.isPlanned ? ' · gepland' : ''}
                  </div>
                  <div className="insp-entry-row3">
                    <span>{e.hours.toFixed(1).replace('.',',')}u · {fmtEUR2.format(e.rate)}/u</span>
                    <span>·</span>
                    <span>{e.mileage}km</span>
                    <span style={{marginLeft:'auto'}} className="amt">{fmtEUR2.format(e.billable)}</span>
                  </div>
                  {status && (
                    <div style={{marginTop:8, display:'flex', alignItems:'center', gap:8}}>
                      <span className="status-chip" style={statusVars(status)}>
                        <span className="dot" />
                        {STATUS_META[status].label}
                      </span>
                      {e.invoiceId && <span style={{fontSize:11, color:'var(--ink-3)', fontFamily:'var(--font-mono)'}}>#{e.invoiceId}</span>}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Quick add form */}
      {adding && !block && (
        <div className="qa">
          <div className="qa-title">Nieuwe werkdag</div>
          <div className="qa-field">
            <label>Klant</label>
            <select className="qa-select" value={clientId} onChange={e => setClientId(e.target.value)}>
              {CLIENTS.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="qa-field">
            <label>Tijd</label>
            <div className="qa-row" style={{flex:1}}>
              <input className="qa-input mono" type="time" value={start} onChange={e => setStart(e.target.value)} />
              <input className="qa-input mono" type="time" value={end} onChange={e => setEnd(e.target.value)} />
            </div>
          </div>
          <div className="qa-field">
            <label>Omschrijving</label>
            <input className="qa-input" placeholder="Waarneming dagpraktijk" value={desc} onChange={e => setDesc(e.target.value)} />
          </div>
          <div className="qa-summary">
            <div>
              <div className="l">{newHours.toFixed(1).replace('.',',')} uur · {c.km*2}km · {fmtEUR2.format(c.rate)}/u</div>
            </div>
            <div className="v">{fmtEUR2.format(newAmt)}</div>
          </div>
          <div style={{display:'flex', gap:8}}>
            <button className="btn ghost" style={{flex:1, justifyContent:'center'}} onClick={() => setAdding(false)}>Annuleren</button>
            <button className="btn primary" style={{flex:1, justifyContent:'center'}} onClick={() => setAdding(false)}>
              <Icon name="check" size={14} color="white" /> Opslaan
            </button>
          </div>
        </div>
      )}

      {!block && ents.length > 0 && !adding && (
        <div className="insp-foot">
          <button className="btn"><Icon name="edit" size={13} /> Bewerken</button>
          {ents.some(e => !e.invoiceId && !e.isPlanned) && (
            <button className="btn primary"><Icon name="send" size={13} color="white" /> Maak factuur</button>
          )}
        </div>
      )}
    </div>
  );
};

// === Income Forecast — next 6 weeks ===
const IncomeForecast = ({ anchor }) => {
  const startWeek = startOfWeek(TODAY);
  const weeks = Array.from({length: 6}, (_, i) => addDays(startWeek, i*7));
  const data = weeks.map(ws => ({ ws, agg: weekAggregate(ws), wnum: isoWeekNum(ws) }));
  const maxAmt = Math.max(...data.map(d => d.agg.totalAmt), 1);

  return (
    <div className="aside-card">
      <h3>Inkomstenprognose <span className="meta">6 wkn</span></h3>
      <div className="aside-card-body">
        <div className="fc-rows">
          {data.map(({ws, agg, wnum}, i) => {
            const isCur = i === 0;
            const widthPct = (agg.totalAmt / maxAmt) * 100;
            return (
              <div key={wnum} className={'fc-row' + (isCur ? ' current' : '')}>
                <div>
                  <div className="fc-week">W{wnum}</div>
                  <div className="fc-week-sub">{fmtDateShort(ws)}</div>
                </div>
                <div className="fc-bar-wrap">
                  <div className="fc-bar" style={{width: Math.max(8, widthPct) + '%'}}>
                    {agg.totalAmt > 0 ? (
                      <>
                        {agg.confirmedAmt > 0 && <span className="confirmed" style={{flex: agg.confirmedAmt}} />}
                        {agg.plannedAmt > 0 && <span className="planned" style={{flex: agg.plannedAmt}} />}
                        {agg.expectedAmt > 0 && <span className="expected" style={{flex: agg.expectedAmt}} />}
                      </>
                    ) : agg.blockedD > 0 ? (
                      <span className="blocked" style={{flex:1}} />
                    ) : null}
                  </div>
                  <div className="fc-meta">
                    {agg.confirmedD + agg.plannedD + agg.expectedD} dag{(agg.confirmedD + agg.plannedD + agg.expectedD)!==1?'en':''}
                    {agg.expectedAmt > 0 ? ` · ${Math.round(agg.expectedAmt/agg.totalAmt*100)}% verwacht` : ''}
                    {agg.blockedD > 0 && (agg.confirmedD + agg.plannedD + agg.expectedD) === 0 ? ` · ${agg.blockedD} vrij` : ''}
                  </div>
                </div>
                <div>
                  <div className="fc-amt">{fmtEUR.format(agg.totalAmt)}</div>
                  {agg.confirmedAmt > 0 && agg.confirmedAmt < agg.totalAmt && (
                    <div className="fc-amt-sub">{fmtEUR.format(agg.confirmedAmt)} bevestigd</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// === Recurring Patterns widget ===
const RecurringPatterns = () => {
  const dayLabels = ['M','D','W','D','V','Z','Z'];
  const withPattern = CLIENTS.filter(c => c.pattern);
  if (!withPattern.length) return null;
  return (
    <div className="aside-card">
      <h3>Vaste waarneemdagen <span className="meta">{withPattern.length}</span></h3>
      <div className="aside-card-body" style={{paddingTop:6, paddingBottom:6}}>
        {withPattern.map(c => (
          <div key={c.id} className="rp-row" style={clientVars(c.id)}>
            <div className="rp-swatch" style={{background: c.color}}>{c.short.split(' ').map(w=>w[0]).slice(0,2).join('')}</div>
            <div className="rp-body">
              <div className="rp-name">{c.name}</div>
              <div className="rp-pattern">
                {dayLabels.map((lbl, i) => {
                  const iso = i + 1;
                  const on = c.pattern.weekdays.includes(iso);
                  return <span key={i} className={'d' + (on?' on':'')}>{lbl}</span>;
                })}
                <span style={{flex:1}} />
              </div>
              <div className="rp-time">
                {String(Math.floor(c.pattern.startHour)).padStart(2,'0')}:00–{String(Math.floor(c.pattern.endHour)).padStart(2,'0')}:{c.pattern.endHour%1?'30':'00'}
                {' · '}{fmtEUR2.format(c.rate)}/u
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// === Urencriterium (BTW: small business / hours threshold) ===
const Urencriterium = () => {
  const yearStart = new Date(TODAY.getFullYear(), 0, 1);
  const total = TIME_ENTRIES
    .filter(e => !e.isPlanned && e.date.getFullYear() === TODAY.getFullYear() && e.date <= TODAY)
    .reduce((a, e) => a + e.hours, 0);
  // Add expected hours to year-end projection
  let expectedRest = 0;
  for (let d = addDays(TODAY, 1); d.getFullYear() === TODAY.getFullYear(); d = addDays(d, 1)) {
    const k = dateKey(d);
    if (BLOCKED.has(k)) continue;
    const real = ENTRIES_BY_DATE.get(k) || [];
    if (real.length) { expectedRest += real.reduce((a,e)=>a+e.hours, 0); continue; }
    expectedRest += expectedEntriesForDate(d).reduce((a,e)=>a+e.hours, 0);
  }
  const projected = total + expectedRest;
  const target = 1225;
  const pct = Math.min(100, (total / target) * 100);
  const projectedPct = Math.min(100, (projected / target) * 100);
  const dayOfYear = Math.floor((TODAY - yearStart) / 86400000) + 1;
  const yearLen = 365;
  const pacePct = (dayOfYear / yearLen) * 100;
  const willMake = projected >= target;

  return (
    <div className="aside-card">
      <h3>Urencriterium <span className="meta">{TODAY.getFullYear()}</span></h3>
      <div className="aside-card-body">
        <div className="uc-hero">
          <span className="uc-now mono">{Math.round(total)}</span>
          <span className="uc-of">van</span>
          <span className="uc-target">1.225 uur</span>
        </div>
        <div className="uc-bar">
          <div className="uc-fill" style={{width: pct + '%'}} />
          {/* projected (with expected recurring) — ghosted continuation */}
          <div style={{
            position:'absolute',
            left: pct + '%',
            width: (projectedPct - pct) + '%',
            top: 0, bottom: 0,
            background: 'repeating-linear-gradient(45deg, rgba(0,122,255,0.4), rgba(0,122,255,0.4) 3px, rgba(0,122,255,0.15) 3px, rgba(0,122,255,0.15) 6px)',
          }} />
          <div className="uc-pace" style={{left: pacePct + '%'}} title="Verwacht tempo" />
        </div>
        <div className="uc-foot">
          <span>Prognose: {Math.round(projected)}u</span>
          <span style={{color: willMake ? '#34C759' : '#FF9500'}}>
            {willMake ? '✓' : '!'} {willMake ? 'Voldoet' : 'Krap'}
          </span>
        </div>
      </div>
    </div>
  );
};

const MonthSummary = ({ anchor }) => {
  const m = anchor.getMonth(), y = anchor.getFullYear();
  let workH = 0, workD = 0, revenue = 0;
  let plannedRev = 0, expectedRev = 0, plannedD = 0, expectedD = 0;
  let unbilledN = 0, unbilledAmt = 0;
  let blockedD = 0;

  for (const e of TIME_ENTRIES) {
    if (e.date.getMonth() !== m || e.date.getFullYear() !== y) continue;
    if (e.isPlanned) { plannedRev += e.billable; plannedD++; }
    else {
      workH += e.hours; workD++; revenue += e.billable;
      if (!e.invoiceId) { unbilledN++; unbilledAmt += e.billable; }
    }
  }

  // count blocked & expected days in this month
  const ms = startOfMonth(anchor);
  const lastDay = new Date(y, m+1, 0).getDate();
  for (let day = 1; day <= lastDay; day++) {
    const d = new Date(y, m, day);
    const k = dateKey(d);
    if (BLOCKED.has(k)) blockedD++;
    else if (d > TODAY && !ENTRIES_BY_DATE.has(k)) {
      const exp = expectedEntriesForDate(d);
      if (exp.length) {
        expectedRev += exp.reduce((a,e)=>a+e.billable, 0);
        expectedD++;
      }
    }
  }

  const projection = revenue + plannedRev + expectedRev;

  return (
    <div className="aside-card">
      <h3>Deze maand <span className="meta">{anchor.toLocaleDateString('nl-NL',{month:'long'})}</span></h3>
      <div className="aside-card-body">
        <div className="kpi-grid">
          <div className="kpi-tile">
            <div className="l"><Icon name="check" size={11} color="#34C759" /> Bevestigd</div>
            <div className="v">{fmtEUR.format(revenue)}</div>
            <div className="s">{workD} dagen · {Math.round(workH)}u</div>
          </div>
          <div className="kpi-tile">
            <div className="l"><Icon name="calendar" size={11} color="#007AFF" /> Gepland</div>
            <div className="v">{fmtEUR.format(plannedRev)}</div>
            <div className="s">{plannedD} dagen</div>
          </div>
          <div className="kpi-tile">
            <div className="l"><Icon name="sparkle" size={11} color="#AF52DE" /> Verwacht</div>
            <div className="v">{fmtEUR.format(expectedRev)}</div>
            <div className="s">{expectedD} vaste dagen</div>
          </div>
          <div className="kpi-tile">
            <div className="l"><Icon name="warning" size={11} color="#FF9500" /> Open</div>
            <div className="v">{fmtEUR.format(unbilledAmt)}</div>
            <div className="s">{unbilledN} ongefactureerd</div>
          </div>
        </div>
        <div style={{marginTop:12, padding:'10px 12px', background:'linear-gradient(90deg, rgba(52,199,89,0.10), rgba(0,122,255,0.06))', borderRadius:8, display:'flex', alignItems:'center', justifyContent:'space-between'}}>
          <div>
            <div style={{fontSize:10.5, fontWeight:600, color:'var(--ink-3)', textTransform:'uppercase', letterSpacing:'0.04em'}}>Maandprognose</div>
            <div style={{fontSize:10.5, color:'var(--ink-3)', fontFamily:'var(--font-mono)'}}>
              {blockedD > 0 ? `${blockedD} vrij/feestdagen` : ''}
            </div>
          </div>
          <div className="rounded" style={{fontSize:18, fontWeight:700, fontVariantNumeric:'tabular-nums'}}>
            {fmtEUR.format(projection)}
          </div>
        </div>
      </div>
    </div>
  );
};

const Legend = () => (
  <div className="legend">
    <span className="legend-item"><span className="legend-swatch" />Bevestigd</span>
    <span className="legend-item"><span className="legend-swatch dashed" />Gepland</span>
    <span className="legend-item"><span className="legend-swatch dotted" />Verwacht (vast)</span>
    <span className="legend-item"><span className="legend-swatch hatched" />Vrij/feestdag</span>
    <span className="legend-item"><span className="legend-dot" style={{background:'#34C759'}}/>Betaald</span>
    <span className="legend-item"><span className="legend-dot" style={{background:'#FF9500'}}/>Open</span>
    <span className="legend-item"><span className="legend-dot" style={{background:'#FF3B30'}}/>Vervallen</span>
  </div>
);

// === Main App ===
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "showRecurring": true,
  "showLegend": true,
  "showWeekIncome": true
}/*EDITMODE-END*/;

const App = () => {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [anchor, setAnchor] = useState(new Date(TODAY));
  const [selected, setSelected] = useState(new Date(TODAY));
  const [active, setActive] = useState('agenda');

  const monthMeta = useMemo(() => {
    let h = 0, r = 0, d = 0;
    for (const e of TIME_ENTRIES) {
      if (e.date.getMonth() !== anchor.getMonth() || e.date.getFullYear() !== anchor.getFullYear()) continue;
      h += e.hours; r += e.billable; d++;
    }
    return { h, r, d };
  }, [anchor]);

  const goPrev = () => setAnchor(addMonths(anchor, -1));
  const goNext = () => setAnchor(addMonths(anchor, 1));
  const goToday = () => { setAnchor(new Date(TODAY)); setSelected(new Date(TODAY)); };

  const handleConfirmExpected = (e) => {
    // In the real app: insert TimeEntry, mirror to EventKit calendar, save
    alert(`Bevestigd: ${e.client.name} op ${fmtDateLong(e.date)}\n${fmtTime(e.start)}–${fmtTime(e.end)} · ${fmtEUR2.format(e.billable)}`);
  };

  return (
    <div className="app">
      <Sidebar active={active} onSelect={setActive} />
      <div className="main">
        <Topbar title="Agenda">
          <div className="seg">
            <button className="on">Maand</button>
            <button>Week</button>
            <button>Dag</button>
          </div>
          <button className="btn" title="Zoeken"><Icon name="search" size={14} /></button>
          <button className="btn"><Icon name="bell" size={14} /></button>
          <button className="btn primary" onClick={() => setSelected(new Date(TODAY))}>
            <Icon name="plus" size={14} color="white" /> Nieuwe registratie
          </button>
        </Topbar>

        <div className="page">
          <div>
            <div className="card">
              <div className="cal-tb">
                <div>
                  <div className="cal-tb-title rounded">{anchor.toLocaleDateString('nl-NL',{month:'long', year:'numeric'})}</div>
                  <div className="cal-tb-meta">{monthMeta.d} dagen · {Math.round(monthMeta.h)} uur · {fmtEUR.format(monthMeta.r)}</div>
                </div>
                <div style={{flex:1}} />
                <div style={{display:'flex', gap:4}}>
                  <button className="icon-btn" onClick={goPrev}><Icon name="left" size={14} /></button>
                  <button className="btn ghost" onClick={goToday}>Vandaag</button>
                  <button className="icon-btn" onClick={goNext}><Icon name="right" size={14} /></button>
                </div>
              </div>
              <MonthGrid
                anchor={anchor}
                selected={selected}
                onSelect={(d) => { setSelected(d); if (d.getMonth() !== anchor.getMonth()) setAnchor(d); }}
                showRecurring={tweaks.showRecurring}
              />
              {tweaks.showLegend && <Legend />}
            </div>
          </div>

          <aside className="inspector">
            <DayInspector date={selected} onConfirmExpected={handleConfirmExpected} />
            <IncomeForecast anchor={anchor} />
            <MonthSummary anchor={anchor} />
            <RecurringPatterns />
            <Urencriterium />
          </aside>
        </div>
      </div>

      <TweaksPanel title="Tweaks">
        <TweakSection title="Agenda">
          <TweakToggle label="Vaste dagen tonen" value={tweaks.showRecurring} onChange={v => setTweak('showRecurring', v)} />
          <TweakToggle label="Legenda tonen" value={tweaks.showLegend} onChange={v => setTweak('showLegend', v)} />
        </TweakSection>
      </TweaksPanel>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
