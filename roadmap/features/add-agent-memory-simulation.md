---
id: add-agent-memory-simulation
title: Add an end-to-end generic agent-memory simulation
status: queued
priority: high
commitment: committed
milestone: Phase 2
---

## Summary

Add a small end-to-end simulation of a generic agent that uses Pallium as its unstructured memory layer.

## Why

The walking skeleton should prove a real usage loop instead of only exposing storage and retrieval primitives in isolation.

## In Scope

- add a small producer that submits normalized source items to Pallium
- add a small consumer path that queries Pallium and prints compact evidence-backed memory results
- use discussion, investigation, and decision-like sample inputs
- keep the simulation generic and avoid naming any internal consumer directly

## Out of Scope

- a production agent runtime
- connector integrations
- polished UI work

## Done When

1. A developer can run a local script or command that ingests sample items into Pallium.
2. A developer can run a local query path that returns usable memory context for a simulated agent.
3. The end-to-end flow exercises the write path, semantic layer, persistence, and read path together.

## Notes

Sources: `roadmap/scope.md`, `docs/context/architecture.md`, `docs/designs/004-reference-consumer-analysis.md`
