# QuickHitFactor
Easy to use hit factor calculator for USPSA classifiers.

Pick a classifier to see its stage diagram, pick a division (and Minor or Major where the division allows it) to see the minimum hit factor for each class, then pick a class to see every A/C/D/miss combination that makes it and the slowest time each one allows.

## Data
- `data/classifiers.json`: the 68 active classifiers from [uspsa.org/classifiers](https://uspsa.org/classifiers), with scoring type, scoring hits, steel count and the high hit factor (HHF) per division.
- HHFs come from USPSA's [2025 High Hit Factor tables](https://s3.uspsa.io/classification/Classifier%20Committee%20-%202025_Recommended_High_Hit_Factors_and_System_Updates.pdf). That report predates the 25-series, and the 26-series are trial classifiers, so those 14 have no HHF yet; the app lets you type one in.
- Limited-10 uses the Limited HHFs.
- `diagrams/`: page 1 of each USPSA stage sheet (© USPSA), rendered from `https://uspsa.org/resources/classifiers/<code>.pdf`.
- `tools/build_data.py` rebuilds both from the downloaded PDFs.

## Scoring
- Min HF = HHF × class percentage (GM 95, M 85, A 75, B 60, C 40).
- Points: A 5; C 3 minor / 4 major; D 1 minor / 2 major; miss −10. Steel scores as an A or a miss.
- Max time = points ÷ min HF, rounded down to 0.01 s. No-shoots and procedurals are not included.

## Run it
`npm start`, then open http://localhost:8000. `npm test` runs the calculator tests.

Pushes to `main` deploy to GitHub Pages through `.github/workflows/pages.yml` once Pages is set to "GitHub Actions" in the repository settings.
