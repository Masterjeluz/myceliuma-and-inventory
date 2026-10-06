# MYCELIUM AI — CURRENT STATE

HEAD:
6697e9ade01f5787a9d5ad27141bd40043c6bcea

HEAD MESSAGE:
(no commit message provided)

ORIGIN:
d8bfb640b7b42aa2906c2922112eb9ade5674653

LOCAL COMMITS AHEAD:
10

STASH:
stash@{0}: On main: RECOVERY_CHECKPOINT_BEFORE_AGENT_LOSS

## RECENT COMMITS

6697e9a (HEAD -> main) (no commit message provided) edb0a98 feat: BambuPrinterAdapter implementatie toegevoegd f19e7ec checkpoint: printer3d.py restored, tests passing 776eecc (no commit message provided) afa0217 docs: Documenteer camera pipeline activatie e557587 fix: Implementeer placeholder voor snapshot in WindowsWebcamAdapter 1d562eb fix: Camera adapters mogelijk maken voor snapshots d687145 test: Voeg tests toe voor Bambu adapter met mock MQTT e6200ae feat: Importeer httpx en paho-mqtt voor printercommunicatie cc7834a feat: Voeg BambuPrinterAdapter toe d8bfb64 (origin/main) feat(research): bridge dossiers to mission plans 3bb36ab (backup-before-v1) feat(missions): close dispatched steps on task completion 062da4d feat(missions): auto-dispatch research steps c427f05 feat(core): integrate workspaces forge remote input and node capabilities 0f9919a feat(nodes): external worker, scout, linux installer and tick loop 68ea281 refactor(agent): format agent UI without behavior changes eec38dd feat(inventory): expand search type selector 24633be BIG #45 - finish living ecosystem connections b049831 BIG #44 - build the living solarpunk world 5a023f7 BIG #43 - build the living game layer ab51bca BIG #42 - ecosystem hardening + first V2 workflows 4f5da99 BIG #41 - build Mycelium V2 foundation cfa1673 BIG #40 - build presence ecosystem 75e5caa BIG #39 - build hardware reality layer e1c31cc BIG #38 - build living automation 786c331 BIG #37 - build conversation intelligence 6893008 BIG #36 - build mobile Mycelium 6422f25 BIG #35 - build 3D workshop ecosystem d0475ad BIG #34 - build camera ecosystem 98a9dab BIG #33 - build the living world

## CURRENT FILE TREE

.gitignore AGENTS.md AUTOPILOT_ROADMAP.md.txt Mycelium/agent/ARCHITECTURE_CONTRACT.md Mycelium/agent/CANONICAL_PROJECTS.md Mycelium/agent/README.md Mycelium/agent/SAFETY.md Mycelium/agent/WORLD_MODEL.md Mycelium/agent/agent.json Mycelium/agent/agent.py Mycelium/agent/agent_ui.py Mycelium/agent/agent_ui.py.backup Mycelium/agent/checkpoint.py Mycelium/agent/discovery.json Mycelium/agent/inventory_bridge.py Mycelium/agent/inventory_writer.py Mycelium/agent/mapping_store.py Mycelium/agent/permission_log.jsonl Mycelium/agent/permissions.py Mycelium/agent/project_index.json Mycelium/agent/project_index.py Mycelium/agent/tests/test_checkpoint.py Mycelium/agent/tests/test_discovery.py Mycelium/agent/tests/test_inventory_bridge.py Mycelium/agent/tests/test_inventory_writer.py Mycelium/agent/tests/test_mapping_store.py Mycelium/agent/tests/test_permissions.py Mycelium/agent/tests/test_project_index.py README.md docs/NEXT-AI-CONTEXT.md inventory/.gitattributes inventory/.gitignore inventory/INVENTory/.gitattributes inventory/INVENTory/README.md inventory/README.md inventory/app/__init__.py inventory/app/database.py inventory/app/ids.py inventory/app/main.py inventory/app/schemas.py inventory/pyproject.toml inventory/tests/__init__.py inventory/tests/test_database.py inventory/tests/test_milestone_1b.py inventory/tests/test_milestone_3_1.py inventory/tests/test_milestone_3_2.py inventory/tests/test_milestone_3_3.py inventory/tests/test_milestone_3_4.py inventory/tests/test_milestone_3_5.py inventory/tests/test_milestone_3_6.py inventory/tests/test_milestone_3_7.py inventory/tests/test_milestone_3_8.py inventory/tests/test_milestone_4.py inventory/tests/test_objects.py inventory/tests/test_search_types_ui.py mycelium-ai-main/.env.example mycelium-ai-main/.gitignore mycelium-ai-main/Dockerfile mycelium-ai-main/MYCELIUM_INVENTORY_MASTER_CONTEXT.md.txt mycelium-ai-main/README.md mycelium-ai-main/code_worker/README.md mycelium-ai-main/code_worker/__init__.py mycelium-ai-main/code_worker/main.py mycelium-ai-main/coordinator/__init__.py mycelium-ai-main/coordinator/app/__init__.py mycelium-ai-main/coordinator/app/adapter_contracts.py mycelium-ai-main/coordinator/app/adapters.py mycelium-ai-main/coordinator/app/advisor_proposals.py mycelium-ai-main/coordinator/app/agenda.py mycelium-ai-main/coordinator/app/agent_loop.py mycelium-ai-main/coordinator/app/agent_results.py mycelium-ai-main/coordinator/app/approval.py mycelium-ai-main/coordinator/app/automation.py mycelium-ai-main/coordinator/app/bootstrap.py mycelium-ai-main/coordinator/app/cad.py mycelium-ai-main/coordinator/app/camera_ecosystem.py mycelium-ai-main/coordinator/app/cameras.py mycelium-ai-main/coordinator/app/campaigns.py mycelium-ai-main/coordinator/app/capability_matching.py mycelium-ai-main/coordinator/app/command.py mycelium-ai-main/coordinator/app/computer_actions.py mycelium-ai-main/coordinator/app/connections.py mycelium-ai-main/coordinator/app/context_engine.py mycelium-ai-main/coordinator/app/context_packet.py mycelium-ai-main/coordinator/app/controlled_writes.py mycelium-ai-main/coordinator/app/conversation_bridge.py mycelium-ai-main/coordinator/app/conversation_intel.py mycelium-ai-main/coordinator/app/conversations.py mycelium-ai-main/coordinator/app/craft.py mycelium-ai-main/coordinator/app/database.py mycelium-ai-main/coordinator/app/decisions.py mycelium-ai-main/coordinator/app/desktop_runtime.py mycelium-ai-main/coordinator/app/diststate.py mycelium-ai-main/coordinator/app/domains.py mycelium-ai-main/coordinator/app/drones.py mycelium-ai-main/coordinator/app/ecosystem.py mycelium-ai-main/coordinator/app/embeddings.py mycelium-ai-main/coordinator/app/energy.py mycelium-ai-main/coordinator/app/events.py mycelium-ai-main/coordinator/app/executor_registry.py mycelium-ai-main/coordinator/app/fab_flow.py mycelium-ai-main/coordinator/app/fabrication.py mycelium-ai-main/coordinator/app/failover.py mycelium-ai-main/coordinator/app/familiars.py mycelium-ai-main/coordinator/app/finance.py mycelium-ai-main/coordinator/app/forge.py mycelium-ai-main/coordinator/app/game.py mycelium-ai-main/coordinator/app/garmin.py mycelium-ai-main/coordinator/app/git_commit.py mycelium-ai-main/coordinator/app/git_context.py mycelium-ai-main/coordinator/app/guide.py mycelium-ai-main/coordinator/app/hardware_links.py mycelium-ai-main/coordinator/app/health.py mycelium-ai-main/coordinator/app/interface.py mycelium-ai-main/coordinator/app/inventory_read.py mycelium-ai-main/coordinator/app/inventory_writes.py mycelium-ai-main/coordinator/app/jobs.py mycelium-ai-main/coordinator/app/knowledge.py mycelium-ai-main/coordinator/app/linux_node.py mycelium-ai-main/coordinator/app/live.py mycelium-ai-main/coordinator/app/living_state.py mycelium-ai-main/coordinator/app/main.py mycelium-ai-main/coordinator/app/memory.py mycelium-ai-main/coordinator/app/mesh3d.py mycelium-ai-main/coordinator/app/meshops.py mycelium-ai-main/coordinator/app/mission_executor.py mycelium-ai-main/coordinator/app/mission_loop.py mycelium-ai-main/coordinator/app/mission_templates.py mycelium-ai-main/coordinator/app/missions.py mycelium-ai-main/coordinator/app/mobile.py mycelium-ai-main/coordinator/app/model_router.py mycelium-ai-main/coordinator/app/n8n.py mycelium-ai-main/coordinator/app/nodemesh.py mycelium-ai-main/coordinator/app/nodes.py mycelium-ai-main/coordinator/app/notify_center.py mycelium-ai-main/coordinator/app/nutrition.py mycelium-ai-main/coordinator/app/observations.py mycelium-ai-main/coordinator/app/ollama_advisor.py mycelium-ai-main/coordinator/app/payloads.py mycelium-ai-main/coordinator/app/pipeline3d.py mycelium-ai-main/coordinator/app/plans.py mycelium-ai-main/coordinator/app/presence.py mycelium-ai-main/coordinator/app/printer3d.py mycelium-ai-main/coordinator/app/project_context.py mycelium-ai-main/coordinator/app/project_package.py mycelium-ai-main/coordinator/app/promotion.py mycelium-ai-main/coordinator/app/proposal_tasks.py mycelium-ai-main/coordinator/app/providers.py mycelium-ai-main/coordinator/app/quests.py mycelium-ai-main/coordinator/app/recovery.py mycelium-ai-main/coordinator/app/remote_input.py mycelium-ai-main/coordinator/app/reports.py mycelium-ai-main/coordinator/app/research.py mycelium-ai-main/coordinator/app/research_engine.py mycelium-ai-main/coordinator/app/research_extract.py mycelium-ai-main/coordinator/app/research_plan.py mycelium-ai-main/coordinator/app/research_transport.py mycelium-ai-main/coordinator/app/retention.py mycelium-ai-main/coordinator/app/retrieval.py mycelium-ai-main/coordinator/app/robots.py mycelium-ai-main/coordinator/app/routes_conversations.py mycelium-ai-main/coordinator/app/routing.py mycelium-ai-main/coordinator/app/schemas.py mycelium-ai-main/coordinator/app/semantic_store.py mycelium-ai-main/coordinator/app/sim_nodes.py mycelium-ai-main/coordinator/app/skills.py mycelium-ai-main/coordinator/app/slicer3d.py mycelium-ai-main/coordinator/app/symbiosis.py mycelium-ai-main/coordinator/app/sync.py mycelium-ai-main/coordinator/app/task_queue_bridge.py mycelium-ai-main/coordinator/app/twin.py mycelium-ai-main/coordinator/app/ui.py mycelium-ai-main/coordinator/app/verification.py mycelium-ai-main/coordinator/app/vision_flow.py mycelium-ai-main/coordinator/app/vision_ingest.py mycelium-ai-main/coordinator/app/vision_provider.py mycelium-ai-main/coordinator/app/voice.py mycelium-ai-main/coordinator/app/voice_approval.py mycelium-ai-main/coordinator/app/watcher.py mycelium-ai-main/coordinator/app/workshop3d.py mycelium-ai-main/coordinator/app/workspaces.py mycelium-ai-main/coordinator/app/world.py mycelium-ai-main/coordinator/app/worldgraph.py mycelium-ai-main/desktop_agent/__init__.py mycelium-ai-main/desktop_agent/agent.py mycelium-ai-main/desktop_agent/identity.py mycelium-ai-main/desktop_agent/main.py mycelium-ai-main/docker-compose.yml mycelium-ai-main/docs/3d-architecture.md mycelium-ai-main/docs/3d-workflow.md mycelium-ai-main/docs/3d-workshop.md mycelium-ai-main/docs/ARCHITECTURE_STATUS.md mycelium-ai-main/docs/BIG31-final-report.md mycelium-ai-main/docs/BIG32-final-report.md mycelium-ai-main/docs/BIG33-final-report.md mycelium-ai-main/docs/BIG34-final-report.md mycelium-ai-main/docs/BIG35-final-report.md mycelium-ai-main/docs/BIG36-final-report.md mycelium-ai-main/docs/BIG37-final-report.md mycelium-ai-main/docs/BIG38-final-report.md mycelium-ai-main/docs/BIG38-progress.md mycelium-ai-main/docs/BIG39-final-report.md mycelium-ai-main/docs/BIG40-final-report.md mycelium-ai-main/docs/BIG41-final-report.md mycelium-ai-main/docs/BIG42-final-report.md mycelium-ai-main/docs/BIG43-final-report.md mycelium-ai-main/docs/BIG44-final-report.md mycelium-ai-main/docs/BIG45-final-report.md mycelium-ai-main/docs/LINUX_NODE_INSTALL.md mycelium-ai-main/docs/NEXT-AI-CONTEXT.md mycelium-ai-main/docs/ROADMAP-V2.md mycelium-ai-main/docs/ROADMAP.md mycelium-ai-main/docs/advanced-workshop.md mycelium-ai-main/docs/agenda-import.md mycelium-ai-main/docs/architecture.md mycelium-ai-main/docs/automation-security.md mycelium-ai-main/docs/autonomous-mission-loop.md mycelium-ai-main/docs/autonomous-missions.md mycelium-ai-main/docs/cad.md mycelium-ai-main/docs/camera-architecture.md mycelium-ai-main/docs/camera-ecosystem.md mycelium-ai-main/docs/camera-workflow.md mycelium-ai-main/docs/chat-agent-architecture.md mycelium-ai-main/docs/community-guide.md mycelium-ai-main/docs/context-packets.md mycelium-ai-main/docs/controlled-writes-and-verification.md mycelium-ai-main/docs/conversation-bridge.md mycelium-ai-main/docs/conversation-intelligence.md mycelium-ai-main/docs/coordinator-failover.md mycelium-ai-main/docs/desktop-hands.md mycelium-ai-main/docs/digital-twin.md mycelium-ai-main/docs/distributed-architecture.md mycelium-ai-main/docs/distributed-state.md mycelium-ai-main/docs/drones.md mycelium-ai-main/docs/energy-ecosystem.md mycelium-ai-main/docs/fabrication.md mycelium-ai-main/docs/finance-ecosystem.md mycelium-ai-main/docs/first-node-blueprint.md mycelium-ai-main/docs/garmin.md mycelium-ai-main/docs/hardware-reality-layer.md mycelium-ai-main/docs/hardware-verification.md mycelium-ai-main/docs/health.md mycelium-ai-main/docs/human-interface-architecture.md mycelium-ai-main/docs/knowledge-lifecycle.md mycelium-ai-main/docs/linux-node-setup.md mycelium-ai-main/docs/living-automation.md mycelium-ai-main/docs/living-ecosystem.md mycelium-ai-main/docs/living-game-layer.md mycelium-ai-main/docs/living-principles.md mycelium-ai-main/docs/living-solarpunk-world.md mycelium-ai-main/docs/living-workshop-ui.md mycelium-ai-main/docs/living-workshop.md mycelium-ai-main/docs/memory.md mycelium-ai-main/docs/mission-templates.md mycelium-ai-main/docs/mobile-mycelium.md mycelium-ai-main/docs/mobile-node-flow.md mycelium-ai-main/docs/morning-reports.md mycelium-ai-main/docs/mycelium-live.md mycelium-ai-main/docs/mycelium-ui-personality.md mycelium-ai-main/docs/mycelium-v1.md mycelium-ai-main/docs/n8n-integration.md mycelium-ai-main/docs/nutrition.md mycelium-ai-main/docs/origin_story.md mycelium-ai-main/docs/overnight-research.md mycelium-ai-main/docs/presence-ecosystem.md mycelium-ai-main/docs/quest-trails.md mycelium-ai-main/docs/r29-shots/dossier-1440.png mycelium-ai-main/docs/r29-shots/dossier-390.png mycelium-ai-main/docs/r29-shots/morning-1440.png mycelium-ai-main/docs/r29-shots/research-1440.png mycelium-ai-main/docs/r29-shots/research-390.png mycelium-ai-main/docs/r30-shots/3d-1440.png mycelium-ai-main/docs/r30-shots/activity-1440.png mycelium-ai-main/docs/r30-shots/cameras-1440.png mycelium-ai-main/docs/r30-shots/conversation-detail-1440.png mycelium-ai-main/docs/r30-shots/conversations-1440.png mycelium-ai-main/docs/r30-shots/mobile-1440.png mycelium-ai-main/docs/r30-shots/mobile-390.png mycelium-ai-main/docs/r30-shots/nodes-1440.png mycelium-ai-main/docs/r30-shots/research-1440.png mycelium-ai-main/docs/r30-shots/world-1440.png mycelium-ai-main/docs/r30-shots/world-390.png mycelium-ai-main/docs/r31-shots/camera-detail-1440.png mycelium-ai-main/docs/r31-shots/conversations-1440.png mycelium-ai-main/docs/r31-shots/mobile-1440.png mycelium-ai-main/docs/r31-shots/mobile-390.png mycelium-ai-main/docs/r31-shots/morning-1440.png mycelium-ai-main/docs/r31-shots/nodes-1440.png mycelium-ai-main/docs/r31-shots/search-1440.png mycelium-ai-main/docs/r31-shots/world-1440.png mycelium-ai-main/docs/r31-shots/world-390.png mycelium-ai-main/docs/r31-shots/writes-1440.png mycelium-ai-main/docs/r32-shots/conversations-1440.png mycelium-ai-main/docs/r32-shots/knowledge-1440.png mycelium-ai-main/docs/r32-shots/mobile-1440.png mycelium-ai-main/docs/r32-shots/mobile-390.png mycelium-ai-main/docs/r32-shots/morning-1440.png mycelium-ai-main/docs/r32-shots/nodes-routing-1440.png mycelium-ai-main/docs/r32-shots/world-filters-1440.png mycelium-ai-main/docs/r33-shots/activity-1440.png mycelium-ai-main/docs/r33-shots/cameras-1440.png mycelium-ai-main/docs/r33-shots/conversations-1440.png mycelium-ai-main/docs/r33-shots/craft-1440.png mycelium-ai-main/docs/r33-shots/guide-1440.png mycelium-ai-main/docs/r33-shots/home-1440.png mycelium-ai-main/docs/r33-shots/knowledge-1440.png mycelium-ai-main/docs/r33-shots/missions-1440.png mycelium-ai-main/docs/r33-shots/mobile-1440.png mycelium-ai-main/docs/r33-shots/mobile-390.png mycelium-ai-main/docs/r33-shots/nodes-1440.png mycelium-ai-main/docs/r33-shots/research-1440.png mycelium-ai-main/docs/r33-shots/symbiosis-1440.png mycelium-ai-main/docs/r33-shots/world-1440.png mycelium-ai-main/docs/r34-shots/camera-detail-1440.png mycelium-ai-main/docs/r34-shots/cameras-1440.png mycelium-ai-main/docs/r34-shots/guide-1440.png mycelium-ai-main/docs/r34-shots/mobile-390.png mycelium-ai-main/docs/r35-shots/3d-1440.png mycelium-ai-main/docs/r35-shots/3d-390.png mycelium-ai-main/docs/r35-shots/craft-1440.png mycelium-ai-main/docs/r35-shots/guide-1440.png mycelium-ai-main/docs/r35-shots/mobile-390.png mycelium-ai-main/docs/r35-shots/symbiosis-1440.png mycelium-ai-main/docs/r35-shots/world-1440.png mycelium-ai-main/docs/r36-shots/mobile-1440.png mycelium-ai-main/docs/r36-shots/mobile-390.png mycelium-ai-main/docs/r36-shots/mobile-approval.png mycelium-ai-main/docs/r36-shots/mobile-camera.png mycelium-ai-main/docs/r36-shots/mobile-craft.png mycelium-ai-main/docs/r36-shots/mobile-guide.png mycelium-ai-main/docs/r36-shots/mobile-nodes.png mycelium-ai-main/docs/r36-shots/mobile-symbiosis.png mycelium-ai-main/docs/r37-shots/conversation-390.png mycelium-ai-main/docs/r37-shots/conversation-detail.png mycelium-ai-main/docs/r37-shots/conversations-1440.png mycelium-ai-main/docs/r37-shots/guide-conversation.png mycelium-ai-main/docs/r37-shots/mobile-intel.png mycelium-ai-main/docs/r37-shots/world-conversation-overlay.png mycelium-ai-main/docs/r38-shots/automation-detail-completed.png mycelium-ai-main/docs/r38-shots/automation-detail-waiting.png mycelium-ai-main/docs/r38-shots/automation-overview.png mycelium-ai-main/docs/r38-shots/guide-automation.png mycelium-ai-main/docs/r38-shots/mobile-automation.png mycelium-ai-main/docs/r38-shots/morning-automation.png mycelium-ai-main/docs/r39-shots/guide-1440.png mycelium-ai-main/docs/r39-shots/hardware-1440.png mycelium-ai-main/docs/r39-shots/mobile-1440.png mycelium-ai-main/docs/r39-shots/nodes-1440.png mycelium-ai-main/docs/r39-shots/routing-1440.png mycelium-ai-main/docs/r39-shots/world-1440.png mycelium-ai-main/docs/r40-shots/desktop-presence-1440.png mycelium-ai-main/docs/r40-shots/guide-1440.png mycelium-ai-main/docs/r40-shots/mobile-presence-1440.png mycelium-ai-main/docs/r40-shots/morning-1440.png mycelium-ai-main/docs/r40-shots/node-aware-waiting-1440.png mycelium-ai-main/docs/r40-shots/notifications-1440.png mycelium-ai-main/docs/r40-shots/world-activity-1440.png mycelium-ai-main/docs/r41-shots/craft-1440.png mycelium-ai-main/docs/r41-shots/guide-1440.png mycelium-ai-main/docs/r41-shots/mobile-1440.png mycelium-ai-main/docs/r41-shots/nodes-1440.png mycelium-ai-main/docs/r41-shots/presence-1440.png mycelium-ai-main/docs/r41-shots/symbiosis-1440.png mycelium-ai-main/docs/r41-shots/world-1440.png mycelium-ai-main/docs/r42-shots/guide-1440.png mycelium-ai-main/docs/r42-shots/mobile-1440.png mycelium-ai-main/docs/r42-shots/morning-1440.png mycelium-ai-main/docs/r42-shots/nodes-reality-1440.png mycelium-ai-main/docs/r42-shots/quest-1440.png mycelium-ai-main/docs/r42-shots/symbiosis-1440.png mycelium-ai-main/docs/r42-shots/world-1440.png mycelium-ai-main/docs/r43-shots/campaign-1440.png mycelium-ai-main/docs/r43-shots/craft-1440.png mycelium-ai-main/docs/r43-shots/game-1440.png mycelium-ai-main/docs/r43-shots/guide-1440.png mycelium-ai-main/docs/r43-shots/mobile-1440.png mycelium-ai-main/docs/r43-shots/morning-1440.png mycelium-ai-main/docs/r43-shots/quest-1440.png mycelium-ai-main/docs/r43-shots/symbiosis-1440.png mycelium-ai-main/docs/r43-shots/world-1440.png mycelium-ai-main/docs/r44-shots/campaign-1440.png mycelium-ai-main/docs/r44-shots/craft-1440.png mycelium-ai-main/docs/r44-shots/guide-1440.png mycelium-ai-main/docs/r44-shots/hardware-1440.png mycelium-ai-main/docs/r44-shots/morning-1440.png mycelium-ai-main/docs/r44-shots/nodes-1440.png mycelium-ai-main/docs/r44-shots/presence-1440.png mycelium-ai-main/docs/r44-shots/symbiosis-1440.png mycelium-ai-main/docs/r44-shots/world-1440.png mycelium-ai-main/docs/r44-shots/world-mobile-390.png mycelium-ai-main/docs/r45-shots/campaigns-1440.png mycelium-ai-main/docs/r45-shots/connections-detail-1440.png mycelium-ai-main/docs/r45-shots/guide-1440.png mycelium-ai-main/docs/r45-shots/mobile-390.png mycelium-ai-main/docs/r45-shots/morning-1440.png mycelium-ai-main/docs/r45-shots/world-focused-1440.png mycelium-ai-main/docs/r45-shots/world-mobile-390.png mycelium-ai-main/docs/r45-shots/world-network-1440.png mycelium-ai-main/docs/recovery.md mycelium-ai-main/docs/research-engine.md mycelium-ai-main/docs/research-ingestion.md mycelium-ai-main/docs/research-network.md mycelium-ai-main/docs/research-routing.md mycelium-ai-main/docs/research-runbook.md mycelium-ai-main/docs/research-security.md mycelium-ai-main/docs/robots.md mycelium-ai-main/docs/semantic-world-model.md mycelium-ai-main/docs/skills.md mycelium-ai-main/docs/stabilization.md mycelium-ai-main/docs/startup.md mycelium-ai-main/docs/user-profile.md mycelium-ai-main/docs/v1-shots/agenda-1440.png mycelium-ai-main/docs/v1-shots/chat-1440.png mycelium-ai-main/docs/v1-shots/mission-1440.png mycelium-ai-main/docs/v1-shots/missions-1440.png mycelium-ai-main/docs/v1-shots/missions-390.png mycelium-ai-main/docs/v1-shots/morning-1440.png mycelium-ai-main/docs/v1-shots/morning-390.png mycelium-ai-main/docs/v1-shots/world-1440.png mycelium-ai-main/docs/v1-shots/world-390.png mycelium-ai-main/docs/v2-ecosystem.md mycelium-ai-main/docs/vision-architecture.md mycelium-ai-main/docs/watcher.md mycelium-ai-main/n8n/README.md mycelium-ai-main/n8n/workflow-a-schedule-morning-report.json mycelium-ai-main/n8n/workflow-b-outbox-notify.json mycelium-ai-main/node_client/__init__.py mycelium-ai-main/node_client/bootstrap.py mycelium-ai-main/node_client/install.py mycelium-ai-main/node_client/main.py mycelium-ai-main/node_client/mycelium-node.service mycelium-ai-main/node_client/remote_mouse.py mycelium-ai-main/pyproject.toml mycelium-ai-main/scout/README.md mycelium-ai-main/scout/__init__.py mycelium-ai-main/scout/main.py mycelium-ai-main/scripts/b33_seed_shots.py mycelium-ai-main/scripts/b34_smoke.py mycelium-ai-main/scripts/b35_smoke.py mycelium-ai-main/scripts/b36_smoke.py mycelium-ai-main/scripts/b37_smoke.py mycelium-ai-main/scripts/b38_screenshots2.py mycelium-ai-main/scripts/b38_shots.py mycelium-ai-main/scripts/b38_smoke.py mycelium-ai-main/scripts/b39_screenshots.py mycelium-ai-main/scripts/b39_shots.py mycelium-ai-main/scripts/b39_smoke.py mycelium-ai-main/scripts/b40_screenshots.py mycelium-ai-main/scripts/b40_shots.py mycelium-ai-main/scripts/b40_smoke.py mycelium-ai-main/scripts/b41_screenshots.py mycelium-ai-main/scripts/b41_shots.py mycelium-ai-main/scripts/b41_smoke.py mycelium-ai-main/scripts/b42_screenshots.py mycelium-ai-main/scripts/b42_shots.py mycelium-ai-main/scripts/b42_smoke.py mycelium-ai-main/scripts/b43_screenshots.py mycelium-ai-main/scripts/b43_shots.py mycelium-ai-main/scripts/b43_smoke.py mycelium-ai-main/scripts/b44_screenshots.py mycelium-ai-main/scripts/b44_shots.py mycelium-ai-main/scripts/b44_smoke.py mycelium-ai-main/scripts/b45_screenshots.py mycelium-ai-main/scripts/b45_shots.py mycelium-ai-main/scripts/b45_smoke.py mycelium-ai-main/scripts/install_linux_node.sh mycelium-ai-main/scripts/mycelium-notify.py mycelium-ai-main/scripts/register-startup.ps1 mycelium-ai-main/scripts/start-mycelium.ps1 mycelium-ai-main/scripts/tick_mycelium.py mycelium-ai-main/scripts/unregister-startup.ps1 mycelium-ai-main/tests/test_adapters.py mycelium-ai-main/tests/test_advanced_3d.py mycelium-ai-main/tests/test_advise.py mycelium-ai-main/tests/test_advisor_proposals.py mycelium-ai-main/tests/test_agenda.py mycelium-ai-main/tests/test_agent_loop.py mycelium-ai-main/tests/test_api.py mycelium-ai-main/tests/test_approval.py mycelium-ai-main/tests/test_approvals_api.py mycelium-ai-main/tests/test_b10_security.py mycelium-ai-main/tests/test_bambu_adapter.py mycelium-ai-main/tests/test_big30_living_ecosystem.py mycelium-ai-main/tests/test_big31_activation.py mycelium-ai-main/tests/test_big32_knowledge.py mycelium-ai-main/tests/test_big33_living_world.py mycelium-ai-main/tests/test_big34_camera_ecosystem.py mycelium-ai-main/tests/test_big35_workshop.py mycelium-ai-main/tests/test_big36_mobile.py mycelium-ai-main/tests/test_big37_conversation_intel.py mycelium-ai-main/tests/test_big38_automation.py mycelium-ai-main/tests/test_big39_telemetry.py mycelium-ai-main/tests/test_big40_presence.py mycelium-ai-main/tests/test_big41_v2.py mycelium-ai-main/tests/test_big42_ecosystem.py mycelium-ai-main/tests/test_big43_game.py mycelium-ai-main/tests/test_big44_world.py mycelium-ai-main/tests/test_big45_connections.py mycelium-ai-main/tests/test_cameras.py mycelium-ai-main/tests/test_capability_matching.py mycelium-ai-main/tests/test_chat_api.py mycelium-ai-main/tests/test_cockpit.py mycelium-ai-main/tests/test_command.py mycelium-ai-main/tests/test_concurrency.py mycelium-ai-main/tests/test_controlled_writes.py mycelium-ai-main/tests/test_conversations.py mycelium-ai-main/tests/test_decisions.py mycelium-ai-main/tests/test_desktop_agent.py mycelium-ai-main/tests/test_desktop_api.py mycelium-ai-main/tests/test_desktop_contracts.py mycelium-ai-main/tests/test_desktop_hands.py mycelium-ai-main/tests/test_desktop_runtime.py mycelium-ai-main/tests/test_digital_world.py mycelium-ai-main/tests/test_dist_queue.py mycelium-ai-main/tests/test_dist_security.py mycelium-ai-main/tests/test_dist_sim.py mycelium-ai-main/tests/test_diststate.py mycelium-ai-main/tests/test_events.py mycelium-ai-main/tests/test_executor_registry.py mycelium-ai-main/tests/test_fab_api.py mycelium-ai-main/tests/test_fab_security.py mycelium-ai-main/tests/test_failover.py mycelium-ai-main/tests/test_failover_race.py mycelium-ai-main/tests/test_fencing.py mycelium-ai-main/tests/test_forge.py mycelium-ai-main/tests/test_forge_library.py mycelium-ai-main/tests/test_forge_persistence.py mycelium-ai-main/tests/test_forge_slice.py mycelium-ai-main/tests/test_git_commit.py mycelium-ai-main/tests/test_git_context.py mycelium-ai-main/tests/test_hardening.py mycelium-ai-main/tests/test_health_nutrition.py mycelium-ai-main/tests/test_honesty.py mycelium-ai-main/tests/test_integration_pass.py mycelium-ai-main/tests/test_interface.py mycelium-ai-main/tests/test_interface_api.py mycelium-ai-main/tests/test_inventory_read.py mycelium-ai-main/tests/test_inventory_writes.py mycelium-ai-main/tests/test_live_integration.py mycelium-ai-main/tests/test_maintenance_sweep.py mycelium-ai-main/tests/test_memory.py mycelium-ai-main/tests/test_mesh3d.py mycelium-ai-main/tests/test_mission_closeout.py mycelium-ai-main/tests/test_mission_dispatch.py mycelium-ai-main/tests/test_mission_loop.py mycelium-ai-main/tests/test_mission_task_binding.py mycelium-ai-main/tests/test_mission_templates.py mycelium-ai-main/tests/test_missions.py mycelium-ai-main/tests/test_model_router.py mycelium-ai-main/tests/test_mokerpass.py mycelium-ai-main/tests/test_n8n.py mycelium-ai-main/tests/test_n8n_workflows.py mycelium-ai-main/tests/test_node_auth.py mycelium-ai-main/tests/test_node_client.py mycelium-ai-main/tests/test_nodes.py mycelium-ai-main/tests/test_ollama_advisor.py mycelium-ai-main/tests/test_pass1_inventory_link.py mycelium-ai-main/tests/test_pass3_worker_loop.py mycelium-ai-main/tests/test_pass4_parallelism.py mycelium-ai-main/tests/test_pass6_forge_readiness.py mycelium-ai-main/tests/test_perf.py mycelium-ai-main/tests/test_physical.py mycelium-ai-main/tests/test_pipeline3d.py mycelium-ai-main/tests/test_plans.py mycelium-ai-main/tests/test_play_shell.py mycelium-ai-main/tests/test_printer3d.py mycelium-ai-main/tests/test_product_loop.py mycelium-ai-main/tests/test_project_context.py mycelium-ai-main/tests/test_project_package.py mycelium-ai-main/tests/test_promotion.py mycelium-ai-main/tests/test_proposal_tasks.py mycelium-ai-main/tests/test_providers.py mycelium-ai-main/tests/test_queue_leases.py mycelium-ai-main/tests/test_recovery.py mycelium-ai-main/tests/test_remote_control.py mycelium-ai-main/tests/test_remote_input.py mycelium-ai-main/tests/test_research_api.py mycelium-ai-main/tests/test_research_engine.py mycelium-ai-main/tests/test_research_extract.py mycelium-ai-main/tests/test_research_perf.py mycelium-ai-main/tests/test_research_plan.py mycelium-ai-main/tests/test_research_security.py mycelium-ai-main/tests/test_research_skills.py mycelium-ai-main/tests/test_research_transport.py mycelium-ai-main/tests/test_research_workspace.py mycelium-ai-main/tests/test_retention.py mycelium-ai-main/tests/test_routing.py mycelium-ai-main/tests/test_semantic.py mycelium-ai-main/tests/test_slicer3d.py mycelium-ai-main/tests/test_smoke11_15.py mycelium-ai-main/tests/test_sync.py mycelium-ai-main/tests/test_task_ownership.py mycelium-ai-main/tests/test_task_queue_bridge.py mycelium-ai-main/tests/test_tasks_from_proposal.py mycelium-ai-main/tests/test_v1.py mycelium-ai-main/tests/test_verification.py mycelium-ai-main/tests/test_vision_api.py mycelium-ai-main/tests/test_vision_flow.py mycelium-ai-main/tests/test_vision_ingest.py mycelium-ai-main/tests/test_vision_provider.py mycelium-ai-main/tests/test_vision_security.py mycelium-ai-main/tests/test_voice.py mycelium-ai-main/tests/test_voice_approval.py mycelium-ai-main/tests/test_workshop.py mycelium-ai-main/tests/test_workshop_ui.py mycelium-ai-main/tests/test_workspaces.py mycelium-ai-main/tests/test_workstream.py mycelium-ai-main/tests/test_world_proxy.py mycelium-ai-main/tests/test_worldgraph.py mycelium-ai-main/tests/test_write_api.py mycelium-ai-main/tests/test_write_mission.py mycelium-ai-main/tests/test_write_security.py

## LOCAL VS GITHUB

 .gitignore                                        |    1 +  AUTOPILOT_ROADMAP.md.txt                          | 1106 +++++++++++++++++++++  docs/NEXT-AI-CONTEXT.md                           |    0  mycelium-ai-main/coordinator/app/printer3d.py     |  380 ++++++-  mycelium-ai-main/coordinator/app/vision_ingest.py |   12 +-  mycelium-ai-main/tests/test_bambu_adapter.py      |   88 ++  6 files changed, 1563 insertions(+), 24 deletions(-)

## IMPORTANT HISTORICAL COMMITS

d8bfb64 = research → mission bridge
ebb36a7 = Bambu MQTT implementation
edb0a98 = BambuPrinterAdapter implementation
f19e7ec = printer3d restored / tests passing
d687145 = Bambu mock MQTT tests
776eecc = vision ingest change

## RECOVERY

A recovery stash exists:
stash@{0}: On main: RECOVERY_CHECKPOINT_BEFORE_AGENT_LOSS

## BIG47 — LIVING WORKSHOP VERTICAL (uncommitted, 2026-09-25)

GOAL MET: one real vertical digital loop works end-to-end (proven live,
not only in tests): /play Oracle (real Ollama qwen3.5:4b advice) →
POST /api/v1/play/code-task → existing queue → real code_worker
(OpenCode, model opencode/muse-spark-1.3-contributor-free) claim →
execute → complete → task.completed event → /play Workshop snapshot.

FILES (all uncommitted, none committed/pushed):
- NEW mycelium-ai-main/coordinator/app/play_workshop.py
  (GET /api/v1/play/status snapshot + bounded code-task queue;
  code.review/patch/test only; no execution; no physical authority)
- mycelium-ai-main/coordinator/app/main.py
  (+2 routes; Luma dialog +Workshop choice, workshop render fns,
  shared lifecycleLegend/stageChip helper, oraclequeue/wsrefresh/
  wsqueue/wsdrive actions, oracle queue-task button)
- NEW mycelium-ai-main/tests/test_big47_vertical.py (5 tests, pass)

LIVE DEMO (tmp DBs, :8000, all real): advice model qwen3.5:4b;
worker b47-opencode-01; task #3 completed, 0 files changed (review);
real OpenCode sentence stored in task result. code_worker quirk found:
bare `opencode` binary name unresolvable on Windows (task #2 failed
honestly); full exe path via --opencode-bin works. New node
registration requires node_token (code_worker supports via
--node-token/MYCELIUM_NODE_TOKEN).

NEXT BIG JUMP: game-created missions without hand-made conversations
(POST /api/v1/play/mission: advice -> pending_approval mission in one
call) + worker presence/liveness heartbeat strip in /play header.

## BIG48 — PRIMARY GAME RUNTIME (uncommitted, 2026-09-25)

ACCEPTANCE CHAIN PROVEN LIVE (tmp DBs, :8000, no reload, no fakes):
session play_4b7cf7c69151a403 -> position (1180,420) -> real Ollama
qwen3.5:4b advice -> POST /api/v1/play/mission (mission_8c56ea2d
pending_approval + quest qst_... + analysis step) -> YES -> POST
/api/v1/play/code-task met step_id (task #1) -> echte code_worker
b48-live-worker claim -> echte OpenCode run (completed, 0 files) ->
bestaande closeout sloot de step -> tick -> mission completed ->
quest COMPLETED 1/1 -> fungi 2 knopen / 1 vink in snapshot ->
resume na refresh herstelde (1180,420).

FILES (uncommitted, nothing committed/pushed):
- coordinator/app/play_workshop.py: step_id-binding (code.review +
  analysis only), play_sessions (throttled 2s), world counts.
- coordinator/app/main.py: routes play/session, play/position,
  play/mission; dispatch analysis-tak; kind-bewuste closeout-tekst;
  sessie-JS + refreshAfterAction/refreshJourneyData + playmission/
  stepqueue-acties (inline, geen refactor).
- coordinator/app/missions.py: DISPATCHABLE += analysis (goal ->
  code.review, cap).
- coordinator/app/quests.py: _mission_state leest echte status
  (was altijd WAITING door .record-bug) + fabrication-key in detail.
- coordinator/app/world.py: completed missies als vink-nodes
  (representatie only).
- coordinator/app/database.py: play_sessions-tabel (additief).
- NEW tests/test_big48_runtime.py (7 tests, pass).

EERLIJKE BEVINDINGEN: OpenCode permission-systeem weigerde C:\*-
toegang tijdens demo-run (auto-reject, safety werkt); worker
rapporteerde completed met echte output. Oude :8000-server moest
eerst gekilled (poortconflict).

TESTS: 7 nieuw + 26 missie + 70 big46/playshell + 20 big43/47 +
39 research/templates/world44-45 = alles groen. node --check 3/3.

NEXT BIG JUMP: tweede speelbare lus naast review (research.fetch
vanuit game-quest: issue->dossier->missie->worker->INVENTory-record
-> world_rep) + fungi-grove client-side her-render. Est. 3-4u.

## BIG49 — SIDE-VIEW SLICE /side (uncommitted, 2026-09-25)

Eigen Mycelium-game (Terraria = inspiratie only): GET /side naast
/play (vervangt niets). Inline canvas + vanilla JS (zelfde tech als
/play). Handgemaakte wereld 1920px: homebase + wildernis, gravity/
jump/AABB-collision, werkbank/waterbron/plantplek + scripted NPC
Mos, touch-knoppen (◀ ▶ ⤒ E). Geen nieuwe tabellen/routes:
discovery=echte candidate (observation, idempotent op titel),
keuze=advise/research-queue, quest=play/mission, positie=play-
session zone "side". XP in localStorage only, nooit poort.

LIVE BEWEZEN (:8001, tmp-DB): candidate 201, research 201 draft,
quest+mission 201 pending_approval, oracle 502 eerlijk
(INVENTory offline -> UNAVAILABLE, niets verzonnen).

FILES: main.py (+/side route), ui.py (+1 nav-regel Side),
NEW tests/test_big49_side.py (6 pass). Per ongeluk geraakt:
test_canvas_no_backend_writes brak op nieuwe kolom
position_updated_at ("position"-substring) -> hernoemd naar
moved_at; 18/18 groen (canvas+side+big48). node --check 2/2.

START: cd mycelium-ai-main && python -m uvicorn
coordinator.app.main:app --port 8000 -> http://127.0.0.1:8000/side

NEXT SLICE: tweede interactieve discovery (plantplek ->
zaailing-observatie), spring-uitdaging naar platform met
lore-beloning, NPC Mos met 1 echte flow-keuze. Est. 1-2u.

## BIG49 FOLLOW-UP — ECHT SPEELBAAR (uncommitted, 2026-09-25)

AUDIT (echte Chrome/Playwright vs BIG49-rapportage): renderen,
lopen, camera, sessie-restore en E-interactie klopten; platforms
waren ONBEREIKBAAR (sprong max ~107px vs 120/180px nodig) en er
was geen land/nabij-feedback. Gefixt, geen nieuwe content.

SPEELBAAR EN WERKEND (browser-bewezen): sprong -680/gravity 1800
(~128px hoog, ~195px ver); platforms p1 (300,390) p2 (580,300)
p3 (920,340) — sprong-op-p1 met aanloop in screenshot bewezen;
"geland"-feedback, "[E] naam" in bereik, "dichterbij komen"
daarbuiten; val-respawn; volledige lus waterbron->E->discovery
(+10 XP)->Research-run res_...->quest+missie pending_approval,
alles in echte Chrome incl. platform-sprong; /play /world / 200.

BACKEND-AFHANKELIJK: discovery->echte candidate (observation),
Oracle->echt qwen3.5:4b-advies live bewezen, Research-queue echt,
quest+missie pending_approval achter exacte-YES; offline ->
eerlijke 502/UNAVAILABLE (live gezien).

NOG PRESENTATIE/PROTOTYPE: NPC Mos (scripted hints only),
plantplek/werkbank (info+links), XP (teller only), platforms 2-3
alleen via sprong bereikbaar maar zonder beloning, touch-knoppen
niet op hardware getest.

FILES: main.py (/side physics/feedback only). Tests ongewijzigd;
suites: big49+big48 13/13, canvas 5/5, node --check 2/2.

## BIG49-X — GAME-WERELD + RESEARCH-STATION (uncommitted, 2026-09-25)

DOCS GEBRUIKT: AUTOPILOT_ROADMAP (P0 Research->Mission E2E, P3
Terraria-presentatie), MYCELIUM_CANVAS_DIRECTION (additief, skin
over data), REALITY_MAP (E-roadmap, paho-mqtt stock-broken),
living-game-layer.md (game = VIEW, geen 2e DB), PROJECT_STATE
BIG47/48/49 + follow-up. Code/tests als bewijs, docs als intentie.

MATRIX-KEUZE: Research full-loop als in-world Onderzoek-station
(queue->run-once->dossier->plan->pending_approval missie), want
P0-prioriteit, volledig bestaand/getest, eerlijke offline-tak,
direct vervolg op waterbron-discovery. INVENTory-lezen, fabricage
en camera bewust niet gekozen (bridge offline / SIMULATED zonder
printer / geen adapter).

WERELD (zelfde stack, geen assets): dusk-sky + sterren + maan,
2 parallax-heuvellagen, mycelium-draden, hut met verlicht raam +
schoorsteenrook, lantaarnpaal met glow, hek, zone-boog
WILDERNIS, mos-platforms met ranken, riet, paddenstoelen,
ruinestenen, zodiende zaailingen, fireflies, kapperspeler met
lantaarn, Mos als figuur met staf + naam, speech-bubble,
"E · TALK"/range-ringen in-scene, touch-bar gestyled.

LIVE BEWEZEN (echte Chrome, :8003, tmp-DB): Mos-TALK + bubble,
discovery, research queue->run (wikipedia offline -> eerlijke
stop), dossierlijst met seeded completed dossier, plan->echte
missie pending_approval met YES-notice. Oracle-tak: echt
qwen3.5:4b-advies. Geen page-errors.

FILES: main.py (/side draw + station-flow), tests/test_big49_side
(+markers). Controles: big49+canvas 11/11, node --check 2/2
(na brace-fix), /play /world / 200. Geen commit/push.

NOG PROTOTYPE: plantplek/werkbank info-only, XP-teller, Mos
scripted, touch niet op hardware getest.
VOLGENDE KLEINSTE STAP: plantplek als 2e discovery
(zaailing-observatie ->zelfde station-flow) + beloning op p3
(lore-candidate). Est. 1-2u.

## BIG50 — ATLAS, JOURNAL, RESEARCH-FIX (uncommitted, 2026-09-25)

FASE 1+2: `PROJECTATLAS.md` (root: 9 apps, gamedata-gebruik, 5
overlapclusters C1–C5 met canonieke bronnen, missend/simulated,
statusmodellen, routerefs) + `MYCELIUM_BIG50_DOCS.zip` (root, 59
entries: atlas + big50/MANIFEST/OUTDATED_DOCS/GAPMATRIX +
bestaande docs; geen secrets/DBs/venvs/binaries — geverifieerd).
Nieuwe bestanden: `AI_HANDOFF/big50/{MANIFEST,OUTDATED_DOCS,
GAPMATRIX}.md`.

FASE 3 JOURNAL: `GET /api/v1/play/journal` (read-only rangschikking
over bestaande stores — geen ongerangschikt alternatief; geen
nieuwe tabellen/missies) + in-game Journal-view in /side (actieve
missie met tik, wachtenden met YES, open quests/research/vondsten
met deep links). Live bewezen: actieve+wachtende missie, YES via
Journal (approved), support via plantplek (♥1).

FASE 4 RESEARCH-FIX: Plan-knop alleen bij planbaar dossier
(completed/REAL/TEST-inhoud; backend 422 blijft eindoordeel met
leesbare station-terugkeer); run-zonder-dossier toont "zonder
bruikbaar dossier" + retry/Oracle/dossierlijst. 422-contract met
test bewezen (draft-run zonder dossier -> 422 "no completed
dossier").

FASE 5 KENNIS-SLICE: plantplek toont open vondsten + Support
(bestaande gate, supporter "speler", no-op bij dubbel) —
browser-bewezen.

BEVINDINGEN: /chat hangt live op trage Ollama (>120s) — seeden via
play/mission; wikipedia offline -> eerlijke unavailable-runs;
TEST-dossiers zijn planbaar (201 bewezen); browser-interval vs
API-positionering vraagt verse sessies in tests.

TESTS: test_big50_game.py 6/6 nieuw; big49+big50 12/12;
big49+canvas 11/11; node --check 2/2; browser: Journal->YES,
support, dossier->plan->pending_approval missie, /, /play,
/world, /side 200. Geen commit/push.

VOLGENDE FASERING (GAPMATRIX): F1 proj_-doelen in Journal, F2
dossier->memory-link, F3 live fabrication_chain bij werkbank, F4
automation-drive vanuit Journal, F5 tiles/sprites-skin.

## BIG51 — GAME-FIRST PRODUCTRICHTING + PROJECTLUS (uncommitted, 2026-09-25)

RICHTING (gebruikerskeuze, leidend boven verouderde roadmaptekst):
`/side` is de primaire Mycelium-ervaring (Terraria-geïnspireerde
eigen gamewereld), geen late presentatie-polish. Vastgelegd in
`PROJECTATLAS.md` §6 + C5 (runtime `/side`; `/play` behouden; geen
derde game-ervaring). Behouden: backend leidend, geen dubbele
truth, approvals intact, XP optioneel/geen poort. Oude docs
(AUTOPILOT P0–P3 "game last", ROADMAP-V2, BIG48 `/play`=runtime,
CANVAS FUTURE) blijven archief, geen sturing. ZIP-afwijking:
`MYCELIUM_BIG50_DOCS.zip`/`PROJECT_STATE.md` stopt bij BIG49-X;
werkboom bevat BIG50 + BIG51 (verwacht snapshot-lag, geen
tegenspraak). Live INVENTory `:8080` draait maar is LEEG
(objects/projects/ideas/files 0; M3-collecties 404) — Journal
toont dit eerlijk, verzint niets.

FASE 2 JOURNAL (GAPMATRIX F1): `play_journal()` + `/side`
Journal-view tonen echte `proj_`-records (status→waarom,
bronrecord, deeplink `/world?entity_id=proj_…&depth=1`).
GET-only loopback bridge (≤5s, geen redirects); offline →
UNAVAILABLE + bestaande vervolgstap (`/world`); leeg → eerlijk
leeg. Geen tweede backlogstore; brainstorm ≠ missies; geen
missie-aanmaak vanuit Journal.

FASE 3 LUS "ONDERZOEK → ONTHOUD" (GAPMATRIX F2/G10, hoogste
beschikbare waarde — INVENTory-leegte maakt F1 als lus
onmogelijk): waterbron-discovery → Onderzoek-station
(queue→run-once TEST) → completed dossier → bestaande
auto-remember → station toont "Onthouden als mem_…" (+/memory) →
Journal kennis-sectie (dossier + mem_ + telling) → wereld:
zaailingen groeien + gouden geheugensporen (alleen bij echte
telling) → volgende keuze (Plan→missie/Oracle). Geen XP als
voortgangsbewijs.

RESEARCH-REGRESSIE (BIG50-fix behouden, expliciet getest in
`tests/test_big51_game.py`): draft zonder dossier → 422, geen
Plan-actie in Journal; TEST-completed → plan → pending_approval;
unavailable → eerlijke status + retry/Oracle/dossierlijst.

FILES: `play_workshop.py` (projects+knowledge-secties),
`main.py` (/side Journal-secties, station-memoryregel,
worldMemory + canvas-sporen/zaailingen), `PROJECTATLAS.md`
(§6 + C5 + Stand), `GAPMATRIX.md` (F1/F2 DONE),
NEW `tests/test_big51_game.py`. Geen commit/push.

NOG PROTOTYPE: Mos scripted, werkbank/plantplek info+links,
touch niet op hardware getest, F3–F5 open.
VOLGENDE KLEINSTE SLICE: F3 werkbank toont live
`fabrication_chain()` read-only. Est. 1–2u.

## BIG52 — WERK ALS CAMPAIGN + WERKBANK F3 (uncommitted, 2026-09-25)

TRACKING-MODELGAT (eerlijk, geen data toegevoegd): Quest/Campaign
kunnen een ontwikkelbacklog NIET bijhouden — `note`-steps zonder
ref zijn permanent MISSING (`derive_step_state`), zelfs mét ref
blijft een note MISSING, `entity`-steps blijven WAITING; alleen
missie/task/finance/energy/hardware-steps met ECHT record leven.
Een Quest voor "nog te bouwen werk" zou nooit COMPLETE kunnen
worden; missies aanmaken voor F3–F5 zou uitvoerbare missies
verzinnen. Kleinste bestaande-model-oplossing: read-only
questlijn `roadmap` in `play_journal()` (VIEW over GAPMATRIX, geen
tweede backlog-DB, geen records) — F3/F4/F5 met status
open/in-uitvoering, live bewijs (F3: echte ketentelling; F4: open
runs + drive-route), bron + bestaande route. Brainstorm blijft
nergens quest; operationele missies in bestaande secties.

F3 WERKBANK (`/side` bench-spot → `renderBench()`): echte
`fabrication_chain()` via GET `/api/v1/play/status` + echte
`mdl_`-modellen via GET `/api/v1/workshop/models`; per stap chip
(✅REAL/🎭SIMULATED/⛔BLOCKED/🔌UNAVAILABLE), betekenis, via+detail
(blokkade), volgende actie als link (slicing/approval/execution:
expliciet geen knop + reden). Alleen GET, nergens POST —
`prints/propose|/inspect|/execute|/dispatch|/drive` afwezig in
bench-JS (getest). Niets geprint-claim.

PROVENANCE (BIG52): knowledge-entries krijgen `origin`; niet-REAL
→ "Proefherkomst … nooit feit", tellingen `memories_test`/
`memories_real`; station-regel en objectief tonen TEST-herkomst
("TEST-proef — geen feit") zodat gouden sporen geen verificatie
suggereren. BIG50-regel behouden (draft→422, getest).

TESTS: `tests/test_big52_game.py` 7/7 (roadmap, origin, regressie,
keten-states, bench-start-niets, links, markers); regressie
big51+big50+big49+canvas 24/24. BEVINDING: GET `/cameras` crasht
het testproces native in `cameras.py:_windows_image_devices`
(ctypes, pre-existing) — uitgesloten uit link-resolve-test, link
blijft bestaan. Live-browsertest NIET uitgevoerd: geen
coordinator beschikbaar (alleen :8080 INVENTory 200); bench is
gedekt via API- + marker-tests. `/`, `/play`, `/world`, `/side`
200 via TestClient. Geen commit/push.

NOG PROTOTYPE: Mos scripted, plantplek info+links, touch niet op
hardware getest.
REST (F4/F5, in Journal questlijn): F4 drive-knop naast
Journal-missie; F5 tiles/sprites-skin. STOP na deze slice.

## BIG53 — CORE GAME LOOP / TERRARIA VERTICAL (uncommitted, 2026-09-27)

LOOP (2D side-view, echt speelbaar, 30 min): 9 nodes (houtstronk/
vezelplant/kei) → E plukt in sessie-voorraad (server: +1, cooldown
90s/node) → werkbank craft 4 recepten (stok/fakkel/plankbrug/hekje,
server valideert kosten) → ghost-plaatsmodus (klik in veld;
plank alleen bij kloof x1050–1270, server valideert bezit+grenzen)
→ plankbrug als echte collider, fakkel als licht, hekje als decor
→ oost-zone met 2 sporepuffers (patrol, contact = terugduw + 1s
stun, nooit schade/verlies) → codex-steen (Oracle/Research/quest
via bestaande flows). Doelenlijst in-world (6 echte flags), XP
alleen beloning (+1/+5/+3, nooit poort).

BACKEND (bestaande patronen): tabellen `play_inventory`/
`play_gather`/`play_builds` (additief, game-state zoals
play_sessions — nooit backend-records, bridge blijft read-only);
routes GET `/play/inventory`, POST `/play/gather|craft|place`
(404 onbekende sessie, 422 onbekende node/recept/tekort/cooldown/
grenzen). IRL-haken: specimen→candidate, recept→research-kind,
bouwsel→proposal-missie (alleen haken, niets gebouwd).

BEVINDINGEN: `#side-result` ontbrak initieel (alle vroege feedback
stil — hersteld als permanent element); load-time canvas-klik
bleek onbetrouwbaar in testen, ghost-draad nu runtime via
`stage.onclick` bij moduswissel (+ reserve-listener); kloof-val =
vriendelijke hut-respawn (bestaat al); ascii-testprints vermengen
✓/○ (alleen test-artefact).

TESTS: `tests/test_big53_loop.py` 6/6 (shapes, 404/422, cooldown,
craft-verbruik, place-verbruik/bounds, markers); `node --check`
op /side-JS schoon; regressie big49+canvas 11/11, big50-reeks
17/17 (eerder), big51+52 14/14, big52 7/7 (na wijziging).
BROWSER (echte Chrome, :8003 tmp-DB): gather hout 3 → craft plank
→ plaats bij kloof (plank verbruikt, ✓ Plaats, brug zichtbaar,
screenshot b53-bridge.png); puffer-contact (bubbel + ✓, geen
straf); bench met recepten + 14-staps keten; geen page-errors
(enige console-404 = pre-existing favicon). Geen commit/push.

## BIG54 — GAME UI CLEANUP + WORLD PRESENTATION (uncommitted, 2026-09-27)

GEEN backend-feature: alleen `/side`-presentatie over de
ongewijzigde BIG53-game (zelfde routes, flows, gates, tabellen).

WORLD-FIRST: canvas-paneel eerst met HUD-overlay (gebied +
voorraad + XP + Journal bovenin, interactieprompt onderin);
dashboardlink-rij ingeklapt in `<details>Mycelium-web` (hrefs
behouden); dubbele canvas-HUD-balk verwijderd (zone/x alleen in
DOM-HUD). HUD: `📍 Gebied · x`, `Hout × n`-voorraad, `[✓]/[ ]`-
doelen, XP als beloning. Werkwoorden overal: E·Verzamel /
E·Werkbank / E·Codex / E·TALK (canvas) + zinnen (prompt).
VISUEEL: warmere lucht + gouden horizon, dag-tint per dagdeel
(puur presentatie), rijkere grondlagen, node-glyphs groter met
naamlabels, speler-contour voor contrast.

BEVINDING: tweede canvas-HUD-balk (na speler-draw) gebruikte
verwijderde `zone`-var → `zone is not defined`-spam per frame;
beide balken verwijderd, DOM-HUD is leidend. Geen page-errors
meer (favicon-404 pre-existing).

TESTS: `tests/test_big54_ui.py` 5/5 (layout, werkwoorden, geen
nieuwe routes, lus intact, routes); regressie big53 6/6,
big49-vorm 3/3, big52-markers 3/3; `node --check` JS schoon.
BROWSER (echte Chrome, :8003): HUD-overlay, `[E] Verzamel —
Vezelplant`, `Vezel × 1`, doelen `[✓]/[ ]`, screenshot
b54-world.png; geen page-errors. Geen commit/push.

## HERMES NPC — MOS ALS ECHTE AGENT (uncommitted, 2026-09-28)

Hermes API bewezen (127.0.0.1:8642, Bearer, chat round-trip);
sleutel in Hermes-home `.env` (alleen bestand daar gewijzigd).
`coordinator/app/hermes_bridge.py` (loopback-only, ≤120s, 503/422/
502-ladder) + `tests/test_hermes_bridge.py` 7/7. `hermes_npc.py`:
Mos-identiteit, sessie `npc-mos-<play_session>`, wereldcontext
(voorraad/bouwsels/flags/Journal + echte `obj_`-steekproef);
route `POST /api/v1/hermes/chat`; agent handelt nooit zelf.
Game: Mos-dialoog met chat + Missie-0-voorstelformulier
(bestaande writes/approvals-flow).

MISSIE 0 LIVE BEWEZEN (:8003 tmp-DB, :8080 echte DB): chat met
echte Hermes-agent → voorstel `wrt-ac88cbdc` (inert) → operator
YES + execute → echt `obj_1a0e8773d83cd9cf6e3` "Soldeerbout
Weller" in INVENTory → agent leest terug met exact ID + stelt
gameplay-koppeling voor. Bevinding: context miste eerst
objecten (agent zei eerlijk "leeg") — steekproef toegevoegd.
Tests: `test_hermes_npc.py` 7/7 (incl. /side-markers). Geen
commit/push. Camera/Insta360/live-vision: NIET GEÏMPLEMENTEERD
(file-ingest bestaat; geen capture-adapters).

## BIG55 — LIVING MYCELIUM WORLD (uncommitted, 2026-09-27)

WERELD (3840px, zelfde physics): Homebase/Wildernis/Oostland +
Undergrove (donker, fakkel-gate)/Moeraslab (mist, sporen)/
Outpost (settlement); 15 nodes (hout/vezel/steen/kristal/riet/
schroot), 9 recepten, regio-HUD met Dag/fase. Geen nieuwe engine:
deterministische data-constanten.

SYSTEMEN (game-owned tabellen, additief): `play_chests*` (E→overlay,
deposit/withdraw, eigendom), `play_npc` (kamer+licht-validatie,
toewijzing), `play_flags` (quest/encounter-persistentie),
`world_clock` (dag/minuut/fase, +10min per 60s, nooit wandklok),
`play_notes` (quest-notities + prioriteit). Routes:
GET/POST flags/notes, chest get/deposit/withdraw, npc get/assign,
clock/tick. Interactie = dichtstbijzijnde wint.

NPC's (6): Mos/Orakel/Smid/Archivaris/Voorman/Seinwachter met
zichtbare eisen, huis-toewijzing, computers op bestaande routes
(fabrication/knowledge/missions/nodes/advise). Nodes als
outpost-masten (echte `/nodes`-lijst). Questbord: hydroponics met
live eisen + notities; geen tweede engine.

ENCOUNTERS: kruiper (achtervolgt), sporenzones (halveren),
Modderhart-boss (ontdek→bereid→20s trotseren→candidate-beloning
+ kristal-vrij + wortels), ruïne-mysterie (kompas→research→
zendmast→Seinwachter), events (sporenregen/bloei/handelaar/
stilte/stormvlaag, afgeleid, geen daemon). Vriendelijk: nooit
schade/verlies.

BEVINDINGEN: node verslaat kist bij gelijke afstand → dichtstbijzijnde
wint; dialogs lezen oud cache → refreshInv bij openen; kristal-gate
+ kruiper-bewaking werken samen; ascii-prints vermengen ✓/○.

TESTS: `tests/test_big55_world.py` 7/7 (flags, chests+eigendom,
npc-validatie, klok, notes, mast, markers); BIG53-grens 1920→3840
bijgewerkt; regressie big53/54/52 groen; `node --check` schoon.
BROWSER (:8003): kist-UI, NPC-toewijzing, kristal-gate, questbord,
Modderhart (vlag + candidate + wortels), hotbar, screenshots
b55-*.png; geen page-errors. Geen commit/push.
