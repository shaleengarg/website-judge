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
timeout_sec = 420.0

[agent]
timeout_sec = 900.0

[environment]
build_timeout_sec = 900.0
cpus = 2
memory_mb = 4096
storage_mb = 10240
gpus = 0
allow_internet = true
