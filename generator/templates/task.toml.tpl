schema_version = "1.1"

[task]
name = "{{TASK_NAME}}"
description = "{{TASK_DESCRIPTION}}"
authors = [{ name = "Website Bench", email = "shaleengarg.in@gmail.com" }]
keywords = ["frontend", "html", "css", "vision", "replication", "{{GENRE}}", "tier-{{TIER}}"]

[metadata]
difficulty_explanation = "{{DIFFICULTY_EXPLANATION}}"
category = "frontend"
tier = {{TIER}}
genre = "{{GENRE}}"

[verifier]
# V4 grader makes ~3-6× more API calls than V3.3 (3 viewports × ensemble of 3
# × 5 pages, sending 6 images per call). Under concurrent harbor runs, 429
# backoff storms from the Anthropic API can stretch a single trial's
# verifier past 1000s. 420s timed out 2/12 trials in the v3 dataset; 1200s
# leaves enough headroom for retry backoffs to land.
# Tier-9 (motion) tasks bump this because the verifier additionally captures
# 6 motion frames × 3 viewports × 5 pages for the agent side (~90 extra
# screenshots, each preceded by a clock fast-forward).
timeout_sec = {{VERIFIER_TIMEOUT_SEC}}

[agent]
# V4-aware sites must be responsive across desktop/tablet/phone, ~3× the
# design work per page vs V3-era 1280×800-only tasks. 900s timed out 4/12
# v3 trials; 1500s leaves headroom for complex tier-6+ multi-page flows.
timeout_sec = 1500.0

[environment]
build_timeout_sec = 900.0
cpus = 2
memory_mb = 4096
storage_mb = 10240
gpus = 0
allow_internet = true
