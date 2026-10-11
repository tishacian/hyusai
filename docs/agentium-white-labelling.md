# White labelling through the product UI

The workspace owner can configure an identity without editing JSON. Application
authors can configure an identity in the Studio and publish it through the
existing application lifecycle. NAWA's dedicated interface and palettes remain
client-owned designs; they are not replaced by the generic appearance editor.

## User paths

**Workspace:** Workspace settings → General → White labelling.
The stable route is `/workspace/{slug}/settings`.

1. Enable a custom identity, enter its display name and import a main logo.
2. Choose Standard, Graphite or Sand, an action colour and corner shape.
3. Check the light and dark previews. An optional second logo supports light
   backgrounds. Resetting the style keeps the logos; disabling the identity
   restores the default platform brand after saving.
4. Save. The common Cockpit and Work home use this workspace identity.

The existing workspace administrator/owner check governs this shared setting.
Saving compares the previously read brand under the existing workspace lock.
A conflict asks the user to reload; unrelated settings are not replaced.
The canonical audit records the actor and changed field names, without images.

**Application:** Create → Apps → New, or open an application and select
**Visual identity**. The existing **Identity & access** panel holds the settings.

1. Choose the application's appearance and inspect both preview modes.
2. Save its draft metadata. An existing Work application continues using its
   published release.
3. Review and publish/deploy through the existing controls. Work reads appearance
   and identity from the resolved release. Editing a draft cannot restyle an
   already published version.

Existing contributor, reviewer and administrator permissions are retained:
being allowed to design an application does not grant publication permission.
Dedicated applications using `live_href` retain their native interface and
show an explanation in place of the generic appearance editor.

## Rendering contract

- Existing `platform_brand` owns workspace identity; its optional `appearance`
  configures common chrome. Application `theme.appearance` belongs to its release.
- Options are bounded: three palettes, a six-digit accent, three corner shapes,
  and main/light logos. Uploaded PNG, JPEG and WebP files are limited to 96 KiB.
  The API also accepts existing local assets and HTTPS logo URLs.
- Colours carrying execution status, approval or evidence meaning are not brand
  options. Foreground on the action colour is selected for contrast.
- The shared editor and runtime use the same projection. Scoped dark tokens and
  semantic aliases allow a dark application or preview inside a light Cockpit.
- NAWA SCSS, assets, components and the NAWA Studio palette are unchanged. The
  generic editor does not offer a NAWA preset or rewrite an immersive app brand.
- This adds no flag, migration, CSS dependency or publication mechanism.
  An application still needs the existing Experience feature and permissions.

This is a shared identity contract, not a replacement of every legacy component
style. Mission Room layouts and native client applications retain their existing
designs. Their complete visual acceptance remains a separate release check.

## Local verification

Base SHA: `7a4924f7dd406b831ca0b2eafd110d079b664330`; uncommitted implementation in
`codex/adoption-roadmap`. No deployment or client setting was changed.

- Frontend: 1,412 unit tests pass. The complete suite was split with the existing
  `FLOW_UNIT_FILTER` because a single batch exhausted local temporary disk space.
- Backend: 59 tests pass for appearance, Experience API and authorization;
  the focused appearance suite also passes after adding the audit event.
- Production build and `check:i18n`, `check:nav-links`, `check:ui-chrome` pass.
- Browser checks use the existing canary 16 with synthetic API fixtures. They
  exercise onboarding compatibility, brand editing, image import, reload and
  a release whose theme differs from the current draft. See [local evidence](evidence/white-labelling-local/README.md)
  for the final browser result and screenshots.

The mock browser checks do not attest a deployed client workspace or a live
NAWA visual comparison. Backend tests separately exercise persistence, rights,
compare-and-set and immutable release behaviour.
