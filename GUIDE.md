# Tapp's Weather Channel: how it works

This guide explains every file in this repository, what each one does, and how the code inside it works. It is written for someone who knows the meteorology but has not written this kind of code.

- Display page: https://strmywxatx.github.io/weather-channel/
- Repository: https://github.com/strmywxATX/weather-channel

## The big picture

There are two halves.

1. **The data job.** Every 10 minutes, GitHub runs a Python script on its own servers. The script downloads weather data from NOAA, the National Weather Service, the Iowa Environmental Mesonet and TexMesonet, converts it into small files, and publishes those files next to the display page.
2. **The display page.** One web page (`index.html`) that you open full screen on your laptop. It reads the small files the job produced and draws everything: the globe, the meteogram, the sun and moon scene, the rotating maps and the forecast ticker. It re-reads the files every 5 minutes.

The page never talks to NOAA directly (with one exception, the two Oklahoma Mesonet maps). That is deliberate: if a NOAA server is slow just before lecture, the page still shows the last good data rather than an empty panel.

```
NOAA / NWS / IEM / TexMesonet
            |
   scripts/fetch.py        (runs on GitHub every 10 minutes)
            |
   live/*.json, *.png      (published on the gh-pages branch)
            |
       index.html          (your laptop, full screen)
```

### Two branches

- **`main`** holds the source: the page, the scripts and the settings. This is the branch you edit.
- **`gh-pages`** is the published website. The job rebuilds it from scratch on every run, so never edit it by hand. It contains a copy of the page plus the `live/` and `relief/` folders described below.

## Files in the repository (`main` branch)

| File | What it is |
|---|---|
| `index.html` | The whole display page: layout, styling and all drawing code |
| `config.json` | Your settings: lecture schedule, custom headlines, rotation speed, video |
| `scripts/fetch.py` | The data job: downloads and converts all live data |
| `scripts/build_relief.py` | One-time builder for the terrain shading image |
| `.github/workflows/update.yml` | Tells GitHub when and how to run the job and publish the site |
| `requirements.txt` | The Python libraries the job needs |
| `data/boundaries.json` | Coastlines, lakes, state and country borders |
| `data/stations.json` | Preferred airports for wind barbs (major airports first) |
| `data/elevation.png` | Coarse backup elevation map, used only if the relief image is missing |
| `README.md` | Short summary and settings reference |
| `GUIDE.md` | This guide |
| `.gitignore` | Keeps Python's temporary files out of the repository |

## `config.json`: your settings

This is the one file you are likely to edit. Change it on GitHub (pencil icon), commit, and the next run picks it up.

```json
{
  "lectures": [
    {"campus": "rr", "days": ["Mon", "Wed"], "start": "12:30"},
    {"campus": "sm", "days": ["Tue", "Thu"], "start": "09:30"}
  ],
  "defaultCampus": "sm",
  "headlines": [],
  "rotateSeconds": 20,
  "video": ""
}
```

- **`lectures`**: one entry per class. `campus` is `rr` (Round Rock) or `sm` (San Marcos). `days` uses three-letter day names. `start` is 24-hour Central time. This drives both the countdown and which campus the page shows on a given day.
- **`defaultCampus`**: the campus shown on days with no lecture.
- **`headlines`**: your own lines, in quotes and separated by commas, for example `["Exam 3 is Thursday", "Cold front arrives Wednesday night"]`. They appear first in the headlines panel.
- **`rotateSeconds`**: how long each step of the rotating panel stays up.
- **`video`**: a YouTube link or the address of an .mp4 file. If set, it becomes an extra step in the rotation, always muted.

### Address options

Add these to the end of the page address:

- `?campus=rr` or `?campus=sm` forces a campus regardless of the day.
- `?start=11:00` counts down to a one-off start time.
- `?edit` shows the globe control box (layer switches, jet height, and "Copy view settings").

Combine them with `&`, for example `?campus=rr&edit`.

## `.github/workflows/update.yml`: the schedule

This file is the timer and the assembly line. It runs in three situations: every 10 minutes (`cron: "*/10 * * * *"`), whenever something is pushed to `main`, and when you press "Run workflow" on the Actions tab.

Each run does this, in order:

1. Copies the repository onto a fresh GitHub computer and installs Python and the libraries in `requirements.txt`.
2. **Assembles the site** in a folder called `site`: the page, `config.json`, and the `data` folder. It then copies in the `live/` and `relief/` folders from the previously published site, so anything that fails to update keeps its last good version.
3. **Builds the relief image** only if it is missing (normally just the very first run).
4. **Fetches live data** by running `python scripts/fetch.py site/live`.
5. **Publishes** by replacing the `gh-pages` branch with the contents of `site`.

Things to know:

- GitHub often starts scheduled runs late, sometimes by 10 to 30 minutes at busy times. Each legend on the page shows the valid time of its data so you can always tell how fresh it is.
- GitHub pauses scheduled workflows in a repository that has had no activity for 60 days. If the data stops updating after a long break, open the Actions tab and re-enable the workflow.
- Public repositories get this service free.

## `scripts/fetch.py`: the data job

The script is a list of independent tasks. Each one is wrapped by a helper called `run`, which records success or failure in `live/status.json` and then moves on, so one broken source never stops the others.

| Task | Source | Output file | Used for |
|---|---|---|---|
| `rap` | NOAA RAP model analysis | `rap.json` | Jet stream layer |
| `asos` | Iowa Environmental Mesonet | `asos.json` | Wind barbs and temperature numbers |
| `radar` | Iowa Environmental Mesonet | `radar.png`, `radar.json` | Radar |
| `station` | TexMesonet, site 142 | `station.json` | Meteogram and current readings |
| `forecast` | National Weather Service | `forecast.json` | Bottom ticker |
| `images` | NOAA, Weather Prediction Center | `sat.gif`, `wpc.jpg`, `images.json` | Rotating panel |
| `headlines` | NWS alerts plus the files above | `headlines.json` | Headlines panel |

### `rap`: the 250 mb jet stream

1. **Find the newest analysis.** It looks in NOAA's public RAP archive for the current hour's file (`rap.tHHz.awip32f00.grib2`, the 32 km North America grid, forecast hour zero, which is the analysis). If that hour is not posted yet it steps back an hour at a time, up to 9 hours.
2. **Download only what is needed.** Each RAP file has a small index listing where every field sits inside it. The script reads the index and downloads just four fields: 250 mb U wind, 250 mb V wind, 250 mb height, and 2 m temperature. That is a few hundred kilobytes instead of the whole file.
3. **Rotate the winds.** RAP winds are stored relative to the model's Lambert conformal grid, not true north. The script rotates each wind vector to true east and north using the grid's central longitude and standard latitude, both read from the file.
4. **Regrid.** The model grid is converted to a simple half-degree latitude and longitude grid covering 170°W to 40°W and 5°N to 80°N. Each new point is a distance-weighted blend of the four nearest model points. Points more than 45 km from any model point are left empty.
5. **Smooth lightly.** Wind and height are smoothed by about one grid cell so the isotach bands and height contours draw cleanly.
6. **Save.** Winds are stored in knots, heights in metres, temperature in °F.

The 2 m temperature is still collected but the page no longer draws it; it is there if you want the gradient back.

### `asos`: surface winds and temperatures

It asks the Iowa Environmental Mesonet for the latest report from every ASOS and AWOS station in the 48 contiguous states, one state at a time. Reports older than 90 minutes are dropped. Wind speed and direction are converted to east and north components.

There are over 2,000 reports, far too many to plot, so the list is thinned: a station is kept only if it is at least 1.6 degrees from every station already kept. Stations listed in `data/stations.json` (major airports) are considered first, so they win the spacing contest.

### `radar`: the national composite

It downloads the Iowa Environmental Mesonet's national NEXRAD base-reflectivity mosaic, a very large image (12,200 by 5,400 pixels) in which each pixel's color index encodes reflectivity in half-dBZ steps. The script converts the index to dBZ, shrinks the image by a factor of five while keeping the strongest echo in each block (so storm cores are not averaged away), drops anything under 10 dBZ, and saves a small gray image where brightness equals dBZ. The page applies the colors.

### `station`: your Round Rock station

Two requests to TexMesonet: the current reading for every station (from which site 142 is picked out), and the past 1,440 minutes of charting data for site 142. Both are saved as received, in TexMesonet's units (°C, m/s, mm, mb). The page does the unit conversions.

### `forecast`: the 7-day forecast

For each campus, it asks the National Weather Service which forecast grid covers that latitude and longitude, then downloads the 14 forecast periods (day and night for 7 days): name, temperature, short description and chance of precipitation.

### `images`: satellite and fronts

A short list of image addresses, each saved under a fixed name. If the first address for an image fails, the next one is tried.

- `sat.gif`: the GOES-19 CONUS GeoColor loop.
- `wpc.jpg`: the Weather Prediction Center's fronts and weather map.

To change or add a NOAA image, edit the `IMAGES` list near this function.

The Oklahoma Mesonet dew point and altimeter maps are not in this list. The page loads those two directly from the Mesonet's server.

### `headlines`: the bulletin list

Built in this order, and the page shows the first five:

1. Your own lines from `config.json`.
2. Up to two national lines from active NWS alerts, taking the most serious types first (tornado warnings at the top, advisories at the bottom), with a count and the states affected.
3. One Texas line listing active alert types, or a note that there are none.
4. The strongest 250 mb wind on the map between 140°W and 60°W.
5. Your station's high and low over the past 24 hours.

## `scripts/build_relief.py`: terrain shading

Run once, automatically, the first time the site is built. It downloads about 600 small elevation tiles from a public terrain dataset (Mapzen Terrain Tiles on Amazon's open data service), stitches them together, converts them from the Mercator map projection to plain latitude and longitude, and saves `relief/elev.png`. Elevation is packed into the image's red and green channels. The page turns this into the soft shading you see on the land.

If you ever delete `relief/elev.png` from the published site, the next run rebuilds it.

## `index.html`: the display page

One file with three parts: styling at the top, the page structure in the middle, and two blocks of code at the bottom (the globe, then the side panels).

### Styling and layout

The screen is a grid: a header strip, a main area split into the globe (about 62%) and a column of three cards, and the ticker along the bottom. All sizes are tied to the width of the screen, so the page scales to any projector. Colors are named once at the top (`--gold`, `--panel`, and so on) and reused everywhere.

### The globe

The globe is drawn with three.js, a free 3D graphics library loaded from a public server. The scene is built from several layers:

- **Base sphere.** A dark ocean with flat land shapes for the whole world.
- **Regional map.** A higher-detail patch over North America. It is painted onto a flat canvas first, in this order: ocean, land, lakes, relief shading, state and country borders, radar, wind barbs, temperature numbers, and the TXST marker. That painted canvas is then wrapped onto the sphere.
- **Relief shading.** Calculated in the page from the elevation image: for each pixel it works out the slope, lights it from the northwest with two softer fill lights, and blends the result into the land color.
- **Wind barbs.** Drawn in the standard way: the staff points toward where the wind comes from, with a half barb for 5 kt, a full barb for 10 kt and a pennant for 50 kt, on the left side looking downwind. Speeds are rounded to the nearest 5 kt, and a circle marks calm.
- **Jet stream layer.** A second, transparent patch floating above the surface. Isotach bands use the UCAR breaks (50, 60, 80, 100, 125, 150 kt). Height contours are drawn every 12 dm as dark lines with a light edge.
- **Flow lines.** About 850 small particles that drift along the 250 mb wind, each leaving a short fading trail. A particle is retired when it gets old, leaves the map or drifts into weak wind, and a new one is started somewhere the wind is strong.
- **Tethers.** Thin vertical lines from the ground up to the jet core every 10 degrees of longitude, so the height of the layer is readable.
- **Atmosphere glow and stars.** Decoration.

**Jet layer height.** 250 mb is about 10.4 km up, which would be invisible on a globe at true scale, so the layer is raised 25 times higher than reality. The slider in `?edit` mode changes this.

**The camera.** It sits south of the United States looking north, and sways a few degrees so the scene feels alive. Dragging turns the globe and scrolling zooms. Your view and jet height are remembered in that browser. The built-in defaults are near the top of the globe code:

- `const view={lat:19.8,lon:-100.1,dist:1.89,...}` is the default camera position.
- `let jetExag=25;` is the default jet height.

To make a new view permanent for every computer, set it in `?edit` mode, press "Copy view settings", and replace those numbers.

**Fallback.** If a live file is missing, that layer falls back to built-in demo weather and a gold "Demo data" badge appears in the header naming the affected layers. If you ever see that badge, the job has not produced that file.

**Easy adjustments**, all near the top of the globe code:

- `JET` is the list of isotach breaks, colors and transparency.
- `RAD` is the radar color table.
- `RELIEF` controls the terrain: `gain` is how strong the shading is.
- `OCEAN` and `LAND` are the two basemap colors.

### The side panels

**Campus and countdown.** The page reads the day of the week in Central time and picks the campus with a lecture that day, or the default campus otherwise. That choice sets the forecast in the ticker and the location used for sun and moon times. The countdown finds the next lecture across the coming week and ticks every second; it changes to "Lecture is starting" at the start time and holds for five minutes.

**Sun and moon.** Calculated in the page by a small astronomy library (SunCalc), so no data feed is needed. The scene shows the Earth's curved horizon with a dashed arc from sunrise to sunset. By day the sun sits on the arc at the position matching the current time; at night the sky darkens, stars appear, and the moon is drawn if it is up. About once a month the moon does not rise or set within a calendar day, and the card then shows the next one with its weekday.

**Meteogram.** Four panels sharing one 24-hour time axis, in the style of the Oklahoma Mesonet meteograms:

1. Air temperature (red fill) over dew point (green fill). Dew point is calculated from temperature and relative humidity with the Magnus formula.
2. Wind speed (dark bars) and gusts (light bars) in mph on the right axis, and wind direction (yellow circles) on the left axis running N, E, S, W, N from bottom to top.
3. Sea-level pressure in millibars.
4. Solar radiation (orange) in front of an estimated clear-sky maximum (gray). The maximum is not measured: it is a standard clear-sky formula based on the sun's elevation at the station at each time.

The current reading is printed to the right of each panel. Hours along the top are Central time.

**Rotating panel.** Steps through its slides on a timer, with a fade between them: satellite beside the fronts map, dew point beside altimeter, then headlines, then your video if one is set. If an image fails to load it is hidden, and if both images of a pair fail, that step is skipped.

**Ticker.** The 14 forecast periods for the day's campus, scrolling at a steady speed that adjusts to the length of the text.

**Refresh.** Clocks and the countdown update every second. The campus, and the sun and moon scene, are rechecked every minute. All data files are re-read every 5 minutes.

## The `data` folder

- **`boundaries.json`**: outlines as lists of longitude and latitude points. Coastlines, lakes and country borders come from Natural Earth; state borders come from the US Census Bureau. Both are free to use.
- **`stations.json`**: about 120 large and medium US airports, already spaced apart. Used only to decide which stations get priority for wind barbs.
- **`elevation.png`**: a coarse world elevation map kept as a backup for the relief shading.

## What the job publishes (`gh-pages` branch)

| File | Contents |
|---|---|
| `live/rap.json` | Gridded 250 mb wind, height and 2 m temperature, with the analysis time |
| `live/asos.json` | The thinned station list with wind and temperature |
| `live/radar.png`, `live/radar.json` | Radar image and its map bounds and time |
| `live/station.json` | Round Rock current reading and 24-hour series |
| `live/forecast.json` | Forecast periods for both campuses |
| `live/sat.gif`, `live/wpc.jpg`, `live/images.json` | Rotation images and the list of which ones arrived |
| `live/headlines.json` | The headline list |
| `live/status.json` | A report card for the last run |
| `relief/elev.png` | High-resolution elevation for the terrain shading |

A few older files (`live/spc.gif`, `live/wpc.gif`) are left over from earlier versions and are not used.

## When something looks wrong

1. **Check the report card.** Open https://strmywxatx.github.io/weather-channel/live/status.json. Each source shows `"ok": true` or an error message, plus the time of the run.
2. **Check the run itself.** On GitHub, open the **Actions** tab. A green check means the run finished; click a red X to read what failed.
3. **Run it by hand.** On the Actions tab, choose "Update weather data", then "Run workflow".

| Symptom | Likely cause |
|---|---|
| Gold "Demo data" badge | That layer's file is missing; see the report card |
| Data times in the legends are old | Scheduled runs are delayed or paused; run it by hand |
| Dew point or altimeter map missing | The Oklahoma Mesonet server was unreachable; the step is skipped until it returns |
| Page shows 404 | In the repository's Settings, Pages, set the source to the `gh-pages` branch |
| Nothing has updated for weeks | GitHub paused the schedule after 60 days of no activity; re-enable it on the Actions tab |
| Globe is blank | The browser could not start 3D graphics; try a current Chrome or Safari |

## Data sources and credits

- **RAP analysis**: NOAA/NCEP, via the NOAA Open Data Dissemination archive.
- **ASOS reports and NEXRAD composite**: Iowa Environmental Mesonet, Iowa State University.
- **Round Rock station**: TexMesonet, Texas Water Development Board.
- **Forecast and alerts**: National Weather Service.
- **Satellite**: NOAA/NESDIS GOES-19 GeoColor.
- **Fronts map**: NWS Weather Prediction Center.
- **Dew point and altimeter maps**: Oklahoma Mesonet, loaded directly from their server. These are copyrighted by the Oklahoma Mesonet; check their usage policy for a public page.
- **Map outlines**: Natural Earth; US Census Bureau.
- **Elevation**: Mapzen Terrain Tiles.
- **Software**: three.js (3D graphics), SunCalc (sun and moon), pygrib, NumPy, SciPy and Pillow (data job).
