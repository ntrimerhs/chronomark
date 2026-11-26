# ChronoMark: Privacy Policy

Last updated: 25 November 2026

## 1. Who we are

The controller of your personal data for ChronoMark (chronomark.0digital.xyz) is Marios Drimeris, Milou 2, 12243 Aigaleo, Greece, VAT no. 184556010, contact email: drimeris@0digital.xyz.

This policy explains what data we process when you use our online service, why we process it, where it is stored, and what rights you have under the General Data Protection Regulation (EU) 2016/679 (GDPR) and Greek Law 4624/2019.

## 2. What data we collect

We collect only what is needed to run ChronoMark:

| Category | What it includes |
| --- | --- |
| Account | email, display name, profile picture (if you sign in with Google or GitHub), subscription plan |
| Files and content | videos, audio, YouTube links, PDF/PPTX/DOCX documents, the text extracted from them, transcripts and numerical representations (embeddings) used for search |
| Conversations | your questions and the answers, with or without a file attached, references to pages or timestamps, any quizzes and flashcards you generate, and the title of each conversation, which is written automatically by AI from its content (you can rename it) |
| Payments (once paid plans are available) | your card is entered only with Stripe, never on our servers. We receive the subscription status, billing email, the last digits of the card and your Stripe customer ID |
| Technical | IP address, device and browser type, operational logs, usage records (how many pages or minutes you have processed) |
| Sign-in | the session token stored in your browser (localStorage) |

We do not ask for special categories of data (for example health data). If the files you upload contain such data, you are responsible for that processing (see section 8).

## 3. Purposes and legal bases

We use your data only for the following purposes:

| Purpose | Legal basis (GDPR) |
| --- | --- |
| Creating and managing your account, providing the service (upload, analysis, answers, quizzes) | Performance of a contract, Art. 6(1)(b) |
| Subscription payments, invoicing and tax obligations | Contract, Art. 6(1)(b), and legal obligation, Art. 6(1)(c) |
| Security, abuse prevention, enforcing usage limits | Legitimate interests, Art. 6(1)(f) |
| Support and communication with you | Contract or legitimate interests, Art. 6(1)(b) or (f) |
| Sending the content of your files and your questions to DeepSeek, which stores data in China | Explicit consent, Art. 49(1)(a), which you can withdraw at any time (see section 5) |

**Marketing emails.** We will send you news and offers about ChronoMark only if you have explicitly opted in (a separate, unticked checkbox in the consent window shown before your first upload, or in your settings). The legal basis is consent, Art. 6(1)(a) GDPR and Art. 11 of Greek Law 3471/2006. Every marketing email contains an unsubscribe link, and you can withdraw your consent at any time from your account settings or at drimeris@0digital.xyz. We do not sell your data.

## 4. Recipients and processors

To run the service, the following providers process your data. We do not sell your data to anyone.

| Provider | What it does | What data it receives | Location |
| --- | --- | --- | --- |
| Hetzner Online GmbH (Germany) | Application hosting | Everything, while it is processed | Finland (EU) |
| Supabase | Accounts, database, conversations | Email, name, conversations, usage | EU |
| Qdrant Cloud | Content search (vectors) | Numerical representations of the content | EU (eu-west-1) |
| Google Document AI | Text recognition (OCR) for documents | PDF documents you upload | France (EU) |
| Cloudflare R2 | File storage | Files you upload | Mostly Europe, without a legal region guarantee; US-based provider |
| Google (Sign in with Google) and GitHub | Optional sign-in with your account | Email, name, profile picture | Worldwide, US |
| Groq | Speech-to-text, reading diagrams | Audio and images from your files | US |
| OpenAI | Creating embeddings for search | Text from your files | US |
| DeepSeek | Generating answers, quizzes, flashcards | Text of your files and your questions | China (see section 5) |
| Stripe | Subscription payments | Email, billing details, card details (directly to Stripe) | EU and US |

Stripe (for the EU, Stripe Payments Europe Ltd, Ireland) processes payment data both as our processor and as an independent controller for matters such as fraud prevention and its own legal obligations. Its own privacy policy applies to that processing. Your card details never pass through our servers.

With the providers that act as processors we have data processing agreements or we accept their processing terms. These providers may not use your data for their own purposes, except as described in section 5 for DeepSeek.

We may disclose data to authorities when the law requires it.

## 5. Transfers outside the European Union

The text of your files and your questions are sent to DeepSeek, which stores and processes data on servers in the People's Republic of China. **The European Commission has not issued an adequacy decision for China, and we have not agreed standard contractual clauses or other safeguards with the provider.**

This means that:

- your data may be less protected than in the EU;
- authorities in that country may have access to it;
- the provider's retention period is not defined;
- the provider may use the data to improve its models, as described in its own privacy policy.

The transfer is based on your explicit consent (Art. 49(1)(a) GDPR), which we ask for before your first upload. If you do not consent, you will not be able to use the features that need it. You can withdraw your consent at any time from your account settings or by email, without affecting the lawfulness of the processing carried out before the withdrawal. We recommend that you do not upload files containing personal, medical or confidential information about other people.

### United States

For providers based in or processing data in the United States, we rely on the following:

- **Groq:** the European Commission's standard contractual clauses (SCCs, Decision 2021/914) through Groq's data processing addendum (DPA), which applies when its terms are accepted.
- **OpenAI:** standard contractual clauses or an adequacy decision, through OpenAI's data processing addendum (DPA).
- **Cloudflare:** standard contractual clauses (SCCs) through Cloudflare's data processing addendum (DPA).
- **Stripe:** the EU-US Data Privacy Framework and, as a fallback, standard contractual clauses.
- **Supabase, Google, GitHub:** standard contractual clauses or the Data Privacy Framework, depending on the service. Our database is located in the EU.

You can request a copy of these safeguards at drimeris@0digital.xyz.

## 6. Data retention

We keep your data only as long as needed:

| Data | How long |
| --- | --- |
| Account details | While the account exists, and up to 30 days after it is closed (backups) |
| Files, transcripts, embeddings | Deleted automatically at most 3 hours after upload, or sooner if you delete them |
| Conversations | Until you delete them or close your account. Chat history, including its title and the name of the file it belongs to, is the only thing we keep after the 3 hours |
| Technical logs and usage records | 90 days |
| Payment and invoice records | As long as tax law requires (currently up to 10 years from the end of the tax year) |
| Email address for marketing updates | Until you withdraw your consent |

Deleting your files, automatically or manually, also deletes the extracted text, the summary, the transcript, the frames and audio, and the corresponding embeddings in Qdrant. If our storage runs full, a file can be removed before the 3 hours are up. How long DeepSeek keeps the data sent to it is decided by that provider and we cannot control it.

## 7. Your rights

You have the following rights:

- **Access:** to learn whether we process your data and to receive a copy of it.
- **Rectification:** to have inaccurate or incomplete data corrected.
- **Erasure:** to ask for your data to be deleted, either with the delete button in the app or by email.
- **Restriction and objection:** to restrict or object to specific processing.
- **Portability:** to receive the data you gave us in a structured format.
- **Withdrawal of consent:** for the transfer to China and for marketing emails, at any time. Withdrawal does not affect the lawfulness of processing before it.

To exercise any of these rights, email drimeris@0digital.xyz. We will reply within one month, or extend that period as the law allows.

You also have the right to lodge a complaint with the Hellenic Data Protection Authority (HDPA, 1-3 Kifisias Ave., 115 23 Athens, www.dpa.gr).

## 8. Other terms

**Security.** We use encryption in transit (HTTPS), access control with per-account data isolation in the database (row level security), and authentication of requests with a digitally signed session token. If a data breach affecting you is identified, we will inform you and notify the Authority within the period set by law (72 hours).

**Minors.** We do not set a minimum age for using the service. If you are under 15, you need the consent of your parent or guardian for the processing of your data (Art. 8 GDPR, Art. 21 of Greek Law 4624/2019), and the consent to the transfer to China must be given by them. If you believe a minor has created an account without such consent, contact us and we will delete it.

**Files containing other people's data.** If the files you upload contain other people's personal data (for example voices or names in a lecture video), you are responsible for having the right to use them and for any permission to reproduce them. Do not upload medical, financial or other sensitive information about other people.

**Service limits.** To keep the service stable, documents can be up to 40 MB, and only a few files are processed at the same time, so your upload may wait for its turn. YouTube imports are limited to 1080p. We may introduce usage limits per account.

**Artificial intelligence.** Answers, quizzes and flashcards are generated automatically with artificial intelligence and may contain errors. We do not make decisions that legally affect you solely by automated processing.

**Browser storage.** To keep you signed in, we store the session token in your browser's localStorage. It is necessary for the service to work and does not require consent. We do not use advertising, tracking or analytics cookies. Stripe may place its own cookies on the payment page.

**Changes.** We will change this policy when our providers or the service change. We will update the date at the top and, if the change is significant (for example a new processor of your data or a new transfer), we will notify you and ask for your consent again where necessary.

**Contact.** For any personal data matter: Marios Drimeris, Milou 2, 12243 Aigaleo, Greece, drimeris@0digital.xyz.
