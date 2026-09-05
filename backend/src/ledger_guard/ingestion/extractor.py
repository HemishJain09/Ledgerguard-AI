import os
import polars as pl
import pdfplumber

def extract_file(file_path: str) -> pl.DataFrame:
    """
    Routes files to the appropriate extraction engine based on file extension.
    Returns a Polars DataFrame representing the raw rows.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == '.csv':
        return extract_csv_with_polars(file_path)
    elif ext == '.pdf':
        return extract_pdf_with_pdfplumber(file_path)
    elif ext == '.xlsx':
        return extract_xlsx_with_polars(file_path)
    else:
        raise ValueError(f"Unsupported file format: {ext}")

def extract_csv_with_polars(file_path: str) -> pl.DataFrame:
    """
    High-throughput, memory-safe tabular parsing for CSV files.
    """
    # Use strict=False to ensure we parse as much as possible, 
    # relying on the invariant probes later to catch bad types.
    return pl.read_csv(file_path, infer_schema_length=10000, ignore_errors=True)

def extract_xlsx_with_polars(file_path: str) -> pl.DataFrame:
    """
    Extracts Excel sheets into Polars DataFrame.
    """
    return pl.read_excel(file_path)

def extract_pdf_with_pdfplumber(file_path: str) -> pl.DataFrame:
    """
    Extracts structured rows from unstructured bank statement PDFs.
    Returns a Polars DataFrame.
    """
    extracted_rows = []
    
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            # Assuming the bank statement has a standard table structure
            table = page.extract_table()
            if table:
                # The first row of the first table is usually headers
                if not extracted_rows:
                    extracted_rows.extend(table)
                else:
                    # Skip headers on subsequent pages if they exist, 
                    # or just append raw data depending on format
                    extracted_rows.extend(table[1:] if table[0] == extracted_rows[0] else table)
                    
    if not extracted_rows:
        raise ValueError("Could not extract any tabular data from the PDF.")
        
    # Convert list of lists to Polars DataFrame
    headers = extracted_rows[0]
    data = extracted_rows[1:]
    
    return pl.DataFrame(data, schema=headers, orient="row")
