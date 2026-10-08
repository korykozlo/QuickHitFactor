"""Rebuild data/classifiers.json and the diagram images from USPSA sources.

Usage: python3 tools/build_data.py <dir-with-classifier-pdfs> <hhf-report.pdf>

Classifier PDFs: https://uspsa.org/resources/classifiers/<code>.pdf
HHF report: https://s3.uspsa.io/classification/Classifier%20Committee%20-%202025_Recommended_High_Hit_Factors_and_System_Updates.pdf
Needs poppler-utils (pdftotext, pdftoppm) and Pillow.
"""
import json, os, re, subprocess, sys, tempfile
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "classifiers.json")
DIAGRAMS = os.path.join(ROOT, "diagrams")
HHF_SOURCE = "https://s3.uspsa.io/classification/Classifier%20Committee%20-%202025_Recommended_High_Hit_Factors_and_System_Updates.pdf"

# Read from each classifier's stage sheet: scoring type, scoring hits, steel targets.
# Steel scores as an A (5 points) and has no C/D zone.
STAGES = {
    "03-03": ("Comstock", 11, 3), "03-05": ("Comstock", 10, 6), "03-07": ("Virginia", 20, 0),
    "03-08": ("Virginia", 14, 0), "03-09": ("Virginia", 16, 0), "03-18": ("Virginia", 24, 0),
    "06-03": ("Virginia", 20, 0), "06-04": ("Comstock", 8, 2), "06-05": ("Comstock", 8, 2),
    "06-10": ("Comstock", 6, 6), "08-02": ("Virginia", 20, 0), "08-03": ("Comstock", 6, 2),
    "09-10": ("Comstock", 12, 0), "13-02": ("Virginia", 8, 0), "13-04": ("Virginia", 18, 0),
    "13-05": ("Virginia", 16, 0), "13-06": ("Virginia", 10, 0), "18-03": ("Virginia", 24, 0),
    "18-05": ("Comstock", 16, 4), "18-07": ("Comstock", 8, 2), "18-08": ("Virginia", 16, 0),
    "18-09": ("Virginia", 24, 0), "19-01": ("Comstock", 12, 0), "19-02": ("Comstock", 12, 4),
    "19-04": ("Comstock", 14, 0), "20-01": ("Comstock", 12, 2), "20-02": ("Comstock", 12, 0),
    "20-03": ("Comstock", 12, 4), "21-01": ("Comstock", 24, 0), "22-01": ("Comstock", 18, 0),
    "22-02": ("Comstock", 18, 0), "22-04": ("Virginia", 16, 0), "22-06": ("Comstock", 7, 1),
    "22-07": ("Comstock", 14, 0), "23-01": ("Comstock", 12, 0), "23-02": ("Comstock", 12, 0),
    "24-01": ("Virginia", 24, 0), "24-02": ("Comstock", 18, 0), "24-04": ("Virginia", 18, 0),
    "24-06": ("Comstock", 18, 0), "24-08": ("Comstock", 24, 0), "24-09": ("Comstock", 18, 0),
    "25-01": ("Comstock", 19, 1), "25-02": ("Comstock", 10, 0), "25-03": ("Comstock", 10, 0),
    "25-04": ("Comstock", 10, 0), "25-05": ("Comstock", 16, 4), "25-06": ("Comstock", 14, 0),
    "25-07": ("Comstock", 14, 0), "25-08": ("Comstock", 10, 0), "25-09": ("Virginia", 12, 0),
    "26-01": ("Comstock", 14, 2), "26-02": ("Comstock", 14, 2), "26-03": ("Comstock", 10, 0),
    "26-04": ("Comstock", 12, 0), "26-05": ("Comstock", 12, 0), "99-08": ("Virginia", 12, 0),
    "99-10": ("Comstock", 12, 0), "99-11": ("Virginia", 12, 0), "99-12": ("Comstock", 12, 0),
    "99-13": ("Virginia", 24, 0), "99-19": ("Virginia", 12, 0), "99-28": ("Comstock", 12, 6),
    "99-42": ("Comstock", 12, 4), "99-46": ("Virginia", 24, 0), "99-53": ("Comstock", 12, 6),
    "99-57": ("Comstock", 12, 4), "99-62": ("Comstock", 6, 4),
}

DIVISION_TABLES = {
    "Open": "open", "Limited": "limited", "Production": "production", "Revolver": "revolver",
    "Single Stack": "single-stack", "Carry Optics": "carry-optics", "PCC": "pcc",
    "Limited Optics": "limited-optics",
}


def read_hhfs(report):
    text = subprocess.run(["pdftotext", "-layout", report, "-"], capture_output=True, text=True).stdout
    text = text.split("Appendix B: High Hit Factor Tables")[-1]
    hhfs, division = {}, None
    for line in text.splitlines():
        m = re.search(r"Table \d+: (.+?) Division", line)
        if m:
            division = DIVISION_TABLES[m.group(1).strip()]
            continue
        m = re.match(r"\s*(\d\d-\d\d)\s+.+?\s+(\d+\.\d+)\s+(?:-?\d+\.\d+|-)?\s*(?:-?\d+\.\d+|-)?\s*$", line)
        if m and division:
            hhfs.setdefault(m.group(1), {})[division] = float(m.group(2))
    return hhfs


def render_diagram(pdf, out):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-r", "110", "-png", pdf, f"{tmp}/p"], check=True)
        png = next(os.path.join(tmp, f) for f in os.listdir(tmp))
        img = Image.open(png).convert("RGB")
        img.save(out, "WEBP", quality=72, method=6)


def main(pdf_dir, report):
    data = json.load(open(DATA))
    hhfs = read_hhfs(report)
    os.makedirs(DIAGRAMS, exist_ok=True)
    for c in data["classifiers"]:
        code = c["code"]
        scoring, hits, steel = STAGES[code]
        c["scoring"] = scoring
        c["rounds"] = hits
        c["points"] = hits * 5
        c["steel"] = steel
        c["hhf"] = hhfs.get(code, {})
        # Placeholder: tools/fetch_hitfactor_hhfs.py replaces it with hitfactor.info's L10 HHF.
        if "limited" in c["hhf"]:
            c["hhf"]["limited-10"] = c["hhf"]["limited"]
        c["pdf"] = f"https://uspsa.org/resources/classifiers/{code}.pdf"
        c["diagram"] = f"diagrams/{code}.webp"
        render_diagram(os.path.join(pdf_dir, f"{code}.pdf"), os.path.join(DIAGRAMS, f"{code}.webp"))
    data["hhfSource"] = HHF_SOURCE
    data["retrieved"] = "2026-10-07"
    with open(DATA, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    main(*sys.argv[1:3])
