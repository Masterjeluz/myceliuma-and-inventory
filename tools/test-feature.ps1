<# test-feature: run alle tests van één feature (zie docs/TESTING.md mapping).
Gebruik: .\tools\test-feature.ps1 -Feature missions
         .\tools\test-feature.ps1 -Feature research
Alleen die feature; geen volledige regressie. #>
param(
  [string]$Feature = "missions",
  [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$tmp = [System.IO.Path]::GetTempPath()
$env:MYCELIUM_DATABASE_PATH = Join-Path $tmp ("myc_feat_{0}.db" -f $PID)
$env:MYCELIUM_CHAT_DATABASE_PATH = Join-Path $tmp ("myc_chat_feat_{0}.db" -f $PID)
$env:INVENTORY_DATABASE_PATH = Join-Path $tmp ("inv_feat_{0}.db" -f $PID)

$map = @{
  "inventory-objects" = @{ dir = "inventory"; files = @("tests/test_objects.py", "tests/test_database.py") }
  "inventory-search"  = @{ dir = "inventory"; files = @("tests/test_milestone_3_1.py", "tests/test_milestone_3_2.py", "tests/test_milestone_4.py", "tests/test_search_types_ui.py") }
  "inventory-all"     = @{ dir = "inventory"; files = @("tests/") }
  "missions"    = @{ dir = "mycelium-ai-main"; files = @("tests/test_missions.py", "tests/test_big46_quest_mission.py") }
  "research"    = @{ dir = "mycelium-ai-main"; files = @("tests/test_research_api.py", "tests/test_research_engine.py", "tests/test_research_extract.py", "tests/test_research_plan.py", "tests/test_research_security.py", "tests/test_research_transport.py") }
  "knowledge"   = @{ dir = "mycelium-ai-main"; files = @("tests/test_big32_knowledge.py", "tests/test_knowledge_lifecycle.py") }
  "nodes-tasks" = @{ dir = "mycelium-ai-main"; files = @("tests/test_nodes.py", "tests/test_node_auth.py", "tests/test_node_client.py", "tests/test_dist_queue.py", "tests/test_desktop_agent.py") }
  "vision"      = @{ dir = "mycelium-ai-main"; files = @("tests/test_cameras.py", "tests/test_bambu_camera.py", "tests/test_vision_api.py", "tests/test_vision_flow.py", "tests/test_vision_security.py", "tests/test_big34_camera_ecosystem.py", "tests/test_capture_probe.py", "tests/test_probe_grab.py", "tests/test_vision_capabilities.py") }
  "fab"         = @{ dir = "mycelium-ai-main"; files = @("tests/test_fab_api.py", "tests/test_fab_security.py", "tests/test_printer3d.py", "tests/test_advanced_3d.py", "tests/test_bambu_readonly.py", "tests/test_bambu_exec.py", "tests/test_big57_printfase.py") }
  "workshop"    = @{ dir = "mycelium-ai-main"; files = @("tests/test_workshop.py", "tests/test_big35_workshop.py", "tests/test_big57_printfase.py") }
  "automation"  = @{ dir = "mycelium-ai-main"; files = @("tests/test_big38_automation.py", "tests/test_controlled_writes.py", "tests/test_approvals_api.py") }
  "game"        = @{ dir = "mycelium-ai-main"; files = @("tests/test_big43_game.py", "tests/test_big44_world.py", "tests/test_big46_quest_mission.py", "tests/test_big47_vertical.py", "tests/test_big48_runtime.py", "tests/test_big49_side.py", "tests/test_big50_game.py", "tests/test_big51_game.py", "tests/test_big52_game.py", "tests/test_big53_loop.py", "tests/test_big54_ui.py", "tests/test_big55_world.py", "tests/test_big56_drive.py", "tests/test_canvas.py") }
  "solarpunk"   = @{ dir = "mycelium-ai-main"; files = @("tests/test_solarpunk.py") }
  "insta360"    = @{ dir = "mycelium-ai-main"; files = @("tests/test_insta360.py") }
  "homebase"    = @{ dir = "mycelium-ai-main"; files = @("tests/test_homebase.py") }
  "town"        = @{ dir = "mycelium-ai-main"; files = @("tests/test_town.py") }
  "world"       = @{ dir = "mycelium-ai-main"; files = @("tests/test_world_areas.py", "tests/test_world_observations.py", "tests/test_world_proxy.py", "tests/test_world_workspace.py") }
  "hermes"      = @{ dir = "mycelium-ai-main"; files = @("tests/test_hermes_npc.py", "tests/test_hermes_bridge.py", "tests/test_hermes_all_npcs.py") }
  "agent"       = @{ dir = "Mycelium/agent"; files = @("tests/") }
}

if (-not $map.ContainsKey($Feature)) {
  Write-Output ("Onbekende feature '{0}'. Kies uit: {1}" -f $Feature, ($map.Keys -join ", "))
  exit 2
}

$entry = $map[$Feature]
$projDir = Join-Path $root $entry.dir
Push-Location -LiteralPath $projDir
try {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $argList = @("-q", "--tb=short") + $entry.files
  & python -m pytest @argList
  $code = $LASTEXITCODE
  $sw.Stop()
  Write-Output ("test-feature [{0}] exit={1} duur={2:N1}s" -f $Feature, $code, $sw.Elapsed.TotalSeconds)
  exit $code
} finally { Pop-Location }
