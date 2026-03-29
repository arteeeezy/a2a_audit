---
name: batch-large-scale-codebase-changes
description: Batch - Large-scale Codebase Changes
---

# Batch - Large-scale Codebase Changes

Usage: /batch <instruction>

Process:
1. Researches the codebase
2. Decomposes work into 5 to 30 independent units
3. Presents a plan for approval
4. Spawns one background agent per unit in isolated git worktree
5. Each agent implements its unit, runs tests, and opens a pull request

Requirements: Git repository

Example: /batch migrate src/ from Solid to React


## Steps

1. Researches the codebase
2. Decomposes work into 5 to 30 independent units
3. Presents a plan for approval
4. Spawns one background agent per unit in isolated git worktree
5. Each agent implements its unit, runs tests, and opens a pull request

