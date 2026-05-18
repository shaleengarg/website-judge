# Website Bench

10 HTML/CSS replication tasks, organized by tier.

## Tasks

- **001-minimal-portfolio** (tier 1, portfolio): A minimalist designer's portfolio. Single column, lots of negative space, very restrained.
- **002-restaurant-simple** (tier 1, restaurant): A small neighborhood Italian restaurant. Traditional, warm, no flashy graphics.
- **003-personal-blog** (tier 1, personal-blog): A personal blog by a single writer. Posts-first, no marketing fluff.
- **004-saas-marketing** (tier 2, saas-marketing): A typical SaaS startup marketing site for a productivity tool called Tempo.
- **005-conference-event** (tier 2, conference): A two-day design conference called LAYOUT 2026.
- **006-app-landing** (tier 2, mobile-app): Landing site for a habit-tracking mobile app called Loop.
- **007-news-magazine** (tier 2, editorial): An online newspaper called The Western Tribune.
- **008-docs-site** (tier 3, documentation): Technical documentation site for a fake CLI tool called 'orbit'.
- **009-ecommerce-product** (tier 3, ecommerce): An online store selling minimalist home goods.
- **010-dashboard-admin** (tier 3, dashboard): An admin dashboard for a fake B2B SaaS analytics tool.

## Running a task

```bash
harbor check ./001-minimal-portfolio
harbor run -p ./001-minimal-portfolio -a oracle --env modal
harbor run -p ./001-minimal-portfolio -a claude-code \
  -m anthropic/claude-opus-4-7 --env modal
```

## Running all tasks

There's no built-in dataset wrapping yet; iterate with a shell loop:

```bash
for d in */; do
  harbor run -p "$d" -a oracle --env modal
done
```
