// Plain-language messages for the screener's file and application reason codes
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

const APPLICATION_REASONS = {
  consent_required: "Please give your consent to apply.",
  invalid_name: "Please enter your full name.",
  invalid_email: "Please enter a valid email address.",
  cv_required: "Please attach your CV.",
  job_closed: "This offer is closed and no longer takes applications.",
  job_not_found: "This offer is not available.",
  too_many_applications: "Too many attempts. Please wait a minute and try again.",
  try_later: "We are receiving many applications. Please try again in a few minutes.",
  upload_too_large: "Your files are too large. Each must be 5 MB or less.",
};

export function applicationMessage(code) {
  if (APPLICATION_REASONS[code]) return APPLICATION_REASONS[code];
  for (const [prefix, label] of [["cover_letter_", "Cover letter"], ["cv_", "CV"]]) {
    if (code?.startsWith(prefix)) {
      return `${label}: ${FILE_REASONS[code.slice(prefix.length)] ?? "This file was refused"}.`;
    }
  }
  return "Your application could not be sent. Please try again.";
}
