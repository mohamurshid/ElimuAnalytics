"""
Day 4: test whether the downloaded KICD curriculum design PDF has real,
selectable text (good -- straightforward to extract) or is a scanned
image (bad -- would need OCR, significantly more work).
"""

import pdfplumber

PDF_PATH = "grade5_mathematics_curriculum_design.pdf"  # adjust to your downloaded filename

with pdfplumber.open(PDF_PATH) as pdf:
    print(f"Total pages: {len(pdf.pages)}")
    print()

    # Check the first 3 pages
    for i, page in enumerate(pdf.pages[:3]):
        text = page.extract_text()
        print(f"--- Page {i + 1} ---")
        if text and len(text.strip()) > 20:
            print(f"REAL TEXT FOUND ({len(text)} characters)")
            print("First 300 characters:")
            print(text[:300])
        else:
            print("NO TEXT EXTRACTED -- this page is likely a scanned image, would need OCR")
        print()

    # Also check for tables, since curriculum designs are often laid out as tables
    # (Strand | Sub-strand | Learning Outcomes | Suggested Learning Experiences | Key Inquiry Questions)
    first_page_tables = pdf.pages[0].extract_tables()
    print(f"Tables found on page 1: {len(first_page_tables)}")
    if first_page_tables:
        print("First table preview:")
        for row in first_page_tables[0][:5]:
            print(row)
