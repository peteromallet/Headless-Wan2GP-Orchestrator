# Task Failure Analysis Report

**Generated:** 2025-08-24T11:59:04.234939
**Time Range:** Last 72 hours
**Total Failed Tasks:** 100
**Critical Tasks Analyzed:** 10

📋 EXECUTIVE SUMMARY
================================================================================
• Total Failed Tasks: 100
• Time Period: Last 72 hours
• Critical Tasks: 10
• Top Error Types:
  - Other Error: 94 (94.0%)
  - No error message: 6 (6.0%)
• Affected Workers: 16


📊 Failure Analysis (100 tasks)
================================================================================
📅 Time Range:
   Oldest failure: 2025-08-23T19:09:33.159+00:00
   Newest failure: 2025-08-24T08:33:06.469+00:00

❌ Error Categories:
   Other Error: 94 (94.0%)
   No error message: 6 (6.0%)

📝 Task Types:
   travel_segment: 79 (79.0%)
   travel_stitch: 15 (15.0%)
   travel_orchestrator: 4 (4.0%)
   single_image: 2 (2.0%)

🤖 Worker Analysis:
   None: 81 failures
      └─ Other Error: 79
      └─ No error message: 2
   gpu-20250824_102008-ee8e1551: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250824_091601-478b087a: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250824_015049-cad9aa38: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250823_232948-20621ad7: 2 failures
      └─ Other Error: 1
      └─ No error message: 1
   gpu-20250824_102100-eececbd1: 1 failures
      └─ Other Error: 1
   gpu-20250824_102102-b4f50815: 1 failures
      └─ Other Error: 1
   gpu-20250824_093031-bfac884d: 1 failures
      └─ Other Error: 1
   gpu-20250824_093102-9f0139e3: 1 failures
      └─ Other Error: 1
   gpu-20250824_093104-2919c5bb: 1 failures
      └─ Other Error: 1

🔄 Attempt Distribution:
   0 attempts: 100 (100.0%)

⏱️  Timing Analysis:
   Avg queue duration: 24222.1s

🔍 DETAILED LOG ANALYSIS
================================================================================

🔍 Task 1: e53abb84-8199-496d-a037-4f9eb2fc2405
   Category: Other Error
   Worker: gpu-20250824_102008-ee8e1551
   Attempts: 0
   Created: 2025-08-24T08:08:00.192+00:00
   Failed: 2025-08-24T08:33:06.469+00:00
   Error: Cascaded failed from related task 34623d75-4aa0-4ed6-ae6a-6099e2cdd285
   📋 Orchestrator Log: No entries found
   🤖 Worker Log (S3): 10 entries
      [2811] [08:33:05] ❌ TRAVEL [Task e53abb84-8199-496d-a037-4f9eb2fc2405] Stitch: Unexpected error during stitching: list index ou...
      [2937] [CRITICAL DEBUG] Using cross-fade due to overlap values: [10, 10, 10, 10, 10]. Output to: /workspace/Headless-Wan2GP/Wan...
      [2999] [08:33:06] ❌ HEADLESS [Task e53abb84-8199-496d-a037-4f9eb2fc2405] Task failed. Output: Stitch task failed: list index ou...

🔍 Task 2: 871526fd-5e2b-46ba-b74f-50f7c8df83bc
   Category: Other Error
   Worker: Unassigned
   Attempts: 0
   Created: 2025-08-24T08:22:14.376+00:00
   Failed: 2025-08-24T08:33:05.918+00:00
   Error: Cascaded failed from related task 34623d75-4aa0-4ed6-ae6a-6099e2cdd285
   📋 Orchestrator Log: No entries found
   🤖 Worker Log: No worker assigned

🔍 Task 3: 102bda18-ca4d-44c0-af58-f59f12da59ad
   Category: Other Error
   Worker: gpu-20250824_102100-eececbd1
   Attempts: 0
   Created: 2025-08-24T08:22:13.481+00:00
   Failed: 2025-08-24T08:33:05.918+00:00
   Error: Cascaded failed from related task 34623d75-4aa0-4ed6-ae6a-6099e2cdd285
   📋 Orchestrator Log: No entries found
   🤖 Worker Log (S3): 30 entries
      [2012] 2025-08-24 08:31:19,919 [INFO] HeadlessQueue: [GENERATION_DEBUG] Task travel_seg_102bda18-ca4d-44c0-af58-f59f12da59ad: U...
      [2013] 2025-08-24 08:31:19,921 [INFO] HeadlessQueue: [GENERATION_DEBUG] Task travel_seg_102bda18-ca4d-44c0-af58-f59f12da59ad: V...
      [2014] 2025-08-24 08:31:19,921 [INFO] HeadlessQueue: [GENERATION_DEBUG] Task travel_seg_102bda18-ca4d-44c0-af58-f59f12da59ad: V...

🔍 Task 4: 3b0d4716-0de4-4f0d-bc01-3f4ae1ea96c5
   Category: Other Error
   Worker: Unassigned
   Attempts: 0
   Created: 2025-08-24T08:20:14.062+00:00
   Failed: 2025-08-24T08:33:05.918+00:00
   Error: Cascaded failed from related task 34623d75-4aa0-4ed6-ae6a-6099e2cdd285
   📋 Orchestrator Log: No entries found
   🤖 Worker Log: No worker assigned

🔍 Task 5: 7819c0f5-2988-4c4f-8bfb-2d4c6a5cbff2
   Category: Other Error
   Worker: Unassigned
   Attempts: 0
   Created: 2025-08-24T08:22:14.103+00:00
   Failed: 2025-08-24T08:33:05.918+00:00
   Error: Cascaded failed from related task 34623d75-4aa0-4ed6-ae6a-6099e2cdd285
   📋 Orchestrator Log: No entries found
   🤖 Worker Log: No worker assigned

💡 RECOMMENDATIONS
================================================================================

🤖 PROBLEMATIC WORKERS:
   • None: 81 failures
     └─ Primary issue: Other Error (79 times)

⚠️  SYSTEM HEALTH: High failure volume (100 failures)
   • Review overall system capacity
   • Consider maintenance window
   • Audit recent configuration changes

📋 OPERATIONAL:
   • Monitor failure trends over longer periods
   • Set up automated alerts for error spikes
   • Review task retry policies
   • Consider implementing circuit breakers