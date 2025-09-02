# Task Failure Analysis Report

**Generated:** 2025-08-22T02:52:41.130658
**Time Range:** Last 24 hours
**Total Failed Tasks:** 69
**Critical Tasks Analyzed:** 10

📋 EXECUTIVE SUMMARY
================================================================================
• Total Failed Tasks: 69
• Time Period: Last 24 hours
• Critical Tasks: 10
• Top Error Types:
  - Other Error: 53 (76.8%)
  - No error message: 16 (23.2%)
• Affected Workers: 15


📊 Failure Analysis (69 tasks)
================================================================================
📅 Time Range:
   Oldest failure: 2025-08-21T17:19:29.203+00:00
   Newest failure: 2025-08-21T22:09:01.139+00:00

❌ Error Categories:
   Other Error: 53 (76.8%)
   No error message: 16 (23.2%)

📝 Task Types:
   travel_segment: 27 (39.1%)
   travel_stitch: 26 (37.7%)
   travel_orchestrator: 16 (23.2%)

🤖 Worker Analysis:
   None: 39 failures
      └─ Other Error: 37
      └─ No error message: 2
   gpu-20250821_223905-4c643f54: 7 failures
      └─ Other Error: 4
      └─ No error message: 3
   gpu-20250821_234833-8a8e8035: 4 failures
      └─ Other Error: 2
      └─ No error message: 2
   gpu-20250821_235104-39148871: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250821_232733-e6c0cc18: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250821_223907-e6edb06f: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250821_222250-f1a86f9c: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250821_222541-c4b9c63c: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250821_220501-0cb182bc: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250821_200647-49e91eb3: 2 failures
      └─ Other Error: 1
      └─ No error message: 1

🔄 Attempt Distribution:
   0 attempts: 69 (100.0%)

⏱️  Timing Analysis:
   Avg processing duration: 298.7s
   Avg queue duration: 11639.0s

🔍 DETAILED LOG ANALYSIS
================================================================================

🔍 Task 1: 47bd96fa-fbad-40b0-86f3-df403ea81c86
   Category: Other Error
   Worker: gpu-20250821_235104-39148871
   Attempts: 0
   Created: 2025-08-21T21:57:01.793811+00:00
   Failed: 2025-08-21T22:09:01.139+00:00
   Error: Cascaded failed from related task ed46c8b2-5bbc-43b1-b436-dad3a2376bb9
   📋 Orchestrator Log: No entries found
   🤖 Worker Log (S3): 22 entries
      [1463] [IMMEDIATE DEBUG] orchestrator_task_id_ref: 47bd96fa-fbad-40b0-86f3-df403ea81c86
      [1498] [ORCHESTRATOR_COMPLETION_DEBUG] Stitch task complete. Orchestrator 47bd96fa-fbad-40b0-86f3-df403ea81c86 will be marked c...
      [1529] [ORCHESTRATOR_COMPLETION_DEBUG] Stitch task complete. Orchestrator 47bd96fa-fbad-40b0-86f3-df403ea81c86 will be marked c...

🔍 Task 2: ed46c8b2-5bbc-43b1-b436-dad3a2376bb9
   Category: No error message
   Worker: gpu-20250821_235104-39148871
   Attempts: 0
   Created: 2025-08-21T21:57:04.56+00:00
   Failed: 2025-08-21T22:09:00.981+00:00
   📋 Orchestrator Log: No entries found
   🤖 Worker Log (S3): 12 entries
      [1522] Stitch Task ed46c8b2-5bbc-43b1-b436-dad3a2376bb9: Final video saved to: /workspace/Headless-Wan2GP/Wan2GP/outputs/defaul...
      [1536] [22:09:01] ✅ HEADLESS [Task ed46c8b2-5bbc-43b1-b436-dad3a2376bb9] Task completed successfully: /workspace/Headless-Wan2G...
      [1538] [22:09:01] ✅ HEADLESS [Task ed46c8b2-5bbc-43b1-b436-dad3a2376bb9] Task completed successfully: /workspace/Headless-Wan2G...

🔍 Task 3: c9aba692-605b-41df-8561-d84cfd53ae7e
   Category: Other Error
   Worker: gpu-20250821_234833-8a8e8035
   Attempts: 0
   Created: 2025-08-21T22:00:08.80166+00:00
   Failed: 2025-08-21T22:04:17.627+00:00
   Error: Cascaded failed from related task 5d8c1243-4e15-472b-b03c-23f602ca7d1e
   📋 Orchestrator Log: No entries found
   🤖 Worker Log (S3): 22 entries
      [2180] [IMMEDIATE DEBUG] orchestrator_task_id_ref: c9aba692-605b-41df-8561-d84cfd53ae7e
      [2215] [ORCHESTRATOR_COMPLETION_DEBUG] Stitch task complete. Orchestrator c9aba692-605b-41df-8561-d84cfd53ae7e will be marked c...
      [2246] [ORCHESTRATOR_COMPLETION_DEBUG] Stitch task complete. Orchestrator c9aba692-605b-41df-8561-d84cfd53ae7e will be marked c...

🔍 Task 4: 5d8c1243-4e15-472b-b03c-23f602ca7d1e
   Category: No error message
   Worker: gpu-20250821_234833-8a8e8035
   Attempts: 0
   Created: 2025-08-21T22:00:10.445+00:00
   Failed: 2025-08-21T22:04:17.487+00:00
   📋 Orchestrator Log: No entries found
   🤖 Worker Log (S3): 12 entries
      [2239] Stitch Task 5d8c1243-4e15-472b-b03c-23f602ca7d1e: Final video saved to: /workspace/Headless-Wan2GP/Wan2GP/outputs/defaul...
      [2253] [22:04:17] ✅ HEADLESS [Task 5d8c1243-4e15-472b-b03c-23f602ca7d1e] Task completed successfully: /workspace/Headless-Wan2G...
      [2255] [22:04:17] ✅ HEADLESS [Task 5d8c1243-4e15-472b-b03c-23f602ca7d1e] Task completed successfully: /workspace/Headless-Wan2G...

🔍 Task 5: 847f772d-0837-412e-912f-cd878e9fe67d
   Category: Other Error
   Worker: gpu-20250821_234833-8a8e8035
   Attempts: 0
   Created: 2025-08-21T21:48:21.583771+00:00
   Failed: 2025-08-21T21:56:49.78+00:00
   Error: Cascaded failed from related task a43029e7-59da-4307-90ae-55a77da14c5c
   📋 Orchestrator Log: No entries found
   🤖 Worker Log (S3): 22 entries
      [1471] [IMMEDIATE DEBUG] orchestrator_task_id_ref: 847f772d-0837-412e-912f-cd878e9fe67d
      [1506] [ORCHESTRATOR_COMPLETION_DEBUG] Stitch task complete. Orchestrator 847f772d-0837-412e-912f-cd878e9fe67d will be marked c...
      [1537] [ORCHESTRATOR_COMPLETION_DEBUG] Stitch task complete. Orchestrator 847f772d-0837-412e-912f-cd878e9fe67d will be marked c...

💡 RECOMMENDATIONS
================================================================================

🤖 PROBLEMATIC WORKERS:
   • None: 39 failures
     └─ Primary issue: Other Error (37 times)
   • gpu-20250821_223905-4c643f54: 7 failures
     └─ Primary issue: Other Error (4 times)

⚠️  SYSTEM HEALTH: High failure volume (69 failures)
   • Review overall system capacity
   • Consider maintenance window
   • Audit recent configuration changes

📋 OPERATIONAL:
   • Monitor failure trends over longer periods
   • Set up automated alerts for error spikes
   • Review task retry policies
   • Consider implementing circuit breakers