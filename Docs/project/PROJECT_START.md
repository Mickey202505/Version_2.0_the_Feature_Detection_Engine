# Feature Detection Engine (FDE)

## Project Start

Version: 2.0

Status: Active

---

# Vision

The Feature Detection Engine (FDE) is a reusable TypeScript library that converts
user-supplied satellite or aerial imagery of golf courses into accurate,
editable vector geometry.

The engine performs deterministic computer vision using OpenCV.

The FDE is independent of:

- Google Maps
- Bing Maps
- Mapping providers
- User interface frameworks

The host application is responsible for imagery, coordinate conversion and
displaying the results.

---

# Objectives

- Produce highly accurate golf feature polygons.
- Generate editable geometry.
- Follow Clean Architecture.
- Follow SOLID principles.
- Follow Test Driven Development (TDD).
- Keep the public API independent of OpenCV.
- Produce deterministic results.
- Maintain high code quality.

---

# Initial Detection Order

1. Green Detection
2. Green Fringe Generation
3. Tee Detection
4. Bunker Detection
5. Fringe Clipping
6. Fairway Detection
7. Remaining detectors

---

# Primary Documentation

The project documentation consists of:

- HANDBOOK.md
- ARCHITECTURE.md
- ROADMAP.md
- PROGRESS.md
- DECISIONS.md
- CHANGELOG.md

HANDBOOK.md is the primary source of truth.

---

# Development Rule

No production code should be written until HANDBOOK Version 2.0 is complete and
reviewed.

## Working Agreement

Before implementing any feature:

1. The handbook is reviewed.
2. Any architectural changes are documented.
3. The design is agreed.
4. Tests are written.
5. Implementation begins.
6. All tests pass before completion.

Documentation is considered part of the implementation and must remain current.