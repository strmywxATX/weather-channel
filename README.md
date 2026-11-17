# Tapp's Weather Channel

A pre-lecture weather display for GEO 1305 Meteorology at Texas State University.

- `index.html` is the display page: a 3D globe with surface temperature, ASOS wind barbs and radar, and the 250 mb jet stream on a raised layer.
- `scripts/fetch.py` collects the live data. `.github/workflows/update.yml` runs it every 10 minutes and publishes the page plus fresh data to the `gh-pages` branch.
- `data/` holds the map outlines, elevation shading and the preferred station list.

Data sources: NOAA RAP analysis (250 mb wind, 2 m temperature), Iowa Environmental Mesonet (ASOS winds, NEXRAD composite), TexMesonet (TXST Round Rock station, site 142). Map outlines from Natural Earth and the US Census Bureau.

`live/status.json` on the published site records when each source last updated and any errors.

## Settings

- Campus: add `?campus=sm` to the page address for San Marcos; Round Rock is the default. The Round Rock station panel always shows.
- `config.json`:
  - `lectures`: list of `{"campus": "rr" or "sm", "days": ["Tue", "Thu"], "start": "11:00"}` (24-hour Central time). A countdown shows during the hour before a lecture. `?start=11:00` in the address also works.
  - `headlines`: your own lines, shown first in the headlines panel.
  - `rotateSeconds`: how long each rotating panel stays up.
  - `video`: a YouTube link or an .mp4 address to add as a rotating panel (muted).
- Add `?edit` to the address to show the globe controls.
