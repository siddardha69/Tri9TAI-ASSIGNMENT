import pdfplumber
import sys

# Reconfigure stdout to use utf-8
sys.stdout.reconfigure(encoding='utf-8')

def extract_and_save(filepath, output_txt):
    print(f"=== Extracting {filepath} to {output_txt} ===")
    with pdfplumber.open(filepath) as pdf:
        with open(output_txt, "w", encoding="utf-8") as f:
            f.write(f"=== {filepath} ===\n")
            f.write(f"Total pages: {len(pdf.pages)}\n\n")
            for idx, page in enumerate(pdf.pages):
                f.write(f"--- Page {idx + 1} ---\n")
                text = page.extract_text()
                if text:
                    f.write(text)
                else:
                    f.write("[No text found on this page]")
                f.write("\n\n")
    print(f"Done saving to {output_txt}")

if __name__ == "__main__":
    extract_and_save("ct200_manual.pdf", "ct200_manual_extracted.txt")
    extract_and_save("ct200_manual_v2.pdf", "ct200_manual_v2_extracted.txt")
