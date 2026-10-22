"""Rebuild vector identity assets. Requires fontTools only at design time."""
from pathlib import Path
from html import escape
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / 'static' / 'brand'
OUT.mkdir(exist_ok=True)
INK = '#1d1d1f'
BLUE = '#0071e3'

def symbol(ink=INK, accent=BLUE):
    return f'''<g fill="none" stroke="{ink}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M25 7v7m14-7v7M25 50v7m14-7v7M7 25h7m-7 14h7m36-14h7m-7 14h7"/>
      <rect x="14" y="14" width="36" height="36" rx="9"/>
      </g>
      <path d="m32 22 10 6v12l-10 6-10-6V28z" fill="none" stroke="{ink}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="m32 34 10-6v12l-10 6z" fill="{accent}"/>
      <path d="m22 28 10 6 10-6M32 34v12" fill="none" stroke="{ink}" stroke-width="2.2" stroke-linejoin="round"/>
      '''

def svg(body, width, height, title):
    title = escape(title, quote=True)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{title}"><title>{title}</title>{body}</svg>'

font = TTFont(BASE / 'static/fonts/inter-2.font')
glyphs = font.getGlyphSet()
cmap = font.getBestCmap()
scale = 34 / font['head'].unitsPerEm
text_paths = []
x = 82
for char in 'P&T AI SQUARE':
    glyph = glyphs[cmap[ord(char)]]
    pen = SVGPathPen(glyphs)
    glyph.draw(pen)
    if pen.getCommands():
        text_paths.append(f'<path transform="translate({x:.3f} 44) scale({scale:.8f} {-scale:.8f})" d="{pen.getCommands()}"/>')
    x += glyph.width * scale - .65

for suffix, ink, accent in [('', INK, BLUE), ('-mono', INK, INK), ('-white', '#ffffff', '#ffffff')]:
    (OUT / f'pt-ai-square-symbol{suffix}.svg').write_text(svg(symbol(ink, accent), 64, 64, 'P&T AI SQUARE'), encoding='utf-8')
    wordmark = symbol(ink, accent) + f'<g fill="{ink}">' + ''.join(text_paths) + '</g>'
    (OUT / f'pt-ai-square-logo{suffix}.svg').write_text(svg(wordmark, round(x+3), 64, 'P&T AI SQUARE'), encoding='utf-8')

(OUT / 'README.txt').write_text('''P&T AI SQUARE — Chip / Shared Space

The chip outline represents semiconductor technology. The inner three-dimensional
space represents a shared square for tools, skills and ideas. A single blue face
marks the connection point. No gradient is used.

Primary: pt-ai-square-logo.svg (outlined lettering; no font installation needed)
Small icon / favicon: pt-ai-square-symbol.svg
Monochrome: *-mono.svg; on dark backgrounds: *-white.svg
Keep clear space at least one pin length. Do not stretch or rotate.
Symbol minimum recommended display size: 24 px.
Colors: ink #1d1d1f, accent #0071e3, canvas #f5f5f7, white #ffffff.
Web fonts: Inter for Latin, Pretendard for Korean. Licenses in ../fonts/.
Apple reference typography is not bundled; only size/weight/spacing is referenced.
''', encoding='utf-8')
print(f'Created logo assets in {OUT}')
