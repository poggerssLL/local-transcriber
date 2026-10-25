# Graph Report - Local Transcriber  (2026-10-25)

## Corpus Check
- 146 files · ~249,193 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: .toml 5, (none) 4, .cmd 1)

## Summary
- 2956 nodes · 7742 edges · 151 communities (114 shown, 37 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 922 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b3567154`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Model Downloader & Queue Task Execution
- Web UI Application Logic
- Runtime Paths & Configuration
- Remote Gateway Test Harness
- REST API & Event Streaming
- test_api_chatgpt_summary.py
- Remote Gateway HMAC & Security
- ChatGPT API Transport Client
- Development Roadmap
- ChatGPTAuthManager
- api.py
- Output Exporters & Data Formats
- Server-Sent Events & Lease Loss
- Antigravity Summarizer Transport
- live-browser.js
- Frontend API Client
- __init__.py
- connectSSE
- test_chatgpt_auth.py
- initGlobalBar
- resumeSession
- PyAV Media Library Ingestion
- Core Summarizer Data Structures
- summarizer.py
- test_transcription.py
- Transcription Segments & Intervals
- remote_session.py
- .summarize
- __init__.py
- Database
- modern-screenshot.umd.js
- Frontend Async State & Event Tracking
- SummaryConfig
- test_remote_session.py
- .process_claimed_job
- LLM Response JSON Parsing & Markdown
- DOM Manipulation Utilities
- Technical Architecture Overview
- initPageChat
- el
- Known Issues Registry
- Timeline Entry & Topic Representation
- Frontend Node Test Helpers
- applyEditing
- Database Persistence Test Suite
- Project State Snapshot
- Phase 08C Style and Heartbeat Tests Report
- new-work.md
- test_web.py
- SKILL.md
- Responsive Design
- run
- Repository Rules & Mandatory Invariants
- TailscaleCli
- Impeccable Asset Producer
- SQLite Schema Evolution & FTS5
- onAnnotDown
- Hardening Dimensions
- Phase 06 Web Interface Report
- handleManualEditActivity
- Phase 08 Structured Summarizer & Web Integration Report
- createLiveBrowserDomHelpers
- SSE Replay & Event Streaming ADRs
- live.md
- Sign in with ChatGPT OAuth Integration
- onboard.md
- RemoteSessionManager
- Early Faster-Whisper Validation Phases
- The Toolkit
- ProcessVerifier
- Deterministic Output Exporters ADR
- Conservative Execution Profiles ADR
- Loopback REST Endpoints ADR
- Single Consumer Process Lock ADR
- Monotonic SSE Generation Tokens ADR
- createLiveBrowserSessionState
- Transient SQLite Retry Invariants
- Environment Prerequisites Guide
- Troubleshooting Matrix Guide
- pytest
- actOnAgentTarget
- .start
- animate.md
- Handle `generate`
- CDN-Free Offline OpenAPI Spec
- Generate Report
- Package Metadata Configuration
- Planejamento das Próximas Implementações de Acesso Remoto
- FasterWhisperEngine
- New visual work
- optimize.md
- ChatGPTTokenStore
- Scan mode (approach C: auto-extract, then confirm descriptive language)
- critique.md
- generate.md
- Plano de Integração e Arquitetura de Acesso Remoto (Etapas 1 a 3)
- clarify.md
- Nielsen's 10 Heuristics
- Generate Combined Critique Report
- document.md
- polish.md
- quieter.md
- scheduleAcceptCleanup
- Init flow
- .exports
- LLMTransport
- Common Cognitive Load Violations
- iOS platform
- Operate mode depth (and Read notes)
- Shape
- adapt.native.md
- Android platform
- Persona-Based Design Testing
- Generate Report
- Cognitive Load Assessment
- Impeccable Finish Reviewer
- Impeccable Manual Edit Applier
- live-browser-ignores.js
- Fase 8J — Etapa 1: Sessão Privada Temporária e Orquestração Tailscale Serve (2026-10-25)
- Diagnostic Scan
- $impeccable hooks
- Visualize: Direction Comps & Asset Production
- Any
- Impeccable Documenter
- Region map
- Integra??o MCP local do Graphify ? 2026-10-25
- Configura??o local de ferramentas do agente ? 2026-10-25
- OllamaUnavailableError
- test_runtime_probe_configures_dll_search_before_importing_ctranslate2
- Installation Guide
- Heuristics Scoring Guide
- Operate
- Read
- auth_mgr
- Media Library Architecture

## God Nodes (most connected - your core abstractions)
1. `create_app()` - 107 edges
2. `Repository` - 101 edges
3. `RuntimePaths` - 75 edges
4. `create_remote_gateway_app()` - 60 edges
5. `TranscriptionJob` - 49 edges
6. `Technical Architecture Overview` - 46 edges
7. `ChatGPTAuthManager` - 41 edges
8. `Transcript` - 39 edges
9. `TranscriptionWorker` - 36 edges
10. `ProfileResolver` - 35 edges

## Surprising Connections (you probably didn't know these)
- `Etapa 3 — Protocolo de Upload Particionado e Tolerância a Quedas (Worker Subsequente)` --references--> `MediaLibrary`  [INFERRED]
  docs/REMOTE_ACCESS_INTEGRATION_PLAN.md → src/local_transcriber/media.py
- `Etapa 2: Entrada Restrita e Governança de Acesso (Proposta Técnica)` --references--> `Repository`  [INFERRED]
  docs/REMOTE_ACCESS_NEXT_IMPLEMENTATIONS.md → src/local_transcriber/repository.py
- `Etapa 3: Protocolo de Upload Resumable Real (Proposta Técnica)` --references--> `Repository`  [INFERRED]
  docs/REMOTE_ACCESS_NEXT_IMPLEMENTATIONS.md → src/local_transcriber/repository.py
- `4.2 Matriz de Falhas e Comportamento Fail-Closed` --references--> `TailscaleNotFoundError`  [INFERRED]
  docs/REMOTE_ACCESS_INTEGRATION_PLAN.md → src/local_transcriber/remote_session.py
- `4.2 Matriz de Falhas e Comportamento Fail-Closed` --references--> `TailscaleNotRunningError`  [INFERRED]
  docs/REMOTE_ACCESS_INTEGRATION_PLAN.md → src/local_transcriber/remote_session.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **AI Synthesis Multi-Provider Architecture** — docs_phase_08_structured_summarizer_and_web_integration_map_reduce_temporal_summarizer, docs_phase_08i_sign_in_with_chatgpt_summarizer_2026_10_24_chatgpt_responses_api_streaming, src_local_transcriber_web_index_summary_section [INFERRED 0.85]
- **Resilient Concurrency and Lifecycle Gates** — docs_phase_07b_local_cuda_acceleration_active_job_deletion_protection, docs_phase_08b_maintenance_validation_2026_10_05_heartbeat_intermittent_timing, docs_phase_08c_style_and_heartbeat_tests_2026_10_05_fakeclock_deterministic_heartbeat_testing, docs_phase_08j_remote_gateway_2026_10_24_upload_streaming_dos_defense [INFERRED 0.85]
- **End-to-End SSE Event Delivery and Monotonic Sequence Architecture** — docs_foundation_sse_pipeline, docs_phase_05_local_api_and_sse_sse_streaming_protocol, docs_phase_05b_offline_docs_and_incremental_sse_batched_incremental_sse, docs_phase_06b_async_concurrency_reliability_job_event_tracker [INFERRED 0.95]
- **Local-First Zero-Trust Architecture** — docs_project_contract_local_first_privacy_invariants, docs_phase_06_web_interface_strict_csp_policy, docs_phase_08j_remote_gateway_2026_10_24_tailscale_identity_allowlist, docs_phase_08i_sign_in_with_chatgpt_summarizer_2026_10_24_user_opt_in_consent_mechanism [INFERRED 0.95]
- **Progressive Media Ingestion, Inspection and Deduplication Pipeline** — docs_foundation_media_library, docs_phase_02_media_library_media_pipeline, docs_decisions_adr_005_pyav_inspection, docs_decisions_adr_006_progressive_import, docs_decisions_adr_007_exact_sha256_duplication [INFERRED 0.95]
- **SQLite Queue Lease and Concurrency Control Subsystem** — docs_foundation_lease_heartbeat_mechanism, docs_phase_04_persistent_queue_worker_claim_loop, docs_phase_04b_lease_reliability_lease_ownership_lost_handling, docs_phase_05c_sqlite_contention_reliability_idle_polling_precheck [INFERRED 0.95]

## Communities (151 total, 37 thin omitted)

### Community 0 - "Model Downloader & Queue Task Execution"
Cohesion: 0.06
Nodes (41): _is_transient_sqlite_error(), _WorkerController, _LeaseHeartbeat, TranscriptionWorker, ProfileResolver, _context(), FakeClock, FixedProbe (+33 more)

### Community 1 - "Web UI Application Logic"
Cohesion: 0.08
Nodes (71): addMetric(), announce(), api, appendOption(), buildPendingJob(), cancelJob(), connectActiveJobs(), createExport() (+63 more)

### Community 2 - "Runtime Paths & Configuration"
Cohesion: 0.08
Nodes (21): _seed_subject_and_recording(), _seed_transcript(), test_download_summary_invalid_format_returns_422(), test_download_summary_json(), test_download_summary_markdown_default(), test_download_summary_not_found_returns_404(), test_get_summary_existing_sidecar_returns_200(), test_get_summary_not_found_returns_404() (+13 more)

### Community 3 - "Remote Gateway Test Harness"
Cohesion: 0.06
Nodes (61): _bounded_int(), _Claim, GatewayStateStore, RemoteGatewayConfigError, RemoteGatewayError, _string_set(), Clock, clock() (+53 more)

### Community 4 - "REST API & Event Streaming"
Cohesion: 0.08
Nodes (44): job_events(), stream_job_events(), app(), client(), _create_subject(), FixedProbe, _install_model(), _seed_transcript() (+36 more)

### Community 5 - "test_api_chatgpt_summary.py"
Cohesion: 0.12
Nodes (16): ChatGPTTokens, app(), client(), _seed_transcript(), test_api_summary_with_chatgpt_not_connected_raises_401(), test_api_summary_with_chatgpt_success(), test_auth_callback_error_and_invalid_state(), test_auth_callback_html_escaping() (+8 more)

### Community 6 - "Remote Gateway HMAC & Security"
Cohesion: 0.06
Nodes (39): _security_headers(), secure_file_permissions(), MediaImportSettings, ApiModel, create_remote_gateway_app(), _create_job(), enforce_gateway_boundary(), _existing_recording() (+31 more)

### Community 7 - "ChatGPT API Transport Client"
Cohesion: 0.10
Nodes (10): chatgpt_status(), ChatGPTTransport, test_http_status_errors(), test_model_catalog_check_accepts_luna(), test_model_catalog_check_rejects_when_luna_absent(), test_responses_api_payload_and_sse_streaming_completed(), mock_urlopen(), test_sse_prevents_duplication_when_output_item_done_follows_deltas() (+2 more)

### Community 8 - "Development Roadmap"
Cohesion: 0.14
Nodes (18): Phase 01 Foundation Report, Non-Commercial Personal Use License, Phase 08H GitHub Installation Report, PowerShell Installer and Packaging Smoke Test, GitHub Actions Windows Runner CI Validation, Phase 08H Post-Publication Windows CI Validation Report, Sign in with ChatGPT OAuth 2.0 PKCE Flow, Phase 08I Sign in with ChatGPT Summarizer Report (+10 more)

### Community 9 - "ChatGPTAuthManager"
Cohesion: 0.15
Nodes (10): ChatGPTAuthManager, ChatGPTAuthError, ChatGPTTokenRevokedError, test_exchange_code_first_registration_missing_client_id_rejected(), test_exchange_code_missing_id_token_rejected(), test_exchange_code_reauthorization_swap_client_id_rejected(), test_refresh_token_revocation_clears_store(), test_refresh_token_rotation() (+2 more)

### Community 10 - "api.py"
Cohesion: 0.03
Nodes (82): ApiModel, CapabilitiesResponse, ChartVisualizationResponse, ChatGPTLoginResponse, ChatGPTLogoutResponse, ChatGPTStatusResponse, create_app(), api_version() (+74 more)

### Community 11 - "Output Exporters & Data Formats"
Cohesion: 0.12
Nodes (21): _clean_text(), ExportFormat, _format_timestamp(), _markdown_escape(), _milliseconds(), _ordered_segments(), _render_json(), _render_markdown() (+13 more)

### Community 12 - "Server-Sent Events & Lease Loss"
Cohesion: 0.08
Nodes (19): _event_name(), _sse_event(), LeaseOwnershipLost, JobEvent, JobPhase, JobStatus, _non_negative_finite(), Recording (+11 more)

### Community 13 - "Antigravity Summarizer Transport"
Cohesion: 0.13
Nodes (13): AntigravityTransport, AntigravityInferenceError, app(), client(), test_api_antigravity_status(), test_api_summary_with_antigravity_success(), test_find_antigravity_cli_via_localappdata(), test_generate_failure_raises_inference_error() (+5 more)

### Community 14 - "live-browser.js"
Cohesion: 0.03
Nodes (139): applyLiveBarPreference(), applyOriginalAttrsToSvelteAnchor(), applyPlaceholderSizingStyles(), averageRgb01(), bindEditBadgeProxy(), bufferToBase64(), buildCollapsible(), buildColorModels() (+131 more)

### Community 15 - "Frontend API Client"
Cohesion: 0.11
Nodes (3): ApiError, LocalApi, readError()

### Community 16 - "__init__.py"
Cohesion: 0.06
Nodes (21): RuntimePaths, InvalidMediaError, MediaInfo, sanitize_filename(), ModelDownloadConfirmationError, ModelError, ModelManager, ModelNotInstalledError (+13 more)

### Community 17 - "connectSSE"
Cohesion: 0.07
Nodes (80): abandonForeignSession(), abandonSupersededGo(), abortSvelteComponentInjection(), buildInsertPlaceholderSnapshotFromDom(), buildPickedAnchorSnapshot(), cancelEditing(), cancelEditingToPicking(), captureAndEmit() (+72 more)

### Community 18 - "test_chatgpt_auth.py"
Cohesion: 0.17
Nodes (15): b64url_encode(), generate_pkce_pair(), validate_id_token(), verify_rs256_signature(), _get_prime(), _is_prime(), _make_jwt(), _make_test_rsa_key() (+7 more)

### Community 19 - "initGlobalBar"
Cohesion: 0.06
Nodes (70): agentHasWorkInFlight(), agentStatusText(), barPaletteForTheme(), beginNewLiveConfiguration(), brandMarkSvg(), buildDesignHeader(), cancelInsertConfigure(), clearAnnotations() (+62 more)

### Community 20 - "resumeSession"
Cohesion: 0.06
Nodes (61): applyParamDefaults(), applyParamValue(), applySavedParamValues(), applySavedSessionMeta(), buildParamsPanel(), checkpointPayload(), clampVariantIndex(), clearHandled() (+53 more)

### Community 21 - "PyAV Media Library Ingestion"
Cohesion: 0.08
Nodes (14): DuplicateMediaError, MediaImportError, MediaInspector, MediaLibrary, MediaTooLargeError, library(), test_delete_rejects_recording_with_active_job_and_preserves_media(), test_duplicate_and_size_limit_are_rejected() (+6 more)

### Community 22 - "Core Summarizer Data Structures"
Cohesion: 0.20
Nodes (7): ExecutiveSummary, FlashcardEntry, GlossaryEntry, TimelineEntry, TranscriptSummary, _make_dummy_summary_dict(), test_models_instantiation()

### Community 23 - "summarizer.py"
Cohesion: 0.12
Nodes (11): _clean_markdown_escapes(), format_timestamp_clock(), parse_timestamp_seconds(), ParsedSegment, TranscriptChunk, flush_current(), test_chunk_by_time(), test_parse_transcript_bracketed_and_srt() (+3 more)

### Community 24 - "test_transcription.py"
Cohesion: 0.22
Nodes (16): capabilities(), FakeProbe, _service_context(), test_atomic_completion_rolls_back_partial_transcript(), test_auto_falls_back_but_explicit_cuda_fails_actionably(), test_failure_records_sanitized_error_without_partial_transcript(), test_faster_whisper_adapter_consumes_lazy_segments_and_converts_output(), transcribe() (+8 more)

### Community 25 - "Transcription Segments & Intervals"
Cohesion: 0.19
Nodes (15): Segment, _validate_interval(), Word, EngineOutput, ProgressEvent, FakeEngine, transcribe(), transcribe() (+7 more)

### Community 26 - "remote_session.py"
Cohesion: 0.11
Nodes (10): main(), main(), make_speech(), NoRedirect, normalize(), summary_indicators(), word_error_rate(), main() (+2 more)

### Community 27 - ".summarize"
Cohesion: 0.12
Nodes (5): ChartVisualizationEntry, test_summarizer_with_antigravity_transport(), test_summarize_end_to_end_mocked(), test_summarize_progress_callback_emits_all_phases(), test_summarize_progress_callback_exception_tolerance()

### Community 28 - "__init__.py"
Cohesion: 0.08
Nodes (14): find_antigravity_cli(), antigravity_status(), b64url_decode(), AntigravityError, AntigravityUnavailableError, ChatGPTError, ChatGPTInferenceError, ChatGPTLimitError (+6 more)

### Community 29 - "Database"
Cohesion: 0.16
Nodes (14): _context(), Database, _create_v1_database(), test_empty_database_runs_all_migrations(), test_existing_v2_database_migrates_to_v4(), test_existing_v3_database_migrates_to_v4(), test_fts_searches_title_subject_and_transcript_safely(), test_v4_migrates_existing_v1_and_is_idempotent() (+6 more)

### Community 30 - "modern-screenshot.umd.js"
Cohesion: 0.09
Nodes (55): ae(), be(), bt(), Ce(), s(), Ct(), de(), dt() (+47 more)

### Community 31 - "Frontend Async State & Event Tracking"
Cohesion: 0.14
Nodes (5): Step 4: Accept and close, The contract (read once), JobEventTracker, LatestRequest, sequenceNumber()

### Community 32 - "SummaryConfig"
Cohesion: 0.22
Nodes (6): OllamaTransport, SummaryConfig, _sample_transcript_file(), test_ollama_transport_provenance(), test_summarizer_failure_does_not_persist_partial_sidecar_or_fallback(), test_summarizer_with_chatgpt_transport()

### Community 33 - "test_remote_session.py"
Cohesion: 0.16
Nodes (11): RemoteGatewayConfig, enabled_gateway_config(), fake_process_terminator(), temp_runtime(), test_cli_remote_session_status_json(), test_cli_remote_session_status_no_session(), test_cli_remote_session_stop_idempotent(), test_session_manager_fails_if_core_unreachable() (+3 more)

### Community 35 - "LLM Response JSON Parsing & Markdown"
Cohesion: 0.19
Nodes (5): _extract_json(), TranscriptSummarizer, test_map_prompt_specifies_item_keys_and_source_timestamps(), test_reduce_removes_exact_duplicates_but_keeps_distinct_facts(), test_ollama_resilience_errors()

### Community 36 - "DOM Manipulation Utilities"
Cohesion: 0.14
Nodes (4): element(), phaseLabels, statusLabels, textPair()

### Community 37 - "Technical Architecture Overview"
Cohesion: 0.11
Nodes (11): FasterWhisperEngine Adapter, Lease and Heartbeat Mechanism, Local HTTP API Architecture, SSE Event Stream Pipeline, TranscriptionEngine Protocol, TranscriptionQueue Persistent Worker, TranscriptionService Coordinator, Vanilla Web Frontend Architecture (+3 more)

### Community 38 - "initPageChat"
Cohesion: 0.07
Nodes (55): applyGlobalBarLabelState(), armPageChatForTyping(), attachSteerFocusDebug(), attachSteerFocusGuard(), buildSteerProcessingDots(), buildSteerQueueHint(), clearSteerAwaitTimer(), clearSteerFocusRecoverTimer() (+47 more)

### Community 39 - "el"
Cohesion: 0.08
Nodes (51): actionLabel(), applyConfigureBarChrome(), bindConfigureCountPillTooltip(), bindConfigureInlineControlHover(), bindConfigureModifierPillHover(), buildConfigureActionControl(), buildConfigureCountControl(), buildConfigureRow() (+43 more)

### Community 40 - "Known Issues Registry"
Cohesion: 0.12
Nodes (15): Remote Gateway Architecture, Byte-Exact Duplication Limit, Cooperative Cancellation Delay, Filesystem-SQLite Disruption Window, Gateway Fail-Closed Idempotency Limit, Known Issues Registry, PyAV Codec Limits, Remote Gateway Synthetic-Only Validation Limit (+7 more)

### Community 41 - "Timeline Entry & Topic Representation"
Cohesion: 0.31
Nodes (6): factual_summary(), test_indicators_never_claim_semantic_approval(), test_lexical_coverage_does_not_approve_empty_timeline(), test_missing_critical_number_is_rejected(), test_nonfinite_and_inconsistent_timestamps_are_rejected(), test_repeated_paragraphs_rejected_despite_fact_coverage()

### Community 43 - "applyEditing"
Cohesion: 0.06
Nodes (41): addManualContextText(), applyEditing(), buildLocatorForLeaf(), canRestoreManualEditElement(), collectEditableTextRows(), visit(), collectManualContextPieces(), walk() (+33 more)

### Community 44 - "Database Persistence Test Suite"
Cohesion: 0.35
Nodes (8): database(), make_recording(), test_database_creation_and_idempotent_migration(), test_essential_operations_and_restart_preserve_unicode(), test_filter_recordings_uses_exact_parameter(), test_foreign_keys_are_enforced(), test_invalid_states_and_values(), test_queries_are_parameterized_against_injection()

### Community 45 - "Project State Snapshot"
Cohesion: 0.15
Nodes (26): Core Domain Models, Summarizer Map-Reduce Temporal Architecture, Technical Architecture Overview, Phase 02 Media Library Report, Phase 03 Whisper and CLI Report, Phase 03B Real Validation Report, Phase 03C Second Real Validation Report, Phase 04 Persistent Queue Report (+18 more)

### Community 46 - "Phase 08C Style and Heartbeat Tests Report"
Cohesion: 0.22
Nodes (10): Code Freeze Integrity Gate, Heartbeat Intermittent Timing Sensitivity, Phase 08B Maintenance & Baseline Validation Report, FakeClock Deterministic Heartbeat Testing, Phase 08C Style and Heartbeat Tests Report, Phase 08F Synthetic Native Validation Report, Synthetic Native Harness Validation, Factual Ground Truth Map-Reduce Prompting (+2 more)

### Community 47 - "new-work.md"
Cohesion: 0.07
Nodes (25): Recommended Actions, Craft (deprecated alias), Monorepo notes, Opting out of the boot check, Step 1: Run the pass, Step 2: Act by severity, Step 3: Deprecated fields are binding, Step 4: Do not overclaim on truth drift (+17 more)

### Community 48 - "test_web.py"
Cohesion: 0.09
Nodes (15): RuntimeCapabilities, RuntimeProbe, FixedProbe, FixedProbe, SemanticParser, test_frontend_uses_safe_dom_modular_javascript_and_persistent_sse(), test_openapi_keeps_web_shell_outside_versioned_api(), test_runtime_reports_stopped_worker_to_interface() (+7 more)

### Community 49 - "SKILL.md"
Cohesion: 0.07
Nodes (22): Before you finish, Scope is sovereign, The amplification, The skeleton test, Why it reads flat, Craft floor, Refuse, Verify (+14 more)

### Community 50 - "Responsive Design"
Cohesion: 0.08
Nodes (25): Assess Adaptation Challenge, Breakpoints: Content-Driven, Content Adaptation, Desktop Adaptation (Mobile → Desktop), Detect Input Method, Not Just Screen Size, Email Adaptation (Web → Email), Implement Adaptations, Layout Adaptation Patterns (+17 more)

### Community 51 - "run"
Cohesion: 0.07
Nodes (16): _add_transcription_options(), build_parser(), _job_payload(), main(), run(), _transcription_settings(), _absolute_path(), AppConfig (+8 more)

### Community 52 - "Repository Rules & Mandatory Invariants"
Cohesion: 0.25
Nodes (7): Data and Git Hygiene, Mandatory Architecture Invariants, Mandatory Repository Rules, Documentation Reading Order, Scope and Phases Enforcement, Validation and Lint Standards, Architecture Decisions Registry

### Community 53 - "TailscaleCli"
Cohesion: 0.14
Nodes (12): TailscaleCli, TailscaleError, TailscaleNotFoundError, TailscaleNotRunningError, TailscaleStatus, fake_tailscale_runner(), test_tailscale_disable_serve_never_uses_reset(), test_tailscale_enable_serve_failure() (+4 more)

### Community 54 - "Impeccable Asset Producer"
Cohesion: 0.12
Nodes (12): Act on the receipt, Assemble and review, Plan and asset review, Plan, capture, serve, Core Rule, Decision Comps, Impeccable Asset Producer, Input Contract (+4 more)

### Community 55 - "SQLite Schema Evolution & FTS5"
Cohesion: 0.33
Nodes (4): SQLite Schema v1, SQLite Schema v2 and FTS5, SQLite Schema v3, SQLite Schema v4 Queue and Events

### Community 56 - "onAnnotDown"
Cohesion: 0.12
Nodes (25): applyPlaceholderDimensions(), beginEditPin(), buildAnnotationsForCapture(), buildPinElement(), buildPlaceholderResizeHandles(), cancelEditingPin(), cursorForPlaceholderEdge(), finalizeEditingPin() (+17 more)

### Community 57 - "Hardening Dimensions"
Cohesion: 0.08
Nodes (22): Assess Current State, Code Simplification, Content Simplification, Document Removed Complexity, Information Architecture, Interaction Simplification, Layout Simplification, Plan Simplification (+14 more)

### Community 58 - "Phase 06 Web Interface Report"
Cohesion: 0.33
Nodes (6): Phase 06 Web Interface Report, Strict Content Security Policy, Vanilla Web UI Architecture, Web UI HTML Application Shell, #reader-tabs View Switcher, #transcription-dialog Modal Dialog

### Community 59 - "handleManualEditActivity"
Cohesion: 0.19
Nodes (24): clearStoredManualApplyState(), fetchPendingCount(), handleManualEditActivity(), hidePendingApplyDock(), manualApplyLoadingText(), manualApplyStateKey(), manualEditEventForCurrentPage(), numberOrNull() (+16 more)

### Community 60 - "Phase 08 Structured Summarizer & Web Integration Report"
Cohesion: 0.40
Nodes (5): Temporal Map-Reduce Pedagogical Summarizer, Phase 08 Structured Summarizer & Web Integration Report, Atomic Sidecar Markdown and JSON Storage, ChatGPT Responses API SSE Streaming, #summary-section AI Study & Synthesis Panel

### Community 61 - "createLiveBrowserDomHelpers"
Cohesion: 0.13
Nodes (19): createLiveBrowserDomHelpers(), activeElementDeep(), cloneWithoutChrome(), copyTextViaSelection(), cssId(), liveUiRoot(), makeFrozenAnchor(), own() (+11 more)

### Community 62 - "SSE Replay & Event Streaming ADRs"
Cohesion: 0.50
Nodes (3): Server-Sent Events Job Streaming, Batched Incremental SSE Polling, JobEventTracker Monotonic Sequence Tracker

### Community 63 - "live.md"
Cohesion: 0.09
Nodes (21): Apply at system scale, Audit before choosing, Choose a strategy, Contrast and perception, Live-mode signature params, Verify, Visitor mode, Cleanup (+13 more)

### Community 64 - "Sign in with ChatGPT OAuth Integration"
Cohesion: 0.17
Nodes (3): Sign in with ChatGPT OAuth Integration, RuntimePaths Layout, SQLite Persistence and Migrations

### Community 65 - "onboard.md"
Cohesion: 0.09
Nodes (22): Assess Onboarding Needs, Context Over Ceremony, Contextual Help, Design Onboarding Experiences, Documentation & Help, Empty State Design, Feature Discovery & Adoption, Guided Tours & Walkthroughs (+14 more)

### Community 67 - "Early Faster-Whisper Validation Phases"
Cohesion: 0.67
Nodes (3): Faster Whisper Integration, Phase 03B CPU Smoke Test, Phase 03C Real CPU Execution

### Community 68 - "The Toolkit"
Cohesion: 0.10
Nodes (20): Animate complex properties, Assess What "Extraordinary" Means Here, For data-heavy interfaces, For functional UI, For performance-critical UI, For visual/marketing surfaces, Implement with Discipline, Interact with the device (+12 more)

### Community 69 - "ProcessVerifier"
Cohesion: 0.15
Nodes (8): 1. Módulo `remote_session.py`, ProcessVerifier, RemoteSessionOwnershipError, fake_process_inspector(), test_process_verifier_fails_on_creation_time_mismatch(), test_process_verifier_fails_on_marker_mismatch(), test_process_verifier_ownership_success(), test_terminate_verified_pid_fails_closed()

### Community 75 - "createLiveBrowserSessionState"
Cohesion: 0.19
Nodes (17): createLiveBrowserSessionState(), clearHandled(), clearScrollY(), clearSession(), isHandled(), loadSession(), markHandled(), nextCheckpointRevision() (+9 more)

### Community 91 - "pytest"
Cohesion: 0.17
Nodes (8): app(), client(), test_secure_file_permissions(), invoke(), test_cli_import_list_transcribe_guard_and_delete(), test_cli_models_list_and_check_do_not_download(), test_cli_serve_rejects_public_bind_and_multiple_workers(), test_cli_subject_and_recording_lists_use_existing_services()

### Community 92 - "actOnAgentTarget"
Cohesion: 0.29
Nodes (17): actOnAgentTarget(), agentTargetBusyReason(), agentTargetOverlayGone(), agentTargetTaken(), claimAgentTarget(), claimAndActOnAgentTarget(), declineAgentTargetBusy(), declineAgentTargetUnresolvable() (+9 more)

### Community 93 - ".start"
Cohesion: 0.17
Nodes (7): RemoteGatewayDisabledError, check_core_api(), RemoteSessionConflictError, RemoteSessionError, RemoteSessionState, test_session_manager_fails_if_gateway_disabled(), test_session_manager_start_conflict_when_already_active()

### Community 94 - "animate.md"
Cohesion: 0.12
Nodes (14): Accessibility and control, Choose material by meaning, Find the job, Implement to the runtime, Set the motion thesis, Timing and easing, Verify, Visitor mode (+6 more)

### Community 95 - "Handle `generate`"
Cohesion: 0.12
Nodes (16): 1. Read the screenshot (if present), 2. Wrap the element, 3. Load the action's reference, 4. Plan three variants: identity first, then mode, then axes, 5. Apply the freeform prompt (if present), 6. Deliver variants, 7. Parameters (composition-sized, 0-4 per variant), 8. Signal done (+8 more)

### Community 97 - "Generate Report"
Cohesion: 0.13
Nodes (14): 1. Accessibility (A11y), 2. Performance, 3. Theming, 4. Responsive Design, 5. Implementation Integrity (CRITICAL), Audit Health Score, Detailed Findings by Severity, Diagnostic Scan (+6 more)

### Community 100 - "Planejamento das Próximas Implementações de Acesso Remoto"
Cohesion: 0.14
Nodes (13): 1. Visão Geral, Topologia e Objetivo Proposto, 2. Estado Factual Atual e Ressalvas da Etapa 1, 3. Pendências Técnicas da Etapa 1 (Etapa 0 - Complemento Pré-Gate), 4. Ordem e Especificação das Próximas Etapas, 5. Matriz de Dependências, Riscos e Critérios de Aceite, 6. Procedimentos de Recuperação e Reversão, 7. Diretrizes de Governança e Regras de Transição, Etapa 0: Complemento e Fechamento do Gate da Etapa 1 (+5 more)

### Community 101 - "FasterWhisperEngine"
Cohesion: 0.16
Nodes (3): FasterWhisperEngine, TranscriptionEngine, _windows_cuda_dll_directories()

### Community 102 - "New visual work"
Cohesion: 0.14
Nodes (14): 1. Decide what is already true, 2. Ask what will change the work, 3. Choose the right amount of invention, 4. Commit the world, 5. Record the decision, 6. Build with full commitment, 7. Inspect and finish, Both paths (+6 more)

### Community 103 - "optimize.md"
Cohesion: 0.14
Nodes (13): Animation Performance, Assess Performance Issues, Core Web Vitals Optimization, Cumulative Layout Shift (CLS < 0.1), Interaction to Next Paint (INP < 200ms), Largest Contentful Paint (LCP < 2.5s), Loading Performance, Network Optimization (+5 more)

### Community 105 - "Scan mode (approach C: auto-extract, then confirm descriptive language)"
Cohesion: 0.15
Nodes (13): Component translation rules, Narrative mapping, Scan mode (approach C: auto-extract, then confirm descriptive language), Schema, Step 1: Find the design assets, Step 2: Auto-extract what can be auto-extracted, Step 2b: Stage the frontmatter, Step 3: Ask the user for qualitative language (+5 more)

### Community 106 - "critique.md"
Cohesion: 0.17
Nodes (11): Action Summary, Ask the User, Assessment A: Design Review, Assessment B: Detector + Browser Evidence, Assessment Orchestration, Deliver the Report, Hard Invariants, Persist the Snapshot (+3 more)

### Community 107 - "generate.md"
Cohesion: 0.17
Nodes (10): Step 1: Parse the request, Step 2: Reuse the page, then start, Step 3: Generate, append-arrays, append-string, Config drift, Consent prompt (use this phrasing), CSP detection (first-time only) (+2 more)

### Community 108 - "Plano de Integração e Arquitetura de Acesso Remoto (Etapas 1 a 3)"
Cohesion: 0.17
Nodes (11): 1. Visão Geral e Motivação, 2. Invariantes Arquiteturais e Fronteiras de Segurança, 3. Detalhamento das Etapas e Roadmap, 4.1 Pré-requisitos do Operador, 4.2 Matriz de Falhas e Comportamento Fail-Closed, 4. Guia Operacional e Modos de Falha, 5. Portão de Qualidade e Critérios de Transição, Etapa 1 — Ciclo de Vida da Sessão Temporária e Orquestração (Escopo Atual) (+3 more)

### Community 109 - "clarify.md"
Cohesion: 0.18
Nodes (10): Actions and navigation, Audit the language, Errors and permissions, Forms, Help and instructional text, Loading, empty, and success states, Rewrite by function, Set the message hierarchy (+2 more)

### Community 110 - "Nielsen's 10 Heuristics"
Cohesion: 0.18
Nodes (11): 10. Help and Documentation, 1. Visibility of System Status, 2. Match Between System and Real World, 3. User Control and Freedom, 4. Consistency and Standards, 5. Error Prevention, 6. Recognition Rather Than Recall, 7. Flexibility and Efficiency of Use (+3 more)

### Community 111 - "Generate Combined Critique Report"
Cohesion: 0.18
Nodes (11): Design Health Score, Design Specificity Verdict, Generate Combined Critique Report, Minor Observations, Overall Impression, Persona Red Flags, Priority Issues, Questions to Consider (+3 more)

### Community 112 - "document.md"
Cohesion: 0.18
Nodes (10): Pitfalls, Seed mode, Step 1: Route through new-work's workshop, Step 2: Write seed DESIGN.md, Step 3: Confirm, Style guidelines, The frontmatter: token schema, The markdown body: eight sections (canonical order) (+2 more)

### Community 113 - "polish.md"
Cohesion: 0.18
Nodes (10): 1. Establish the system, 2. Gather the evidence, 3. Triage, 4. Polish the whole path, 5. Verify and finish, Color, imagery, and icons, Content and code, Flow and hierarchy (+2 more)

### Community 114 - "quieter.md"
Cohesion: 0.18
Nodes (10): Assess Current State, Color Refinement, Composition Refinement, Motion Reduction, Plan Refinement, Refine the Design, Simplification, Verify Quality (+2 more)

### Community 115 - "scheduleAcceptCleanup"
Cohesion: 0.31
Nodes (11): acceptedDomAlreadyClean(), clearHandledWrapperReloadStamp(), deferredRecoverySuperseded(), ensureAcceptedDomClean(), findAcceptedRuntimeWrappers(), handledWrapperReloadKey(), reloadAfterMissingAcceptedDom(), restoreAcceptedDomFromSnapshot() (+3 more)

### Community 116 - "Init flow"
Cohesion: 0.20
Nodes (10): Completion gate, Init flow, Step 1: Load current state, Step 2: Explore the project, Step 3: Interview for product truth, Step 4: Write PRODUCT.md, Step 5: Record workflow defaults, Step 6: Wrap up or resume (+2 more)

### Community 119 - "Common Cognitive Load Violations"
Cohesion: 0.22
Nodes (9): 1. The Wall of Options, 2. The Memory Bridge, 3. The Hidden Navigation, 4. The Jargon Barrier, 5. The Visual Noise Floor, 6. The Inconsistent Pattern, 7. The Multi-Task Demand, 8. The Context Switch (+1 more)

### Community 120 - "iOS platform"
Cohesion: 0.22
Nodes (9): Color & materials, Components & controls, iOS platform, Layout & structure, Motion, The iOS slop test, Touch targets, Typography (+1 more)

### Community 121 - "Operate mode depth (and Read notes)"
Cohesion: 0.22
Nodes (9): Color, Components, Layout, Motion, Operate mode depth (and Read notes), Product constraints, Product permissions, The product slop test (+1 more)

### Community 122 - "Shape"
Cohesion: 0.22
Nodes (8): Cadence, Confirm and stop, Phase 1: Discovery interview, Phase 2: Resolve the design direction, Phase 3: Write the brief, Round 1: purpose, people, and outcome, Round 2: material, behavior, and boundaries, Shape

### Community 123 - "adapt.native.md"
Cohesion: 0.25
Nodes (7): Adaptation Strategies, Assess Adaptation Challenge, Implement & Verify, Orientation & foldables, Phone → Tablet (iPad / large screens), Platform → platform (iOS ↔ Android), Web → native (porting a website or web app)

### Community 124 - "Android platform"
Cohesion: 0.25
Nodes (8): Android platform, Color & theming, Components & motion, Layout & structure, The Android slop test, Touch targets, Typography, Verifying the build

### Community 125 - "Persona-Based Design Testing"
Cohesion: 0.25
Nodes (8): 1. Impatient Power User: "Alex", 2. Confused First-Timer: "Jordan", 3. Accessibility-Dependent User: "Sam", 4. Deliberate Stress Tester: "Riley", 5. Distracted Mobile User: "Casey", Persona-Based Design Testing, Project-Specific Personas, Selecting Personas

### Community 126 - "Generate Report"
Cohesion: 0.29
Nodes (7): Audit Health Score, Detailed Findings by Severity, Executive Summary, Generate Report, Patterns & Systemic Issues, Platform Conformance Verdict, Positive Findings

### Community 127 - "Cognitive Load Assessment"
Cohesion: 0.29
Nodes (7): Cognitive Load Assessment, Cognitive Load Checklist, Extraneous Load: Bad Design, Germane Load: Learning Effort, Intrinsic Load: The Task Itself, The Working Memory Rule, Three Types of Cognitive Load

### Community 128 - "Impeccable Finish Reviewer"
Cohesion: 0.29
Nodes (6): Checks, in order, Disposition, Impeccable Finish Reviewer, Input Contract, Output Contract, Verdict Pass

### Community 129 - "Impeccable Manual Edit Applier"
Cohesion: 0.29
Nodes (6): Checks, Entry Atomicity, Impeccable Manual Edit Applier, Input Contract, Output Contract, Workflow

### Community 131 - "live-browser-ignores.js"
Cohesion: 0.52
Nodes (6): globToRegex(), matchesScope(), normalizeIgnoreRule(), normalizeIgnoreValue(), pageCandidates(), resolveDetectIgnores()

### Community 132 - "Fase 8J — Etapa 1: Sessão Privada Temporária e Orquestração Tailscale Serve (2026-10-25)"
Cohesion: 0.29
Nodes (6): 2. Comandos CLI e Launcher, Arquitetura Implementada, Contexto e Objetivo, Fase 8J — Etapa 1: Sessão Privada Temporária e Orquestração Tailscale Serve (2026-10-25), Limitações e Próximos Passos, Validação e Resultados

### Community 133 - "Diagnostic Scan"
Cohesion: 0.33
Nodes (6): 1. Accessibility (VoiceOver / TalkBack), 2. Performance, 3. Appearance & Theming, 4. Platform Conformance (CRITICAL), 5. Adaptivity, Diagnostic Scan

### Community 134 - "$impeccable hooks"
Cohesion: 0.33
Nodes (6): Constraints, Failure modes, Flow, $impeccable hooks, Routing, Triage findings

### Community 135 - "Visualize: Direction Comps & Asset Production"
Cohesion: 0.33
Nodes (5): After approval: the comp becomes a spec, Generate three compositional options, One approval point, Plates and provenance, Visualize: Direction Comps & Asset Production

### Community 137 - "Impeccable Documenter"
Cohesion: 0.40
Nodes (4): Impeccable Documenter, Input Contract, Output Contract, Workflow

### Community 138 - "Region map"
Cohesion: 0.40
Nodes (4): Containment, Painted material, Region map, What varies independently

### Community 139 - "Integra??o MCP local do Graphify ? 2026-10-25"
Cohesion: 0.40
Nodes (4): Instala??o e valida??o real, Integra??o MCP local do Graphify ? 2026-10-25, Limites, Resultado

### Community 140 - "Configura??o local de ferramentas do agente ? 2026-10-25"
Cohesion: 0.40
Nodes (4): Configura??o, Configura??o local de ferramentas do agente ? 2026-10-25, Escopo e resultado, Evid?ncias e limites

### Community 143 - "Installation Guide"
Cohesion: 0.50
Nodes (3): Windows Installation CI Workflow, Installation Guide, PowerShell Automated Installer

### Community 144 - "Heuristics Scoring Guide"
Cohesion: 0.50
Nodes (4): Heuristics Scoring Guide, Issue Severity (P0–P3), Reference Material, Score Summary

### Community 145 - "Operate"
Cohesion: 0.50
Nodes (3): Comps, Directions, Operate

### Community 146 - "Read"
Cohesion: 0.50
Nodes (3): Comps, Directions, Read

## Knowledge Gaps
- **49 isolated node(s):** `local-transcriber`, `Core Domain Models`, `Summarizer Map-Reduce Temporal Architecture`, `PowerShell Automated Installer`, `Cooperative Cancellation Delay` (+44 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 918 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **37 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CsrfSigner` connect `Impeccable Asset Producer` to `Remote Gateway HMAC & Security`?**
  _High betweenness centrality (0.437) - this node is a cross-community bridge._
- **Are the 24 inferred relationships involving `create_app()` (e.g. with `domain_error()` and `lifespan()`) actually correct?**
  _`create_app()` has 24 INFERRED edges - model-reasoned connections that need verification._
- **What connects `local-transcriber`, `Core Domain Models`, `Summarizer Map-Reduce Temporal Architecture` to the rest of the system?**
  _49 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Model Downloader & Queue Task Execution` be split into smaller, more focused modules?**
  _Cohesion score 0.06167527251864601 - nodes in this community are weakly interconnected._
- **Are the 42 inferred relationships involving `Repository` (e.g. with `Etapa 2: Entrada Restrita e Governança de Acesso (Proposta Técnica)` and `Etapa 3: Protocolo de Upload Resumable Real (Proposta Técnica)`) actually correct?**
  _`Repository` has 42 INFERRED edges - model-reasoned connections that need verification._
- **Should `Web UI Application Logic` be split into smaller, more focused modules?**
  _Cohesion score 0.07724505327245053 - nodes in this community are weakly interconnected._
- **Are the 50 inferred relationships involving `RuntimePaths` (e.g. with `TranscriptExporter` and `MediaLibrary`) actually correct?**
  _`RuntimePaths` has 50 INFERRED edges - model-reasoned connections that need verification._