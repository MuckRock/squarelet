# Staff KPI dashboard

Bring the login metrics from `allanlasser/kpi-dashboard` into Squarelet, read
straight from `LoginLog` instead of CSV exports.

## Scope

- Monthly active users: total and per service.
- Multi-service usage: users who logged in to 2+ services in a month, total and,
  per service, the share of that service's users who also used another.
- Out of scope: paid/free split, FOIA, DocumentCloud and revenue tabs.

## Decisions

- **Charts: LayerChart 2.** Svelte 5-native and built on D3; gives axes,
  tooltips and responsive sizing without hand-rolled D3. The prototype already
  used it. Imported only by the `kpi_dashboard` Vite entry.
- **Service = OIDC client name.** Clients sharing a name count as one service.
- **Months are local (America/New_York)** and the window is the trailing 24
  months. Charts and headline tiles use complete months; the table can show
  the month to date.
- **One SQL query** (CTE of month, user, services) computes everything; results
  are cached for an hour. A concurrent index on `LoginLog.created_at` bounds
  the scan.

## Pieces

- `squarelet/statistics/kpis.py` - `monthly_activity`, `cached_monthly_activity`
- `squarelet/statistics/views.py`, `urls.py` - `/statistics/kpis/`, staff only
- `squarelet/templates/statistics/kpis.html` - `json_script` payload
- `frontend/views/kpi_dashboard.ts`, `frontend/components/kpis/`
- `squarelet/users/migrations/0016_loginlog_created_at_index.py`
