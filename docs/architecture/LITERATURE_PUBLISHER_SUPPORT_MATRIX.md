# Publisher Full-text Support Matrix

This matrix describes implemented and verified code paths in
pipeline_contracts/literature_acquisition. A WebVPN resource ID alone is not
evidence of publisher support.

| Publisher | Status | Implemented route | SI route |
|---|---|---|---|
| Elsevier / ScienceDirect | **SUPPORTED** | Crossref DOI→PII; CDP article page/lazy-load/print CSS cleanup/Page.printToPDF | MMC / ars.els-cdn.com attachment discovery; validated PDF/ZIP/DOCX |
| Wiley Online Library | **SUPPORTED** | /doi/pdfdirect/{doi}?download=true | Full-text page downloadSupplement link discovery |
| IOP Publishing | **SUPPORTED** | /article/{doi}/pdf | No dedicated SI algorithm in upstream implementation |
| The Electrochemical Society (ECS) | **SUPPORTED via IOP-compatible route only when publisher metadata maps to ECS and the configured resource resolves to that route** | /article/{doi}/pdf | No dedicated SI algorithm |
| Springer / Springer Nature | **NOT_IMPLEMENTED** | None | None |
| ACS / American Chemical Society | **NOT_IMPLEMENTED** | None | None |
| RSC / Royal Society of Chemistry | **NOT_IMPLEMENTED** | None | None |
| Nature Portfolio | **NOT_IMPLEMENTED** | None | None |
| Science / AAAS | **NOT_IMPLEMENTED** | None | None |
| Other / unknown | **NOT_IMPLEMENTED or UNAVAILABLE** | No generic downloader | None |

When a supported publisher is identified but local WebVPN portal/resource
configuration, authorized Cookie accounts or a browser executable is missing,
the result is UNAVAILABLE. CAPTCHA, access denial and rate limiting stop
retrieval; they are not bypassed. No Open Access fallback is claimed because
this port does not include a separately implemented and tested OA downloader.
