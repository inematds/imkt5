# video-text-designer

Capability: `video.text_overlay`. Porta 8116.

## Papel

Pré-renderiza **texto de cena como PNG transparente** via Playwright +
Chromium headless, usando mesma estética chrome-gradient + halo do
`carousel-designer` (c79-inspired). O PNG é consumido pelo
`ffmpeg-local` como overlay sobre o clip da cena — permitindo que o
vídeo tenha tipografia no mesmo nível visual do carrossel rico.

## Quando usar

- Modo `chrome_text_overlay: true` no ffmpeg-local
- Substitui o `drawtext` ffmpeg pelo text_overlay PNG pré-renderizado
- Funciona em video-quick e video-pro, aspect-adaptive (9:16, 1:1, 16:9)

## Input

```json
{
  "scenes": [
    {
      "text_overlay": "IA AMPLIFICA VOCÊ",
      "text_position": "top",          // top | center | bottom
      "scene_type": "hook",            // hook | problem | solution | proof | cta
      "width": 1080,
      "height": 1920
    },
    ...
  ],
  "tenant_id": "inema",
  "style": "editorial_chrome"          // por enquanto só este
}
```

## Output

```json
{
  "outputs": [
    {
      "scene_index": 0,
      "text_png_url": "/s3/imkt4/inema/<job>/scene_00_text.png",
      "width": 1080,
      "height": 1920,
      "has_text": true
    },
    {"scene_index": 1, "has_text": false}   // cena sem text_overlay
  ]
}
```

## Template atual

- `editorial_chrome_textonly.html` — fundo transparente + headline
  Instrument Serif italic + chrome gradient linear + halo glow duplo
  + text position variable (top/center/bottom)

## Roadmap

- `editorial_chrome_bar_top` (barra escura + chrome) — variante c/ bar
- `kinetic_scale_8x` — 3 frames de SCALE 1→4→8× pra animar via ffmpeg overlay
- `word_stagger_reveal` — PNG por palavra, composited com timing whisper

## Regras

- Fundo sempre `rgba(0,0,0,0)` — transparência total pro overlay
- PNG com alpha channel (ffmpeg format rgba)
- Textos vazios → output com `has_text: false`, sem PNG
- Tamanho fixo via width/height da cena
