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
- Scores come from [hitfactor.info](https://www.hitfactor.info)'s open API (`/api/shooters/<division>/<member>`), which mirrors classifier scores uploaded to PractiScore. uspsa.org's classification pages sit behind a bot challenge and send no CORS headers, so a page on another site can't read them.
- Class = average of the best 6 of the latest 8 classifier percentages in the division (each score's HF ÷ this app's HHF where it has one). Under 5 scores is unclassed; with 5, the 6th score sets the class, and the target is the class above their 5-score average.
- USPSA never moves a member down, so the class USPSA has on record (as hitfactor.info reports it) wins when it's higher.

## Scoring
- Min HF = HHF × class percentage (MAX 110, HHF 100, GM 95, M 85, A 75, B 60, C 40).
- Points: A 5; C 3 minor / 4 major; D 1 minor / 2 major; miss −10. Steel scores as an A or a miss.
- Max time = points ÷ min HF, rounded down to 0.01 s. No-shoots and procedurals are not included.

## Run it
`npm start`, then open http://localhost:8000. `npm test` runs the calculator tests.

Pushes to `main` deploy to GitHub Pages through `.github/workflows/pages.yml` once Pages is set to "GitHub Actions" in the repository settings.
