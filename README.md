# GEO 1305 Weather Channel

A pre-lecture weather display for GEO 1305 Meteorology at Texas State University.

- `index.html` is the display page: a 3D globe with surface temperature, ASOS wind barbs and radar, and the 250 mb jet stream on a raised layer.
- `scripts/fetch.py` collects the live data. `.github/workflows/update.yml` runs it every 10 minutes and publishes the page plus fresh data to the `gh-pages` branch.
- `data/` holds the map outlines, elevation shading and the preferred station list.

Data sources: NOAA RAP analysis (250 mb wind, 2 m temperature), Iowa Environmental Mesonet (ASOS winds, NEXRAD composite), TexMesonet (TXST Round Rock station, site 142). Map outlines from Natural Earth and the US Census Bureau.

`live/status.json` on the published site records when each source last updated and any errors.
