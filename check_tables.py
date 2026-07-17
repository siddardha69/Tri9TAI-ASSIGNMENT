import pdfplumber

def check_tables(filepath):
    print(f"=== Tables in {filepath} ===")
    with pdfplumber.open(filepath) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if tables:
                print(f"Page {i+1} has {len(tables)} tables:")
                for table in tables:
                    for row in table[:3]:
                        print(f"  {row}")
                    if len(table) > 3:
                        print(f"  ... and {len(table)-3} more rows")
            else:
                print(f"Page {i+1} has no tables.")

if __name__ == "__main__":
    check_tables("ct200_manual.pdf")
