// Plain-language messages for the screener's file reason codes
export const FILE_REASONS = {
  unsupported_type: "Only PDF and DOCX are accepted",
  file_too_large: "Larger than 5 MB",
  bad_signature: "The content does not match the file type",
  encrypted_pdf: "Password-protected PDF",
  too_many_pages: "More than 10 pages",
  zip_bomb: "Unsafe DOCX archive",
  bad_archive_path: "Unsafe DOCX archive",
  no_text: "No readable text",
  empty_file: "Empty file",
  unreadable_pdf: "The PDF could not be read",
  unreadable_docx: "The DOCX could not be read",
  ingest_failed: "Processing failed",
  cv_missing: "This row has no CV",
  cv_file_missing: "The CV file named in this row was not uploaded",
  cover_letter_file_missing: "The cover letter file named in this row was not uploaded",
  cover_letter_needs_posting: "Cover letter not kept: select a published offer before uploading",
};

export const UPLOAD_REASONS = {
  csv_no_cv_column: "The CSV needs a column named cv.",
  csv_empty: "The CSV has no candidates.",
  csv_too_many_rows: "The CSV has more than 100 candidates.",
  csv_too_large: "The CSV is larger than 5 MB.",
  csv_unreadable: "The CSV could not be read.",
  one_csv_only: "Upload one CSV at a time.",
};
