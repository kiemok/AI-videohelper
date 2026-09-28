---
name: Deep Telemetry & Intelligence Workspace
colors:
  surface: '#10131e'
  surface-dim: '#10131e'
  surface-bright: '#363945'
  surface-container-lowest: '#0b0e18'
  surface-container-low: '#181b26'
  surface-container: '#1c1f2a'
  surface-container-high: '#272a35'
  surface-container-highest: '#313440'
  on-surface: '#e0e1f1'
  on-surface-variant: '#bdc8d1'
  inverse-surface: '#e0e1f1'
  inverse-on-surface: '#2d303c'
  outline: '#87929b'
  outline-variant: '#3e4850'
  surface-tint: '#7ed0ff'
  primary: '#7ed0ff'
  on-primary: '#00344a'
  primary-container: '#00aeec'
  on-primary-container: '#003d56'
  inverse-primary: '#00658b'
  secondary: '#d0bcff'
  on-secondary: '#3c0091'
  secondary-container: '#571bc1'
  on-secondary-container: '#c4abff'
  tertiary: '#ffb3b6'
  on-tertiary: '#680019'
  tertiary-container: '#ff7883'
  on-tertiary-container: '#78001f'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#c5e7ff'
  primary-fixed-dim: '#7ed0ff'
  on-primary-fixed: '#001e2d'
  on-primary-fixed-variant: '#004c6a'
  secondary-fixed: '#e9ddff'
  secondary-fixed-dim: '#d0bcff'
  on-secondary-fixed: '#23005c'
  on-secondary-fixed-variant: '#5516be'
  tertiary-fixed: '#ffdada'
  tertiary-fixed-dim: '#ffb3b6'
  on-tertiary-fixed: '#40000c'
  on-tertiary-fixed-variant: '#920027'
  background: '#10131e'
  on-background: '#e0e1f1'
  surface-variant: '#313440'
typography:
  headline-xl:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 26px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Geist
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 22px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  body-md:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  body-sm:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.01em
  label-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: -0.01em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.03em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.75rem
  margin: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style
The design system delivers an ultra-focused, high-density analytical cockpit for engineers, data analysts, and AI practitioners. Blending the surgical precision and keyboard-driven ergonomics of Linear and Raycast with the real-time observability aesthetics of Datadog, it projects an aura of absolute control, technical sophistication, and calm mastery.

The visual style is **Precision Dark Minimalist** layered with **Targeted Luminescence**. The interface relies on dark obsidian and deep zinc slate tones to eliminate visual fatigue during sustained operational sessions. Purposeful neon strikes—Cyan for real-time streams and telemetries, Coral for volatility, warnings, and performance triggers, and Violet for neural synthesis and automated inference—anchor the user's attention strictly where real-time analysis requires action. Visual excess is systematically stripped away: gradients remain subtle and low-chroma, surfaces rely on structural borders rather than heavy drop shadows, and layout geometry mirrors rigid technical instruments.

## Colors
The color architecture is built for mission-critical dark-mode operational environments. Contrast, hierarchy, and signal fidelity take precedence over decorative color application.

### Canvas & Surface Hierarchy
- **Canvas Base (`#0F1117`)**: The foundational canvas; used for viewport background, desktop window frames, and root splitters.
- **Surface Level 1 (`#181B26`)**: The primary component housing for sidebars, toolbars, and inactive widget modules.
- **Surface Level 2 (`#1E2235`)**: Hover layers, active panel headers, raised cards, and popover menus.
- **Surface Level 3 / Input (`#252A40`)**: Text inputs, search command inputs, and nested list rows.
- **Border Structural (`#2B3045`)**: The definitive 1px perimeter border used across all tiles, panels, splitters, and cards.
- **Border Subtle (`#202436`)**: Internal module dividers and nested table row strokes.

### Accent Signals
- **Primary Cyan (`#00AEEC`)**: Telemetry streams, real-time data ingestion, primary action buttons, active navigation markers, and verified indicators.
- **Secondary Violet (`#8B5CF6`)**: Model inference nodes, neural weight metrics, generative agent processes, and synthetic insights.
- **Tertiary Coral (`#FE2C55`)**: Critical thresholds, anomalies, volatility alerts, system degradations, and destructive mutations.

### Text & Metrics Tones
- **High-Contrast Text (`#F1F5F9`)**: Primary headers, values, active tab text, and key telemetry metrics.
- **Medium-Contrast Text (`#94A3B8`)**: Secondary labels, column headers, meta information, and inactive tabs.
- **Muted Text (`#64748B`)**: Hotkey prompts, disabled controls, placeholder text, and structural timestamps.

## Typography
Typography is tuned for terminal-grade density, high-velocity scanning, and alphanumeric legibility:

- **Geist** governs structural headlines, navigation, and core interaction labels. Its tight geometric aperture and neutral sans-serif metrics keep dashboards compact without feeling cramped.
- **JetBrains Mono** governs all raw data tables, model status indicators, memory offsets, latency stats, hotkey badges, and scalar figures. It preserves absolute vertical alignment across tabular data.

### Hierarchy & Style Rules
- Headers (`headline-xl`, `headline-lg`) must use tight letter-spacing (`-0.02em` to `-0.015em`) to maintain a clean, compact appearance.
- Secondary descriptions and auxiliary stats default to `body-sm` (`12px`) rendered in `#94A3B8`.
- Metric numbers and analytical values always render in `JetBrains Mono` with tabular numerals enabled (`font-variant-numeric: tabular-nums`) to prevent horizontal layout shift during live socket streaming.

## Layout & Spacing
The layout model follows a rigid desktop workstation doctrine optimized for native rendering environments like PySide6/Qt or Electron split-panes.

### Layout Model
- **Split-Pane Workspace Architecture**: The main viewport is constructed of multi-tier dockable and resizable splitters. An outer margin of `16px` (`margin`) separates the window bounds from inner workspace canvases.
- **Module Grid**: Modular cards and data tiles arrange along an adaptive multi-column grid with a baseline gutter of `12px` (`gutter`).
- **Rhythm & Padding Hierarchy**:
  - `space-xs` (4px): Inner item gaps, icon-to-label separation, badge padding.
  - `space-sm` (8px): Compact element spacing, input vertical padding, toolbar gaps.
  - `space-md` (12px): Standard modular card padding, nested container spacing.
  - `space-lg` (16px): Outer container padding, structural widget headers, modal view interiors.
  - `space-xl` (24px): Canvas section margins and primary workflow separators.

### Desktop Adaptation
- **Window States**: Panels auto-collapse into compact vertical icon rails when an individual pane width drops below `320px`.
- **Docking Flexibility**: Inner panels support 2-column, 3-column, or asymmetrical dashboard distributions (e.g., 240px persistent tree view, 1fr flex telemetry canvas, 360px AI inspector dock).

## Elevation & Depth
Elevation is achieved using tonal layering, micro-borders, and subtle backlight glow rather than traditional drop shadows:

1. **Layer 0 (Canvas Base - `#0F1117`)**: Recessed window foundation; absorbs surrounding elements.
2. **Layer 1 (Card / Tile - `#181B26`)**: Elevated panels bounded by a crisp `1px solid #2B3045` stroke. Zero ambient drop shadow; relies purely on stroke contrast to establish separation.
3. **Layer 2 (Hover / Active Module - `#1E2235`)**: Hovered cards, context rows, and active dropdown triggers transition to this layer. Border transitions to `#383F5B`.
4. **Layer 3 (Overlay / Popover / Command Palette - `#1E2235`)**: Floated dialogs, command bars, and context menus. Outlined with `1px solid #00AEEC` (at 40% alpha) and cast with a soft directional occlusion shadow: `0 12px 32px -8px rgba(0, 0, 0, 0.65)`.
5. **Signal Glow**: When an AI worker is executing or a critical threshold triggers, cards emit an internal ring or ambient glow (`box-shadow: 0 0 16px -4px rgba(139, 92, 246, 0.25)` for AI Violet; `0 0 16px -4px rgba(254, 44, 85, 0.25)` for Coral alerts).

## Shapes
The shape system uses a compact, technical profile (`roundedness: 1`):

- **Default Radii (`0.25rem` / 4px)**: Buttons, inputs, inline badges, status chips, segmented switch pills, and context menu rows.
- **Card & Panel Radii (`0.5rem` / 8px - `rounded-lg`)**: Widget frames, workspace modules, dialog windows, and chart containers.
- **Nested Inner Corners**: Inner elements nested inside cards (e.g., data wells, chart viewports) use 4px radii to ensure concentric corner curves with the outer 8px parent.
- **Status Dots & Avatars**: True circles (`50%` / 9999px) strictly reserved for real-time pulse dots and identity indicators.

## Components

### Buttons
- **Primary**: Background `#00AEEC`, text `#0F1117`, font `Geist Medium 13px`. Hover: `#33BEF0`. Active: `#0098CF`. Focus ring: 2px solid `#00AEEC` with 2px offset.
- **Secondary / Ghost**: Background `#1E2235`, border `1px solid #2B3045`, text `#F1F5F9`. Hover: background `#252A40`, border `#383F5B`.
- **AI Special**: Background `rgba(139, 92, 246, 0.12)`, border `1px solid #8B5CF6`, text `#8B5CF6`. Hover: background `rgba(139, 92, 246, 0.22)`.
- **Destructive**: Background `rgba(254, 44, 85, 0.12)`, border `1px solid #FE2C55`, text `#FE2C55`. Hover: background `rgba(254, 44, 85, 0.22)`.
- **Height**: 28px for compact data toolbars; 32px for standard forms.

### Segmented Tab Controls
- Background `#0F1117`, border `1px solid #2B3045`, padding `2px`, border-radius `6px`.
- Segments render with 4px border-radius. Inactive segment: text `#94A3B8`, background transparent. Active segment: text `#F1F5F9`, background `#1E2235`, border `1px solid #2B3045`.

### Status Indicators & Badges
- **Status Indicator**: 6px solid dot with an optional CSS or QProperty pulse animation.
  - Active / Streaming: `#00AEEC`
  - Processing / Inference: `#8B5CF6`
  - Warning / Drift: `#FE2C55`
  - Idle / Standby: `#64748B`
- **Badges**: Monospace `JetBrains Mono 10px`, uppercase, tracking `0.03em`. Padding `2px 6px`, border-radius `4px`. Background tint at 10% opacity, border at 30% opacity matching the semantic signal.

### Modular Cards & Widgets
- Background `#181B26`, border `1px solid #2B3045`, border-radius `8px`.
- Card Header: Height `36px`, padding `0 12px`, border-bottom `1px solid #202436`. Title in `Geist 13px SemiBold` with action icons grouped right.
- Card Body: Padding `12px` default, `0px` for dense data tables.

### Input Fields & Search (Raycast-Style)
- Background `#181B26`, border `1px solid #2B3045`, text `#F1F5F9`, placeholder `#64748B`. Height `32px`, padding `0 10px`, font `Geist 13px`.
- Focus state: border `1px solid #00AEEC`, subtle cyan glow (`0 0 0 1px rgba(0, 174, 236, 0.3)`).
- Inline shortcut hints (e.g., `⌘K`) styled with `#252A40` background, `#94A3B8` font, and 1px border.

### Checkboxes & Radios
- Box size `14px x 14px`, border `1px solid #2B3045`, background `#0F1117`, border-radius `3px`.
- Checked: background `#00AEEC`, border `#00AEEC`, icon check in `#0F1117`.

### Lists & Telemetry Tables
- Row height `28px` (dense) or `36px` (standard). Alternating rows disabled; rows utilize bottom border `1px solid #202436`.
- Hover row state: background `#1E2235`. Selected row: background `rgba(0, 174, 236, 0.08)`, left indicator stroke `2px solid #00AEEC`.