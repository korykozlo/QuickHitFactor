# QuickHitFactor
Easy to use hit factor calculator for USPSA classifiers.

Pick a classifier to see its stage diagram, pick a division (and Minor or Major where the division allows it) to see the minimum hit factor for each class, then pick a class to see every A/C/D/miss combination that makes it and the slowest time each one allows.

## Data
- `data/classifiers.json`: the 68 active classifiers from [uspsa.org/classifiers](https://uspsa.org/classifiers), with scoring type, scoring hits, steel count and the high hit factor (HHF) per division.
- HHFs come from USPSA's [2025 High Hit Factor tables](https://s3.uspsa.io/classification/Classifier%20Committee%20-%202025_Recommended_High_Hit_Factors_and_System_Updates.pdf). That report predates the 25-series, so those come from hitfactor.info's current HHF, as does Limited-10 for every classifier.
- The 26-series HHFs are worked out from the published minimum hit factor for each class (HHF = GM minimum ÷ 0.95).
- `diagrams/`: page 1 of each USPSA stage sheet (© USPSA), rendered from `https://uspsa.org/resources/classifiers/<code>.pdf`.
- `tools/build_data.py` rebuilds both from the downloaded PDFs.

## Member lookup
Type a USPSA member number to see the hit factor that member needs on the selected classifier and division to move up a class, with the hit/time combinations for it.
- The class and average shown are the ones USPSA has on file. The scores decide what the next classifier needs: best 6 of the latest 8 in the division, each counting for at most 110%, a classifier shot again on a later day replacing the earlier attempt, zeros counting, and major matches counting at the member's match percentage. On the same date the higher percentage counts as more recent. Worked out this way, the average matches USPSA's own on the pages tested.

## Scoring
- Min HF = HHF × class percentage (MAX 110, HHF 100, GM 95, M 85, A 75, B 60, C 40).
- Points: A 5; C 3 minor / 4 major; D 1 minor / 2 major; miss −10. Steel scores as an A or a miss.
- Max time = points ÷ min HF, rounded down to 0.01 s. No-shoots and procedurals are not included.

## Run it
`npm start` runs the server (Node 18 or later, no dependencies), then open http://localhost:8000. `npm test` runs the tests.

Server settings, all optional: `SCRAPE_FALLBACK=0` turns off the Playwright fallback used when uspsa.org blocks a plain request; `PORT` (default 8000); `ALLOWED_ORIGIN` for a front end hosted on another site (default `*`); `CACHE_MINUTES` (default 15); `USPSA_PAGES_DIR` to read saved pages named `<NUMBER>.html` from a folder instead of fetching them. If the front end is hosted apart from the server, put the server's address in the `qhf-api` meta tag in `index.html`.

Pushes to `main` deploy the static site to GitHub Pages through `.github/workflows/pages.yml`. GitHub Pages can't run the server, so member lookup needs the server hosted somewhere too.

## Docker and Render
`docker build -t quickhitfactor . && docker run -p 8000:8000 quickhitfactor` runs the app and server in one container. The image has no Python or Playwright and sets `SCRAPE_FALLBACK=0`, so it only makes plain requests to uspsa.org; when uspsa.org's Cloudflare check blocks one, member lookup says so and the rest of the app keeps working.

To deploy on Render, create a Blueprint from this repo (New > Blueprint) and it picks up `render.yaml`: one free Docker web service that rebuilds on every push to `main`. Render sets `PORT` itself. To use it from the GitHub Pages site, put the Render URL in the `qhf-api` meta tag in `index.html`.
