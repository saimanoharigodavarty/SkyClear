#!/usr/bin/env bash
# Mechanical checks for DESIGN_RULES.md. Exit 1 if any rule is broken.
cd "$(dirname "$0")/.." || exit 2
FILES=$(find frontend backend data README.md API.md TEAM.md PRODUCT.md ARCHITECTURE.md docs CLAUDE.md DESIGN_RULES.md -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.md' -o -name '*.py' -o -name '*.json' -o -name '*.geojson' \) ! -name CLAUDE.md ! -name DESIGN_RULES.md)
fail=0
chk() { # name, pattern. Round instruments (joystick, compass) may be circles, so those lines are skipped for the radius check.
  out=$(grep -nE "$2" $FILES 2>/dev/null | { if [ "$1" = "radius > 12px" ]; then grep -vE '\.stick|\.knob|\.compass'; else cat; fi; })
  if [ -n "$out" ]; then echo "FAIL $1"; echo "$out"; fail=1; fi
}
chk "gradient"            'gradient\('
chk "pure white"          '#fff\b|#ffffff|:[[:space:]]*white|rgb\(255, ?255, ?255\)'
chk "shadow"              '(box|text)-shadow:[[:space:]]*[^n[:space:]]|drop-shadow'
chk "heavy blur"          'blur\(([1-9][3-9]|[2-9][0-9])px\)'
chk "em/en dash"          '—|–|&mdash;|&ndash;'
chk "emoji/checkmark"     '[✓✔✅❌★☆✨🚀🎯💡]'
chk "banned font"         '\b(Inter|Geist|Space Grotesk)\b'
chk "left stripe"         'border-left'
chk "radius > 12px"       'border-radius:[[:space:]]*(1[3-9]|[2-9][0-9]|[0-9]{3,})px|border-radius:[[:space:]]*50%'
chk "purple"              'purple|violet|#7c3aed|#8b5cf6|#a855f7'
chk "transition/animation" 'transition|@keyframes|animation:|:hover'
chk "lucide"              'lucide'
chk "neon/pastel names"   'neon|pastel'
for f in frontend/terms.html frontend/privacy.html; do [ -f "$f" ] || { echo "FAIL missing $f"; fail=1; }; done
grep -rq 'skel' frontend || { echo "FAIL no skeleton loader"; fail=1; }
[ $fail -eq 0 ] && echo "design check passed"
exit $fail
