# Profile art

`build.py` draws every image in `assets/` and writes `README.md`. Change the content near the top of the script (apps, links, toolbox) and run:

```bash
python3 -m pip install fonttools brotli pillow
python3 tools/build.py
```

The contribution snake is drawn separately by `.github/workflows/snake.yml` into the `output` branch every day.

Fonts in `fonts/` are Bricolage Grotesque, Instrument Serif, Inter and JetBrains Mono from Google Fonts, under the SIL Open Font License 1.1. Brand icons in `si/` come from [Simple Icons](https://simpleicons.org) (CC0). App icons in `icons/` belong to my own apps.
