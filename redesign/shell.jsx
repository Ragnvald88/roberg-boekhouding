/* SF Symbol-style icons (drawn) and SVG glyphs */
const Icon = ({ name, size = 16, color = 'currentColor', filled = false }) => {
  const s = size;
  const strokeWidth = filled ? 0 : 1.6;
  const common = { width: s, height: s, viewBox: '0 0 24 24', fill: filled ? color : 'none', stroke: color, strokeWidth, strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'chart': return <svg {...common}><path d="M4 19V5"/><path d="M9 19v-7"/><path d="M14 19v-4"/><path d="M19 19V9"/></svg>;
    case 'dashboard': return <svg {...common}><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>;
    case 'calendar': return <svg {...common}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>;
    case 'clock': return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>;
    case 'car': return <svg {...common}><path d="M5 17h14M6 13l1.5-4a2 2 0 0 1 1.9-1.4h5.2a2 2 0 0 1 1.9 1.4L18 13"/><rect x="3" y="13" width="18" height="5" rx="1.5"/><circle cx="7.5" cy="18" r="1.3" fill={color}/><circle cx="16.5" cy="18" r="1.3" fill={color}/></svg>;
    case 'doc': return <svg {...common}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></svg>;
    case 'people': return <svg {...common}><circle cx="9" cy="8" r="3"/><path d="M3 20c0-3 2.7-5 6-5s6 2 6 5"/><circle cx="17" cy="8.5" r="2.5"/><path d="M16 14.5c2.5.3 4 2 4 4.5"/></svg>;
    case 'reports': return <svg {...common}><path d="M4 19h16"/><path d="M7 16V9M12 16V5M17 16v-9"/></svg>;
    case 'settings': return <svg {...common}><circle cx="12" cy="12" r="3"/><path d="M19.4 14.5a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1c0 .7.4 1.3 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9c.2.6.8 1 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>;
    case 'plus': return <svg {...common}><path d="M12 5v14M5 12h14"/></svg>;
    case 'check': return <svg {...common}><path d="M5 12.5l4.5 4.5L19 7"/></svg>;
    case 'x': return <svg {...common}><path d="M6 6l12 12M18 6L6 18"/></svg>;
    case 'left': return <svg {...common}><path d="M14 6l-6 6 6 6"/></svg>;
    case 'right': return <svg {...common}><path d="M10 6l6 6-6 6"/></svg>;
    case 'edit': return <svg {...common}><path d="M16 4l4 4-12 12H4v-4z"/></svg>;
    case 'euro': return <svg {...common}><path d="M18 7a6 6 0 1 0 0 10M4 10h9M4 14h9"/></svg>;
    case 'warning': return <svg {...common}><path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/></svg>;
    case 'link': return <svg {...common}><path d="M10 14a3.5 3.5 0 0 0 5 0l3-3a3.5 3.5 0 0 0-5-5l-1 1"/><path d="M14 10a3.5 3.5 0 0 0-5 0l-3 3a3.5 3.5 0 0 0 5 5l1-1"/></svg>;
    case 'send': return <svg {...common}><path d="M3 11l18-7-7 18-2.5-7.5z"/></svg>;
    case 'sparkle': return <svg {...common}><path d="M12 4v4M12 16v4M4 12h4M16 12h4M6.5 6.5l2.5 2.5M15 15l2.5 2.5M6.5 17.5l2.5-2.5M15 9l2.5-2.5"/></svg>;
    case 'menu': return <svg {...common}><path d="M4 7h16M4 12h16M4 17h16"/></svg>;
    case 'search': return <svg {...common}><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>;
    case 'bell': return <svg {...common}><path d="M6 17h12l-2-3V10a4 4 0 0 0-8 0v4z"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>;
    case 'home': return <svg {...common}><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-7h-6v7H4a1 1 0 0 1-1-1z"/></svg>;
    case 'pin': return <svg {...common}><path d="M12 21v-7M8 4h8l-1 6 3 2H6l3-2z"/></svg>;
    default: return <svg {...common}><circle cx="12" cy="12" r="3"/></svg>;
  }
};

const Sidebar = ({ active, onSelect }) => {
  const main = [
    { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
    { id: 'agenda', label: 'Agenda', icon: 'calendar' },
    { id: 'time', label: 'Tijdregistratie', icon: 'clock' },
    { id: 'mileage', label: 'Kilometrage', icon: 'car' },
    { id: 'invoices', label: 'Facturen', icon: 'doc' },
  ];
  const mgmt = [
    { id: 'clients', label: 'Klanten', icon: 'people' },
    { id: 'reports', label: 'Rapporten', icon: 'reports' },
    { id: 'settings', label: 'Instellingen', icon: 'settings' },
  ];

  // Live computed stats
  const monthEarnings = TIME_ENTRIES
    .filter(e => !e.isPlanned && e.date.getMonth() === TODAY.getMonth() && e.date.getFullYear() === TODAY.getFullYear())
    .reduce((a, e) => a + e.billable, 0);
  const monthHours = TIME_ENTRIES
    .filter(e => !e.isPlanned && e.date.getMonth() === TODAY.getMonth() && e.date.getFullYear() === TODAY.getFullYear())
    .reduce((a, e) => a + e.hours, 0);
  const unpaidAmt = INVOICES
    .filter(i => i.status === 'pending' || i.status === 'overdue')
    .reduce((a, i) => a + i.total, 0);
  const unpaidCount = INVOICES.filter(i => i.status === 'pending' || i.status === 'overdue').length;

  return (
    <aside className="sidebar">
      <div className="sb-header">
        <div className="sb-header-icon"><Icon name="chart" size={18} color="white" /></div>
        <div className="sb-header-text">
          <h1>BookKeeper Pro</h1>
          <p>Medical Invoice System</p>
        </div>
      </div>
      <div className="sb-scroll">
        <div className="sb-section">
          <div className="sb-section-title">Hoofdmenu</div>
          {main.map(t => (
            <div key={t.id} className={'sb-item' + (active === t.id ? ' active' : '')} onClick={() => onSelect && onSelect(t.id)}>
              <span className="sb-icon"><Icon name={t.icon} size={15} /></span>
              {t.label}
            </div>
          ))}
        </div>
        <div className="sb-section">
          <div className="sb-section-title">Beheer</div>
          {mgmt.map(t => (
            <div key={t.id} className={'sb-item' + (active === t.id ? ' active' : '')} onClick={() => onSelect && onSelect(t.id)}>
              <span className="sb-icon"><Icon name={t.icon} size={15} /></span>
              {t.label}
            </div>
          ))}
        </div>
        <div className="sb-section">
          <div className="sb-section-title">Overzicht</div>
          <div className="sb-stats">
            <div className="sb-stat-row">
              <div className="sb-stat-icon" style={{background:'rgba(52,199,89,0.12)', color:'#34C759'}}><Icon name="euro" size={15} /></div>
              <div className="sb-stat-body">
                <div className="sb-stat-title">Deze maand</div>
                <div className="sb-stat-value mono">{fmtEUR.format(monthEarnings)}</div>
              </div>
              <div className="sb-stat-trend" style={{color:'#34C759'}}>↗ 12%</div>
            </div>
            <div className="sb-stat-row">
              <div className="sb-stat-icon" style={{background:'rgba(0,122,255,0.12)', color:'#007AFF'}}><Icon name="clock" size={15} /></div>
              <div className="sb-stat-body">
                <div className="sb-stat-title">Gewerkte uren</div>
                <div className="sb-stat-value mono">{Math.round(monthHours)} uur</div>
              </div>
            </div>
            {unpaidCount > 0 && (
              <div className="sb-stat-row">
                <div className="sb-stat-icon" style={{background:'rgba(255,149,0,0.12)', color:'#FF9500'}}><Icon name="warning" size={15} /></div>
                <div className="sb-stat-body">
                  <div className="sb-stat-title">Onbetaald</div>
                  <div className="sb-stat-value mono">{fmtEUR.format(unpaidAmt)}</div>
                </div>
                <div className="sb-stat-trend" style={{color:'#FF9500'}}>{unpaidCount}</div>
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="sb-footer">
        <div className="sb-user">
          <div className="sb-avatar">RH</div>
          <div style={{flex:1, minWidth:0}}>
            <div style={{fontSize:12, fontWeight:600}}>Ronald Hoekstra</div>
            <div style={{fontSize:10, color:'var(--ink-3)'}}>Huisarts · Waarneming</div>
          </div>
        </div>
      </div>
    </aside>
  );
};

const Topbar = ({ title, children }) => (
  <header className="topbar">
    <h2 className="rounded">{title}</h2>
    <div className="topbar-spacer" />
    <div className="topbar-actions">{children}</div>
  </header>
);

Object.assign(window, { Icon, Sidebar, Topbar });
