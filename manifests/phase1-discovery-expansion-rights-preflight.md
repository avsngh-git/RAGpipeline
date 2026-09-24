# Phase 1 discovery expansion: source and rights preflight

**Reviewed:** 2026-09-24  
**Status:** preliminary, read-only source review. This does not approve the 33
proposed additions or authorize PDF acquisition, storage, extraction, indexing,
or public passage display. No PDFs were added to the project artifact store.

This preflight concerns the exact 33 candidates in the
[screening proposal](phase1-discovery-expansion-screening-proposal.md). The
OpenAlex metadata snapshot reported a primary-location PDF URL for 29 records,
`cc-by` for 20, `cc-by-nc-nd` for 3, and no license for 10. Those are discovery
metadata, not proof of the terms attached to the actual file that would be
selected. Direct source checks below found some differences from those labels.

## Candidate-level outcome

| Preliminary source status | Candidate IDs | Finding and remaining check |
|---|---|---|
| CC BY 4.0 stated by the hosting source | W4389520670, W4404781523, W4404784153, W4412886806, W3015883388, W3156836409, W3170739233, W3172119680, W3206455169, W4389524402, W4402671832, W4404781233, W4404782892, W4404783040, W4411113095, W4412888476 | These 16 records are ACL Anthology papers published after 2016. The Anthology copyright notice says materials published in or after 2016 use CC BY 4.0. Check the selected article page and PDF for any separately credited third-party material before acquisition. |
| CC BY 4.0 stated by the hosting source | W3203288040, W4297162632, W4403006857 | Their arXiv records link to CC BY 4.0. For W3203288040 and W4297162632, OpenAlex did not report a license; the arXiv pages do. Preserve the arXiv version and attribution when choosing a source. |
| CC BY 4.0 stated by the publisher | W4406596702, W4414925442 | The Nature and Frontiers article pages state CC BY. The Nature article expressly notes that separately credited third-party content can have different terms. |
| CC BY 4.0 stated for repository-hosted final versions | W4412673546, W4396821195 | TU Delft identifies W4412673546's repository copy as the final published version under CC BY 4.0. The University of Pisa repository's W4396821195 PDF states CC BY 4.0. Verify that the exact repository file selected at acquisition is the reviewed version. |
| CC BY-NC-ND 4.0 publisher versions | W7127589252, W4410634422, W4402854593 | Publisher pages state noncommercial use and sharing, and no sharing of adapted material. Whether the planned local extraction, chunking, and indexing fit those terms has not been established. Keep these versions out of the full-text set until that use is reviewed or separate permission is obtained. |
| CC BY-NC-ND 4.0 author-hosted preprint statement | W4281259526 | Coauthor Yiding Liu's publication page labels the ERNIE-Search preprint CC BY-NC-ND 4.0 and links to its arXiv PDF. This is a version-specific author-side statement; verify the exact file and licensing authority, and review how the project's processing and any display fit the terms before acquisition. |
| CC BY-NC-SA 4.0 alternate versions | W4411549467, W4409282347 | The arXiv versions (2405.13576 and 2407.15353 v2, respectively) link to CC BY-NC-SA 4.0. The inspected author-hosted FlashRAG ACM PDF carries a different personal/classroom-use notice, and the EDA ACM proceedings version still needs item-level review. Do not transfer terms between versions. Review the license conditions for the project's processing, derived artifacts and any public display before acquisition. |
| Author-hosted accepted version with ACM personal/classroom-use notice | W4384656680 | The University of Glasgow repository identifies this as an accepted version. Its PDF permits personal/classroom copies and says other copying, server posting or redistribution requires prior permission. The arXiv version separately links to arXiv's non-exclusive distribution license. Neither source establishes permission for this project's storage and indexing. |
| Publisher/source rights unresolved | W4385889719, W4389269373 | W4385889719 has a 2025 ACM TOIS version linked from an author publication page; the arXiv version links only to arXiv's non-exclusive distribution license. W4389269373 is an ACM journal article whose author/research-lab page links to the publisher record. Item-level reuse terms for the exact selected versions were not confirmed. ACM's 2026 Open Access transition announcement does not establish terms for these older versions. |
| Publisher version is all rights reserved; repository version needs its own review | W4399480372 | Oxford marks the published version “Available for Purchase” and says all rights reserved. PubMed lists a PMC record, and an institutional repository identifies a post-print, but this review did not verify reuse terms for that deposited copy. PMC's author-manuscript guidance allows text mining and uses consistent with fair use; it does not establish the project's storage/indexing rights for this copy. The repository copy is not cleared for ingestion yet. |

The grouped outcomes account for all 33 recommendations: 23 have a CC BY
source-level path identified, while 10 require further rights review. A CC BY
statement is still not blanket clearance for separately credited content or for
a different version downloaded from another host. Before any acquisition,
record the exact file/version, source URL, permission evidence, acquisition
time, checksum, and document version. Assess public passage display separately.

## Source records consulted

- ACL Anthology: [information for submitters](https://aclanthology.org/info/contrib/)
  and an [included article page](https://aclanthology.org/2025.acl-long.131/).
  Anthology article pages carry the publication-date copyright notice.
- arXiv records: [2308.07107](https://arxiv.org/abs/2308.07107),
  [2110.03611](https://arxiv.org/abs/2110.03611),
  [2205.09153](https://arxiv.org/abs/2205.09153),
  [2209.11755](https://arxiv.org/abs/2209.11755),
  [2307.16779](https://arxiv.org/abs/2307.16779),
  [2405.13576](https://arxiv.org/abs/2405.13576),
  [2407.15353](https://arxiv.org/abs/2407.15353), and
  [2408.10343](https://arxiv.org/abs/2408.10343). The three default-license
  records link to [arXiv's non-exclusive distribution license](https://arxiv.org/licenses/nonexclusive-distrib/1.0/license.html).
  The arXiv records 2405.13576 and 2407.15353 link to the
  [CC BY-NC-SA 4.0 license](https://creativecommons.org/licenses/by-nc-sa/4.0/);
  the latter page identifies v2 as the current version. For ERNIE-Search,
  [coauthor Yiding Liu's publication page](https://liuyiding.net/publication/lu-2022-ernie/)
  states CC BY-NC-ND 4.0 for its preprint page; the associated PDF link points
  to arXiv.
- Repository/author versions: the [University of Glasgow record for LADR](https://eprints.gla.ac.uk/296333/)
  identifies an accepted version; its [PDF](https://eprints.gla.ac.uk/296333/2/296333.pdf)
  contains the ACM personal/classroom-use notice. The [RUC author publication page's
  survey PDF](https://playbigdata.ruc.edu.cn/dou/publication/2025_Survey_LLM4IR.pdf)
  could not be inspected for rights terms during this preflight. The [Naver Labs
  record for sparse neural IR](https://europe.naverlabs.com/research/publications/towards-effective-and-efficient-sparse-neural-information-retrieval/)
  links to the ACM version; its DOI page was inaccessible to this review.
- Publisher terms: [Clinical entity augmented retrieval](https://www.nature.com/articles/s41746-024-01377-1),
  [OpenScholar](https://www.nature.com/articles/s41586-025-10072-4),
  [Dual retrieving and ranking medical LLM](https://www.nature.com/articles/s41598-025-00724-w),
  [MEGA-RAG](https://www.frontiersin.org/journals/public-health/articles/10.3389/fpubh.2025.1635381/full),
  and the [2026 RAG survey](https://link.springer.com/article/10.1007/s10462-026-11605-7).
- RefAI: [Oxford's article record](https://academic.oup.com/jamia/article/31/9/2030/7690757),
  [PubMed record](https://pubmed.ncbi.nlm.nih.gov/38857454/),
  [PMC full-text record](https://pmc.ncbi.nlm.nih.gov/articles/PMC11339508/),
  [PMC copyright and author-manuscript guidance](https://pmc.ncbi.nlm.nih.gov/about/copyright/),
  and the [institutional repository record identifying the post-print](https://digitalcommons.library.tmc.edu/uthshis_docs/671/).
- Repository-hosted ACM versions: [TU Delft's final-version record for W4412673546](https://repository.tudelft.nl/record/uuid:bab4a12e-455b-49ea-bdf8-7f6a88478f60)
  and the [University of Pisa's W4396821195 PDF](https://arpi.unipi.it/retrieve/14da2143-a4df-443b-b422-03d92afdfc62/3626772.3657769%20%281%29.pdf).
- ACM: [transition announcement](https://www.acm.org/publications/openaccess)
  and the [inspected author-hosted FlashRAG published-version PDF](https://playbigdata.ruc.edu.cn/dou/publication/2025_WWW_Demo_FlashRAG.pdf).
  The announcement describes the 2026 transition; item-level terms for the two
  remaining ACM records remain to be checked.

## Gate

Keep the v2/v3 manifests in draft with undecided records. The user must first
approve the screening decisions. If approved, source review still has to select
and document a permitted full-text version for each paper. Do not count a
metadata inclusion as a full-text acceptance.
