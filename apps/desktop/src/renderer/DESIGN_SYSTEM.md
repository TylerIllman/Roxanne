# Roxanne Design System

Reference guide for all UI tokens and component patterns. Follow these rules when adding or modifying any UI code.

---

## Colour Palette

| Role | Token | Usage |
|------|-------|-------|
| **Primary text** | `text-zinc-900` | Headings, body text, active items |
| **Secondary text** | `text-zinc-500` | Descriptions, inactive sidebar items |
| **Muted text** | `text-zinc-400` | Hints, placeholders, timestamps |
| **Primary bg** | `bg-white` | Main content, cards, modals |
| **Secondary bg** | `bg-zinc-50` | Sidebar, inset panels, hover states |
| **Tertiary bg** | `bg-zinc-100` | Active states, pressed, badges |
| **Border** | `border-zinc-200` | All borders — no opacity variants |
| **Accent green** | `emerald-{50,200,700}` | Success states, active indicators |
| **Accent amber** | `amber-{50,200,700}` | Warnings, progress, setup prompts |
| **Accent red** | `red-{50,200,500}` | Errors, destructive actions |
| **Accent blue** | `blue-{50,200,700}` | Links, citations, info |

### Rules
- Never use opacity modifiers on borders or backgrounds (no `border-zinc-200/60`, `bg-zinc-50/80`).
- Never use `zinc-950` — use `zinc-900` instead.
- Never use `zinc-300` for borders — always `zinc-200`.

---

## Typography

| Scale | Token | Usage |
|-------|-------|-------|
| **Base** | `text-base` (16px) | Page titles, wizard headings |
| **Body** | `text-sm` (14px) | Body text, input values, buttons (default) |
| **Small** | `text-xs` (12px) | Labels, hints, badges, sidebar items, buttons (sm) |

### Rules
- Only use `text-xs`, `text-sm`, `text-base`. Never use custom sizes like `text-[0.65rem]`.
- Labels: `text-xs font-semibold text-zinc-900 uppercase tracking-wide`
- Section headers: `text-xs font-bold text-zinc-400 uppercase tracking-wider`
- Hints: `text-xs text-zinc-400`

---

## Spacing

### Gaps (between siblings)
| Token | Px | Usage |
|-------|-----|-------|
| `gap-1` | 4 | Tight groups (icon + text, dot indicators) |
| `gap-2` | 8 | Standard list items, form fields within a group |
| `gap-3` | 12 | Between form sections, card content |
| `gap-4` | 16 | Between major sections |
| `gap-6` | 24 | Between top-level page sections |

### Padding
| Token | Usage |
|-------|-------|
| `px-3 py-2` | Standard interactive items (list rows, sidebar items) |
| `px-4 py-3` | Cards, panels, modal content |
| `p-3` | Inset card content |
| `p-4` | Modal/wizard card body |
| `px-5 py-3` | Page-level horizontal padding |
| `px-6 py-8` | Centered settings content |

### Rules
- Never use `.5` fractional spacing for gaps (`gap-1.5`, `gap-2.5`).
- Padding can use `py-0.5`, `px-1` for tiny elements (badges, inline pills).
- Avoid `px-3.5`, `py-3.5` — round to `px-4`/`py-3` or `px-3`/`py-4`.

---

## Border Radius

| Token | Usage |
|-------|-------|
| `rounded-lg` | **Default** — cards, panels, buttons, inputs, modals, dropdowns, list items |
| `rounded-full` | Badges, pills, switches, dot indicators, avatar circles |
| `rounded-2xl` | Chat message bubbles only |

### Rules
- Never use `rounded-md`, `rounded-xl`, `rounded-3xl`.
- Chat bubbles use `rounded-2xl rounded-br-sm` (user) / `rounded-2xl rounded-bl-sm` (assistant).

---

## Shadows

| Token | Usage |
|-------|-------|
| `shadow-sm` | Elevated cards, active sidebar items, buttons (default variant) |
| `shadow-lg` | Overlays only: toasts, tooltips, dropdowns |

### Rules
- Never use `shadow-2xl` or custom shadow values.
- Most elements should have no shadow — only use when showing elevation.

---

## Transitions

| Token | Usage |
|-------|-------|
| `transition-colors` | **Default** — all hover/focus state changes |
| `transition-all duration-300` | Progress bar width animations only |

### Rules
- Never use `transition-all` for hover effects.
- Never use `transition-all duration-150` or custom durations for interactive elements.

---

## Focus States

All interactive elements use:
```
focus-visible:ring-2 focus-visible:ring-zinc-900/20
```

Inputs additionally get:
```
focus-visible:border-zinc-400
```

---

## Component Patterns

### Button (use `<Button>` component)
```
variant="default"   → bg-zinc-900 text-white, h-9 px-4
variant="outline"   → border border-zinc-200 bg-white, h-9 px-4
variant="secondary"  → bg-zinc-100 text-zinc-900, h-9 px-4
variant="ghost"      → transparent, hover:bg-zinc-100
size="sm"            → h-8 px-3 text-xs
```

Never style inline buttons with ad-hoc classes when `<Button>` fits.

### Status Indicator Row
```tsx
<div className={cn(
  "flex items-center gap-2 px-3 py-2 border rounded-lg text-xs",
  ready
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : "border-zinc-200 bg-zinc-50 text-zinc-500"
)}>
  <span className={cn("shrink-0 w-5 h-5 grid place-items-center rounded-full",
    ready ? "bg-emerald-100" : "bg-zinc-200"
  )}>
    {ready ? <IconCheck className="w-3 h-3" /> : <span className="w-1.5 h-1.5 rounded-full bg-zinc-400" />}
  </span>
  <span className="font-medium">{label}</span>
  <span className="ml-auto font-medium">{ready ? "Installed" : "Not installed"}</span>
</div>
```

### Selectable List Item (voices, models, conversations)
```tsx
<div className={cn(
  "flex items-center gap-2 px-3 py-2 border rounded-lg text-xs cursor-pointer transition-colors",
  isActive
    ? "border-zinc-900 bg-zinc-50 ring-1 ring-zinc-900"
    : isInstalled
      ? "border-zinc-200 hover:bg-zinc-50"
      : "border-zinc-200 bg-zinc-50 text-zinc-400"
)}>
```

### Progress Bar
```tsx
<div className="w-full h-1.5 bg-zinc-100 rounded-full overflow-hidden">
  <div
    className="h-full bg-zinc-900 rounded-full transition-all duration-300"
    style={{ width: `${percent}%` }}
  />
</div>
```

For amber/warning progress:
```tsx
<div className="w-full h-1.5 bg-amber-100 rounded-full overflow-hidden">
  <div className="h-full bg-amber-500 rounded-full transition-all duration-300" style={{ width: `${percent}%` }} />
</div>
```

### Section Header (in settings/panels)
```tsx
<h3 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">Section Name</h3>
```

### Field with Label + Hint
```tsx
<Field label="Field name" hint="Optional helper text.">
  <Input ... />
</Field>
```

### Card / Inset Panel
```tsx
<div className="flex flex-col gap-2 p-3 border border-zinc-200 rounded-lg bg-zinc-50">
  ...
</div>
```

### Toast Notification
```tsx
<div className={cn(
  "flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg border backdrop-blur-sm",
  tone === "success" && "bg-emerald-50 border-emerald-200 text-emerald-800",
  tone === "error" && "bg-red-50 border-red-200 text-red-800",
)}>
```

### Sidebar Navigation Item
```tsx
<button className={cn(
  "flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors w-full",
  isActive
    ? "bg-white text-zinc-900 shadow-sm border border-zinc-200"
    : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-700"
)}>
```

---

## Layout

### App Shell
```
grid grid-cols-[240px_minmax(0,1fr)]
```
- Sidebar: 240px, `bg-zinc-50`, border-right
- Main: flexible, `bg-white`

### Frameless Window
- macOS: `titleBarStyle: "hiddenInset"`, traffic lights at `{ x: 16, y: 16 }`
- Draggable areas: `style={{ WebkitAppRegion: "drag" }}`
- Interactive elements inside draggable areas: `style={{ WebkitAppRegion: "no-drag" }}`

### Settings
- Full-screen overlay: `fixed inset-0 z-50 bg-white`
- Horizontal tab bar at top
- Content centred: `max-w-xl mx-auto py-8 px-6`
- Auto-saves on change (800ms debounce)

### Chat Bubbles
- User: `bg-zinc-900 text-white rounded-2xl rounded-br-sm`
- Assistant: `bg-white border border-zinc-200 rounded-2xl rounded-bl-sm shadow-sm`
- Max width: `max-w-[min(85%,720px)]`
