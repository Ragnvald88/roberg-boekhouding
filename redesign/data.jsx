/* Mock data aligned to BookKeeperPro SwiftData models + recurring/holidays extension.

   Existing models (Swift):
     Client { name, hourlyRate, mileageRate, shortAddress, ... }
     TimeEntry { date, startTime, endTime, hours, hourlyRate, client, description, isConfirmed, invoiceID }
     MileageEntry { date, distance, isRoundTrip, rate, client }
     Invoice { number, isPaid/isDraft/isOverdue, client, total, dueDate }

   Proposed extensions (mirrored here for the design):
     Client.recurringPattern: {
       weekdays: [Mon..],            // 1=Mon..7=Sun (ISO)
       startHour, endHour,           // default day window
       description,                  // default text
       active: bool, validFrom, validUntil
     }
     Blocker { date(s), kind: 'holiday'|'vacation'|'sick'|'training', label }
       Holiday list comes from a built-in Dutch national holiday calc + user blockers.
*/

const TODAY = new Date(2026, 4, 13); // 13 mei 2026 (woensdag) — mid-month for richer demo
TODAY.setHours(0, 0, 0, 0);

// === Clients with recurring patterns ===
// weekdays: ISO 1=Mon..7=Sun
const CLIENTS = [
  {
    id: 'c1', name: 'Huisartsenpraktijk Centrum', short: 'HAP Centrum',
    city: 'Groningen', km: 6, rate: 82.50, color: '#007AFF',
    pattern: { weekdays: [1, 3], startHour: 8, endHour: 17, description: 'Waarneming dagpraktijk' },
  },
  {
    id: 'c2', name: 'Huisartsenpraktijk De Linde', short: 'HAP De Linde',
    city: 'Haren', km: 12, rate: 80.00, color: '#34C759',
    pattern: { weekdays: [2, 4], startHour: 8, endHour: 17, description: 'Waarneming dagpraktijk' },
  },
  {
    id: 'c3', name: 'Praktijk Westerkwartier', short: 'Westerkwartier',
    city: 'Zuidhorn', km: 22, rate: 77.50, color: '#FF9500',
    pattern: { weekdays: [5], startHour: 8, endHour: 16.5, description: 'Vrijdag dagpraktijk' },
  },
  {
    id: 'c4', name: 'HAP Hoogeveen Spoed', short: 'HAP Hoogeveen',
    city: 'Hoogeveen', km: 54, rate: 95.00, color: '#AF52DE',
    pattern: null, // ad-hoc shifts only
  },
  {
    id: 'c5', name: 'Doktersdienst Drenthe', short: 'DDD',
    city: 'Assen', km: 28, rate: 90.00, color: '#FF3B30',
    pattern: null, // weekend / on-call
  },
];
const CLIENT_BY_ID = Object.fromEntries(CLIENTS.map(c => [c.id, c]));

// === Dutch national holidays (computed for any year) ===
function easterSunday(year) {
  const a = year % 19, b = Math.floor(year/100), c = year % 100;
  const d = Math.floor(b/4), e = b % 4;
  const f = Math.floor((b+8)/25), g = Math.floor((b-f+1)/3);
  const h = (19*a + b - d - g + 15) % 30;
  const i = Math.floor(c/4), k = c % 4;
  const L = (32 + 2*e + 2*i - h - k) % 7;
  const m = Math.floor((a + 11*h + 22*L)/451);
  const month = Math.floor((h + L - 7*m + 114)/31);
  const day = ((h + L - 7*m + 114) % 31) + 1;
  return new Date(year, month-1, day);
}
function dutchHolidays(year) {
  const easter = easterSunday(year);
  const add = (d, n) => { const x = new Date(d); x.setDate(x.getDate()+n); return x; };
  return [
    { date: new Date(year, 0, 1),   label: 'Nieuwjaarsdag' },
    { date: add(easter, -2),        label: 'Goede Vrijdag' },
    { date: easter,                 label: 'Eerste Paasdag' },
    { date: add(easter, 1),         label: 'Tweede Paasdag' },
    { date: new Date(year, 3, 27),  label: 'Koningsdag' },
    { date: new Date(year, 4, 5),   label: 'Bevrijdingsdag' },
    { date: add(easter, 39),        label: 'Hemelvaart' },
    { date: add(easter, 49),        label: 'Eerste Pinksterdag' },
    { date: add(easter, 50),        label: 'Tweede Pinksterdag' },
    { date: new Date(year, 11, 25), label: 'Eerste Kerstdag' },
    { date: new Date(year, 11, 26), label: 'Tweede Kerstdag' },
  ];
}

// User blockers (vacation, sick, training)
const BLOCKERS = [
  // Spring break vacation
  ...[6,7,8,9,10].map(d => ({ date: new Date(2026, 3, d), kind: 'vacation', label: 'Vakantie' })),
  // Training day
  { date: new Date(2026, 4, 21), kind: 'training', label: 'NHG nascholing' },
  // Summer plan
  ...Array.from({length: 14}, (_,i) => ({ date: new Date(2026, 6, 13+i), kind: 'vacation', label: 'Zomervakantie' })),
];

const dateKey = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');

// Build holiday + blocker map
const BLOCKED = new Map();
function addBlocked(d, kind, label) {
  const k = dateKey(d);
  if (!BLOCKED.has(k)) BLOCKED.set(k, { kind, label });
}
for (const y of [2025, 2026, 2027]) {
  for (const h of dutchHolidays(y)) addBlocked(h.date, 'holiday', h.label);
}
for (const b of BLOCKERS) addBlocked(b.date, b.kind, b.label);

// === Build confirmed time entries ===
const TIME_ENTRIES = [];
const INVOICES = [];

let entryId = 1, invoiceId = 1000;
const descriptions = [
  'Waarneming dagpraktijk',
  'Avonddienst HAP',
  'Weekenddienst',
  'Spoedpost dagdienst',
];

function makeEntry({ date, clientId, startH, endH, descIdx, isPlanned, invoiceStatus, fromRecurring }) {
  const c = CLIENT_BY_ID[clientId];
  const start = new Date(date); start.setHours(Math.floor(startH), Math.round((startH%1)*60), 0, 0);
  const end = new Date(date); end.setHours(Math.floor(endH), Math.round((endH%1)*60), 0, 0);
  const hours = (end - start) / 3600000;
  const mileage = c.km * 2;
  const mileageAmt = mileage * 0.23;
  const billable = hours * c.rate + mileageAmt;
  return {
    id: 'e' + (entryId++),
    date: new Date(date.getFullYear(), date.getMonth(), date.getDate()),
    start, end, hours,
    clientId, client: c,
    description: descriptions[descIdx % descriptions.length],
    rate: c.rate,
    mileage, mileageAmt, billable,
    isPlanned: !!isPlanned,
    fromRecurring: !!fromRecurring, // true = expected from pattern, not yet confirmed
    invoiceId: null,
    invoiceStatus: invoiceStatus || null,
  };
}

let seed = 11;
function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }

// 1) Generate CONFIRMED past entries — mostly following recurring patterns
//    (so the calendar shows recurring days actually being honored)
const monthsRange = [
  [2026, 0], [2026, 1], [2026, 2], [2026, 3], [2026, 4],
];

for (const [y, m] of monthsRange) {
  const lastDay = new Date(y, m + 1, 0).getDate();
  for (let day = 1; day <= lastDay; day++) {
    const dt = new Date(y, m, day);
    if (dt > TODAY) break;
    const k = dateKey(dt);
    if (BLOCKED.has(k)) continue;
    const iso = ((dt.getDay() + 6) % 7) + 1;

    // Find any client with this weekday in pattern
    const candidates = CLIENTS.filter(c => c.pattern && c.pattern.weekdays.includes(iso));
    if (candidates.length === 0) continue;
    // Skip ~10% to mimic real life (sick day, swap)
    if (rnd() < 0.1) continue;

    const c = candidates[Math.floor(rnd() * candidates.length)];
    let status = null;
    if (m <= 1) status = 'paid';
    else if (m === 2) status = rnd() > 0.15 ? 'paid' : 'pending';
    else if (m === 3) status = rnd() > 0.55 ? 'paid' : (rnd() > 0.4 ? 'pending' : 'overdue');
    else status = rnd() > 0.6 ? 'pending' : 'draft';

    TIME_ENTRIES.push(makeEntry({
      date: dt, clientId: c.id,
      startH: c.pattern.startHour, endH: c.pattern.endHour,
      descIdx: 0, invoiceStatus: status,
    }));
  }
}

// 2) Sprinkle a few ad-hoc shifts (HAP Hoogeveen, weekend DDD)
for (const [y, m] of monthsRange) {
  const lastDay = new Date(y, m + 1, 0).getDate();
  let n = 0;
  while (n < 4) {
    const day = 1 + Math.floor(rnd() * lastDay);
    const dt = new Date(y, m, day);
    if (dt > TODAY) break;
    const k = dateKey(dt);
    if (BLOCKED.has(k)) { n++; continue; }
    const dow = dt.getDay();
    const c = (dow === 0 || dow === 6) ? CLIENT_BY_ID.c5 : CLIENT_BY_ID.c4;
    // Don't double-book
    const exists = TIME_ENTRIES.some(e => sameDay(e.date, dt));
    if (exists) { n++; continue; }
    let status = null;
    if (m <= 1) status = 'paid';
    else if (m === 2) status = 'pending';
    else if (m === 3) status = rnd() > 0.5 ? 'pending' : 'overdue';
    else status = 'draft';
    TIME_ENTRIES.push(makeEntry({
      date: dt, clientId: c.id,
      startH: dow === 0 || dow === 6 ? 9 : 17,
      endH: dow === 0 || dow === 6 ? 17 : 23,
      descIdx: dow === 0 || dow === 6 ? 2 : 1,
      invoiceStatus: status,
    }));
    n++;
  }
}

// 3) PLANNED concrete future entries (already confirmed in calendar/EventKit)
//    — a couple of HAP shifts already scheduled
const futurePlans = [
  { date: new Date(2026, 4, 15), clientId: 'c4', startH: 17, endH: 23, descIdx: 1 },
  { date: new Date(2026, 4, 16), clientId: 'c5', startH: 9,  endH: 17, descIdx: 2 },
  { date: new Date(2026, 4, 30), clientId: 'c5', startH: 9,  endH: 17, descIdx: 2 },
  { date: new Date(2026, 5, 6),  clientId: 'c4', startH: 17, endH: 23, descIdx: 1 },
];
for (const p of futurePlans) {
  if (BLOCKED.has(dateKey(p.date))) continue;
  TIME_ENTRIES.push(makeEntry({ ...p, isPlanned: true }));
}

// 4) Generate invoices grouped by client+month for billed entries
const invoiceGroups = {};
for (const e of TIME_ENTRIES) {
  if (e.isPlanned) continue;
  if (!e.invoiceStatus || e.invoiceStatus === 'draft') continue;
  const key = e.clientId + '-' + e.date.getFullYear() + '-' + e.date.getMonth();
  if (!invoiceGroups[key]) invoiceGroups[key] = { clientId: e.clientId, year: e.date.getFullYear(), month: e.date.getMonth(), entries: [], status: e.invoiceStatus };
  invoiceGroups[key].entries.push(e);
}
for (const k in invoiceGroups) {
  const g = invoiceGroups[k];
  const num = '2026-' + String(invoiceId++).padStart(4, '0');
  const total = g.entries.reduce((a, e) => a + e.billable, 0);
  INVOICES.push({ id: num, number: num, clientId: g.clientId, total, status: g.status, year: g.year, month: g.month });
  for (const e of g.entries) e.invoiceId = num;
}

// === Index by date ===
const ENTRIES_BY_DATE = new Map();
for (const e of TIME_ENTRIES) {
  const k = dateKey(e.date);
  if (!ENTRIES_BY_DATE.has(k)) ENTRIES_BY_DATE.set(k, []);
  ENTRIES_BY_DATE.get(k).push(e);
}

// === Compute EXPECTED entries from recurring patterns (read-only ghosts) ===
// Returns expected pseudo-entries for a given date, only if:
//   - date is in the future or today
//   - date is not blocked
//   - no real entry already covers this client/day (avoid duplication)
function expectedEntriesForDate(d) {
  if (d < TODAY) return [];
  const k = dateKey(d);
  if (BLOCKED.has(k)) return [];
  const iso = ((d.getDay() + 6) % 7) + 1;
  const real = ENTRIES_BY_DATE.get(k) || [];
  const realClients = new Set(real.map(e => e.clientId));
  const out = [];
  for (const c of CLIENTS) {
    if (!c.pattern || !c.pattern.weekdays.includes(iso)) continue;
    if (realClients.has(c.id)) continue;
    out.push(makeEntry({
      date: d, clientId: c.id,
      startH: c.pattern.startHour, endH: c.pattern.endHour,
      descIdx: 0, isPlanned: true, fromRecurring: true,
    }));
  }
  return out;
}

// === Week aggregates (confirmed + planned + expected) ===
function weekAggregate(weekStart) {
  let confirmedAmt = 0, plannedAmt = 0, expectedAmt = 0;
  let confirmedH = 0, plannedH = 0, expectedH = 0;
  let confirmedD = 0, plannedD = 0, expectedD = 0;
  let blockedD = 0;
  for (let i = 0; i < 7; i++) {
    const d = addDays(weekStart, i);
    const k = dateKey(d);
    if (BLOCKED.has(k)) { blockedD++; continue; }
    const real = ENTRIES_BY_DATE.get(k) || [];
    const expected = expectedEntriesForDate(d);
    const dayHasReal = real.length > 0;
    const dayHasExpected = expected.length > 0;
    if (dayHasReal) {
      let dayHasConfirmed = false, dayHasPlanned = false;
      for (const e of real) {
        if (e.isPlanned) { plannedAmt += e.billable; plannedH += e.hours; dayHasPlanned = true; }
        else { confirmedAmt += e.billable; confirmedH += e.hours; dayHasConfirmed = true; }
      }
      if (dayHasConfirmed) confirmedD++;
      else if (dayHasPlanned) plannedD++;
    }
    if (dayHasExpected && !dayHasReal) {
      for (const e of expected) { expectedAmt += e.billable; expectedH += e.hours; }
      expectedD++;
    }
  }
  return {
    confirmedAmt, plannedAmt, expectedAmt,
    totalAmt: confirmedAmt + plannedAmt + expectedAmt,
    confirmedH, plannedH, expectedH,
    totalH: confirmedH + plannedH + expectedH,
    confirmedD, plannedD, expectedD, blockedD,
  };
}

const fmtEUR  = new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });
const fmtEUR2 = new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2 });
const fmtHrs = (h) => Number.isInteger(h) ? `${h} uur` : `${h.toFixed(1).replace('.', ',')} uur`;
const fmtTime = (d) => `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
const fmtDateLong = (d) => d.toLocaleDateString('nl-NL', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
const fmtDateShort = (d) => d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });

const STATUS_META = {
  paid:    { label: 'Betaald',     color: '#34C759', icon: 'checkmark.circle.fill' },
  pending: { label: 'Open',        color: '#FF9500', icon: 'clock.fill' },
  overdue: { label: 'Vervallen',   color: '#FF3B30', icon: 'exclamationmark.triangle.fill' },
  draft:   { label: 'Nog niet gefactureerd', color: '#8E8E93', icon: 'doc.text' },
};

const BLOCKER_META = {
  holiday:  { label: 'Feestdag',    color: '#FF3B30', soft: 'rgba(255,59,48,0.10)' },
  vacation: { label: 'Vakantie',    color: '#5AC8FA', soft: 'rgba(90,200,250,0.14)' },
  sick:     { label: 'Ziek',        color: '#FF9500', soft: 'rgba(255,149,0,0.12)' },
  training: { label: 'Nascholing',  color: '#AF52DE', soft: 'rgba(175,82,222,0.12)' },
};

function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function startOfWeek(d) { const x = new Date(d); const day = (x.getDay() + 6) % 7; x.setDate(x.getDate() - day); x.setHours(0,0,0,0); return x; }
function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function addMonths(d, n) { return new Date(d.getFullYear(), d.getMonth() + n, 1); }
function sameDay(a, b) { return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate(); }
function isoWeekNum(d) {
  const x = new Date(d);
  x.setHours(0,0,0,0);
  x.setDate(x.getDate() + 3 - ((x.getDay() + 6) % 7));
  const week1 = new Date(x.getFullYear(), 0, 4);
  return 1 + Math.round(((x - week1) / 86400000 - 3 + ((week1.getDay() + 6) % 7)) / 7);
}

Object.assign(window, {
  TODAY, CLIENTS, CLIENT_BY_ID, TIME_ENTRIES, INVOICES, ENTRIES_BY_DATE, BLOCKED,
  STATUS_META, BLOCKER_META, fmtEUR, fmtEUR2, fmtHrs, fmtTime, fmtDateLong, fmtDateShort, dateKey,
  startOfMonth, startOfWeek, addDays, addMonths, sameDay, isoWeekNum,
  expectedEntriesForDate, weekAggregate,
});
