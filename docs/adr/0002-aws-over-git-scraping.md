# Run on AWS instead of git scraping

Snapshots, their storage and the public page run on AWS. The alternative was git scraping: a GitHub Actions cron job that commits each day's data to this repo, with GitHub Pages serving the page. Git scraping needs no infrastructure, but scheduled workflows can run late or be skipped, GitHub disables them after 60 days without repo activity, and a missed Snapshot can never be recovered. A reliable daily schedule and durable storage outweighed the extra setup.

This decision does not fix which AWS services are used.
