# TOF Clinical design system

Reference: `dashboard-concept.png`. The primary workspace is a true white canvas
with a pale sage navigation rail, a quiet header, a horizontal metric strip, and
schedule/task lists. Charts and encounter editors extend the same visual system.

- UI: TOF's Manrope family, system sans fallback. Identifier font: monospace.
- Text: charcoal green, muted slate. Forest-green primary action, pale-green
  selections. Hairline gray-green borders. No decorative gradients.
- Primary heading: 30–32px semibold with tight tracking; section headings 18–20px;
  controls and body 13–14px; metadata 11–12px.
- Navigation: 220px desktop sidebar, 56–64px top bar, 28–32px content gutter.
- Components: flat metric strip, 1px bordered tables, compact status labels,
  initials avatars, outline icons, restrained modal forms and encounter editor.
- Responsive: collapse navigation on narrow screens, stack schedule/tasks,
  preserve readable tables with contained scrolling, keep forms within viewport.
- All controls and text are native UI; the concept image is a reference only.
- Concept deviations are functional: counts/dates come from the database;
  recent patients are labeled honestly; the connection is not labeled active
  until independently verified. Development data is always identified as synthetic.

Source for the family and sizing: read-only inspection of
`tof-ai-app/app/assets/stylesheets/typography.css`. The requested light/green
scheme adapts the existing TOF light Operator Academy palette; no TOF source
asset or code was modified.
