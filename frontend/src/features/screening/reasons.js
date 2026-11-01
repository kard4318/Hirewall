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
};
