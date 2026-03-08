# Pallium

Pallium is a generic memory engine for agents.

It stores selected source items, derives reusable knowledge through extensible
semantic layers, and returns compact evidence-backed memory objects to
consumers.

## What Pallium Is

Pallium is intended to be:

- a generic memory core
- extensible through semantic use-case layers
- local-first by default
- evidence-backed and replayable
- useful as an unstructured memory layer for agents

## What Pallium Is Not

Pallium is not intended to be:

- a system of record
- an agent runtime
- a connector platform as its primary identity
- a workflow engine
- a replacement for direct retrieval from source systems

## Current Direction

The first implementation is being built as a walking skeleton:

- one local-first service
- one generic core
- one semantic layer interface with a simple in-repo plugin pattern
- one storage layer
- one retrieval path
- one simulated generic agent consumer for end-to-end proof

The current top-level architecture is:

1. API layer
2. Generic core
3. Semantic layer
4. Storage layer
5. Retrieval layer
6. Optional background jobs

## Core Concepts

The generic core currently centers on five primitives:

- SourceItem
- Annotation
- Relation
- IndexEntry
- MemoryObject

The core owns storage and orchestration. Semantic layers define meaning.

## Tiered Memory

Tiered memory is an intended extension, not a v1 requirement.

The idea is to periodically consolidate lower-level memory into higher-level
reusable memory objects such as topic summaries or recurring patterns, while
keeping all lower-level evidence intact.

## Status

This repository is still pre-implementation.

What exists now:

- project context and architecture docs
- design documents for the core model and tiered memory direction
- roadmap and feature planning via Minimap

What comes next:

- define the first core model and API contracts
- choose the initial Python stack and scaffold the service
- add a simulated end-to-end agent-memory workflow

## Repository Guide

- docs/README.md
  Documentation map and ownership model

- docs/context/
  Stable project truth: vision, architecture, decisions, state

- docs/designs/
  Deeper design threads and analyses

- roadmap/
  Canonical planning workspace for queue, scope, and feature status

- tools/minimap/
  Repo-local planning support

## Planning Model

This repo uses Minimap for roadmap and feature planning. `roadmap/` is the
canonical planning surface for active work and sequencing.

## Notes For Contributors

- Keep the core generic.
- Put domain meaning in semantic layers, not in the core.
- Keep memory evidence-backed.
- Prefer additive semantics over destructive rewriting.
- Avoid duplicating source systems of record.

This project uses [Minimap](https://github.com/rore/minimap) for repo-local roadmap and feature planning.
