# Demo Script

Step-by-step walkthrough for the live demo, including the red-team attack scenarios.

TODO: the other services.

## From a job offer to a shortlist

Set up as in "Run the screener" in the README, with Ollama running. The files are in `data/`.

1. **Import an offer.** At `/hr/screening`, choose **Import offer from PDF** and pick `attacks/applications/offer_unfair.pdf`.
   The form fills in, and a warning lists the line asking for age, gender and a photo.
2. **Review and publish.** Correct any field, choose **Publish**, and confirm the warning.
3. **Apply as a candidate.** In a private window, open `/jobs` and then the offer. Enter a fictional name and email,
   attach `resumes/cvs/ines_kacem_backend.pdf` as the CV and `attacks/applications/letter_visible.pdf` as the letter,
   tick consent and send. The applicant sees only a reference id.
4. **See a refused file.** Apply again with a file that is not a PDF or DOCX. The form explains why.
5. **Read the application.** Back in `/hr/screening`, "1 application" appears with a `flagged` label. Open it: the
   injected line is listed, and the CV and letter data are there without a name.
6. **Upload as HR.** Drop `resumes/cvs/walid_saidi_data.pdf`. It is attached to this job as an HR upload.
7. **Score.** Choose **Score candidates**. Only this job's two applicants are scored.
8. **Shortlist.** Tick a candidate, choose **Propose shortlist**, follow the link, and choose **Approve and invite**. The
   candidate gets the Scheduler's invitation at the address in their CV, and appears on the Scheduling page.
   Set `EMAIL_MODE=smtp` to deliver it, and `PUBLIC_BASE_URL` to an address the candidate can open.
   **Propose rejection** works the same way and emails a rejection.
9. **Close the offer.** Choose **Close offer**. The offer leaves `/jobs`, and its page says it is closed.

## Attacks to show

| File in `data/attacks/` | What happens |
|---|---|
| `applications/offer_hidden.pdf` | White text in an offer is removed and shown to HR |
| `applications/letter_hidden.pdf` | White text in a letter is removed and flagged, and the score does not change |
| `resumes/white_text.pdf` | White text in a CV is removed and flagged, and the score does not change |
| `resumes/visible_ar.docx` | A visible instruction in Arabic is removed and flagged |

Both folders have a README with the expected result for every file.
