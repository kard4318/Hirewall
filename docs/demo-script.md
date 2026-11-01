# Demo Script

Step-by-step walkthrough for the live demo, including the red-team attack scenarios.

TODO: the other services.

## From a job offer to a shortlist

Set up as in "Run the screener" in the README, with Ollama running. The files are in `data/`.

1. **Import an offer.** At `/hr/screening`, choose **Import offer from PDF** and pick `attacks/applications/offer_unfair.pdf`.
   The form fills in, and a warning lists the line asking for age, gender and a photo.
2. **Review and publish.** Correct any field, choose **Publish**, and confirm the warning.
3. **Upload candidates.** With the offer selected, drop `resumes/cvs/ines_kacem_backend.pdf` and
   `resumes/cvs/walid_saidi_data.pdf`. They are attached to this job, and listed under "2 applications".
   To import several at once, select the offer and drop `resumes/candidates_sample.csv` with the two PDFs it names. The
   third row holds its CV as text, and cover letters appear under Extracted data.
4. **See a refused file.** Drop a file that is not a PDF or DOCX. The result line explains why.
5. **Read a candidate.** Open one from the list: the CV data is there without a name.
6. **Score.** Choose **Score candidates**. Only this job's two candidates are scored.
7. **Shortlist.** Tick a candidate, choose **Propose shortlist**, follow the link, and choose **Approve and invite**. The
   candidate gets the Scheduler's invitation at the address in their CV, and appears on the Scheduling page.
   Set `EMAIL_MODE=smtp` to deliver it, and `PUBLIC_BASE_URL` to an address the candidate can open.
   **Propose rejection** works the same way and emails a rejection.
8. **Close the offer.** Choose **Review offer**, then **Close offer**.

## Attacks to show

| File in `data/attacks/` | What happens |
|---|---|
| `applications/offer_hidden.pdf` | White text in an offer is removed and shown to HR |
| `resumes/white_text.pdf` | White text in a CV is removed and flagged, and the score does not change |
| `resumes/visible_ar.docx` | A visible instruction in Arabic is removed and flagged |

Both folders have a README with the expected result for every file.
