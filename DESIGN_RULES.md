# SkyClear design rules

Source of truth for the look and the writing of SkyClear. Supplied by the project owner. Every agent and contributor must follow it. [CLAUDE.md](CLAUDE.md) points here so it is loaded each session.

## Banned (must not appear anywhere)

| # | Item | What it means here |
|---|---|---|
| 1 | Harsh gradients | No `linear-gradient`, `radial-gradient`, `conic-gradient` |
| 2 | Lucide icons | No icon library of this style. Use text labels |
| 3 | Pure white background | No `#fff`, `#ffffff`, `white`, `rgb(255,255,255)` as a surface. Use a warm or cool off-white |
| 4 | Rainbow coloring | One accent color plus the four verdict colors, nothing more |
| 5 | Drop shadows | No `box-shadow`, `text-shadow`, `drop-shadow`. Use 1px borders |
| 6 | 3 feature cards in a row | No row of three equal cards |
| 7 | Emojis | None in UI, docs, commits or copy |
| 8 | Liquid glass | No `backdrop-filter`, no translucent blurred panels |
| 9 | Em dashes | No U+2014. Do not use U+2013 as a dash either |
| 10 | Inter / Geist / Space Grotesk | Use another face, or the system font stack |
| 11 | Colored left stripe | No `border-left` accent on cards, quotes, alerts, citations |
| 12 | Fake testimonials | No invented quotes, names, logos or stats |
| 13 | Bento grids | No mosaic of mixed-size tiles |
| 14 | Terminal window | No fake terminal chrome or traffic-light dots. Plain code blocks in docs are fine |
| 15 | "It's not X, it's Y" | No contrast-reveal phrasing in any copy |
| 16 | Checkmark bullets | Plain bullets or numbers only |
| 17 | 3 pricing tiers | No pricing section. SkyClear is free |
| 18 | Soft corner radius | `border-radius` of 0 to 2px only |
| 19 | Purple and black | No purple anywhere, no purple-on-black scheme |
| 20 | Radial orbs | No blurred color blobs |
| 21 | Dot grids | No dotted background patterns |
| 22 | Sparkle icons | No star or sparkle glyphs for "AI" |
| 23 | Animated arrows | No moving or bouncing arrows |
| 24 | Hover animations | No `:hover` transforms, no `transition`, no `animation` tied to hover |
| 25 | Neon colors | No saturated glow colors |
| 26 | Basic pastel colors | No default light pink, mint, baby blue fills |

## Required (generic AI sites skip these)

| # | Item | How SkyClear satisfies it |
|---|---|---|
| 27 | Real product demo | The working map check is the page itself, no mockup |
| 28 | Skeleton loaders | Shown in the result panel while a check is running |
| 29 | Terms of Service | [frontend/terms.html](frontend/terms.html), linked in the footer |
| 30 | Privacy Policy | [frontend/privacy.html](frontend/privacy.html), linked in the footer |

## Allowed palette

Surface `#f4f2ee`, panel `#faf9f6`, text `#1b1f24`, border `#cfcac0`. Accent `#1f4e79`. Verdict colors: green `#1a7f37`, amber `#a15c00`, red `#b3261e`, grey `#5b6570`. Dark mode: surface `#14171a`, panel `#1b1f23`.

## Check

`./scripts/check_design.sh` scans for the mechanical rules. Run it before every commit.
