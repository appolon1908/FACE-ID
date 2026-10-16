# Document Intelligence -> FACE-ID client flow

FACE-ID no longer performs document OCR.

Document scanning, OCR, QR decoding, field extraction, and human review belong to the standalone document products:

- Codestra-Document-Console
- Codestra-Document-Intelligence
- Codestra-OCR-Workers
- Codestra-Document-Schemas
- Codestra-Document-SDK

Canonical cross-system flow:

`Document Console -> Caddy -> Kong -> Middleware V3 :8095 -> Document Intelligence -> OCR Workers`

After review and confirmation, Middleware supplies FACE-ID with the versioned reviewed handoff:

`codestra.document.face-id-handoff/v1`

FACE-ID accepts that handoff at:

`POST /v1/clients/from-document-handoff`

The handoff contains only reviewed client/document references needed by FACE-ID. It does not contain raw ID images or a clear full document number.

## FACE-ID responsibilities

- maintain the client record used by FACE-ID
- store the protected document reference and last four digits
- link the reviewed client to a FACE-ID subject
- require a separate consented face capture for biometric enrollment
- maintain biometric retention, model/version, audit, and recognition state

## Non-responsibilities

FACE-ID does not:

- run Tesseract or another OCR engine
- decode document QR codes
- call issuing-authority websites
- determine government document authenticity
- persist raw ID front/back images
- automatically use the ID-card portrait for biometric enrollment
- call Document Intelligence directly for cross-system orchestration

Middleware V3 remains the cross-system integration authority.
