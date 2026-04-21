/* global React, ReactDOM, Ic, APPDATA, Dashboard, Werkdagen, Facturen, Kosten, Bank, FactuurBuilder */

const { useState: uS, useEffect: uE, useRef: uR } = React;

const DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "light",
  "density": "normal",
  "accent": "teal",
  "nav": "expanded",
  "font": "inter"
}/*EDITMODE-END*/;

const ACCENTS = {
  teal:   { light: { accent: '#0f766e', soft: '#e6f2f0', ink: '#0a524c' }, dark: { accent: '#2dd4bf', soft: '#0d2f2c', ink: '#5eead4' } },
  indigo: { light: { accent: '#4338ca', soft: '#e0e7ff', ink: '#312e81' }, dark: { accent: '#818cf8', soft: '#1e1b4b', ink: '#a5b4fc' } },
  amber:  { light: { accent: '#b45309', soft: '#fef3c7', ink: '#78350f' }, dark: { accent: '#fbbf24', soft: '#422006', ink: '#fcd34d' } },
  slate:  { light: { accent: '#334155', soft: '#e2e8f0', ink: '#0f172a' }, dark: { accent: '#94a3b8', soft: '#1e293b', ink: '#cbd5e1' } },
  rose:   { light: { accent: '#be123c', soft: '#ffe4e6', ink: '#881337' }, dark: { accent: '#fb7185', soft: '#4c0519', ink: '#fda4af' } },
};

const FONTS = {
  inter:  { body: 'Inter, ui-sans-serif, system-ui, sans-serif' },
  geist:  { body: '"Geist", Inter, ui-sans-serif, sans-serif' },
  ibm:    { body: '"IBM Plex Sans", Inter, ui-sans-serif, sans-serif' },
  helv:   { body: '"Helvetica Neue", Helvetica, Arial, sans-serif' },
};

const App = () => {
  const [route, setRoute] = uS('dashboard');
  const [cmdk, setCmdk] = uS(false);
  const [cmdQ, setCmdQ] = uS('');
  const [cmdIdx, setCmdIdx] = uS(0);
  const [cfg, setCfg] = uS(DEFAULTS);
  const [tweaks, setTweaks] = uS(false);

  // Apply theme/density
  uE(() => {
    document.documentElement.setAttribute('data-theme', cfg.theme);
    document.documentElement.setAttribute('data-density', cfg.density);
    document.documentElement.setAttribute('data-nav', cfg.nav);
    const acc = ACCENTS[cfg.accent][cfg.theme === 'dark' ? 'dark' : 'light'];
    document.documentElement.style.setProperty('--accent', acc.accent);
    document.documentElement.style.setProperty('--accent-soft', acc.soft);
    document.documentElement.style.setProperty('--accent-ink', acc.ink);
    document.documentElement.style.setProperty('--f-sans', FONTS[cfg.font].body);
  }, [cfg]);

  // Keyboard shortcuts
  uE(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); setCmdk(v => !v); setCmdQ(''); setCmdIdx(0); }
      if (e.key === 'Escape') setCmdk(false);
      if (!cmdk && !e.metaKey && !e.ctrlKey && !e.target.matches('input,textarea,select')) {
        if (e.key === 'f') { e.preventDefault(); setRoute('factuur_new'); }
        if (e.key === 'w') { e.preventDefault(); setRoute('werkdagen'); }
        if (e.key === 'd') { e.preventDefault(); setRoute('dashboard'); }
        if (e.key === 'b') { e.preventDefault(); setRoute('bank'); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [cmdk]);

  // Edit-mode bridge for Tweaks toolbar
  uE(() => {
    const onMsg = (e) => {
      if (e.data?.type === '__activate_edit_mode') setTweaks(true);
      if (e.data?.type === '__deactivate_edit_mode') setTweaks(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const setCfgKey = (k, v) => {
    const next = { ...cfg, [k]: v };
    setCfg(next);
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits: { [k]: v } }, '*');
  };

  const navGroups = [
    { label: 'Boekhouden', items: [
      { k: 'dashboard', l: 'Dashboard', ic: Ic.dashboard },
      { k: 'werkdagen', l: 'Werkdagen', ic: Ic.calendar, count: APPDATA.WERKDAGEN.filter(w => !w.factuurnummer).length },
      { k: 'facturen', l: 'Facturen', ic: Ic.invoice, count: APPDATA.FACTUREN.filter(f => f.status === 'concept').length || null },
      { k: 'kosten', l: 'Kosten', ic: Ic.cost },
      { k: 'bank', l: 'Bank', ic: Ic.bank, count: APPDATA.BANKTRX.filter(t => !t.categorie && !t.matched).length },
    ]},
    { label: 'Archief', items: [
      { k: 'docs', l: 'Documenten', ic: Ic.docs },
      { k: 'jaar', l: 'Jaarafsluiting', ic: Ic.archive },
      { k: 'aangifte', l: 'Aangifte', ic: Ic.tax },
    ]},
    { label: 'Beheer', items: [
      { k: 'klanten', l: 'Klanten', ic: Ic.users },
      { k: 'settings', l: 'Instellingen', ic: Ic.settings },
    ]},
  ];

  const pageTitles = {
    dashboard: 'Dashboard', werkdagen: 'Werkdagen', facturen: 'Facturen',
    kosten: 'Kosten', bank: 'Bank', docs: 'Documenten', jaar: 'Jaarafsluiting',
    aangifte: 'Aangifte', klanten: 'Klanten', settings: 'Instellingen',
    factuur_new: 'Facturen / Nieuw',
  };

  const cmdItems = [
    { group: 'Acties', icon: Ic.plus, label: 'Nieuwe werkdag', shortcut: ['W'], go: () => setRoute('werkdagen') },
    { group: 'Acties', icon: Ic.plus, label: 'Nieuwe factuur', shortcut: ['F'], go: () => setRoute('factuur_new') },
    { group: 'Acties', icon: Ic.plus, label: 'Nieuwe uitgave', shortcut: [], go: () => setRoute('kosten') },
    { group: 'Acties', icon: Ic.upload, label: 'Importeer Rabobank CSV', shortcut: [], go: () => setRoute('bank') },
    { group: 'Acties', icon: Ic.upload, label: 'Importeer factuur-PDF', shortcut: [], go: () => setRoute('facturen') },
    { group: 'Navigatie', icon: Ic.dashboard, label: 'Ga naar Dashboard', shortcut: ['D'], go: () => setRoute('dashboard') },
    { group: 'Navigatie', icon: Ic.calendar, label: 'Ga naar Werkdagen', shortcut: ['W'], go: () => setRoute('werkdagen') },
    { group: 'Navigatie', icon: Ic.invoice, label: 'Ga naar Facturen', shortcut: ['F'], go: () => setRoute('facturen') },
    { group: 'Navigatie', icon: Ic.bank, label: 'Ga naar Bank', shortcut: ['B'], go: () => setRoute('bank') },
    { group: 'Aangifte', icon: Ic.tax, label: 'Aangifte-overzicht 2026', shortcut: [], go: () => setRoute('aangifte') },
    { group: 'Aangifte', icon: Ic.archive, label: 'Jaarafsluiting 2025 bekijken', shortcut: [], go: () => setRoute('jaar') },
    { group: 'Klanten', icon: Ic.users, label: 'Nieuwe klant toevoegen', shortcut: [], go: () => setRoute('klanten') },
    ...APPDATA.KLANTEN.slice(0, 4).map(k => ({
      group: 'Klanten', icon: Ic.users, label: k.naam, shortcut: [], go: () => setRoute('klanten')
    })),
  ];
  const filteredCmd = cmdQ ? cmdItems.filter(i => i.label.toLowerCase().includes(cmdQ.toLowerCase())) : cmdItems;

  const runCmd = (i) => { filteredCmd[i]?.go(); setCmdk(false); };

  return (
    <div className="app" data-screen-label={pageTitles[route] || route}>
      {/* SIDEBAR */}
      <aside className="sidebar">
        <div className="brand">
          <div className="dot">B</div>
          {cfg.nav === 'expanded' && <>
            <div>
              <div style={{ fontWeight: 600 }}>Boekhouding</div>
              <div style={{ color: 'var(--ink-4)', fontSize: 10 }}>R.P. Berg — Huisarts</div>
            </div>
          </>}
        </div>

        <button className="nav-item" onClick={() => { setCmdk(true); setCmdQ(''); setCmdIdx(0); }} style={{ marginBottom: 8 }}>
          <Ic.search className="nav-ic"/>
          {cfg.nav === 'expanded' && <>
            <span style={{ color: 'var(--ink-3)' }}>Zoeken</span>
            <span className="count" style={{ fontSize: 9 }}>⌘K</span>
          </>}
        </button>

        {navGroups.map(g => (
          <React.Fragment key={g.label}>
            {cfg.nav === 'expanded' && <div className="nav-section">{g.label}</div>}
            {g.items.map(item => (
              <div key={item.k}
                className={`nav-item ${route === item.k || (route === 'factuur_new' && item.k === 'facturen') ? 'active' : ''}`}
                onClick={() => setRoute(item.k)}
                title={item.l}>
                <item.ic className="nav-ic"/>
                {cfg.nav === 'expanded' && <>
                  <span>{item.l}</span>
                  {item.count ? <span className="count">{item.count}</span> : null}
                </>}
              </div>
            ))}
          </React.Fragment>
        ))}

        <div className="sidebar-foot">
          <div className="avatar">RB</div>
          {cfg.nav === 'expanded' && (
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ color: 'var(--ink)', fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>R.P. Berg</div>
              <div style={{ fontSize: 10 }} className="mono">fiscaal jaar 2026</div>
            </div>
          )}
        </div>
      </aside>

      {/* MAIN */}
      <main className="main">
        <div className="topbar">
          <div className="crumbs">
            <span>Boekhouding</span>
            <span className="sep">/</span>
            <span className="cur">{pageTitles[route]}</span>
          </div>
          <div className="topbar-right">
            <button className="btn btn-ghost" onClick={() => { setCmdk(true); setCmdQ(''); setCmdIdx(0); }}>
              <Ic.search style={{ width: 14, height: 14 }}/>
              <span style={{ color: 'var(--ink-3)', fontSize: 12 }}>Zoek of begin te typen</span>
              <span className="kbd">⌘K</span>
            </button>
          </div>
        </div>

        {route === 'dashboard' && <Dashboard setRoute={setRoute}/>}
        {route === 'werkdagen' && <Werkdagen setRoute={setRoute}/>}
        {route === 'facturen' && <Facturen setRoute={setRoute}/>}
        {route === 'factuur_new' && <FactuurBuilder setRoute={setRoute}/>}
        {route === 'kosten' && <Kosten/>}
        {route === 'bank' && <Bank/>}
        {['docs', 'jaar', 'aangifte', 'klanten', 'settings'].includes(route) && <Placeholder title={pageTitles[route]}/>}
      </main>

      {/* COMMAND PALETTE */}
      {cmdk && (
        <div className="cmdk-overlay" onClick={() => setCmdk(false)}>
          <div className="cmdk" onClick={e => e.stopPropagation()}>
            <input
              className="cmdk-input"
              placeholder="Zoek acties, klanten, facturen…"
              autoFocus
              value={cmdQ}
              onChange={e => { setCmdQ(e.target.value); setCmdIdx(0); }}
              onKeyDown={e => {
                if (e.key === 'ArrowDown') { e.preventDefault(); setCmdIdx(Math.min(filteredCmd.length - 1, cmdIdx + 1)); }
                if (e.key === 'ArrowUp') { e.preventDefault(); setCmdIdx(Math.max(0, cmdIdx - 1)); }
                if (e.key === 'Enter') { e.preventDefault(); runCmd(cmdIdx); }
              }}
            />
            <div className="cmdk-list">
              {(() => {
                let lastGroup = '';
                return filteredCmd.map((item, i) => {
                  const g = item.group !== lastGroup ? item.group : null;
                  lastGroup = item.group;
                  return (
                    <React.Fragment key={i}>
                      {g && <div className="cmdk-group">{g}</div>}
                      <div className={`cmdk-item ${i === cmdIdx ? 'active' : ''}`} onClick={() => runCmd(i)} onMouseEnter={() => setCmdIdx(i)}>
                        <item.icon className="ic"/>
                        <span>{item.label}</span>
                        {item.shortcut.length > 0 && <div className="shortcut">{item.shortcut.map((s, j) => <span key={j}>{s}</span>)}</div>}
                      </div>
                    </React.Fragment>
                  );
                });
              })()}
              {filteredCmd.length === 0 && (
                <div className="cmdk-item" style={{ color: 'var(--ink-4)' }}>Geen resultaten voor "{cmdQ}"</div>
              )}
            </div>
            <div className="cmdk-foot">
              <span>↑↓ navigeren</span>
              <span>↵ kies</span>
              <span>esc sluiten</span>
            </div>
          </div>
        </div>
      )}

      {/* TWEAKS */}
      {tweaks && (
        <div className="tweaks">
          <div className="tweaks-head">
            <span>Tweaks</span>
            <button className="btn btn-ghost" style={{ padding: 2 }} onClick={() => setTweaks(false)}>
              <Ic.x style={{ width: 12, height: 12 }}/>
            </button>
          </div>
          <div className="tweaks-body">
            <div className="tweak-row">
              <label>Thema</label>
              <div className="seg">
                <button className={cfg.theme === 'light' ? 'on' : ''} onClick={() => setCfgKey('theme', 'light')}>Licht</button>
                <button className={cfg.theme === 'dark' ? 'on' : ''} onClick={() => setCfgKey('theme', 'dark')}>Donker</button>
              </div>
            </div>
            <div className="tweak-row">
              <label>Accent</label>
              <div className="swatches">
                {Object.keys(ACCENTS).map(a => (
                  <div key={a}
                    onClick={() => setCfgKey('accent', a)}
                    className={`swatch ${cfg.accent === a ? 'on' : ''}`}
                    style={{ background: ACCENTS[a][cfg.theme === 'dark' ? 'dark' : 'light'].accent }}
                  />
                ))}
              </div>
            </div>
            <div className="tweak-row">
              <label>Dichtheid</label>
              <div className="seg">
                <button className={cfg.density === 'compact' ? 'on' : ''} onClick={() => setCfgKey('density', 'compact')}>Compact</button>
                <button className={cfg.density === 'normal' ? 'on' : ''} onClick={() => setCfgKey('density', 'normal')}>Normaal</button>
                <button className={cfg.density === 'spacious' ? 'on' : ''} onClick={() => setCfgKey('density', 'spacious')}>Ruim</button>
              </div>
            </div>
            <div className="tweak-row">
              <label>Navigatie</label>
              <div className="seg">
                <button className={cfg.nav === 'expanded' ? 'on' : ''} onClick={() => setCfgKey('nav', 'expanded')}>Volledig</button>
                <button className={cfg.nav === 'compact' ? 'on' : ''} onClick={() => setCfgKey('nav', 'compact')}>Smal</button>
              </div>
            </div>
            <div className="tweak-row">
              <label>Font</label>
              <div className="seg">
                <button className={cfg.font === 'inter' ? 'on' : ''} onClick={() => setCfgKey('font', 'inter')}>Inter</button>
                <button className={cfg.font === 'geist' ? 'on' : ''} onClick={() => setCfgKey('font', 'geist')}>Geist</button>
                <button className={cfg.font === 'ibm' ? 'on' : ''} onClick={() => setCfgKey('font', 'ibm')}>IBM Plex</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const Placeholder = ({ title }) => (
  <div className="content">
    <div className="page-head">
      <div>
        <h1 className="page-title">{title}</h1>
        <div className="page-sub">Deze sectie is in de redesign-prototype nog niet uitgewerkt.</div>
      </div>
    </div>
    <div className="card" style={{ padding: 60, textAlign: 'center' }}>
      <div style={{ display: 'grid', placeItems: 'center', height: 60, color: 'var(--ink-4)' }}>
        <Ic.inbox style={{ width: 32, height: 32 }}/>
      </div>
      <div className="mono tiny muted mt-12">Vraag een vervolg om {title.toLowerCase()} te ontwerpen</div>
    </div>
  </div>
);

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
