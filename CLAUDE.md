# SkyClear: instructions for every agent session

Read this file before changing anything. The full design rules are in [DESIGN_RULES.md](DESIGN_RULES.md). They are mandatory and apply to the UI, README, docs, copy and any generated page.

## Project

Explainable drone flight check (MongoDB hackathon, Track 2: RAG Engine). Read [README.md](README.md) for the idea and [API.md](API.md) for the API contract.

- Code decides the verdict. The LLM only explains and cites.
- Never say "safe". Say "No restriction found in our data".
- Numbers in the presentation must come from real eval runs.

## Design rules (never break these)

The list below describes generic AI-looking design. None of it may appear in this project. Items that start with "No" in the source list (no skeleton loaders, no TOS, no privacy policy, no real product demos) are things generic sites leave out. Here they must be present.

Banned:

1. Harsh gradients
2. Lucide icons
3. Pure white background (#fff, white)
4. Rainbow coloring
5. Drop shadows
6. 3 feature cards in a row
7. Emojis
8. Liquid glass, except a light blur (12px or less) on panels floating over the map or scrolling content
9. Em dashes (and en dashes used as dashes). Use commas, colons, periods
10. Inter, Geist, Space Grotesk fonts
11. Colored left stripe (border-left accent on cards, quotes, alerts)
12. Fake testimonials
13. Bento grids
14. Terminal window mockups
15. "It's not X, it's Y" phrasing
16. Checkmark bullets
17. 3 pricing tiers
18. Pill shapes and very round corners (use 6px for controls, 10px for panels and cards)
19. Purple and black palette (and any purple accent)
20. Radial orbs
21. Dot grids
22. Sparkle icons
23. Animated arrows
24. Hover animations and transitions
25. Neon colors
26. Basic pastel colors

Required (the absence is the AI tell):

27. Real product demo: the actual working app, not a screenshot or mockup
28. Skeleton loaders while data loads
29. Terms of Service page
30. Privacy Policy page

## Before finishing any UI or copy change

Run `./scripts/check_design.sh` and fix everything it reports. It catches the mechanical rules (white backgrounds, shadows, radius, left stripes, em dashes, emojis, banned fonts, purple, transitions, gradients). Rules it cannot check by script must be reviewed by hand against DESIGN_RULES.md.
