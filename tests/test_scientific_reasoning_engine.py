from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from pipeline_contracts.scientific_planning.planning_orchestrator import filter_resolved_manifest_fields
from pipeline_contracts.scientific_planning.research_planner import build_research_plan
from pipeline_contracts.scientific_planning.decision_policy import evidence_gap
from pipeline_contracts.scientific_planning.literature_engine import (
    ScientificResearchEngine,
    _build_decision_proposals,
    _merge_records,
    _reconcile_identifiers,
    _crossref_retraction_state,
    _external_evidence_matrix,
    build_scientific_context,
    build_search_queries,
    detect_scientific_issues,
    select_literature_databases,
)
from pipeline_contracts.scientific_planning.paperqa2_plugin import query_local_paperqa2
from pipeline_contracts.project_lifecycle import ProjectLifecycle
from pipeline_contracts.project_pipeline import ProjectPipeline
from pipeline_contracts.workflow import WorkflowStore
from pipeline_contracts.scientific_planning.skills import (
    SkillUnavailable,
    list_selected_skills,
    load_skill_instructions,
    verify_vendored_asset,
)


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _profile():
    return {
        "scientific_planning": {
            "intent": {
                "research_question": "How does surface oxygen coverage affect adsorption energy?",
                "research_goal": {
                    "research_object": "oxide surface",
                    "comparison": "oxidized versus clean surface",
                    "target_conclusion": "relative adsorption energy",
                },
                "requested_observables": ["adsorption energy"],
                "requested_task_families": ["ELECTRONIC_STRUCTURE"],
            },
            "scientific_decisions": [{
                "field_path": "method.spin_resolution",
                "declared_by": "synthetic acceptance profile",
                "options": [
                    {
                        "option_id": "option-a",
                        "label": "Alternative A",
                        "value": "A",
                        "definition": "A synthetic methodological alternative",
                        "pros": ["A stated synthetic advantage"],
                        "cons": ["A stated synthetic limitation"],
                        "risks": ["A synthetic validation risk"],
                        "downstream_impacts": ["Changes a declared method field"],
                    },
                    {
                        "option_id": "option-b",
                        "label": "Alternative B",
                        "value": "B",
                        "definition": "A second synthetic methodological alternative",
                        "pros": ["A second synthetic advantage"],
                        "cons": ["A second synthetic limitation"],
                        "risks": ["A second synthetic risk"],
                        "downstream_impacts": ["Changes the same declared method field"],
                    },
                ],
            }],
        }
    }


def _manifest():
    return {
        "source_document": {"file_name": "synthetic-frozen.docx", "sha256": "a" * 64},
        "systems": [{"name": "synthetic surface system"}],
        "claims": [],
        "evidence": [],
        "diagnostics": [],
        "unresolved_definitions": [{
            "code": "METHOD_PARAMETER_MISSING",
            "field_path": "method.spin_resolution",
            "description": "The method spin-resolution policy is not specified.",
            "evidence_ids": [],
        }],
        "unresolved_structured_fields": [],
        "profile_reconciliation": [],
        "confirmations": [],
    }


class _Lifecycle:
    def __init__(self, manifest):
        self._manifest = manifest
        self.saved = []

    def manifest(self, run_id):
        return self._manifest

    def run_info(self, run_id):
        return {"project_id": "synthetic-project"}

    def stage(self, run_id, stage):
        return {"stage": stage, "status": "PENDING", "outputs": {}}

    def approved_scientific_decisions(self, run_id):
        return []

    def research_dossiers(self, run_id):
        return []

    def persist_research_dossier(self, run_id, dossier_id, dossier_sha, json_path, markdown_path, metadata):
        self.saved.append({
            "run_id": run_id, "dossier_id": dossier_id, "dossier_sha256": dossier_sha,
            "json_path": json_path, "markdown_path": markdown_path, "metadata": metadata,
        })


class _PipelineStub:
    def __init__(self, root: Path, manifest):
        self.root = root
        self.lifecycle = _Lifecycle(manifest)

    def _run_root(self, run_id):
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path


class ScientificIssueClassificationTests(unittest.TestCase):
    def test_unique_frozen_source_claim_is_resolved_without_user_decision(self):
        manifest = _manifest()
        manifest["evidence"] = [{
            "evidence_id": "ev-source-1",
            "source": {"part": "word/document.xml", "paragraph": 14},
        }]
        manifest["claims"] = [{
            "field_path": "scientific_intent.research_goal.research_object",
            "value": "the declared source system",
            "evidence_ids": ["ev-source-1"],
        }]
        manifest["unresolved_definitions"] = [{
            "code": "SCIENTIFIC_SCOPE_UNDEFINED",
            "field_path": "scientific_intent.research_goal.research_object",
            "description": "An extracted field appears unresolved.",
            "evidence_ids": ["ev-source-1"],
        }]
        issues = detect_scientific_issues(manifest, _profile())
        issue = next(x for x in issues if x["affected_fields"] == ["scientific_intent.research_goal.research_object"])
        self.assertEqual(issue["classification"], "SOURCE_RESOLVED")
        self.assertEqual(issue["current_status"], "RESOLVED_AUTOMATICALLY")
        self.assertEqual(issue["source_resolution"]["resolved_value"], "the declared source system")
        self.assertEqual(issue["source_resolution"]["evidence_locations"][0]["locator"]["kind"], "paragraph")

    def test_conflicting_source_claims_do_not_auto_resolve(self):
        manifest = _manifest()
        manifest["evidence"] = [
            {"evidence_id": "ev-1", "source": {"paragraph": 10}},
            {"evidence_id": "ev-2", "source": {"paragraph": 21}},
        ]
        manifest["claims"] = [
            {"field_path": "scientific_intent.research_goal.comparison", "value": "A vs B", "evidence_ids": ["ev-1"]},
            {"field_path": "scientific_intent.research_goal.comparison", "value": "A vs C", "evidence_ids": ["ev-2"]},
        ]
        manifest["unresolved_definitions"] = [{
            "code": "SCIENTIFIC_SCOPE_UNDEFINED",
            "field_path": "scientific_intent.research_goal.comparison",
            "description": "The comparison is conflicted.",
            "evidence_ids": ["ev-1", "ev-2"],
        }]
        issue = next(x for x in detect_scientific_issues(manifest, _profile())
                     if x["affected_fields"] == ["scientific_intent.research_goal.comparison"])
        self.assertIsNone(issue["source_resolution"])
        self.assertEqual(issue["classification"], "GENUINE_SCIENTIFIC_DECISION")

    def test_pipeline_mapping_error_is_not_a_scientific_decision(self):
        manifest = _manifest()
        manifest["diagnostics"] = [{
            "code": "FIELD_MAPPING_ERROR",
            "field_path": "scientific_intent.research_goal.comparison",
            "message": "The source field was mapped to the wrong Project Profile property.",
            "blocks_execution": True,
        }]
        issue = next(x for x in detect_scientific_issues(manifest, _profile())
                     if x["source"].get("source_type") == "Frozen DOCX Manifest diagnostic")
        self.assertEqual(issue["classification"], "PIPELINE_INTERPRETATION_ISSUE")
        self.assertEqual(issue["current_status"], "REQUIRES_PIPELINE_REPAIR")

    def test_prior_approved_decision_resolves_same_field_in_child_run(self):
        manifest = _manifest()
        manifest["unresolved_definitions"] = [{
            "code": "METHOD_PARAMETER_MISSING",
            "field_path": "method.spin_resolution",
            "description": "This choice was approved in the parent revision.",
            "evidence_ids": [],
        }]
        bundle = {
            "research_plan": {
                "decision_records": [{
                    "decision_id": "decision-1",
                    "subject": "method.spin_resolution",
                    "status": "APPROVED_BY_USER",
                    "selected_value": "A",
                    "approval_ref": {"object_id": "decision-record-1", "sha256": "b" * 64},
                }]
            }
        }
        issue = next(x for x in detect_scientific_issues(manifest, _profile(), bundle)
                     if x["affected_fields"] == ["method.spin_resolution"])
        self.assertEqual(issue["classification"], "SOURCE_RESOLVED")
        self.assertEqual(issue["source_resolution"]["resolved_value"], "A")
        self.assertEqual(issue["source_resolution"]["decision_record_id"], "decision-record-1")

    def test_source_selected_researchplan_decision_is_not_reopened_on_child_run(self):
        manifest = _manifest()
        manifest["unresolved_definitions"] = [{
            "code": "SCIENTIFIC_SCOPE_UNDEFINED",
            "field_path": "scientific_intent.research_goal.research_object",
            "description": "A source-backed field was resolved in the prior revision.",
            "evidence_ids": [],
        }]
        bundle = {
            "research_plan": {
                "decision_records": [{
                    "decision_id": "source-resolution-1",
                    "subject": "scientific_intent.research_goal.research_object",
                    "status": "SELECTED_FROM_EVIDENCE",
                    "selected_value": "resolved object",
                    "source_evidence_refs": [{
                        "evidence_id": "ev-source-1",
                        "source_sha256": "a" * 64,
                        "locator": {"kind": "paragraph", "value": "word/document.xml#paragraph=12"},
                    }],
                }]
            }
        }
        issue = next(x for x in detect_scientific_issues(manifest, _profile(), bundle)
                     if x["affected_fields"] == ["scientific_intent.research_goal.research_object"])
        self.assertEqual(issue["classification"], "SOURCE_RESOLVED")
        self.assertEqual(issue["current_status"], "RESOLVED_IN_PRIOR_REVISION")
        self.assertEqual(issue["source_resolution"]["resolved_value"], "resolved object")

    def test_genuine_issue_builds_structured_queries_and_selects_domain_sources(self):
        issues = detect_scientific_issues(_manifest(), _profile())
        context = build_scientific_context(issues, _profile(), None, _manifest())
        queries = build_search_queries(context)
        self.assertTrue(queries)
        self.assertIn("openalex", select_literature_databases(context))
        self.assertIn("crossref", select_literature_databases(context))
        self.assertNotIn("europepmc", select_literature_databases(context))
        self.assertIn("europepmc", select_literature_databases({"discipline": "biomedical science"}))
        self.assertIn("arxiv", select_literature_databases({"discipline": "computational physics"}))


    def test_only_exactly_resolved_manifest_fields_are_filtered(self):
        manifest = {
            "unresolved_definitions": [
                {"field_path": "method.spin_resolution"},
                {"field_path": "method.functional"},
            ],
            "diagnostics": [
                {"field_path": "method.spin_resolution", "blocks_execution": True},
                {"field_path": "model.electronic_state.charge", "blocks_execution": True},
            ],
            "unresolved_structured_fields": [
                {"field_path": "method.spin_resolution"},
                {"field_path": "execution.resource_profile"},
            ],
            "profile_reconciliation": [
                {"field_path": "method.spin_resolution"},
                {"field_path": "profile.resource_profile"},
            ],
        }
        filtered, resolved = filter_resolved_manifest_fields(
            manifest,
            decision_overrides=[{"field_path": "method.spin_resolution"}],
        )
        self.assertEqual(resolved, {"method.spin_resolution"})
        self.assertEqual(
            [x["field_path"] for x in filtered["unresolved_definitions"]],
            ["method.functional"],
        )
        self.assertEqual(
            [x["field_path"] for x in filtered["diagnostics"]],
            ["model.electronic_state.charge"],
        )
        self.assertEqual(
            [x["field_path"] for x in filtered["unresolved_structured_fields"]],
            ["execution.resource_profile"],
        )
        self.assertEqual(
            [x["field_path"] for x in filtered["profile_reconciliation"]],
            ["profile.resource_profile"],
        )
        # The frozen parent Manifest is unchanged.
        self.assertEqual(len(manifest["unresolved_definitions"]), 2)

    def test_approved_decision_record_does_not_remove_unrelated_research_gap(self):
        intent = {
            "intent_id": "intent-synthetic",
            "schema_version": "1.0.0",
            "planning_metadata": {"object_sha256": "a" * 64},
            "requested_task_families": ["ANALYSIS"],
            "requested_observables": ["synthetic observable"],
            "source_evidence_refs": [],
        }
        unrelated = evidence_gap(
            "UNRELATED_METHOD_GAP", "method.functional",
            "A separate method choice remains unresolved.",
            "Resolve the unrelated method choice.",
        )
        approved = {
            "decision_id": "approved-decision",
            "subject": "method.spin_resolution",
            "status": "APPROVED_BY_USER",
            "selected_value": "A",
            "requires_user_approval": False,
        }
        plan = build_research_plan(intent, [unrelated], approved_decisions=[approved])
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertEqual(plan["evidence_gaps"], [unrelated])
        self.assertIn(approved, plan["decision_records"])
        self.assertTrue(any(x["code"] == "UNRELATED_METHOD_GAP" for x in plan["evidence_gaps"]))

class LiteratureIdentityAndDecisionTests(unittest.TestCase):
    def test_cross_database_duplicate_records_merge_by_doi(self):
        records = [
            {"database": "openalex", "doi": "https://doi.org/10.1234/example", "title": "A Sample Paper"},
            {"database": "crossref", "doi": "10.1234/EXAMPLE", "title": "A Sample Paper"},
            {"database": "europepmc", "doi": "10.1234/example", "title": "A Sample Paper", "pmid": "12345"},
        ]
        merged = _merge_records(records)
        self.assertEqual(len(merged), 1)
        self.assertEqual(set(merged[0]["database_sources"]), {"openalex", "crossref", "europepmc"})
        self.assertEqual(merged[0]["pmid"], "12345")

    def test_preprint_and_published_version_are_related_not_collapsed(self):
        merged = _merge_records([
            {"database": "arxiv", "arxiv_id": "2601.01234", "title": "A Shared Scientific Title"},
            {"database": "crossref", "doi": "10.1234/published", "title": "A Shared Scientific Title"},
        ])
        self.assertEqual(len(merged), 2)
        self.assertTrue(any(
            relation["relation"] == "preprint_published_version"
            for record in merged for relation in record["version_relationships"]
        ))

    def test_doi_title_mismatch_is_not_accepted_as_verified_identity(self):
        import pipeline_contracts.scientific_planning.literature_engine as module
        original = module._fetch_json
        try:
            module._fetch_json = lambda url: {"message": {"title": ["A Completely Different Title"]}}
            result = _reconcile_identifiers({"doi": "10.1234/demo", "title": "Expected Title"})
        finally:
            module._fetch_json = original
        self.assertEqual(result["status"], "DOI_RESOLVED_TITLE_MISMATCH")

    def test_crossref_retraction_notice_is_preserved(self):
        result = _crossref_retraction_state({
            "crossref_update_to": [{"type": "retraction", "DOI": "10.1234/retraction"}],
        })
        self.assertEqual(result, "RETRACTION_NOTICE_LINKED")

    def test_recommendation_is_withheld_without_option_specific_evidence(self):
        issue = {
            "issue_id": "issue-1", "classification": "GENUINE_SCIENTIFIC_DECISION",
            "affected_fields": ["method.spin_resolution"], "description": "Select a method option.",
            "related_planning_objects": ["MethodPlan"],
        }
        specs = [{
            "field_path": "method.spin_resolution",
            "options": [{"option_id": "A", "label": "A", "value": "A"}],
        }]
        dossier_decisions = _build_decision_proposals([issue], specs, [{"evidence_id": "ev-1"}], {})
        self.assertEqual(dossier_decisions[0]["status"], "PROPOSED")
        self.assertEqual(dossier_decisions[0]["approval_status"], "PENDING")
        self.assertIsNone(dossier_decisions[0]["assessment"]["option_id"])
        self.assertEqual(dossier_decisions[0]["assessment"]["confidence"], "INSUFFICIENT")

    def test_recommendation_requires_option_specific_evidence_ids(self):
        issue = {
            "issue_id": "issue-2", "classification": "GENUINE_SCIENTIFIC_DECISION",
            "affected_fields": ["method.spin_resolution"], "description": "Select a method option.",
            "related_planning_objects": ["MethodPlan"],
        }
        specs = [{
            "field_path": "method.spin_resolution",
            "options": [{"option_id": "A", "label": "A", "value": "A"}],
        }]
        assessment = {
            "recommended_option_id": "A", "reason": "Evidence favours A with stated caveats.",
            "confidence": "LOW",
            "option_assessments": [{
                "option_id": "A", "supporting_evidence_ids": ["ev-1"],
                "challenging_evidence_ids": ["ev-2"], "reason": "Mixed evidence, A remains better supported.",
            }],
        }
        result = _build_decision_proposals(
            [issue], specs, [{"evidence_id": "ev-1"}, {"evidence_id": "ev-2"}],
            {"issue-2": assessment},
        )[0]
        self.assertEqual(result["assessment"]["option_id"], "A")
        self.assertEqual(result["assessment"]["confidence"], "LOW")
        self.assertEqual(set(result["assessment"]["evidence_ids"]), {"ev-1", "ev-2"})


class _MockResearchPipeline:
    def __init__(self, root, manifest):
        self.root = root
        self.lifecycle = _Lifecycle(manifest)

    def _run_root(self, run_id):
        path = self.root / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path


def _mock_openalex_work(doi: str, title: str, year: int, word: str):
    return {
        "id": f"https://openalex.org/{doi.rsplit('/', 1)[-1]}",
        "doi": f"https://doi.org/{doi}",
        "title": title,
        "publication_year": year,
        "publication_date": f"{year}-01-01",
        "type": "article",
        "is_retracted": False,
        "ids": {"doi": doi},
        "authorships": [{"author": {"display_name": "Synthetic Author"}}],
        "primary_location": {"source": {"display_name": "Synthetic Journal"}},
        "open_access": {"is_oa": False, "oa_url": None},
        "abstract_inverted_index": {word: [0], "synthetic": [1], "finding": [2]},
    }


def _mock_crossref_work(doi: str, title: str, year: int):
    return {
        "DOI": doi, "title": [title],
        "author": [{"given": "Synthetic", "family": "Author"}],
        "published": {"date-parts": [[year]]},
        "type": "journal-article", "URL": f"https://doi.org/{doi}",
        "update-to": [],
    }


class LiteratureEngineMockEndToEndTests(unittest.TestCase):
    def test_end_to_end_research_dossier_keeps_support_and_challenge_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
            manifest = _manifest()
            pipeline = _MockResearchPipeline(root, manifest)

            records = [
                _mock_openalex_work("10.1234/alpha", "First Study of Synthetic Oxide Adsorption", 2024, "supportive"),
                _mock_openalex_work("10.1234/beta", "Second Study of Synthetic Oxide Adsorption", 2025, "contrary"),
            ]
            crossref = [
                _mock_crossref_work("10.1234/alpha", "First Study of Synthetic Oxide Adsorption", 2024),
                _mock_crossref_work("10.1234/beta", "Second Study of Synthetic Oxide Adsorption", 2025),
            ]

            def fetch_json(url):
                parsed = urlsplit(url)
                if parsed.netloc == "api.openalex.org":
                    return {"meta": {"count": len(records), "next_cursor": None}, "results": records}
                if parsed.netloc == "api.crossref.org" and parsed.path.endswith("/works"):
                    return {"message": {
                        "items": crossref, "total-results": len(crossref),
                        "next-cursor": None, "items-per-page": 20,
                    }}
                if parsed.netloc == "api.crossref.org" and "/works/" in parsed.path:
                    doi = parsed.path.split("/works/", 1)[1]
                    item = next(x for x in crossref if x["DOI"].casefold() == doi.casefold())
                    return {"message": {"title": item["title"], "URL": item["URL"]}}
                raise AssertionError(f"Unexpected mock URL: {url}")

            def fetch_text(url):
                raise AssertionError(f"No full-text retrieval is expected for this metadata-only fixture: {url}")

            def host_skill_executor(*, skill_name, instructions, task, payload):
                if skill_name == "hypothesis-generation":
                    return {"options": [
                        {"option_id": "generated-c", "label": "Host-proposed C", "value": "C",
                         "definition": "A synthetic host-generated proposal."}
                    ]}
                if skill_name == "scientific-brainstorming":
                    return {"options": [
                        {"option_id": "generated-d", "label": "Host-proposed D", "value": "D",
                         "definition": "A second synthetic host-generated proposal."}
                    ]}
                if skill_name == "scientific-critical-thinking":
                    evidence = payload["evidence_matrix"]
                    first, second = evidence[0]["evidence_id"], evidence[1]["evidence_id"]
                    return {
                        "recommended_option_id": "option-a",
                        "reason": "The synthetic evidence set provides limited support for A but retains a counter-result.",
                        "confidence": "LOW",
                        "option_assessments": [{
                            "option_id": "option-a",
                            "supporting_evidence_ids": [first],
                            "challenging_evidence_ids": [second],
                            "reason": "Both directions are retained; the recommendation is tentative.",
                            "uncertainties": ["The fixture is synthetic and abstracts only."],
                        }],
                        "evidence_ids": [first, second],
                        "evidence_assessments": [
                            {"evidence_id": first, "claim": "oxidation changes adsorption energy",
                             "polarity": "SUPPORTS", "reason": "Synthetic supporting observation.",
                             "study_design": "synthetic mock", "method_applicability": "NOT_ASSESSED"},
                            {"evidence_id": second, "claim": "oxidation changes adsorption energy",
                             "polarity": "CHALLENGES", "reason": "Synthetic opposing observation.",
                             "study_design": "synthetic mock", "method_applicability": "NOT_ASSESSED"},
                        ],
                    }
                raise AssertionError(f"Unexpected Skill: {skill_name}")

            engine = ScientificResearchEngine(
                pipeline, max_records=10, max_calls=3,
                fetch_json=fetch_json, fetch_text=fetch_text,
            )
            result = engine.run(
                "project-synthetic-1", profile_path=profile_path,
                skill_executor=host_skill_executor, allow_external_ai=True,
            )
            dossier = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            schema_path = Path(__file__).resolve().parents[1] / (
                "docs/architecture/schemas/scientific-decision-dossier.schema.json"
            )
            import jsonschema
            jsonschema.validate(
                dossier, json.loads(schema_path.read_text(encoding="utf-8"))
            )
            artifact_dir = os.environ.get("SCIENTIFIC_REASONING_ARTIFACT_DIR")
            if artifact_dir:
                target = Path(artifact_dir).expanduser().resolve()
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(result["json_path"], target / "decision_dossier.json")
                shutil.copy2(result["markdown_path"], target / "decision_dossier.md")
                (target / "demo_summary.json").write_text(json.dumps({
                    "synthetic_fixture": True,
                    "project_run_id": "project-synthetic-1",
                    "dossier_id": result["dossier_id"],
                    "dossier_sha256": result["dossier_sha256"],
                    "unique_literature_records": result["evidence_count"],
                    "decision_count": result["decision_count"],
                    "status": result["status"],
                    "approval_state": result["approval_state"],
                }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(result["status"], "PROPOSED")
            self.assertEqual(result["research_status"], "COMPLETE")
            self.assertEqual(dossier["search"]["unique_record_count"], 2)
            self.assertEqual(dossier["approval_state"], "PENDING")
            self.assertEqual(dossier["execution_authority"], {
                "models_approved": False, "scientific_decisions_approved": False,
                "blockers_cleared": False, "calculations_started": False,
            })
            self.assertEqual(dossier["decisions"][0]["status"], "PROPOSED")
            self.assertEqual(dossier["decisions"][0]["approval_status"], "PENDING")
            self.assertEqual(dossier["decisions"][0]["assessment"]["option_id"], "option-a")
            self.assertEqual(dossier["decisions"][0]["assessment"]["confidence"], "LOW")
            self.assertTrue(any(x["polarity"] == "SUPPORTS" for x in dossier["evidence_matrix"]))
            self.assertTrue(any(x["polarity"] == "CHALLENGES" for x in dossier["evidence_matrix"]))
            self.assertTrue(all(x.get("conflict_group_id") for x in dossier["evidence_matrix"]))
            self.assertEqual(len(pipeline.lifecycle.saved), 1)
            self.assertTrue(Path(result["markdown_path"]).is_file())
            self.assertIn("not an approval", Path(result["markdown_path"]).read_text(encoding="utf-8").casefold())


    def test_network_and_rate_limit_failure_is_visible_and_dossier_still_written(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
            pipeline = _MockResearchPipeline(root, _manifest())

            def failing_fetch(url):
                raise RuntimeError("HTTP 429 rate limited in offline fixture")

            engine = ScientificResearchEngine(
                pipeline, max_records=5, max_calls=1,
                fetch_json=failing_fetch,
                fetch_text=lambda url: "",
            )
            result = engine.run("project-offline-failure", profile_path=profile_path)
            dossier = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["research_status"], "PARTIAL")
            self.assertTrue(any(
                "429" in str(log.get("diagnostic", ""))
                for log in dossier["search"]["retrieval_log"]
            ))
            self.assertEqual(dossier["approval_state"], "PENDING")
            self.assertEqual(dossier["decisions"][0]["assessment"]["confidence"], "INSUFFICIENT")

    def test_no_result_search_is_successfully_reported_and_missing_host_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(_profile()), encoding="utf-8")
            pipeline = _MockResearchPipeline(root, _manifest())

            def empty_fetch(url):
                parsed = urlsplit(url)
                if parsed.netloc == "api.openalex.org":
                    return {"meta": {"count": 0, "next_cursor": None}, "results": []}
                if parsed.netloc == "api.crossref.org" and parsed.path.endswith("/works"):
                    return {"message": {
                        "items": [], "total-results": 0,
                        "next-cursor": None, "items-per-page": 20,
                    }}
                raise AssertionError(f"Unexpected mock URL for empty search: {url}")

            engine = ScientificResearchEngine(
                pipeline, max_records=5, max_calls=1,
                fetch_json=empty_fetch, fetch_text=lambda url: "",
            )
            result = engine.run(
                "project-empty-search", profile_path=profile_path,
                allow_external_ai=True, skill_executor=None,
            )
            dossier = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(result["research_status"], "COMPLETE")
            self.assertTrue(all(x["status"] == "NO_RESULTS" for x in dossier["search"]["retrieval_log"]))
            self.assertTrue(any(
                x.get("status") == "UNAVAILABLE" and "skill_executor" in x.get("reason", "")
                for x in dossier["search"]["skill_executor"]
            ))
            self.assertEqual(dossier["decisions"][0]["approval_status"], "PENDING")
            self.assertEqual(dossier["decisions"][0]["assessment"]["confidence"], "INSUFFICIENT")

    def test_explicit_approval_creates_child_revision_and_keeps_model_gates_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pipeline = ProjectPipeline(root / ".pipeline" / "workflow.sqlite", root / "runs")
            try:
                frozen_bytes = b"synthetic Frozen DOCX bytes for approval lifecycle test"
                frozen_sha = hashlib.sha256(frozen_bytes).hexdigest()
                manifest = {
                    "source_document": {
                        "file_name": "synthetic-frozen.docx",
                        "sha256": frozen_sha,
                        "size_bytes": len(frozen_bytes),
                    },
                    "diagnostics": [{
                        "code": "UNRELATED_BLOCKER",
                        "field_path": "model.electronic_state.charge",
                        "blocks_execution": True,
                    }],
                    "unresolved_definitions": [{
                        "code": "METHOD_PARAMETER_MISSING",
                        "field_path": "method.spin_resolution",
                    }],
                    "evidence": [],
                    "confirmations": [],
                }
                parent_id = pipeline.lifecycle.create("synthetic-approval", manifest)
                parent_root = pipeline._run_root(parent_id)
                frozen_path = parent_root / "source" / "synthetic-frozen.docx"
                frozen_path.parent.mkdir(parents=True, exist_ok=True)
                frozen_path.write_bytes(frozen_bytes)
                (parent_root / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                pipeline.lifecycle.transition(parent_id, "DOCX_INGEST", "COMPLETED", outputs={
                    "source_docx": str(frozen_path),
                    "source_sha256": frozen_sha,
                    "source_size_bytes": len(frozen_bytes),
                })
                pipeline.lifecycle.transition(parent_id, "PLAN_COMPILE", "COMPLETED", outputs={
                    "manifest_path": str(parent_root / "manifest.json"),
                    "manifest_sha256": _sha(parent_root / "manifest.json"),
                })
                pipeline.lifecycle.transition(parent_id, "EVIDENCE_REVIEW", "COMPLETED", outputs={
                    "reviewed": True,
                })

                dossier = {
                    "schema_version": "1.0",
                    "project_run_id": parent_id,
                    "created_at": "2026-11-28T00:00:00+00:00",
                    "status": "PROPOSED",
                    "issues": [],
                    "scientific_context": {},
                    "search": {"queries": [], "databases_selected": [], "retrieval_log": [],
                               "raw_record_count": 0, "unique_record_count": 0},
                    "paper_records": [],
                    "evidence_matrix": [{
                        "evidence_id": "ev-approval-1",
                        "title": "Synthetic approval evidence",
                        "excerpt": "Synthetic evidence excerpt",
                        "full_text_sha256": None,
                        "source_urls": ["https://example.org/synthetic-evidence"],
                        "locator": {"kind": "page", "value": "4"},
                        "polarity": "SUPPORTS",
                    }],
                    "decisions": [{
                        "decision_id": "decision-approval-1",
                        "issue_id": "issue-approval-1",
                        "subject": "method.spin_resolution",
                        "question": "Which declared method option should be selected?",
                        "status": "PROPOSED",
                        "approval_status": "PENDING",
                        "options": [{
                            "option_id": "option-a",
                            "label": "Option A",
                            "value": "A",
                            "supporting_evidence_ids": ["ev-approval-1"],
                            "challenging_evidence_ids": [],
                        }],
                        "option_enumeration_status": "DECLARED",
                        "assessment": {
                            "status": "PROPOSED_WITH_SUPPORTING_ANALYSIS",
                            "option_id": "option-a",
                            "reason": "A synthetic option-specific assessment.",
                            "evidence_ids": ["ev-approval-1"],
                            "uncertainties": ["Synthetic test only."],
                        },
                        "requires_user_approval": True,
                        "selected_option_id": None,
                        "affected_planning_objects": ["ResearchPlan", "MethodPlan"],
                    }],
                    "approval_state": "PENDING",
                    "execution_authority": {
                        "models_approved": False, "scientific_decisions_approved": False,
                        "blockers_cleared": False, "calculations_started": False,
                    },
                    "limitations": ["Synthetic test only."],
                    "dossier_id": "dossier-approval-1",
                }
                dossier["dossier_sha256"] = canonical_sha256(dossier)
                dossier_path = parent_root / "scientific_research" / dossier["dossier_id"] / "decision_dossier.json"
                dossier_path.parent.mkdir(parents=True, exist_ok=True)
                dossier_path.write_text(json.dumps(dossier, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
                markdown_path = dossier_path.with_suffix(".md")
                markdown_path.write_text("# Synthetic approval dossier\n", encoding="utf-8")
                pipeline.lifecycle.persist_research_dossier(
                    parent_id, dossier["dossier_id"], dossier["dossier_sha256"],
                    str(dossier_path), str(markdown_path), {"decision_count": 1, "evidence_count": 1},
                )

                captured = {}
                pipeline.plan_scientific = lambda project_run_id, **kwargs: (
                    captured.update({"project_run_id": project_run_id, **kwargs}) or
                    {"project_run_id": project_run_id, "planning_status": "BLOCKED"}
                )
                result = pipeline.approve_scientific_decision(
                    parent_id,
                    decision_id="decision-approval-1",
                    option_id="option-a",
                    approved_by="Synthetic Reviewer",
                    rationale="Explicitly selected for the approval lifecycle test.",
                )
                child_id = result["new_project_run_id"]
                self.assertNotEqual(child_id, parent_id)
                self.assertEqual(result["decision_status"], "APPROVED")
                self.assertEqual(result["decision_record"]["status"], "APPROVED")
                self.assertEqual(result["decision_record"]["decision_record_id"],
                                 pipeline.lifecycle.approved_scientific_decisions(parent_id)[0]["decision_record_id"])
                approved = pipeline.lifecycle.approved_scientific_decisions(parent_id)[0]
                self.assertEqual(approved["option_id"], "option-a")
                self.assertEqual(approved["evidence_ids"], ["ev-approval-1"])
                self.assertEqual(approved["new_project_run_id"], child_id)
                self.assertEqual(captured["decision_overrides"][0]["field_path"], "method.spin_resolution")
                self.assertEqual(captured["decision_overrides"][0]["value"], "A")
                self.assertEqual(captured["decision_overrides"][0]["source_evidence_refs"][0]["evidence_id"],
                                 "ev-approval-1")
                self.assertEqual(pipeline.lifecycle.manifest(parent_id), manifest)
                self.assertEqual(pipeline.lifecycle.manifest(child_id), manifest)
                child_stages = {x["stage"]: x for x in pipeline.lifecycle.stages(child_id)}
                self.assertEqual(child_stages["EVIDENCE_REVIEW"]["status"], "COMPLETED")
                self.assertEqual(child_stages["MODEL_APPROVAL"]["status"], "PENDING")
                self.assertEqual(child_stages["MODEL_ARTIFACT_FREEZE"]["status"], "PENDING")
                self.assertEqual(child_stages["CALCULATION_PLAN"]["status"], "PENDING")
                self.assertEqual(child_stages["WORKFLOW_EXECUTION"]["status"], "PENDING")
                # The unrelated model blocker is not changed by the method decision.
                self.assertTrue(pipeline.lifecycle.manifest(child_id)["diagnostics"][0]["blocks_execution"])
                self.assertEqual(_sha(frozen_path), frozen_sha)
                self.assertEqual(
                    _sha(pipeline._run_root(child_id) / "source" / "synthetic-frozen.docx"),
                    frozen_sha,
                )
            finally:
                pipeline.close()

class UpstreamIntegrationSafetyTests(unittest.TestCase):
    def test_local_paperqa2_evidence_is_not_sent_to_host_without_separate_consent(self):
        matrix = [
            {"evidence_id": "public-1", "databases": ["openalex"]},
            {"evidence_id": "local-1", "databases": ["paperqa2-local-index"]},
        ]
        default_payload = _external_evidence_matrix(matrix, allow_local_evidence=False)
        consented_payload = _external_evidence_matrix(matrix, allow_local_evidence=True)
        self.assertEqual([x["evidence_id"] for x in default_payload], ["public-1"])
        self.assertEqual({x["evidence_id"] for x in consented_payload}, {"public-1", "local-1"})

    def test_quarantined_literature_review_skill_cannot_be_loaded(self):
        with self.assertRaises(SkillUnavailable):
            load_skill_instructions("literature-review")

    def test_selected_skill_assets_are_hash_verified(self):
        selected = list_selected_skills()
        enabled = {x["name"] for x in selected if x["runtime_status"] == "ENABLED"}
        self.assertEqual(enabled, {
            "paper-lookup", "hypothesis-generation",
            "scientific-critical-thinking", "scientific-brainstorming",
        })
        lock_path = Path(__file__).resolve().parents[1] / (
            "pipeline_contracts/scientific_planning/_vendor/kdense/upstream-lock.json"
        )
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        for item in lock["skills"]:
            self.assertTrue(verify_vendored_asset(item["vendored_path"], item["sha256"]))

    def test_decision_dossier_and_approval_records_share_existing_workflow_store(self):
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStore(Path(temp) / "workflow.sqlite")
            try:
                lifecycle = ProjectLifecycle(store)
                run_id = lifecycle.create("synthetic", _manifest())
                lifecycle.persist_research_dossier(
                    run_id, "dossier-1", "c" * 64, "/tmp/dossier.json",
                    "/tmp/dossier.md", {"decision_count": 1},
                )
                self.assertEqual(lifecycle.latest_research_dossier(run_id)["dossier_id"], "dossier-1")
                self.assertEqual(lifecycle.approved_scientific_decisions(run_id), [])
                record = lifecycle.create_scientific_decision_record(
                    project_run_id=run_id, decision_id="decision-1", issue_id="issue-1",
                    field_path="method.spin_resolution", option_id="option-a", selected_value="A",
                    approved_by="Synthetic Reviewer", rationale="Explicit test approval",
                    dossier_id="dossier-1", dossier_sha256="c" * 64,
                    evidence_ids=["ev-1"], decision_record_id="decision-record-fixed",
                )
                self.assertEqual(record["status"], "APPROVED")
                self.assertEqual(lifecycle.approved_scientific_decisions(run_id)[0]["selected_value"], "A")
                self.assertEqual(lifecycle.latest_research_dossier(run_id)["dossier_sha256"], "c" * 64)
            finally:
                store.close()

    def test_paperqa2_needs_explicit_privacy_consent_before_importing_provider(self):
        result = query_local_paperqa2(
            documents=[], question="synthetic", settings={}, consent_external_processing=False
        )
        self.assertEqual(result["status"], "SKIPPED_PRIVACY_CONSENT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
