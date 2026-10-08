# QuickHitFactor
Easy to use hit factor calculator for USPSA classifiers.

Pick a classifier to see its stage diagram, pick a division (and Minor or Major where the division allows it) to see the minimum hit factor for each class, then pick a class to see every A/C/D/miss combination that makes it and the slowest time each one allows.

## Data
- `data/classifiers.json`: the 68 active classifiers from [uspsa.org/classifiers](https://uspsa.org/classifiers), with scoring type, scoring hits, steel count and the high hit factor (HHF) per division.
- HHFs come from USPSA's [2025 High Hit Factor tables](https://s3.uspsa.io/classification/Classifier%20Committee%20-%202025_Recommended_High_Hit_Factors_and_System_Updates.pdf). That report predates the 25-series, so those come from hitfactor.info's current HHF, as does Limited-10 for every classifier.
- The 26-series (trial) HHFs are worked out from the published minimum hit factor for each class (HHF = GM minimum ÷ 0.95).
- `diagrams/`: page 1 of each USPSA stage sheet (© USPSA), rendered from `https://uspsa.org/resources/classifiers/<code>.pdf`.
- `tools/build_data.py` rebuilds both from the downloaded PDFs.

## Scoring
- Min HF = HHF × class percentage (GM 95, M 85, A 75, B 60, C 40).
- Points: A 5; C 3 minor / 4 major; D 1 minor / 2 major; miss −10. Steel scores as an A or a miss.
- Max time = points ÷ min HF, rounded down to 0.01 s. No-shoots and procedurals are not included.

## Run it
`npm start`, then open http://localhost:8000. `npm test` runs the calculator tests.

Pushes to `main` deploy to GitHub Pages through `.github/workflows/pages.yml` once Pages is set to "GitHub Actions" in the repository settings.
